"""Interface Gradio de GuindiMa AI, pour un Hugging Face Space (ZeroGPU).

Ce fichier ne réimplémente rien : il reprend les modules déjà validés du projet.
Chaque exécution de Gradio est indépendante, ce qui simplifie la mise en cache.

    audio -> transcrire() -> extract_intent() -> StopsMatcher.find_line()
          -> carte HTML + voix_depuis_cache()

Sur un Space, la seule partie qui demande le GPU est la transcription : le
décorateur @spaces.GPU la réserve le temps du calcul puis le libère pour les autres visiteurs.
Le reste du pipeline (extraction, correspondance, voix) tient en CPU et n'a pas
à payer la réservation.
"""

from __future__ import annotations

import atexit
import contextvars
import csv
import html
import io
import itertools
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path

try:
    import gradio as gr
except ImportError:
    # Les tests unitaires importent les fonctions pures de ce module sans
    # installer Gradio. L'interface n'est construite que hors mode test.
    gr = None

import numpy as np

RACINE = Path(__file__).resolve().parent
# Les modules du projet sont importés à plat (asr, intent, matching, tts) : il faut
# que src/ soit dans le chemin, y compris quand app.py est lancé depuis la racine.
sys.path.insert(0, str(RACINE / "src"))

from app import collecte  # noqa: E402
from app.cartes import titre_autre_possibilite, titre_autre_possibilite_texte, titre_section  # noqa: E402
from app.limites import JOUR, MINUTE, LimiteDebit, LimiteParClient, cle_client, entier_env  # noqa: E402
from app.partage import bouton_partage  # noqa: E402
from asr.transcribe import (  # noqa: E402
    MODEL_ASR_GPU,
    REVISION_ASR_GPU,
    SAMPLE_RATE,
    libelle_charge,
    load_audio,
    load_model,
    transcrire,
    transcrir_avec_seconde_chance,
)
from intent.extract_intent import (  # noqa: E402
    NVIDIA_BASE_URL,
    TEXTE_MAX,
    TIMEOUT_APPEL,
    _repli_local,
    extract_intent,
    extract_local,
)
from matching.compagnie import (  # noqa: E402
    MENTION_A_CONFIRMER,
    ligne_a_confirmer,
    message_autre_compagnie,
)
from matching.geo import arrets_non_fiables  # noqa: E402
from matching.lieux import AVANT_NUMERO, FAUX_AMIS, joli, sans_accents  # noqa: E402
from matching.stops_matcher import StopsMatcher  # noqa: E402
from intent.conversation import HORS_SUJET, Intention  # noqa: E402
from intent.conversation import detecter as detecter_conversation  # noqa: E402
from intent.conversation import INTENTIONS, signal_trajet  # noqa: E402
from tts.speak import voix_conversation  # noqa: E402
from tts.speak import (  # noqa: E402
    MAX_POSSIBILITES,
    nombre_en_wolof,
    numero_de,
    voix_correspondances_depuis_cache,
    voix_depuis_cache,
    voix_lieux_possibles,
    voix_trajets_2_depuis_cache,
)

VERT = "#00853F"  # vert du Sénégal, celui du thème et des cartes

# --------------------------------------------------------------------------- #
# GPU
# --------------------------------------------------------------------------- #

try:
    import spaces
except ImportError:
    # Hors Space — poste local, CI, machine sans le SDK — le module n'existe pas.
    # On fabrique un décorateur à la même signature pour que le reste du fichier
    # n'ait aucune condition particulière à vérifier.
    class _SpacesLocal:
        """Remplace le SDK spaces quand il n'est pas installé : no-op."""

        @staticmethod
        def GPU(*args, **kwargs):
            def sans_gpu(fonction):
                return fonction

            return sans_gpu

    spaces = _SpacesLocal()


# Whisper (CPU) et Kiriku (GPU) sont chargés au démarrage du module : ZeroGPU
# recommande un chargement au niveau module, jamais dans la fonction @spaces.GPU,
# qui ne doit couvrir que le calcul. Un échec de chargement ne fait que garder
# None ; la transcription du GPU renvoie alors ERREUR_ASR et l'app s'appuie sur
# l'autre modèle préchargé.
_MODELE_CPU = None
_MODELE_GPU = None

# Les tests unitaires n'ont pas le droit de télécharger ni de charger un modèle.
# Ce garde coupe le préchargement, l'échauffement LLM et la construction Gradio ;
# il n'est jamais activé sur le Space.
MODE_TEST = os.getenv("GUINDIMA_SANS_MODELES", "").strip().lower() in {"1", "true", "oui"}


def _precharger_whisper():
    """Précharge whisper-small quantifié sur CPU, dès l'ouverture du Space.

    Ne pas attendre le premier refus du GPU pour charger le modèle de secours :
    quand ZeroGPU refuse la carte, la transcription part immédiatement au lieu de
    rester une minute devant « chargement du modèle ».
    """
    global _MODELE_CPU
    try:
        _MODELE_CPU = load_model()
        print(f"[ASR] {libelle_charge()} préchargé sur CPU", flush=True)
    except Exception as exc:
        message = f"{type(exc).__name__} : {exc}"[:160]
        print(f"[ASR] préchargement whisper impossible ({message})", flush=True)


def _charger_kiriku_gpu():
    """Le pipeline Kiriku-Wolof-ASR en float16 sur GPU (modèle protégé : HF_TOKEN)."""
    if not REVISION_ASR_GPU:
        raise RuntimeError(
            "ASR_MODEL_GPU_REVISION est obligatoire quand ASR_MODEL_GPU n'est "
            "pas le dépôt Kiriku par défaut."
        )

    import torch
    from transformers import pipeline

    return pipeline(
        "automatic-speech-recognition",
        model=MODEL_ASR_GPU,
        revision=REVISION_ASR_GPU,
        device=0,
        dtype=torch.float16,
        token=os.getenv("HF_TOKEN"),
    )


def _precharger_kiriku():
    """Précharge Kiriku-Wolof-ASR sur GPU au chargement du module.

    Comme avant le refactor : à l'ouverture, si la carte est là, on charge Kiriku.
    Sinon _MODELE_GPU reste None et la transcription GPU renvoie ERREUR_ASR ;
    le whisper CPU préchargé prend alors le relais.
    """
    global _MODELE_GPU
    try:
        import torch

        # Un échec dans torch.init (spaces/zero/wrappers.py) vient souvent d'un
        # torch plus récent que ce que la version de spaces sait patcher :
        # requirements.txt ne fige ni l'un ni l'autre. Les deux versions au
        # journal permettent de le vérifier sans redéployer pour voir.
        try:
            from importlib.metadata import version as _version

            version_spaces = _version("spaces")
        except Exception:
            version_spaces = "absent"
        print(f"[ASR] torch {torch.__version__}, spaces {version_spaces}", flush=True)

        if not torch.cuda.is_available():
            print("[ASR] pas de GPU au démarrage : Kiriku non chargé", flush=True)
            return
        _MODELE_GPU = _charger_kiriku_gpu()
        print(f"[ASR] {MODEL_ASR_GPU} chargé sur GPU", flush=True)
    except Exception as exc:
        message = f"{type(exc).__name__} : {exc}"[:160]
        print(f"[ASR] Kiriku indisponible au démarrage ({message})", flush=True)


if not MODE_TEST:
    _precharger_whisper()
    _precharger_kiriku()

# Crédit affiché en pied de page : les deux modèles de transcription.
# Le whisper CPU est notre fine-tuning sur la collecte dakaroise ; Kiriku sert
# sur GPU, avec repli sur le même whisper quand ZeroGPU refuse la carte.
LIBELLE_ASR = "Whisper wolof fine-tuné à Dakar + Kiriku-Wolof-ASR"
# Voix des réponses pré-générées : la voix native 8_1_c du Space
# Oolel-Voices-Demo, dans data/tts_cache_oolel/ (873 audios attendus,
# dont 4 réponses de conversation posées par installer_conversation).
LIBELLE_VOIX = "Oolel-Voices, voix native (soynade-research)"

# --------------------------------------------------------------------------- #
# Clients et objets reconstruits une fois
# --------------------------------------------------------------------------- #

# Moteur de recherche : « v2 » (nouveau moteur d'itinéraires) par défaut,
# « v1 » pour revenir à l'ancien sans toucher au code : GUINDIMA_MOTEUR=v1.
# Plus de repli silencieux : si v2 ne démarre pas, l'app le dit franchement
# (RuntimeError). Avant, une dépendance manquante renvoyait tranquillement
# l'ancien moteur : un v2 cassé passait pour un v2 en bonne santé.
MOTEUR = os.getenv("GUINDIMA_MOTEUR", "v2").strip().lower()
if MOTEUR not in {"v1", "v2"}:
    MOTEUR = "v2"


def _construire_matcher():
    if MOTEUR == "v1":
        return StopsMatcher()
    try:
        from routing.adapter import MoteurV2

        print("[moteur] v2 actif", flush=True)
        return MoteurV2(StopsMatcher())
    except Exception as exc:
        # On n'avale plus l'erreur : un import raté (dépendance absente du
        # Space, disque plein…) doit s'entendre, pas faire repartir l'app sur
        # v1 en murmurant. Le repli v1 reste un choix explicite du deployeur.
        message = f"{type(exc).__name__} : {exc}"[:160]
        raise RuntimeError(
            "Impossible de démarrer le moteur v2 "
            "(GUINDIMA_MOTEUR non défini, ou défini à « v2 ») — pas de repli "
            "silencieux sur v1 : mettez GUINDIMA_MOTEUR=v1 pour revenir à "
            f"l'ancien moteur. Cause : {message}"
        ) from exc


MATCHER = _construire_matcher()

_CLIENT = None
_CLIENT_TENTE = False
LIMITE_LLM = LimiteDebit(
    entier_env("LLM_MAX_PAR_MINUTE", 30),
    entier_env("LLM_MAX_PAR_JOUR", 1000),
)
LIMITE_LLM_CLIENT = LimiteParClient((
    (MINUTE, entier_env("LLM_MAX_PAR_CLIENT_MINUTE", 5)),
    (JOUR, entier_env("LLM_MAX_PAR_CLIENT_JOUR", 50)),
))
LIMITE_TRAJETS_CLIENT = LimiteParClient((
    (MINUTE, entier_env("TRAJETS_MAX_PAR_MINUTE", 10)),
    (JOUR, entier_env("TRAJETS_MAX_PAR_JOUR", 100)),
))
# Le client de la demande en cours, pour compter ses appels au LLM plus bas.
_CLE_CLIENT: contextvars.ContextVar[str | None] = contextvars.ContextVar("cle_client", default=None)


def _llm_autorise() -> bool:
    """Le plafond du client d'abord : un client bloqué n'entame pas celui du Space."""
    return LIMITE_LLM_CLIENT.autoriser(_CLE_CLIENT.get()) and LIMITE_LLM.autoriser()


def _client_llm():
    """Client NVIDIA partagé, ou None si la clé n'est pas là.

    On lit la clé dans l'environnement plutôt que de laisser extract_intent lever :
    sans clé, on renvoie None, extract_intent tente alors de construire le client,
    échoue, et bascule sur son extraction locale. Un Space sans secret configuré
    dégrade donc la qualité de la détection au lieu de casser la démo.
    """
    global _CLIENT, _CLIENT_TENTE
    if _CLIENT_TENTE:
        return _CLIENT
    _CLIENT_TENTE = True
    cle = os.getenv("NVIDIA_API_KEY", "").strip()
    if cle:
        from openai import OpenAI

        _CLIENT = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=cle,
            timeout=TIMEOUT_APPEL,
            # Nos tentatives sont gérées dans extract_intent ; sans cela le SDK en
            # ajoute deux de son côté et triple le délai avant le repli local.
            max_retries=0,
        )
    return _CLIENT


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #

# Gradio veut un chemin de fichier, la synthèse renvoie des octets WAV. On écrit
# donc dans un dossier temporaire, un fichier par réponse.
DOSSIER_VOIX = Path(tempfile.mkdtemp(prefix="guindima_voix_"))
_COMPTEUR = itertools.count()
DUREE_VIE_VOIX = 600  # secondes : un WAV de réponse plus vieux est supprimé

TAILLE_MAX_AUDIO = 10 * 1024 * 1024  # 10 Mo
DUREE_MAX_AUDIO = 30.0  # secondes
TAILLE_FILE_ATTENTE = 64  # demandes en attente, au-delà Gradio refuse poliment
MESSAGE_AUDIO_TROP_LOURD = (
    "Fichier trop lourd : 10 Mo maximum. / Fi bi bari na : 10 Mo rekk."
)
MESSAGE_AUDIO_TROP_LONG = (
    "Enregistrement trop long : 30 secondes maximum. / "
    "Mbind mi guddoon na : 30 segond rekk."
)
MESSAGE_AUDIO_FORMAT = "Format audio non reconnu. Enregistre-toi avec le micro."
# Le détail d'une erreur (chemins, commande ffmpeg, nom du modèle) reste au serveur.
CARTE_AUDIO_ILLISIBLE = "### 🎤 Audio illisible\n\nRéessaie avec un nouvel enregistrement."
CARTE_TRANSCRIPTION_IMPOSSIBLE = "### 🎤 Transcription impossible\n\nRéessaie dans un instant."
CARTE_TROP_DE_DEMANDES = (
    "### ⏳ Beaucoup de demandes\n\n"
    "Tu as fait beaucoup de demandes. Attends un peu avant de réessayer, merci."
)

ERREUR_ASR = "\x00ERREUR_ASR "


class AudioRefuse(ValueError):
    """Un audio écarté avant transcription (taille ou durée), avec un message clair."""


def _nettoyer_voix_anciennes() -> None:
    """Supprime les réponses WAV trop anciennes du dossier temporaire.

    Gradio a besoin du fichier le temps de servir la réponse ; on ne peut donc
    pas l'effacer juste après l'avoir écrit. On purge à chaque nouvelle réponse,
    et `atexit` enlève le dossier à la fin du processus.
    """
    limite = time.time() - DUREE_VIE_VOIX
    for chemin in DOSSIER_VOIX.glob("reponse_*.wav"):
        try:
            if chemin.stat().st_mtime < limite:
                chemin.unlink()
        except OSError:
            # Un fichier déjà supprimé ou verrouillé ne doit pas casser la réponse.
            pass


atexit.register(shutil.rmtree, DOSSIER_VOIX, ignore_errors=True)


def _signature_audio(octets: bytes) -> bool:
    """Vrai si le début du fichier est celui d'un conteneur audio attendu.

    ffmpeg devine le format d'après le contenu : une « playlist » HLS ou un script
    concat déposé comme audio lui ferait ouvrir d'autres fichiers. Seuls WAV, WebM,
    Ogg, FLAC, MP3, AAC et MP4/M4A vont donc jusqu'au décodage.
    """
    debut = octets[:12]
    return (
        (debut[:4] == b"RIFF" and debut[8:12] == b"WAVE")
        or debut[:4] in {b"\x1aE\xdf\xa3", b"OggS", b"fLaC"}
        or debut[:3] == b"ID3"
        or debut[4:8] == b"ftyp"
        or (len(debut) >= 2 and debut[0] == 0xFF and debut[1] & 0xE0 == 0xE0)
    )


def _refuser_duree_annoncee(octets: bytes) -> None:
    """Refuse un audio trop long AVANT de le décompresser.

    10 Mo de FLAC silencieux peuvent représenter des heures, donc des Go en mémoire.
    Un format que soundfile ne sait pas lire passe par ffmpeg, déjà borné à 31 s.
    """
    import soundfile as sf

    try:
        duree = sf.info(io.BytesIO(octets)).duration
    except Exception:
        return
    if duree > DUREE_MAX_AUDIO + 1:
        raise AudioRefuse(MESSAGE_AUDIO_TROP_LONG)


def _decoder_audio(chemin_audio: str) -> np.ndarray:
    """Lit l'enregistrement (micro ou fichier) en 16 kHz mono, sur CPU.

    Fait hors de la réservation GPU : décoder un fichier n'a pas besoin du GPU.
    La taille est vérifiée avant `read_bytes()` pour ne jamais charger 100 Mo en
    mémoire ; la durée est vérifiée après décodage, avant la transcription.
    """
    chemin = Path(chemin_audio)
    try:
        taille = chemin.stat().st_size
    except OSError as exc:
        raise AudioRefuse("Fichier audio introuvable.") from exc
    if taille > TAILLE_MAX_AUDIO:
        raise AudioRefuse(MESSAGE_AUDIO_TROP_LOURD)

    octets = chemin.read_bytes()
    if not _signature_audio(octets):
        raise AudioRefuse(MESSAGE_AUDIO_FORMAT)
    _refuser_duree_annoncee(octets)
    try:
        son = load_audio(octets)
    except Exception:
        # Le navigateur enregistre en WebM/Opus, que soundfile ne sait pas lire.
        # ffmpeg, déclaré dans packages.txt, ramène ça en WAV avant de réessayer.
        with tempfile.TemporaryDirectory() as dossier:
            converti = Path(dossier) / "micro.wav"
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                        "-i", str(chemin),
                        "-vn",
                        "-t", str(int(DUREE_MAX_AUDIO) + 1),
                        "-ar", str(SAMPLE_RATE),
                        "-ac", "1",
                        str(converti),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                raise AudioRefuse(
                    "Conversion audio trop longue : 30 secondes maximum. / "
                    "Waxtaan wi guddoon na : 30 segond rekk."
                ) from exc
            son = load_audio(converti.read_bytes())

    if son is not None and len(son) > int(DUREE_MAX_AUDIO * SAMPLE_RATE):
        raise AudioRefuse(MESSAGE_AUDIO_TROP_LONG)
    return son


@spaces.GPU(duration=30)
def transcrire_wolof(audio: np.ndarray) -> str:
    """Transcrit avec Kiriku sur GPU — le seul endroit qui réserve le GPU.

    Le modèle est déjà chargé au démarrage du module (recommandation ZeroGPU) :
    la réservation ne couvre que le calcul, d'où les 30 s. Kiriku ne se charge
    jamais ici. S'il est absent (pas de GPU au démarrage), on renvoie une phrase
    préfixée par ERREUR_ASR : l'appelant bascule sur le whisper CPU préchargé.
    """
    if _MODELE_GPU is None:
        return f"{ERREUR_ASR}Kiriku non chargé (pas de GPU au démarrage)"
    try:
        return transcrire(_MODELE_GPU, audio)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return f"{ERREUR_ASR}{type(exc).__name__} : {str(exc)[:300]}"


def _transcrire_cpu(audio: np.ndarray) -> str:
    """whisper-small quantifié sur CPU, préchargé à l'ouverture du Space.

    Charge le modèle à la demande s'il n'a pas pu l'être au démarrage, et lève si
    la transcription échoue : c'est l'appelant qui choisit de remonter l'erreur.
    """
    global _MODELE_CPU
    if _MODELE_CPU is None:
        print("[ASR] chargement de whisper-small sur CPU…", flush=True)
        _MODELE_CPU = load_model()
    return transcrire(_MODELE_CPU, audio)


def _transcrire_premier(audio: np.ndarray) -> tuple[str, str, float]:
    """Essai principal : Kiriku sur GPU, whisper CPU si le GPU est refusé.

    Renvoie (transcription, libellé du modèle, durée). Lève seulement si aucune
    transcription n'aboutit (audio illisible, modèle absent) ; une phrase vide
    signifie qu'il n'y avait rien d'audible.
    """
    debut = time.perf_counter()
    try:
        phrase = transcrire_wolof(audio)
        if phrase.startswith(ERREUR_ASR):
            raise RuntimeError(phrase[len(ERREUR_ASR):])
        return phrase, "Kiriku-Wolof-ASR (GPU)", time.perf_counter() - debut
    except Exception as exc:
        print(f"[ASR] ZeroGPU en échec ({_resume_erreur_gpu(exc)}), secours CPU", flush=True)
        return _transcrire_cpu(audio), libelle_charge(), time.perf_counter() - debut


def _second_essai(audio: np.ndarray, libelle_premier: str) -> tuple[str, str, float]:
    """L'autre modèle ASR, pour la seconde chance.

    Si le premier essai a tourné sur Kiriku, l'autre est le whisper CPU, réputé
    écrire autrement les noms d'arrêts. S'il a fini sur whisper (GPU refusé),
    l'autre est Kiriku : le refus de ZeroGPU peut être passager, on redemande la
    carte. Qu'un des deux échoue, et transcrir_avec_seconde_chance garde le
    premier résultat.
    """
    debut = time.perf_counter()
    if "Kiriku" in libelle_premier:
        return _transcrire_cpu(audio), libelle_charge(), time.perf_counter() - debut
    try:
        phrase = transcrire_wolof(audio)
        if phrase.startswith(ERREUR_ASR):
            raise RuntimeError(phrase[len(ERREUR_ASR):])
        return phrase, "Kiriku-Wolof-ASR (GPU)", time.perf_counter() - debut
    except Exception as exc:
        print(f"[ASR] second essai GPU refusé ({_resume_erreur_gpu(exc)})", flush=True)
        raise


# Départ et arrivée au même endroit : vu en production, Kiriku a écrit
# « damay dem petersen te maa ngi wakaay » ; « wakaay » n'étant pas reconnu, le
# LLM a rendu Petersen -> Petersen, et l'app a répondu « À pied environ 0 min »
# avec des bus au hasard. Même nom, ou marche de moins de 100 m (Palais ->
# Palais 2) : ce n'est pas un trajet, c'est une extraction incomplète.
DISTANCE_MEME_LIEU_M = 100

# On redemande avec une phrase déjà enregistrée, jamais une phrase nouvelle :
# « Wax ma fan nga nekk ak fan nga bëgga dem, ma won la bus bi nga wara jël. »
# (conversation_capacites.wav, validée par le locuteur natif).
_CAPACITES = next(i for i in INTENTIONS if i.nom == "capacites")
DEMANDE_MEME_LIEU = Intention("meme_lieu", _CAPACITES.reponse, _CAPACITES.fichier, ())


def _meme_lieu(depart: str, arrivee: str, resultat: dict | None = None) -> bool:
    """Vrai si départ et arrivée désignent le même endroit (nom ou marche quasi nulle)."""
    if not depart or not arrivee:
        return False
    if sans_accents(depart).lower().strip() == sans_accents(arrivee).lower().strip():
        return True
    a_pied = (resultat or {}).get("a_pied") or {}
    distance = a_pied.get("distance_m")
    return isinstance(distance, (int, float)) and distance <= DISTANCE_MEME_LIEU_M


def _phrase_donne_un_trajet(phrase: str) -> bool:
    """La phrase mène-t-elle déjà à un trajet, sans LLM ?

    Le même chemin que le pipeline principal (extraction locale puis recherche) :
    on évite de re-transcrire quand la première transcription suffit. Un lieu
    manquant ou absent du réseau, ou aucune ligne trouvée, déclenche donc la
    seconde chance.
    """
    if not phrase or phrase.startswith(ERREUR_ASR):
        return False
    local = extract_local(phrase)
    if (
        not (local.get("depart") or local.get("arrivee"))
        and detecter_conversation(phrase)
        and not signal_trajet(phrase)
    ):
        # « Salam » seul est compris : inutile de re-transcrire avec l'autre
        # modèle. Mais « Salaam aleekum, damay dem <lieu mal écrit> » est un
        # trajet : l'autre modèle a sa chance d'écrire le lieu correctement.
        return True
    if not (local.get("depart") and local.get("arrivee")):
        return False
    essai = MATCHER.find_line(local["depart"], local["arrivee"])
    if _meme_lieu(local["depart"], local["arrivee"], essai):
        # Même lieu des deux côtés : l'autre modèle ASR a sa chance.
        return False
    return bool(essai["found"] or essai["correspondances"])


def _voix_wolof(
    lignes: list[dict],
    correspondances: list[dict] | None = None,
    trajets_2: list[dict] | None = None,
    lieux_possibles: list[dict] | None = None,
) -> str | None:
    """La réponse lue en wolof, sous forme de chemin de fichier.

    On assemble uniquement les segments Oolel-Voices présents dans `data/tts_cache/` :
    aucune synthèse en direct. Si le cache est incomplet, les morceaux présents
    sont joués ; si aucun ne l'est, la réponse reste silencieuse. Un trajet à
    deux changements, lui, n'est lu que si tous ses segments sont là ; la marche
    seule reste sans voix.
    """
    correspondances = correspondances or []
    trajets_2 = trajets_2 or []
    if lieux_possibles:
        # « aéroport » seul : une possibilité par aéroport, « Walla, » entre les
        # deux ; avec un seul aéroport desservi, la voix dit lequel.
        return _ecrire_voix(voix_lieux_possibles(lieux_possibles))
    if not lignes and not correspondances and not trajets_2:
        return None
    if lignes:
        octets = voix_depuis_cache(lignes)
    elif correspondances:
        octets = voix_correspondances_depuis_cache(correspondances)
    else:
        # Deux changements : on enchaîne les mêmes segments qu'une
        # correspondance, avec un bus et un lieu de plus. Aucune synthèse en
        # direct ; si un segment manque, la réponse reste silencieuse.
        octets = voix_trajets_2_depuis_cache(trajets_2)
    return _ecrire_voix(octets)


def _ecrire_voix(octets: bytes | None) -> str | None:
    """Écrit l'audio d'une réponse et rend son chemin, ou None sans audio."""
    if octets is None:
        print("[voix] aucun segment disponible, réponse laissée sans voix", flush=True)
        return None
    _nettoyer_voix_anciennes()
    chemin = DOSSIER_VOIX / f"reponse_{next(_COMPTEUR)}.wav"
    chemin.write_bytes(octets)
    return str(chemin)


def _reponse_conversation(
    phrase: str, intention: Intention, modele_asr: str, duree_asr: float
) -> tuple:
    """Une réponse de petite conversation : la phrase wolof, à l'écran et à voix haute."""
    _journal(modele_asr, duree_asr, 0, f"conversation_{intention.nom}")
    return (
        phrase,
        "",
        f"### 💬 {_echapper(intention.reponse)}",
        _ecrire_voix(voix_conversation(intention.fichier)),
        _mention({}, modele_asr),
    )


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #


def _echapper(valeur: object) -> str:
    """Échappe une valeur avant insertion dans du HTML.

    Les noms d'arrêts viennent des CSV, mais `depart`/`arrivee` peuvent venir
    d'une transcription ou d'un LLM : on ne les insère jamais bruts.
    """
    return html.escape("" if valeur is None else str(valeur), quote=True)


def _echapper_markdown(valeur: object) -> str:
    """Échappe HTML puis les caractères Markdown encore actifs dans `gr.Markdown`."""
    texte = _echapper(valeur)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", texte)


# Grands quartiers : leur nom dit ne désigne pas un point précis, le même dit
# peut être à plusieurs kilomètres de l'arrêt conseillé. On invite alors à affiner.
QUARTIERS_VAGUES = {
    "pikine", "guediawaye", "parcelle", "parcelles", "parcelles assainies",
    "keur massar", "rufisque", "yeumbeul", "thiaroye", "grand yoff", "medina",
}


def _cle_lieu(texte: str) -> str:
    """Forme de comparaison d'un nom : minuscules, sans accents ni ponctuation."""
    return re.sub(r"[^a-z0-9]+", " ", sans_accents(texte)).strip()


_NIVEAUX_LARGES = ("arrondissement", "departement")


def _niveau_precis(valeur: str) -> bool:
    """Vrai si la valeur est un quartier/commune et non un arrondissement."""
    return bool(valeur) and not _cle_lieu(valeur).startswith(_NIVEAUX_LARGES)


@lru_cache(maxsize=32)
def _arrets_du_quartier(quartier: str, limite: int = 2) -> tuple[str, ...]:
    """Des arrêts réels d'un quartier, prêts à illustrer l'astuce.

    Lecture seule. Deux passes. D'abord les arrêts dont le NOM contient le
    quartier (« Police Guédiawaye », « Poste Thiaroye »), hors faux amis, en
    gardant en tête ceux dont le quartier est le dernier mot. Seulement s'il n'y
    en a pas : des arrêts de confiance « bonne » au niveau quartier/commune
    précis — jamais « estimee », dont la position peut tomber dans un autre
    quartier. On écarte l'arrêt qui porte exactement le nom du quartier :
    « Médina » n'aide pas à préciser « Médina ».

    Les noms sont rendus comme sur les cartes (joli, chiffres romains en
    chiffres, sans annotation entre parenthèses) et les plus courts sont
    préférés : au plus quatre mots.
    """
    cible = _cle_lieu(quartier)
    if not cible or not ARRETS_GEO.exists():
        return ()

    par_suffixe: list[str] = []
    par_nom: list[str] = []
    par_quartier: list[str] = []
    with open(ARRETS_GEO, newline="", encoding="utf-8") as f:
        for rangee in csv.DictReader(f):
            arret = (rangee.get("arret") or "").strip()
            nom = _cle_lieu(arret)
            hors = _cle_lieu(re.sub(r"\([^)]*\)", " ", arret))
            if not hors or hors == cible or nom in FAUX_AMIS:
                continue
            if f" {cible} " in f" {hors} ":
                (par_suffixe if hors.endswith(cible) else par_nom).append(arret)
                continue
            if rangee.get("confiance", "").strip().lower() != "bonne":
                continue
            lieux = [_cle_lieu(rangee.get("quartier", "")), _cle_lieu(rangee.get("commune", ""))]
            if any(_niveau_precis(v) and f" {cible} " in f" {v} " for v in lieux):
                par_quartier.append(arret)

    bruts = par_suffixe + par_nom or par_quartier
    propres: list[str] = []
    for arret in bruts:
        nom = _nom_astuce(arret)
        if nom and nom not in propres:
            propres.append(nom)
    courts = [nom for nom in propres if len(nom.split()) <= 4]
    choisis = courts + [nom for nom in propres if nom not in courts]
    return tuple(choisis[:limite])


def _astuce_quartier(*lieux: str) -> str:
    """Un rappel quand l'utilisateur n'a nommé qu'un grand quartier.

    L'exemple vient du lieu dit : deux arrêts réels de ce quartier, pris dans
    `data/arrets_geo.csv`. Le fond reste clair et le texte sombre en propre : le
    bloc se lit pareil en mode clair et en mode sombre.
    """
    vague = next(
        (lieu for lieu in lieux if lieu and _cle_lieu(lieu) in QUARTIERS_VAGUES),
        "",
    )
    if not vague:
        return ""
    exemples = _arrets_du_quartier(vague)
    illustration = (
        f"ex. pour {_echapper(joli(vague))} : "
        f"{_echapper(', '.join(exemples))}"
        if exemples
        else "ex. précise la rue ou un repère"
    )
    return (
        "<div style='color:#7A5A00;background:#FFF7E0;border:1px solid #F0DFA8;"
        "border-radius:8px;padding:8px 12px;margin-top:10px;font-size:13px;'>"
        f"💡 Astuce : précise ton lieu ({illustration}) "
        "pour un arrêt plus juste.</div>"
    )


ARRETS_GEO = RACINE / "data" / "arrets_geo.csv"

# Confiances pour lesquelles on affiche le quartier : seul « bonne » est
# localisé au niveau du quartier ; « estimee » (position devinée entre deux
# voisins) peut tomber dans un quartier voisin, on préfère ne rien afficher.
CONFIANCES_QUARTIER = {"bonne"}

# Qualificatifs administratifs qu'on enlève pour ne garder que le nom court du
# quartier (« Commune de Médina » → « Médina »).
_PREFIXE_QUARTIER = re.compile(
    r"^(?:"
    r"commune\s+d'arrondissement\s+(?:de\s+|des\s+|du\s+|d')?"
    r"|commune\s+(?:de\s+|des\s+|du\s+|d')"
    r"|arrondissement\s+(?:de\s+|des\s+|du\s+|d')"
    r"|d[ée]partement\s+(?:de\s+|des\s+|du\s+|d')"
    r")",
    re.IGNORECASE,
)


# Quelques communes qu'on préfère nommer par leur quartier, comme on le dit
# couramment (« Dakar-Plateau » → « Plateau »).
QUARTIERS_RACCOURCIS = {"dakar-plateau": "Plateau"}


def _quartier_court(valeur: str) -> str:
    """Le nom court d'un quartier ou d'une commune, sans son qualificatif."""
    court = _PREFIXE_QUARTIER.sub("", (valeur or "").strip()).strip(" ,-")
    if not court:
        return ""
    court = QUARTIERS_RACCOURCIS.get(sans_accents(court).lower(), court)
    return joli(court)


@lru_cache(maxsize=1)
def _quartiers_arrets() -> dict[str, str]:
    """Arrêt (forme affichée) -> quartier court, quand la confiance le permet.

    Lecture seule de `data/arrets_geo.csv` : on indexe chaque arrêt sous son nom
    brut et sous sa forme affichée, pour retrouver le quartier depuis les arrêts
    déjà mis en forme du trajet. Les arrêts « douteuse » ou « introuvable », les
    rues numérotées et les homonymes isolés sur leur ligne (mêmes jugements que
    la recherche de ligne) sont ignorés : pas de quartier trompeur affiché.
    """
    chemin = ARRETS_GEO
    if not chemin.exists():
        return {}
    ignores = _arrets_sans_quartier()
    table: dict[str, str] = {}
    with open(chemin, newline="", encoding="utf-8") as f:
        for rangee in csv.DictReader(f):
            if rangee.get("confiance", "").strip().lower() not in CONFIANCES_QUARTIER:
                continue
            arret = (rangee.get("arret") or "").strip()
            if not arret or arret in ignores:
                continue
            quartier = _quartier_court(rangee.get("quartier") or rangee.get("commune") or "")
            if quartier:
                table.setdefault(arret, quartier)
                table.setdefault(joli(arret), quartier)
    return table


@lru_cache(maxsize=1)
def _arrets_sans_quartier() -> frozenset[str]:
    """Les arrêts à position non fiable, jugés comme dans la recherche de ligne."""
    try:
        return frozenset(arrets_non_fiables(ARRETS_GEO))
    except Exception:
        return frozenset()


def _source_trajet(match: dict) -> str:
    """L'origine de l'itinéraire, sous la liste des arrêts.

    L'itinéraire officiel d'une ligne AFTU est publié par l'AFTU ; pour Dakar Dem
    Dikk, le tracé vient d'OpenStreetMap. Le lien ne concerne que l'AFTU.
    """
    if match.get("compagnie") == "Tata AFTU":
        numero = numero_de(match.get("ligne"))
        if numero is not None:
            url = f"https://aftu-senegal.org/map/dakar-urbain-ligne-{numero}/"
            return (
                "<div style='color:#6B7A72;font-size:12px;margin-top:8px;'>Source : "
                f"<a href='{url}' target='_blank' rel='noopener' "
                "style='color:#0B6B37;text-decoration:underline;'>"
                "Itinéraire officiel AFTU</a></div>"
            )
        return (
            "<div style='color:#6B7A72;font-size:12px;margin-top:8px;'>"
            "Source : Itinéraire officiel AFTU</div>"
        )
    return (
        "<div style='color:#6B7A72;font-size:12px;margin-top:8px;'>"
        "Source : Itinéraire Dem Dikk / OpenStreetMap</div>"
    )


def _note_sens_inverse(match: dict) -> str:
    """Le rappel discret quand le trajet va à l'inverse de l'itinéraire publié.

    `match['depart']`/`match['arrivee']` suivent le sens du trajet ; l'itinéraire
    publié, lui, va dans l'autre sens, soit de `arrivee` vers `depart`.
    """
    if str(match.get("sens", "")).lower() != "inverse":
        return ""
    sens_publie = f"{_echapper(match.get('arrivee', ''))} → {_echapper(match.get('depart', ''))}"
    if match.get("compagnie") == "Tata AFTU":
        intro = f"L'AFTU publie cet itinéraire dans le sens {sens_publie}."
    else:
        intro = f"L'itinéraire publié va dans le sens {sens_publie}."
    return (
        "<div style='color:#6B7A72;font-size:12px;font-style:italic;"
        "margin-top:6px;'>"
        f"{intro} Au retour, le bus peut emprunter d'autres rues.</div>"
    )


# Chiffres romains remis en chiffres arabes à l'affichage, quand ils suivent un
# mot qui appelle un numéro (« Giratoire de Liberté VI » → « ... 6 »).
_CHIFFRES_ROMAINS = {
    "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
    "vii": "7", "viii": "8", "ix": "9", "x": "10",
}


def _chiffres_du_nom(nom: str) -> str:
    """« Giratoire de Liberté VI » → « Giratoire de Liberté 6 »."""
    mots = nom.split()
    for i, mot in enumerate(mots):
        if not i:
            continue
        cle = sans_accents(mot).strip("()'.,/")
        avant = sans_accents(mots[i - 1]).strip("()'.,")
        if cle in _CHIFFRES_ROMAINS and avant in AVANT_NUMERO:
            mots[i] = _CHIFFRES_ROMAINS[cle]
    return " ".join(mots)


# Annotation d'itinéraire (« Retour Par Rue 37 ») : on l'enlève du nom et on la
# garde à part, à rappeler en petit dans le bloc des arrêts.
_NOTE_RETOUR = re.compile(r"\s*\(\s*(?:au\s+)?retour(?:\s+par)?\s+rue\s+(\d+)\s*\)", re.I)

# Parenthèses qui font partie du NOM (« Rue Abebebikila (Rue 11 Prolongée) ») :
# rendues avec un tiret, pour ne pas ressembler au quartier affiché entre
# parenthèses juste après.
_PARENTHESES_NOM = re.compile(r"\s*\(([^)]*)\)\s*")


def _sans_parentheses_quartier(nom: str) -> str:
    """« Rue Abebebikila (Rue 11 Prolongée) » → « Rue Abebebikila – Rue 11 Prolongée »."""
    transforme = _PARENTHESES_NOM.sub(r" – \1 ", nom)
    return re.sub(r"\s+", " ", transforme).strip()


def _nom_arret(nom: str) -> tuple[str, str]:
    """Le nom d'arrêt affiché et, s'il y a lieu, la note « au retour ».

    « Rue 25 (Retour Par Rue 37) » → (« Rue 25 », « au retour : par la rue 37 »).
    Les parenthèses qui restent font partie du nom et sont rendues avec un tiret.
    """
    propre, note = nom, ""
    trouve = _NOTE_RETOUR.search(nom)
    if trouve:
        note = f"au retour : par la rue {trouve.group(1)}"
        propre = f"{nom[:trouve.start()]} {nom[trouve.end():]}".strip()
    return _sans_parentheses_quartier(_chiffres_du_nom(propre)), note


def _nom_astuce(arret: str) -> str:
    """Nom d'arrêt pour l'astuce : comme sur la carte, sans annotation.

    « RUE10 PIKINE (Retour Par Rue 37) » -> « Rue 10 Pikine ».
    """
    affiche, _ = _nom_arret(joli(arret))
    affiche = re.sub(r"\([^)]*\)", " ", affiche)
    return re.sub(r"\s+", " ", affiche).strip()


def _bloc_arrets(match: dict) -> str:
    """Le détail repliable des arrêts parcourus, montée et descente en gras.

    Chaque arrêt porte entre parenthèses le quartier connu d'`arrets_geo.csv` et,
    s'il y a lieu, la note « au retour » en petit ; sous la liste viennent la
    source de l'itinéraire et le rappel du sens publié.
    """
    arrets = match.get("arrets_trajet") or []
    if not arrets:
        return ""
    quartiers = _quartiers_arrets()
    dernier = len(arrets) - 1
    elements = []
    for i, arret in enumerate(arrets):
        quartier = quartiers.get(arret, "")
        affiche, note = _nom_arret(arret)
        suffixe = (
            f" <span style='color:#6B7A72;font-weight:400;'>"
            f"({_echapper(quartier)})</span>"
            if quartier
            else ""
        )
        note_html = (
            f" <span style='color:#6B7A72;font-size:12px;font-style:italic;'>"
            f"{_echapper(note)}</span>"
            if note
            else ""
        )
        if i in (0, dernier):
            elements.append(
                f"<li style='margin:2px 0;'><b style='color:#081F11;'>"
                f"{_echapper(affiche)}</b>{suffixe}{note_html}</li>"
            )
        else:
            elements.append(
                f"<li style='margin:2px 0;color:#2C4636;'>"
                f"{_echapper(affiche)}{suffixe}{note_html}</li>"
            )
    return (
        "<details style='margin-top:10px;'>"
        "<summary style='color:#0B6B37;font-size:14px;font-weight:700;"
        "cursor:pointer;outline:none;'>Voir les arrêts du trajet</summary>"
        "<ol style='color:#2C4636;font-size:14px;margin:8px 0 0 20px;padding:0;'>"
        f"{''.join(elements)}</ol>"
        f"{_source_trajet(match)}{_note_sens_inverse(match)}</details>"
    )


def _une_carte(
    match: dict,
    etape: str = "",
    depart: str = "",
    arrivee: str = "",
    changement: bool = False,
) -> str:
    """Une ligne : compagnie, numéro, trajet conseillé, arrêts parcourus.

    On ne prétend pas connaître l'arrêt exact de l'utilisateur : on conseille
    l'arrêt le plus proche du lieu qu'il a dit, et on rappelle que tout arrêt de
    la ligne parcouru convient. `changement=True` (1er bus d'une correspondance)
    ajoute « pour changer de bus » à la descente. Les couleurs sont portées en
    propre par chaque bloc (fond clair fixe + texte sombre) : la carte reste
    lisible en mode clair comme en mode sombre, quel que soit le thème Gradio.
    """
    numero = numero_de(match["ligne"])
    affiche = _echapper(re.sub(r"^Ligne\s*", "", str(match["ligne"])))
    rappel = _echapper(nombre_en_wolof(numero) if numero is not None else "")
    entete = (
        f"{_echapper(etape)} · {_echapper(match['compagnie'])}"
        if etape
        else _echapper(match["compagnie"])
    )
    trajet = ""
    if match.get("monte_a") and match.get("descend_a"):
        # Le lieu dit par l'utilisateur, avec l'arrêt conseillé le plus proche.
        monte_a, _ = _nom_arret(match["monte_a"])
        descend_a, _ = _nom_arret(match["descend_a"])
        depart_texte = _echapper(depart if depart else match["monte_a"])
        arrivee_texte = _echapper(arrivee if arrivee else match["descend_a"])
        fin = " pour changer de bus" if changement else ""
        # Arrêt non garanti près du lieu dit (point du lieu inconnu, ou arrêt
        # à plus de 600 m) : on ne montre pas un nom d'arrêt qui risque
        # d'envoyer l'usager à l'autre bout du quartier, on lui dit de
        # chercher l'arrêt le plus proche lui-même.
        conseil_monte = (
            f"— arrêt conseillé : <b style='color:#081F11;'>{_echapper(monte_a)}</b> "
            f"<span style='font-weight:600;font-size:15px;color:#3D5A48;'>"
            f"(ou tout arrêt de la ligne {affiche} près de toi)</span>"
            if not match.get("monte_a_vague")
            else (
                f"<span style='font-weight:600;font-size:15px;color:#3D5A48;'>"
                f": cherche l'arrêt de la ligne {affiche} le plus proche</span>"
            )
        )
        conseil_descente = (
            f"— arrêt conseillé : <b style='color:#081F11;'>{_echapper(descend_a)}</b>"
            if not match.get("descend_a_vague")
            else (
                f"<span style='font-weight:600;font-size:15px;color:#3D5A48;'>"
                f": cherche l'arrêt de la ligne {affiche} le plus proche</span>"
            )
        )
        trajet = (
            f"<div style='color:#11301C;font-size:22px;font-weight:800;"
            f"line-height:1.35;margin-top:8px;'>"
            f"Monte à <b style='color:#081F11;'>{depart_texte}</b> {conseil_monte}<br>"
            f"Descends à <b style='color:#081F11;'>{arrivee_texte}</b> {conseil_descente}{fin}</div>"
        )
    arrets = _bloc_arrets(match)
    # Les terminus de la ligne, en petit : le parcours réel du bus.
    ligne = (
        f"<div style='color:#6B7A72;font-size:13px;margin-top:6px;'>"
        f"Ligne : {_echapper(match['depart'])} → {_echapper(match['arrivee'])}</div>"
    )
    duree = (
        f"<span style='color:#0B6B37;font-weight:700;'>"
        f"~{int(round(float(match['minutes'])))} min"
        # Dem Dikk 11 : un terminus sans position, la durée est un forfait.
        f"{' (durée estimée)' if match.get('estimee') else ''}</span>"
        if match.get("minutes") is not None
        # Positions devinées sur une longue portion (TAF TAF vers l'AIBD) : on
        # ne donne pas de chiffre inventé.
        else "<span style='color:#6B7A72;'>durée inconnue</span>"
        if match.get("duree_inconnue")
        else ""
    )
    # DDD 6, 217, 220, 233 : itinéraire douteux d'après l'audit. On la montre
    # quand même (parfois la seule), mais l'usager doit savoir qu'elle est à vérifier.
    a_confirmer = (
        f"<span style='color:#8A4B00;font-weight:700;'>⚠️ {MENTION_A_CONFIRMER}</span>"
        if match.get("a_confirmer") or ligne_a_confirmer(match)
        else ""
    )
    categorie = " · ".join(
        x for x in (rappel, _echapper(match.get("categorie", "")), duree, a_confirmer) if x
    )
    return f"""
<div style="border:1px solid #D6E6DC;border-top:6px solid {VERT};
            border-radius:12px;padding:16px 20px;margin:8px 0;background:#F6FBF8;">
  <div style="color:{VERT};font-size:12px;font-weight:700;letter-spacing:.14em;
              text-transform:uppercase;">{entete}</div>
  <div style="color:{VERT};font-size:56px;font-weight:800;line-height:1.05;
              margin:4px 0 6px 0;">{affiche}</div>
  {trajet}
  <div style="color:#6B7A72;font-size:13px;margin-top:6px;">
    {categorie}</div>
  {ligne}
  {arrets}
</div>
"""


def _note_distance_pied(depart: str, arrivee: str) -> str:
    """« C'est tout près » quand les deux lieux sont à moins d'un km.

    Texte seulement : la voix reste celle des segments pré-générés, sans nouvelle
    prise. Les bus proposés restent affichés tels quels.
    """
    minutes = MATCHER.geo.minutes_a_pied(depart, arrivee)
    if not minutes:
        return ""
    return (
        "<div style='color:#0B6B37;background:#EAF7EF;border:1px solid #C6E3D2;"
        "border-radius:8px;padding:8px 12px;margin-top:10px;font-size:14px;'>"
        f"C'est tout près : environ {minutes} min à pied</div>"
    )


def _carte_a_pied(a_pied: dict) -> str:
    """La carte de la marche seule, en tête des autres propositions."""

    minutes = int(round(float(a_pied.get("minutes") or 0)))
    distance = int(round(float(a_pied.get("distance_m") or 0)))
    duree = f"environ {minutes} min"
    distance_html = (
        f"<div style='color:#6B7A72;font-size:14px;margin-top:6px;'>"
        f"{distance} m environ</div>"
        if distance
        else ""
    )
    return f"""
<div style="border:1px solid #D6E6DC;border-top:6px solid {VERT};
            border-radius:12px;padding:16px 20px;margin:8px 0;background:#F6FBF8;">
  <div style="color:{VERT};font-size:12px;font-weight:700;letter-spacing:.14em;
              text-transform:uppercase;">À PIED</div>
  <div style="color:{VERT};font-size:28px;font-weight:800;line-height:1.1;
              margin:6px 0 4px 0;">À pied — {duree}</div>
  {distance_html}
</div>
"""


def _cartes_lieux_possibles(
    entete: str, possibles: list[dict], sans_trajet: list[str] | None = None
) -> str:
    """« aéroport » seul : la meilleure possibilité vers chacun des deux aéroports.

    Un bloc titré par aéroport (AIBD à Diass, ancien aéroport LSS à Yoff), avec
    les mêmes cartes qu'une réponse ordinaire. Un seul bloc quand un seul est
    desservi (filtre Tata : aucune Tata ne va à l'AIBD) : son titre dit lequel.
    """
    blocs = [entete]
    if len(possibles) > 1:
        blocs.append(titre_section("✈️ « Aéroport » : il y a deux aéroports, voici les deux"))
    else:
        blocs.append(titre_section("✈️ « Aéroport » : il y a deux aéroports à Dakar"))
    for titre in sans_trajet or []:
        # Dit franchement : aucun trajet v2 vers cet aéroport depuis ce lieu.
        blocs.append(
            "<div style='color:#7A4B00;background:#FFF6E5;border:1px solid #F0D9A8;"
            "border-radius:8px;padding:8px 12px;margin:6px 0;font-size:14px;'>"
            f"✈️ {_echapper(titre)} : aucun trajet en bus trouvé depuis ce lieu "
            "dans nos données.</div>"
        )
    for possible in possibles:
        dep, arr = possible["depart"], possible["arrivee"]
        genre, option = possible["genre"], possible["option"]
        blocs.append(titre_autre_possibilite_texte(f"✈️ {possible['titre']}"))
        if genre == "a_pied":
            blocs.append(_carte_a_pied(option))
        elif genre == "ligne":
            blocs.append(_une_carte(option, depart=dep, arrivee=arr))
        elif genre == "correspondance":
            blocs.append(_une_carte(option["etape_1"], "1er bus", depart=dep, changement=True))
            blocs.append(
                f"<div style='text-align:center;color:#6B7A72;margin:2px 0;'>"
                f"🔁 Change à <b>{_echapper(option['changement'])}</b></div>"
            )
            blocs.append(_une_carte(option["etape_2"], "2e bus", arrivee=arr))
        else:
            etapes = option.get("etapes") or []
            changements = option.get("changements") or []
            for index, etape in enumerate(etapes):
                if index:
                    changement = changements[index - 1] if index - 1 < len(changements) else ""
                    blocs.append(
                        f"<div style='text-align:center;color:#6B7A72;margin:2px 0;'>"
                        f"🔁 Change à <b>{_echapper(changement)}</b></div>"
                    )
                blocs.append(
                    _une_carte(
                        etape,
                        f"{index + 1}er bus" if index == 0 else f"{index + 1}e bus",
                        depart=dep if index == 0 else "",
                        arrivee=arr if index == len(etapes) - 1 else "",
                        changement=index < len(etapes) - 1,
                    )
                )
        if genre != "a_pied":
            blocs.append(
                bouton_partage(
                    dep, arr, possible["resultat"], option if genre != "ligne" else None
                )
            )
    return "".join(blocs)


def _carte(
    resultat: dict,
    depart: str,
    arrivee: str,
    avertissement: str = "",
    bandeau_compagnie: str = "",
) -> str:
    """La réponse en Markdown : compagnie et numéro de ligne mis en avant.

    L'astuce « précise ton lieu » ne figure qu'une fois, au-dessus des cartes,
    et jamais dans chaque carte. `bandeau_compagnie` rappelle d'où vient la
    compagnie (voix ou bouton) ; il précède, lui aussi, les cartes.
    """
    if not depart or not arrivee:
        return (
            "### 🤷 Lieu non détecté\n\n"
            "Je n'ai pas trouvé un départ **et** une arrivée dans ta phrase. "
            "Reformule, ou parle plus près du micro."
        )

    astuce = _astuce_quartier(depart, arrivee)
    possibles = resultat.get("lieux_possibles")
    if possibles:
        # « aéroport » seul : pas de « tout près à pied », qui mesurerait
        # jusqu'à l'un des deux aéroports seulement.
        return _cartes_lieux_possibles(
            bandeau_compagnie + avertissement + astuce,
            possibles,
            resultat.get("lieux_sans_trajet") or [],
        )
    entete = bandeau_compagnie + avertissement + astuce + _note_distance_pied(depart, arrivee)
    lignes = resultat.get("lignes") or []
    correspondances = resultat.get("correspondances") or []
    trajets_2 = resultat.get("trajets_2") or []
    a_pied = resultat.get("a_pied")

    blocs = [entete]
    if a_pied:
        blocs.append(_carte_a_pied(a_pied))

    if lignes:
        blocs.extend(
            _une_carte(match, depart=depart, arrivee=arrivee)
            for match in lignes[:MAX_POSSIBILITES]
        )
        blocs.append(bouton_partage(depart, arrivee, resultat))
        return "".join(blocs)

    if correspondances:
        blocs.append(titre_section("🔁 Pas de bus direct : un changement suffit"))
        for numero, trajet in enumerate(
            correspondances[:MAX_POSSIBILITES], start=1
        ):
            if numero > 1:
                blocs.append(titre_autre_possibilite(numero))
            blocs.append(_une_carte(trajet["etape_1"], "1er bus", depart=depart, changement=True))
            blocs.append(
                f"<div style='text-align:center;color:#6B7A72;margin:2px 0;'>"
                f"🔁 Change à <b>{_echapper(trajet['changement'])}</b></div>"
            )
            blocs.append(_une_carte(trajet["etape_2"], "2e bus", arrivee=arrivee))
            blocs.append(bouton_partage(depart, arrivee, resultat, trajet))

    if trajets_2:
        blocs.append(titre_section("🔁 Avec deux changements"))
        for numero, trajet in enumerate(
            trajets_2[:MAX_POSSIBILITES], start=1
        ):
            if numero > 1:
                blocs.append(titre_autre_possibilite(numero))
            etapes = trajet.get("etapes") or []
            changements = trajet.get("changements") or []
            for index, etape in enumerate(etapes):
                if index:
                    changement = (
                        changements[index - 1]
                        if index - 1 < len(changements)
                        else ""
                    )
                    blocs.append(
                        f"<div style='text-align:center;color:#6B7A72;margin:2px 0;'>"
                        f"🔁 Change à <b>{_echapper(changement)}</b></div>"
                    )
                blocs.append(
                    _une_carte(
                        etape,
                        f"{index + 1}er bus" if index == 0 else f"{index + 1}e bus",
                        depart=depart if index == 0 else "",
                        arrivee=arrivee if index == len(etapes) - 1 else "",
                        changement=index < len(etapes) - 1,
                    )
                )
            blocs.append(bouton_partage(depart, arrivee, resultat, trajet))

    if lignes or correspondances or trajets_2 or a_pied:
        return "".join(blocs)

    inconnus = [
        f"**« {_echapper_markdown(lieu)} »**"
        for lieu, valide in ((depart, resultat["depart_valide"]), (arrivee, resultat["arrivee_valide"]))
        if not valide
    ]
    if inconnus:
        return (
            "### 🗺 Lieu hors réseau\n\n"
            f"Je ne trouve {' ni '.join(inconnus)} sur aucune ligne du jeu de données. "
            "Essaie un quartier ou un arrêt voisin."
        )
    return (
        "### 🗺 Pas de trajet trouvé\n\n"
        f"Je connais **{_echapper_markdown(depart)}** et **{_echapper_markdown(arrivee)}**, "
        "mais aucune ligne ni aucun trajet avec un ou deux changements ne les "
        "relie dans le jeu de données."
    )


def _mention(intent: dict, modele_asr: str = "") -> str:
    """Notes sous la réponse : modèle de transcription utilisé, extraction de secours."""
    notes = []
    if modele_asr:
        notes.append(f"_Transcription : {_echapper(modele_asr)}_")
    if intent.get("source") == "local":
        notes.append(
            "> ⚠️ **Extraction de secours (sans LLM)** — l'API NVIDIA était "
            "indisponible, la détection a été faite sur place."
        )
    elif intent.get("erreur"):
        # Le texte de l'erreur cite le modèle et le statut HTTP : il reste au journal.
        notes.append("> ⚠️ Je n'ai pas tout compris : reformule si la réponse ne convient pas.")
    return "\n\n".join(notes)


# --------------------------------------------------------------------------- #
# Compagnie
# --------------------------------------------------------------------------- #


def _bandeau_autre_compagnie(compagnie: str, resultat: dict) -> str:
    """Le bandeau « aucune ligne <compagnie> » posé au-dessus du résultat de secours.

    Le texte lui-même est partagé avec les tests (matching.compagnie) ; ici on
    l'habille du fond jaune qui distingue un avertissement d'une réponse normale.
    """
    return (
        "<div style='color:#7A5A00;background:#FFF7E0;border:1px solid #F0DFA8;"
        "border-radius:8px;padding:8px 12px;margin:10px 0;font-size:14px;font-weight:600;'>"
        + _echapper(message_autre_compagnie(compagnie, resultat))
        + "</div>\n\n"
    )


NOMS_COMPAGNIES = {"Tata AFTU": "Tata", "Dakar Dem Dikk": "Dem Dikk"}


def _bandeau_compagnie(
    compagnie_voix: str, compagnie_bouton: str, mode: str = "texte"
) -> str:
    """Rappelle la compagnie réellement utilisée, au-dessus des cartes.

    La compagnie dite à la voix l'emporte sur le bouton. En mode texte, une
    compagnie explicitement écrite dans la phrase l'emporte aussi (comportement
    historique des phrases « ... ak Tata »). Sinon on affiche le bouton tel
    qu'il est au moment de la recherche, y compris « Tous » : après un passage
    de Tata à Dem Dikk, l'étiquette ne doit jamais rester sur l'ancien choix.
    """
    if compagnie_voix:
        nom = NOMS_COMPAGNIES.get(compagnie_voix, compagnie_voix)
        mention = (
            "dite à la voix, prioritaire sur le bouton"
            if mode == "voix"
            else "indiquée dans ton texte"
        )
    else:
        nom = NOMS_COMPAGNIES.get(compagnie_bouton, compagnie_bouton) or "Tous"
        mention = "choisie avec le bouton"
    return (
        "<div style='color:#0B6B37;background:#EAF6EF;border:1px solid #C7E6D4;"
        "border-radius:8px;padding:8px 12px;margin:10px 0;font-size:14px;"
        "font-weight:600;'>"
        f"Compagnie : {_echapper(nom)} ({mention})</div>\n\n"
    )


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


def _journal(modele_asr: str, duree_asr: float, nombre_lignes: int, erreur: str = "") -> None:
    """Une ligne de diagnostic, sans aucune donnée personnelle.

    On ne journalise que le modèle ASR, la durée, le nombre de lignes trouvées
    et un code d'erreur générique. Jamais la transcription, les lieux ni le
    texte de l'utilisateur : les logs du Space sont visibles par les admins.
    """
    print(
        f"[trajet] ASR={modele_asr or 'texte'} "
        f"durée={max(duree_asr, 0.0):.1f}s lignes={int(nombre_lignes)} "
        f"erreur={erreur or '-'}",
        flush=True,
    )


def _code_erreur(intent: dict) -> str:
    """Un code d'erreur stable pour les logs, jamais le message brut."""
    if not intent.get("erreur"):
        return ""
    return "extraction_locale" if intent.get("source") == "local" else "extraction_llm"


# Ce que la collecte doit savoir d'une réponse, sans changer les sorties du
# pipeline. Reste à None hors collecte : _noter ne fait alors rien.
_TRACE: contextvars.ContextVar[dict | None] = contextvars.ContextVar("trace_collecte", default=None)


def _noter(**champs) -> None:
    trace = _TRACE.get()
    if trace is not None:
        trace.update(champs)


def _pipeline(
    phrase: str,
    modele_asr: str,
    duree_asr: float,
    compagnie_choix: str = "",
    mode: str = "texte",
) -> tuple:
    """À partir d'une phrase transcrite : extraction, recherche, réponse.

    C'est ce que trouver_le_bus faisait après la transcription, isolé pour pouvoir
    rejouer tout le traitement sur la seconde transcription. `mode` distingue une
    demande tapée d'une demande vocale : il ne change pas la recherche, seulement
    la façon dont le bandeau explique d'où vient la compagnie. Renvoie le
    quintuplet des sorties, suivi d'un booléen : un trajet a-t-il été trouvé ?
    """
    quint = ("", "", _carte({}, "", ""), None, "")
    phrase = (phrase or "").strip()[:TEXTE_MAX]
    if not phrase:
        _journal(modele_asr, duree_asr, 0, "phrase_vide")
        return quint, False
    _noter(repondu=True, phrase=phrase, modele_asr=modele_asr)

    # L'extraction gère elle-même son repli local : si l'API est saturée, elle
    # rend quand même un départ et une arrivée tant que la phrase les porte.
    # L'extraction locale d'abord : elle ne connaît que les arrêts du réseau et
    # ne se trompe pas de numéro (le LLM a déjà rendu « liberti sënk » en
    # Liberté 6). Le LLM ne sert que si elle ne trouve pas un trajet complet.
    local = extract_local(phrase)
    # Petite conversation seulement sans aucun lieu : une demande de trajet gagne
    # toujours (« salam, dama bëgga dem Médina » est un trajet). Les usagers
    # saluent d'abord puis demandent : si la phrase a la forme d'une demande
    # (« damay dem X », « maa ngi X ») sans lieu reconnu localement, le LLM
    # passe avant la salutation. Vu en production : « Salaam aleekum, man damay
    # dem Petersen te maa ngi Ouakam » a reçu trois fois « Maalekum salaam ».
    intention = None
    if not local.get("depart") and not local.get("arrivee"):
        intention = detecter_conversation(phrase)
        if intention is not None and not signal_trajet(phrase):
            return _reponse_conversation(phrase, intention, modele_asr, duree_asr), True
    intent = None
    if local.get("depart") and local.get("arrivee"):
        essai = MATCHER.find_line(local["depart"], local["arrivee"])
        # Même lieu des deux côtés : extraction incomplète, le LLM relit la phrase.
        if (essai["found"] or essai["correspondances"]) and not _meme_lieu(
            local["depart"], local["arrivee"], essai
        ):
            intent = {**local, "source": "reseau", "erreur": None}
    if intent is None:
        intent = (
            extract_intent(phrase, client=_client_llm())
            if _llm_autorise()
            else _repli_local(phrase, "plafond_app")
        )
    depart, arrivee = intent.get("depart") or "", intent.get("arrivee") or ""
    _noter(depart=depart, arrivee=arrivee)

    if not depart and not arrivee:
        # Aucun lieu, même pour le LLM. Une salutation reçoit alors sa réponse
        # habituelle (« Maalekum salaam ! Fan nga bëgga dem ? » redemande le
        # trajet), sinon « hors sujet ». Dans les deux cas, pas de trajet :
        # False laisse sa chance à l'autre modèle ASR.
        quint = _reponse_conversation(phrase, intention or HORS_SUJET, modele_asr, duree_asr)
        return quint[:4] + (_mention(intent, modele_asr),), False
    if not depart or not arrivee:
        _journal(modele_asr, duree_asr, 0, "lieu_manquant")
        return (phrase, "", _carte({}, depart, arrivee), None, _mention(intent, modele_asr)), False

    resultat = MATCHER.find_line(depart, arrivee)

    # Le LLM peut renvoyer un nom hors du réseau (« Marché Liberté », « Géejewaay »)
    # alors que l'extraction locale, alignée sur les arrêts, trouve le bon couple.
    # Si elle mène à une ligne, on la garde.
    if not resultat["found"] and intent.get("source") != "local":
        local = extract_local(phrase)
        if local.get("depart") and local.get("arrivee"):
            essai = MATCHER.find_line(local["depart"], local["arrivee"])
            if essai["found"] or (essai["correspondances"] and not resultat["correspondances"]):
                depart, arrivee, resultat = local["depart"], local["arrivee"], essai
                intent = {**intent, "source": "llm+local"}

    # Toujours le même lieu après le LLM (qui a relu la phrase entière) : jamais
    # de bus ni de « À pied 0 min ». On redemande d'où l'usager part et où il va,
    # avec une phrase déjà enregistrée.
    if _meme_lieu(depart, arrivee, resultat):
        quint = _reponse_conversation(phrase, DEMANDE_MEME_LIEU, modele_asr, duree_asr)
        return quint[:4] + (_mention(intent, modele_asr),), False

    # Compagnie : ce que l'utilisateur a dit à la voix prime sur le bouton.
    compagnie_voix = (intent.get("compagnie") or "").strip()
    compagnie = compagnie_voix or compagnie_choix or ""
    avertissement = ""
    if compagnie:
        # On cherche d'abord dans la compagnie (directe, puis correspondance avec
        # ses deux bus). Sans solution propre, find_line_compagnie retombe sur le
        # réseau entier et `exacte` vaut False : on affiche alors le bandeau.
        resultat, exacte = MATCHER.find_line_compagnie(depart, arrivee, compagnie)
        if not exacte and (resultat["found"] or resultat.get("correspondances")):
            avertissement = _bandeau_autre_compagnie(compagnie, resultat)
    bandeau_compagnie = _bandeau_compagnie(compagnie_voix, compagnie_choix, mode=mode)
    trajets_2 = resultat.get("trajets_2") or []
    trouve = bool(
        resultat["found"]
        or resultat.get("correspondances")
        or trajets_2
        or resultat.get("a_pied")
    )

    nombre_lignes = (
        len(resultat["lignes"])
        + len(resultat.get("correspondances") or [])
        + len(trajets_2)
    )
    _journal(modele_asr, duree_asr, nombre_lignes, _code_erreur(intent))
    if _TRACE.get() is not None:
        _noter(
            depart=depart,
            arrivee=arrivee,
            lignes=collecte.lignes_proposees(resultat, MAX_POSSIBILITES),
        )

    return (
        phrase,
        f"{depart} → {arrivee}",
        _carte(resultat, depart, arrivee, avertissement, bandeau_compagnie),
        _voix_wolof(
            resultat["lignes"],
            resultat.get("correspondances"),
            trajets_2,
            resultat.get("lieux_possibles"),
        ),
        _mention(intent, modele_asr),
    ), trouve


# Les dossiers où Gradio dépose l'audio reçu du navigateur. Seuls les
# fichiers rangés là sont effacés : un chemin pris ailleurs (un audio de
# data/demo_audio/ passé par un test) n'est jamais touché.
def _dossiers_audio_recu() -> list[Path]:
    dossiers = [Path(tempfile.gettempdir()) / "gradio"]
    if os.getenv("GRADIO_TEMP_DIR"):
        dossiers.append(Path(os.environ["GRADIO_TEMP_DIR"]))
    return [dossier.resolve() for dossier in dossiers]


def _effacer_audio_recu(audio: str | None) -> bool:
    """Efface l'enregistrement de l'usager dès qu'il est en mémoire.

    « Ta voix n'est pas enregistrée » : une fois l'audio décodé, la
    transcription (et sa seconde chance) travaillent sur le tableau en
    mémoire, le fichier ne sert plus. Vrai si un fichier a été effacé.
    """
    if not audio:
        return False
    try:
        chemin = Path(audio).resolve()
    except (OSError, ValueError):
        return False
    if not any(chemin.is_relative_to(dossier) for dossier in _dossiers_audio_recu()):
        return False
    try:
        chemin.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def trouver_le_bus(audio: str | None, phrase_ecrite: str, compagnie_choix: str = "") -> tuple:
    """Le pipeline complet, du micro ou du texte jusqu'à la réponse.

    Le micro l'emporte sur le texte : si un enregistrement arrive, on le transcrit
    (Kiriku sur GPU, whisper CPU en secours, et une seconde chance avec l'autre
    modèle si la première transcription ne mène à aucun trajet). La compagnie dite
    à la voix l'emporte sur le bouton. Les cinq retours correspondent aux cinq
    sorties de l'interface.
    """
    vide = ("", "", _carte({}, "", ""), None, "")

    if audio:
        try:
            son = _decoder_audio(audio)
        except AudioRefuse as exc:
            _effacer_audio_recu(audio)
            return ("", "", f"### 🎤 {_echapper(str(exc))}", None, "")
        except Exception as exc:
            _effacer_audio_recu(audio)
            print(f"[audio] illisible ({type(exc).__name__})", flush=True)
            return ("", "", CARTE_AUDIO_ILLISIBLE, None, "")
        # Décodé, l'audio est en mémoire : le fichier de l'usager disparaît.
        _effacer_audio_recu(audio)
        if son is None or len(son) < SAMPLE_RATE * 0.3:
            # Moins de 0,3 s : clic involontaire sur le micro, rien à chercher.
            return vide
        # Hors collecte, il n'y a pas de trace : l'audio ne sort jamais de cette fonction.
        trace = _TRACE.get()
        if trace is not None:
            trace["son"] = son
        try:
            phrase, modele_asr, duree_asr, _ = transcrir_avec_seconde_chance(
                son,
                _transcrire_premier,
                _second_essai,
                _phrase_donne_un_trajet,
            )
        except Exception as exc:
            print(f"[ASR] transcription impossible ({type(exc).__name__})", flush=True)
            return ("", "", CARTE_TRANSCRIPTION_IMPOSSIBLE, None, "")
        if not phrase:
            return vide
        quint, _ = _pipeline(
            phrase, modele_asr, duree_asr, compagnie_choix, mode="voix"
        )
        return quint

    phrase = (phrase_ecrite or "").strip()[:TEXTE_MAX]
    if not phrase:
        return vide
    quint, _ = _pipeline(phrase, "", 0.0, compagnie_choix, mode="texte")
    return quint


def _court(exc: Exception, longueur: int = 160) -> str:
    """Un message d'erreur court : les exceptions techniques font plusieurs lignes."""
    return f"{type(exc).__name__} : {exc}"[:longueur]


def _resume_erreur_gpu(exc: BaseException, longueur: int = 220) -> str:
    """Résumé d'un refus ZeroGPU pour le journal : type, message, cause, lieu.

    En ligne, le journal disait seulement « ZeroGPU en échec (RuntimeError) » :
    le message levé par spaces/zero/wrappers.py (torch.init) était vide ou
    perdu. On ajoute donc la première ligne du message, celle de la cause
    chaînée (__cause__ / __context__), et le dernier cadre de la trace (nom de
    fichier seul, sans chemin). Rien ici ne vient de l'utilisateur : ni audio,
    ni phrase, ni secret.
    """
    import traceback

    def premiere_ligne(e: BaseException) -> str:
        texte = str(e).strip().splitlines()
        return texte[0][:120] if texte else ""

    morceaux = [type(exc).__name__]
    message = premiere_ligne(exc)
    if message:
        morceaux.append(message)
    cause = exc.__cause__ or exc.__context__
    if cause is not None:
        detail = premiere_ligne(cause)
        morceaux.append(f"cause {type(cause).__name__}" + (f" : {detail}" if detail else ""))
    cadres = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    if cadres:
        dernier = cadres[-1]
        morceaux.append(f"à {Path(dernier.filename).name}:{dernier.lineno} {dernier.name}")
    return " | ".join(morceaux)[:longueur]


# Affichée sous la saisie : ce qui part, et où.
NOTE_VIE_PRIVEE = (
    "Ta voix n'est pas enregistrée. Pour comprendre ton trajet, le texte peut "
    "être envoyé à un service d'IA (NVIDIA) et les noms de lieux à OpenStreetMap."
)
# La même note quand la collecte est allumée (COLLECTE_ACTIVE).
NOTE_VIE_PRIVEE_COLLECTE = (
    "Ta voix est gardée pour améliorer le wolof, sans ton nom ni ton numéro (sinon, "
    "utilise Écrire). Si tu donnes ton avis, il est gardé avec les lieux compris et les lignes "
    "proposées. Pour comprendre ton trajet, le texte peut être envoyé "
    "à un service d'IA (NVIDIA) et les noms de lieux à OpenStreetMap."
)

MESSAGE_DEMANDE_VIDE = "Écris ton trajet ou choisis un trajet fréquent"


def _sortie_demande_vide() -> tuple:
    """Le quintuplet affiché quand ni le micro ni le texte ne portent une demande."""
    carte = "### ✍️ À toi de jouer\n\n" + MESSAGE_DEMANDE_VIDE
    return ("", "", carte, None, "")


def _sortie_trop_de_demandes() -> tuple:
    return ("", "", CARTE_TROP_DE_DEMANDES, None, "")


def traiter_demande(
    audio: str | None,
    phrase_ecrite: str,
    compagnie_choix: str = "",
    etat: dict | None = None,
    nouvelle_demande: bool = True,
    request: gr.Request | None = None,
) -> tuple:
    """Identifie le client le temps de la demande (Gradio fournit `request`)."""
    cle = cle_client(request)
    jeton = _CLE_CLIENT.set(cle)
    try:
        return _traiter_demande(audio, phrase_ecrite, compagnie_choix, etat, nouvelle_demande, cle)
    finally:
        _CLE_CLIENT.reset(jeton)


def _traiter_demande(
    audio: str | None,
    phrase_ecrite: str,
    compagnie_choix: str,
    etat: dict | None,
    nouvelle_demande: bool,
    cle: str | None,
) -> tuple:
    """Le seul handler du bouton, du micro et du changement de compagnie.

    Les sept sorties sont : les cinq résultats, le micro d'entrée et l'état de la
    dernière demande. Une nouvelle demande vient du micro (mode « voix ») ou du
    texte (mode « texte »). Un changement de compagnie relit cet état sans
    retranscrire l'audio : la phrase et son mode suffisent, et le bouton courant
    est utilisé pour la recherche et le bandeau.
    """
    compagnie_choix = compagnie_choix or ""

    if not nouvelle_demande:
        if not isinstance(etat, dict):
            return tuple(gr.skip() for _ in range(7))
        phrase = (etat.get("phrase") or "").strip()
        if not phrase:
            return tuple(gr.skip() for _ in range(7))
        mode = etat.get("mode") or "texte"
        if not LIMITE_TRAJETS_CLIENT.autoriser(cle):
            return (*_sortie_trop_de_demandes(), gr.skip(), etat)
        _noter(traitee=True, client=cle)
        quint, _ = _pipeline(phrase, "", 0.0, compagnie_choix, mode=mode)
        # Le micro et la demande restent tels quels : on ne retranscrit rien.
        return (*quint, gr.skip(), etat)

    _noter(traitee=True, client=cle)
    if (audio or (phrase_ecrite or "").strip()) and not LIMITE_TRAJETS_CLIENT.autoriser(cle):
        # Refusé avant tout décodage, mais le fichier reçu ne doit pas rester.
        _effacer_audio_recu(audio)
        return (*_sortie_trop_de_demandes(), None, etat)
    if audio:
        quint = trouver_le_bus(audio, phrase_ecrite, compagnie_choix)
        if not quint[0]:
            return (*quint, None, None)
        return (*quint, None, {"phrase": quint[0], "mode": "voix"})

    phrase = (phrase_ecrite or "").strip()[:TEXTE_MAX]
    if not phrase:
        return (*_sortie_demande_vide(), None, None)
    quint = trouver_le_bus(None, phrase, compagnie_choix)
    return (*quint, None, {"phrase": phrase, "mode": "texte"})


def repondre_et_vider_micro(
    audio: str | None,
    phrase_ecrite: str,
    compagnie_choix: str = "",
    request: gr.Request | None = None,
) -> tuple:
    """Version à six sorties conservée pour l'API et les anciens tests.

    L'interface utilise `traiter_demande`, qui ajoute l'état nécessaire au
    changement de compagnie. Le sixième retour remet le micro à None pour
    l'enregistrement suivant, sans toucher aux cartes ni à la voix.
    """
    return traiter_demande(audio, phrase_ecrite, compagnie_choix, None, True, request)[:6]


def choisir_trajet_frequent(
    choix: str | None,
    compagnie_choix: str = "",
    request: gr.Request | None = None,
) -> tuple:
    """Remplir la phrase wolof, lancer la recherche, puis vider la liste.

    Les neuf sorties sont : la phrase, les sept résultats (dont l'état) et la
    liste remise à None. Vider la liste émet un change ; il est ignoré par le
    garde du début, donc aucun second calcul.
    """
    if not isinstance(choix, str) or choix not in CHOIX_TRAJETS_FREQUENTS:
        return tuple(gr.skip() for _ in range(9))
    trajet = CHOIX_TRAJETS_FREQUENTS[choix]
    phrase = f"Maa ngi {trajet['depart']}, bëgg naa dem {trajet['arrivee']}"
    resultat = traiter_demande(None, phrase, compagnie_choix, None, True, request)
    return (phrase, *resultat, None)


# Un même geste peut déclencher plusieurs événements Gradio : arrêter le micro
# émet change puis stop_recording, déposer un fichier émet upload puis change.
# Sans garde-fou, le pipeline partirait deux fois sur le même audio.
_DERNIERE_RECHERCHE: tuple | None = None
_FENETRE_DOUBLON = 2.0


def rechercher_une_fois(
    audio: str | None,
    phrase_ecrite: str,
    compagnie_choix: str = "",
    etat: dict | None = None,
    request: gr.Request | None = None,
) -> tuple:
    """Lancer une demande une seule fois par audio, jamais sur un micro vidé.

    Le vidage automatique remet le composant à None et émet un change : sans ce
    garde, la phrase encore dans la zone texte relancerait une recherche et
    effacerait le résultat qu'on vient d'afficher. Un micro vide est donc ignoré
    silencieusement. Les doublons d'un même geste renvoient gr.skip() pour garder
    les cartes déjà calculées.
    """
    global _DERNIERE_RECHERCHE
    if not audio:
        return tuple(gr.skip() for _ in range(7))
    cle = (audio, (phrase_ecrite or "").strip(), compagnie_choix or "")
    maintenant = time.monotonic()
    if (
        _DERNIERE_RECHERCHE is not None
        and _DERNIERE_RECHERCHE[0] == cle
        and maintenant - _DERNIERE_RECHERCHE[1] < _FENETRE_DOUBLON
    ):
        return tuple(gr.skip() for _ in range(7))
    _DERNIERE_RECHERCHE = (cle, maintenant)
    return traiter_demande(audio, phrase_ecrite, compagnie_choix, etat, True, request)


# --------------------------------------------------------------------------- #
# Collecte (branchée seulement si COLLECTE_ACTIVE est allumée) : utiliser l'onglet
# Parler vaut accord, décision du propriétaire du projet ; Écrire ne garde jamais de voix.
# --------------------------------------------------------------------------- #


def _suivre(fonction, *args) -> tuple:
    """Appelle un handler existant et recueille ce que le pipeline a noté."""
    trace: dict = {}
    jeton = _TRACE.set(trace)
    try:
        return fonction(*args), trace
    finally:
        _TRACE.reset(jeton)


def _sorties_collecte(trace: dict, suivi: dict | None, nouvelle: bool) -> tuple:
    """Suivi, panneau d'avis, message du code, temps saisi.

    Toute erreur s'arrête ici : la réponse de bus est déjà calculée et doit
    partir. Le journal ne dit que le type d'erreur, sans donnée de l'usager.
    """
    if not trace.get("traitee"):
        # Doublon d'un même geste : l'écran garde ce qu'il affiche.
        return tuple(gr.skip() for _ in range(4))
    masque = (None, gr.update(visible=False), "", gr.update(value=None))
    if not trace.get("repondu"):
        return masque
    try:
        if nouvelle or not suivi:
            suivi, message = collecte.nouveau_suivi(trace)
            temps = gr.update(value=None)
        else:
            suivi, message, temps = collecte.suivi_mis_a_jour(suivi, trace), gr.skip(), gr.skip()
    except Exception as exc:
        print(f"[collecte] contribution ignorée ({type(exc).__name__})", flush=True)
        return masque
    return suivi, gr.update(visible=bool(suivi["lignes"])), message, temps


def traiter_demande_collecte(
    audio, phrase_ecrite, compagnie_choix="", etat=None, nouvelle_demande=True,
    suivi=None, request: gr.Request | None = None,
) -> tuple:
    sortie, trace = _suivre(
        traiter_demande, audio, phrase_ecrite, compagnie_choix, etat, nouvelle_demande, request,
    )
    return (*sortie, *_sorties_collecte(trace, suivi, nouvelle_demande))


def rechercher_une_fois_collecte(
    audio, phrase_ecrite, compagnie_choix="", etat=None, suivi=None,
    request: gr.Request | None = None,
) -> tuple:
    sortie, trace = _suivre(rechercher_une_fois, audio, phrase_ecrite, compagnie_choix, etat, request)
    return (*sortie, *_sorties_collecte(trace, suivi, True))


def choisir_trajet_frequent_collecte(
    choix, compagnie_choix="", suivi=None, request: gr.Request | None = None,
) -> tuple:
    sortie, trace = _suivre(choisir_trajet_frequent, choix, compagnie_choix, request)
    return (*sortie, *_sorties_collecte(trace, suivi, True))


def donner_avis(reponse: str, minutes, suivi: dict | None, request: gr.Request | None = None) -> tuple:
    """Oui / Non / Je ne sais pas, avec le temps réel s'il est déjà saisi."""
    if not suivi or not collecte.avis_autorise(cle_client(request)):
        return gr.skip(), gr.skip()
    try:
        return collecte.noter_avis(suivi, reponse, collecte.minutes_valides(minutes))
    except Exception as exc:
        print(f"[collecte] avis ignoré ({type(exc).__name__})", flush=True)
        return gr.skip(), gr.skip()


# Gradio ne fournit `request` qu'aux fonctions annotées : pas de functools.partial ici.
def avis_oui(minutes, suivi: dict | None, request: gr.Request | None = None) -> tuple:
    return donner_avis("oui", minutes, suivi, request)


def avis_non(minutes, suivi: dict | None, request: gr.Request | None = None) -> tuple:
    return donner_avis("non", minutes, suivi, request)


def avis_ne_sait_pas(minutes, suivi: dict | None, request: gr.Request | None = None) -> tuple:
    return donner_avis("ne_sait_pas", minutes, suivi, request)


def donner_temps(minutes, suivi: dict | None, request: gr.Request | None = None) -> tuple:
    """Le temps réel, souvent connu seulement à la fin du trajet."""
    if not suivi:
        return gr.skip(), gr.skip()
    valeur = collecte.minutes_valides(minutes)
    if valeur is None:
        return gr.skip(), collecte.MESSAGE_MINUTES
    if not collecte.avis_autorise(cle_client(request)):
        return gr.skip(), gr.skip()
    try:
        return collecte.noter_avis(suivi, None, valeur)
    except Exception as exc:
        print(f"[collecte] avis ignoré ({type(exc).__name__})", flush=True)
        return gr.skip(), gr.skip()


def _echauffer_llm():
    """Appel de chauffe à l'API NVIDIA, en arrière-plan au démarrage.

    Le premier appel de Llama d'une instance prend ~13 s (« modèle froid »). En le
    déclenchant dès l'ouverture du Space, le premier visiteur ne paie pas cette
    attente. L'échec n'est qu'un bruit dans les logs : l'extraction fonctionne de
    toute façon en local.
    """
    try:
        client = _client_llm()
        if client is None:
            return
        extract_intent("maa ngi Ouakam, bëgg naa dem Palais 2", client=client)
    except Exception as exc:
        print(f"[LLM] échauffement ignoré ({_court(exc)})", flush=True)


# Thread détaché pour ne pas bloquer le démarrage du Space : le préchargement
# whisper et l'échauffement de l'API avancent chacun de leur côté.
_THREAD_CHAUFFE = threading.Thread(target=_echauffer_llm, name="echauffement-llm", daemon=True)
if not MODE_TEST:
    _THREAD_CHAUFFE.start()


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #

TRAJETS_FREQUENTS_FICHIER = RACINE / "data" / "trajets_frequents.json"
MICRO_ELEM_ID = "micro_guindima"


def _charger_trajets_frequents(
    chemin: Path = TRAJETS_FREQUENTS_FICHIER,
) -> list[dict[str, str]]:
    """Charge et valide la liste proposée dans l'onglet « Écrire ».

    Le fichier est petit et lu une seule fois au démarrage. On refuse les clés
    inconnues et les doublons : une faute de frappe doit se voir au lancement,
    pas se traduire par un choix qui ne fait rien sur le téléphone.
    """
    with open(chemin, encoding="utf-8") as fichier:
        donnees = json.load(fichier)
    if not isinstance(donnees, list):
        raise ValueError("data/trajets_frequents.json doit contenir une liste")

    trajets: list[dict[str, str]] = []
    deja_vus: set[tuple[str, str]] = set()
    for entree in donnees:
        if not isinstance(entree, dict) or set(entree) != {"depart", "arrivee"}:
            raise ValueError(f"trajet fréquent invalide : {entree!r}")
        depart = str(entree["depart"]).strip()
        arrivee = str(entree["arrivee"]).strip()
        if not depart or not arrivee:
            raise ValueError(f"trajet fréquent vide : {entree!r}")
        cle = (depart, arrivee)
        if cle in deja_vus:
            raise ValueError(f"trajet fréquent en double : {depart} → {arrivee}")
        deja_vus.add(cle)
        trajets.append({"depart": depart, "arrivee": arrivee})
    print(f"[trajets fréquents] {len(trajets)} trajets chargés", flush=True)
    return trajets


def _libelle_trajet_frequent(trajet: dict[str, str]) -> str:
    return f"{trajet['depart']} → {trajet['arrivee']}"


TRAJETS_FREQUENTS = _charger_trajets_frequents()
CHOIX_TRAJETS_FREQUENTS = {
    _libelle_trajet_frequent(trajet): trajet for trajet in TRAJETS_FREQUENTS
}


def _theme():
    """Thème vert Sénégal.

    colors.hsl est la voie documentée pour passer une couleur exacte à un thème ;
    si l'API bouge, on retombe sur le nom « green » plutôt que de planter au
    démarrage du Space.
    """
    try:
        from gradio.themes.utils import colors

        return gr.themes.Soft(primary_hue=colors.hsl(146, 0.90, 0.31))
    except Exception:
        return gr.themes.Soft(primary_hue="green")


# Les classes .record-button, .stop-button et .mic-select viennent du frontend
# Gradio 6.30.0 installé (assets/audio-*.css), pas d'une supposition : les
# boutons du micro changent de nom entre les versions. Tout est limité à
# #micro_guindima pour ne pas toucher les autres composants Audio.
CSS_GUINDIMA = r"""
#consigne_micro {
    --body-text-color: #064E2B !important;
    --block-label-text-color: #064E2B !important;
    --link-text-color: #064E2B !important;
    background: #E8F5EE !important;
    border: 1px solid #C7E6D4;
    border-left: 5px solid #00853F;
    border-right: 5px solid #00853F;
    border-radius: 10px;
    font-size: 18px;
    font-weight: 700;
    line-height: 1.35;
    margin: 0 0 10px 0;
    padding: 12px 14px;
}
.dark #consigne_micro {
    --body-text-color: #064E2B !important;
    --block-label-text-color: #064E2B !important;
    --link-text-color: #064E2B !important;
}
#consigne_micro,
#consigne_micro p,
#consigne_micro strong,
#consigne_micro span,
.dark #consigne_micro,
.dark #consigne_micro p,
.dark #consigne_micro strong,
.dark #consigne_micro span {
    color: #064E2B !important;
}
#consigne_micro,
#consigne_micro *,
.dark #consigne_micro,
.dark #consigne_micro * {
    color: #064E2B !important;
}
#consigne_micro p { margin: 0; }

#micro_guindima .mic-wrap,
#micro_guindima .controls,
#micro_guindima .wrapper {
    width: 100%;
}
#micro_guindima .mic-wrap { margin: 0; }
#micro_guindima .controls { justify-content: center; }
#micro_guindima .wrapper { justify-content: center; }

#micro_guindima .record-button,
#micro_guindima .stop-button {
    align-items: center;
    border: 0 !important;
    border-radius: 14px;
    box-sizing: border-box;
    color: #FFFFFF;
    cursor: pointer;
    display: flex;
    font-size: 20px;
    font-weight: 800;
    justify-content: center;
    line-height: 1.1;
    min-height: 64px;
    padding: 0 20px;
    touch-action: manipulation;
}
#micro_guindima .record-button {
    background: #00853F;
    box-shadow: 0 4px 14px rgba(0, 133, 63, 0.35);
    flex: 1 1 100%;
    width: 100%;
}
#micro_guindima .record-button::before {
    background: none;
    border-radius: 0;
    content: "🎙️";
    height: auto;
    margin: 0 10px 0 0;
    width: auto;
}
#micro_guindima .record-button:active { transform: translateY(1px); }
#micro_guindima .record-icon { display: none !important; }

#micro_guindima .stop-button {
    background: #D62828;
    animation: guindima-pulse 1.2s ease-in-out infinite;
    align-self: center;
    flex: 0 0 25%;
    margin: 0 auto !important;
    margin-top: 14px !important;
    min-width: 120px;
    width: 25%;
}
#micro_guindima .stop-button::before {
    background: none;
    border-radius: 0;
    content: "⏹️";
    height: auto;
    margin: 0 10px 0 0;
    width: auto;
}
#micro_guindima .stop-button-paused { background: #D62828; color: #FFFFFF; }

#micro_guindima .mic-select { display: none !important; }

/* La croix du composant Audio efface l'enregistrement avant qu'il soit traité.
   Le DOM Gradio 6.30.0 la rend en <button class="icon-button" aria-label="Effacer">. */
#micro_guindima .icon-button-wrapper.top-panel button[aria-label="Effacer"],
#micro_guindima .icon-button-wrapper.top-panel button[aria-label="Clear"] {
    display: none !important;
}

/* Toute la ligne d'une option est cliquable. Les options sont parfois portées
   hors de #trajets_frequents (position:fixed) : on cible aussi .options, sachant
   qu'il n'y a qu'un seul Dropdown dans cette interface. */
#trajets_frequents .item,
.options .item {
    align-items: center;
    box-sizing: border-box;
    cursor: pointer;
    display: flex;
    justify-content: flex-start;
    min-height: 44px;
    padding: 10px 12px;
    width: 100%;
}
#trajets_frequents .item:hover,
.options .item:hover,
#trajets_frequents .item.selected,
.options .item.selected {
    background: #E8F5EE;
    color: #064E2B;
}

@keyframes guindima-pulse {
    0%, 100% { box-shadow: 0 4px 14px rgba(214, 40, 40, 0.35); }
    50% { box-shadow: 0 4px 24px rgba(214, 40, 40, 0.75); }
}
@media (prefers-reduced-motion: reduce) {
    #micro_guindima .stop-button { animation: none; }
}
"""

I18N_GUINDIMA = (
    gr.I18n(
        fr={"audio.record": "Appuie et parle", "audio.stop": "Arrête"},
        en={"audio.record": "Appuie et parle", "audio.stop": "Arrête"},
    )
    if gr is not None
    else None
)


def _construire():
    # delete_cache : en plus de l'effacement juste après la transcription,
    # Gradio vide toutes les 10 min ses fichiers de plus de 10 min (filet de
    # sécurité si un audio n'arrive jamais jusqu'à la transcription).
    # Collecte éteinte (défaut) : aucun composant ni handler de plus.
    actif = collecte.collecte_active()
    with gr.Blocks(title="GuindiMa AI 🚌", delete_cache=(600, 600)) as interface:
        gr.Markdown("# GuindiMa AI 🚌\n### Wax ma fi nga jëm, ma won la bus bi")
        gr.Markdown(
            "Dis-moi où tu vas, je te montre le bus. "
            "Parle ou écris ton trajet en wolof, à Dakar."
        )

        # Les sorties sont créées hors écran : elles servent au bouton, au micro
        # et à la liste de trajets avant d'être affichées plus bas.
        transcription_out = gr.Textbox(label="Transcription", interactive=False, render=False)
        trajet_out = gr.Textbox(label="Départ → arrivée", interactive=False, render=False)
        mention_out = gr.Markdown(render=False)
        carte_out = gr.Markdown(render=False)
        audio_out = gr.Audio(label="Réponse en wolof", autoplay=True, render=False)
        sorties = [transcription_out, trajet_out, carte_out, audio_out, mention_out]

        with gr.Tab("Parler"):
            gr.Markdown(
                "**Appuie sur le bouton vert, dis ton trajet, puis appuie sur Arrête**",
                elem_id="consigne_micro",
            )
            audio_in = gr.Audio(
                sources=["microphone", "upload"],
                type="filepath",
                show_label=False,
                elem_id=MICRO_ELEM_ID,
            )

        with gr.Tab("Écrire"):
            texte_in = gr.Textbox(
                value="",
                label="Ton trajet en wolof",
                placeholder="Ex. : Maa ngi Parcelles Assainies, bëgg naa dem UCAD",
                lines=2,
                max_length=TEXTE_MAX,
            )
            trajets_in = gr.Dropdown(
                choices=list(CHOIX_TRAJETS_FREQUENTS),
                value=None,
                label="🚌 Trajets fréquents à Dakar",
                info="Tape le nom d'un quartier, par ex. Malika",
                filterable=True,
                allow_custom_value=False,
                elem_id="trajets_frequents",
            )

        gr.Markdown(
            "<div style='color:#6B7A72;font-size:12px;margin:2px 0 6px 0;'>"
            f"{NOTE_VIE_PRIVEE_COLLECTE if actif else NOTE_VIE_PRIVEE}</div>",
            elem_id="note_vie_privee",
        )

        compagnie_in = gr.Radio(
            choices=[("Tous", ""), ("Tata", "Tata AFTU"), ("Dem Dikk", "Dakar Dem Dikk")],
            value="",
            label="Compagnie",
            info="À la voix, ta préférence l'emporte sur ce choix.",
        )

        bouton = gr.Button("Trouver mon bus", variant="primary", size="lg")

        with gr.Accordion("Ce que l'IA a compris", open=True):
            carte_out.render()
            audio_out.render()
            mention_out.render()
            transcription_out.render()
            trajet_out.render()

        entrees_collecte: list = []
        sorties_collecte: list = []
        if actif:
            suivi_state = gr.State(None)
            code_out = gr.Markdown(elem_id="code_collecte")
            with gr.Group(visible=False, elem_id="panneau_avis") as panneau_avis:
                gr.Markdown("**La ligne est juste ?**")
                with gr.Row():
                    boutons_avis = [
                        (gr.Button("Oui"), avis_oui),
                        (gr.Button("Non"), avis_non),
                        (gr.Button("Je ne sais pas"), avis_ne_sait_pas),
                    ]
                minutes_in = gr.Number(
                    value=None,
                    label="Temps réel du trajet (min)",
                    minimum=collecte.MINUTES_MIN,
                    maximum=collecte.MINUTES_MAX,
                    precision=0,
                )
                bouton_temps = gr.Button("Envoyer le temps", size="sm")
            for bouton_avis, gerer_avis in boutons_avis:
                bouton_avis.click(
                    gerer_avis,
                    inputs=[minutes_in, suivi_state],
                    outputs=[suivi_state, code_out],
                    api_visibility="private",
                )
            bouton_temps.click(
                donner_temps,
                inputs=[minutes_in, suivi_state],
                outputs=[suivi_state, code_out],
                api_visibility="private",
            )
            entrees_collecte = [suivi_state]
            sorties_collecte = [suivi_state, panneau_avis, code_out, minutes_in]

        gerer_demande = traiter_demande_collecte if actif else traiter_demande
        gerer_micro = rechercher_une_fois_collecte if actif else rechercher_une_fois
        gerer_frequent = choisir_trajet_frequent_collecte if actif else choisir_trajet_frequent

        gr.Markdown(
            "<div style='text-align:center;color:#8A968F;font-size:12px;"
            "border-top:1px solid #E3EAE6;padding-top:10px;margin-top:18px'>"
            f"Données : Dakar Dem Dikk, Tata AFTU · IA : {LIBELLE_ASR}, NVIDIA Build · Voix : {LIBELLE_VOIX}"
            "</div>"
        )

        sorties_avec_micro = [*sorties, audio_in]
        demande_state = gr.State(None)
        nouvelle_demande = gr.State(True)
        relancer_compagnie = gr.State(False)

        # Point d'entrée API conservé : les scripts et les tests en ligne
        # appellent encore `repondre_et_vider_micro` avec trois champs. Il ne
        # conserve pas d'état, contrairement à l'interface.
        api_bouton = gr.Button("API", visible=False, elem_id="api_repondre")
        api_bouton.click(
            repondre_et_vider_micro,
            inputs=[audio_in, texte_in, compagnie_in],
            outputs=sorties_avec_micro,
        )

        # Le bouton et la compagnie passent par le même handler. Le booléen
        # distingue une nouvelle demande (bouton/micro) d'un simple changement de
        # compagnie, qui relit l'état sans retranscrire l'audio.
        bouton.click(
            gerer_demande,
            inputs=[audio_in, texte_in, compagnie_in, demande_state, nouvelle_demande, *entrees_collecte],
            outputs=[*sorties_avec_micro, demande_state, *sorties_collecte],
        )

        # Un trajet fréquent remplit le texte, lance la recherche avec la
        # compagnie choisie, vide le micro puis remet la liste à vide. Le change
        # provoqué par ce dernier None est ignoré : pas de seconde recherche.
        trajets_in.change(
            gerer_frequent,
            inputs=[trajets_in, compagnie_in, *entrees_collecte],
            outputs=[texte_in, *sorties_avec_micro, demande_state, trajets_in, *sorties_collecte],
        )

        # Recherche automatique, sans bouton : au relâchement du micro
        # (stop_recording), au dépôt d'un fichier (change) et au vidage du micro.
        # La compagnie choisie est passée comme au clic du bouton ;
        # rechercher_une_fois absorbe l'événement en double que produit un même
        # geste et ignore le change dû au vidage.
        for evenement in (audio_in.stop_recording, audio_in.change):
            evenement(
                gerer_micro,
                inputs=[audio_in, texte_in, compagnie_in, demande_state, *entrees_collecte],
                outputs=[*sorties_avec_micro, demande_state, *sorties_collecte],
            )

        # Changer Tata/Dem Dikk/Tous rejoue la dernière demande avec la nouvelle
        # valeur. On lit le bouton dans l'événement, jamais dans une copie gardée
        # en mémoire : l'étiquette et les lignes suivent donc toujours le choix
        # affiché.
        compagnie_in.change(
            gerer_demande,
            inputs=[audio_in, texte_in, compagnie_in, demande_state, relancer_compagnie, *entrees_collecte],
            outputs=[*sorties_avec_micro, demande_state, *sorties_collecte],
        )
    return interface


demo = None if MODE_TEST else _construire()


if __name__ == "__main__":
    # queue() est obligatoire pour ZeroGPU : la réservation du GPU ne fonctionne que
    # si les exécutions passent par la file. Sur un Space, Gradio règle tout seul
    # l'hôte et le port à lancer.
    # Depuis Gradio 6, le thème et le CSS se passent au lancement, plus au
    # constructeur. i18n remplace les libellés anglais du micro.
    # Les deux bornes protègent le Space public : la file ne grossit pas sans fin,
    # et Gradio refuse un gros fichier avant de l'écrire sur le disque. On laisse
    # une marge au-dessus de 10 Mo pour que _decoder_audio donne son message clair.
    demo.queue(max_size=TAILLE_FILE_ATTENTE).launch(
        theme=_theme(),
        css=CSS_GUINDIMA,
        i18n=I18N_GUINDIMA,
        max_file_size=2 * TAILLE_MAX_AUDIO,
    )
