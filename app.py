"""Interface Gradio de GuindiMa AI, pour un Hugging Face Space (ZeroGPU).

Ce fichier ne réimplémente rien : il reprend les modules déjà validés du projet,
dans le même ordre que src/app/app.py. Il n'y a donc qu'une différence avec
l'application Streamlit : le rendu. Ici on ne gère pas de session, chaque
exécution de Gradio est indépendante, ce qui simplifie la mise en cache.

    audio -> transcrire() -> extract_intent() -> StopsMatcher.find_line()
          -> phrase_reponse() + voix_depuis_cache()

Sur un Space, la seule partie qui demande le GPU est la transcription : le
décorateur @spaces.GPU la réserve le temps du calcul puis le libère pour les autres visiteurs.
Le reste du pipeline (extraction, correspondance, voix) tient en CPU et n'a pas
à payer la réservation.
"""

from __future__ import annotations

import itertools
import re
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import gradio as gr
import numpy as np

RACINE = Path(__file__).resolve().parent
# Les modules du projet sont importés à plat (asr, intent, matching, tts) : il faut
# que src/ soit dans le chemin, comme le fait src/app/app.py pour son propre lancement.
sys.path.insert(0, str(RACINE / "src"))

from asr.transcribe import (  # noqa: E402
    MODEL_ASR_GPU,
    MODEL_WHISPER,
    SAMPLE_RATE,
    load_audio,
    load_model,
    transcrire,
)
from intent.extract_intent import (  # noqa: E402
    NVIDIA_BASE_URL,
    TIMEOUT_APPEL,
    extract_intent,
    extract_local,
)
from matching.stops_matcher import StopsMatcher  # noqa: E402
from tts.speak import (  # noqa: E402
    cache_complet,
    load_tts,
    nombre_en_wolof,
    numero_de,
    phrase_reponse,
    synthetiser,
    voix_depuis_cache,
)

VERT = "#00853F"  # vert du Sénégal, celui du thème et des cartes
DEMO_AUDIO_DIR = RACINE / "data" / "demo_audio"

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


def _charger_whisper():
    """Charge le modèle de transcription une seule fois, au chargement du module.

    Sur GPU (le Space) : Kiriku-Wolof-ASR en float16, bien meilleur sur les noms
    d'arrêts. S'il ne se charge pas (secret HF_TOKEN absent, conditions non
    acceptées, réseau), on retombe sur whisper-small-wolof : la démo reste en ligne.
    Sur CPU on délègue à load_model(), qui applique la quantification int8 validée
    sur le laptop.

    Renvoie (pipeline, nom du modèle chargé).
    """
    import torch
    from transformers import pipeline

    if torch.cuda.is_available():
        try:
            modele = pipeline(
                "automatic-speech-recognition",
                model=MODEL_ASR_GPU,
                device=0,
                dtype=torch.float16,
                token=os.getenv("HF_TOKEN"),
            )
            print(f"[ASR] {MODEL_ASR_GPU} chargé sur GPU", flush=True)
            return modele, MODEL_ASR_GPU
        except Exception as exc:
            print(f"[ASR] {MODEL_ASR_GPU} indisponible ({exc}), repli sur {MODEL_WHISPER}", flush=True)
        return (
            pipeline(
                "automatic-speech-recognition",
                model=MODEL_WHISPER,
                device=0,
                dtype=torch.float16,
            ),
            MODEL_WHISPER,
        )
    return load_model(), MODEL_WHISPER


MODELE_WHISPER, NOM_MODELE_ASR = _charger_whisper()
# Crédit affiché en pied de page : le modèle réellement chargé.
LIBELLE_ASR = (
    "Kiriku-Wolof-ASR (AI Hub Sénégal)" if "Kiriku" in NOM_MODELE_ASR else "Whisper wolof"
)

# Le TTS ne sert qu'en secours, quand le cache disque n'a pas l'audio du résultat.
# Le charger à la volée évite de téléchargement 578 Mo pour rien sur un Space.
_TTS = None


def _tts():
    global _TTS
    if _TTS is None:
        _TTS = load_tts()
    return _TTS


# --------------------------------------------------------------------------- #
# Clients et objets reconstruits une fois
# --------------------------------------------------------------------------- #

MATCHER = StopsMatcher()

_CLIENT = None
_CLIENT_TENTE = False


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


ERREUR_ASR = "\x00ERREUR_ASR "


def _decoder_audio(chemin_audio: str) -> np.ndarray:
    """Lit l'enregistrement (micro ou fichier) en 16 kHz mono, sur CPU.

    Fait hors de la réservation GPU : décoder un fichier n'a pas besoin du GPU.
    """
    octets = Path(chemin_audio).read_bytes()
    try:
        return load_audio(octets)
    except Exception:
        # Le navigateur enregistre en WebM/Opus, que soundfile ne sait pas lire.
        # ffmpeg, déclaré dans packages.txt, ramène ça en WAV avant de réessayer.
        with tempfile.TemporaryDirectory() as dossier:
            converti = Path(dossier) / "micro.wav"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-i", chemin_audio,
                    "-ar", str(SAMPLE_RATE),
                    "-ac", "1",
                    str(converti),
                ],
                check=True,
                capture_output=True,
            )
            return load_audio(converti.read_bytes())


@spaces.GPU(duration=30)
def transcrire_wolof(audio: np.ndarray) -> str:
    """Transcrit l'audio avec Kiriku sur GPU.

    Seul endroit de l'app qui réserve le GPU. Le modèle est déjà en mémoire, la
    réservation ne couvre donc que le calcul.
    """
    try:
        return transcrire(MODELE_WHISPER, audio)
    except Exception as exc:
        # ZeroGPU ne renvoie que le nom de l'erreur (« RuntimeError ») : on garde le
        # détail en texte pour l'afficher et le voir dans les logs.
        import traceback

        traceback.print_exc()
        return f"{ERREUR_ASR}{type(exc).__name__} : {str(exc)[:300]}"


# Secours quand ZeroGPU ne fournit pas de GPU (« No CUDA GPUs are available ») :
# whisper-small quantifié sur CPU, chargé seulement le jour où on en a besoin.
_MODELE_CPU = None


def _transcrire_cpu(audio: np.ndarray) -> str:
    global _MODELE_CPU
    if _MODELE_CPU is None:
        print("[ASR] GPU indisponible : chargement de whisper-small sur CPU", flush=True)
        _MODELE_CPU = load_model()
    return transcrire(_MODELE_CPU, audio)


def _phrase_correspondance(trajet: dict) -> str:
    """La réponse à dire pour un trajet en deux bus."""
    morceaux = []
    for etape in (trajet["etape_1"], trajet["etape_2"]):
        numero = numero_de(etape["ligne"])
        dit = f"ligne {nombre_en_wolof(numero)}" if numero is not None else etape["ligne"]
        morceaux.append(f"bus bu {etape['compagnie']}, {dit}")
    return f"Jëlal {morceaux[0]}, ba {trajet['changement']}. Ci ginnaaw, jëlal {morceaux[1]}."


def _voix_wolof(lignes: list[dict], correspondances: list[dict] | None = None) -> str | None:
    """La réponse lue en wolof, sous forme de chemin de fichier.

    Cache disque d'abord : à la démo, tout est déjà synthétisé et aucun modèle n'a
    besoin d'être chargé. Synthèse directe seulement s'il manque un morceau, et
    toujours pour un trajet avec correspondance (phrase propre à chaque trajet).
    """
    if not lignes and not correspondances:
        return None
    octets = voix_depuis_cache(lignes) if lignes and cache_complet() else None
    if octets is None:
        phrase = phrase_reponse(lignes) if lignes else _phrase_correspondance(correspondances[0])
        try:
            octets = synthetiser(_tts(), phrase)
        except Exception as exc:
            print(f"Voix de synthèse indisponible ({exc}), la réponse reste en texte.")
            return None
    chemin = DOSSIER_VOIX / f"reponse_{next(_COMPTEUR)}.wav"
    chemin.write_bytes(octets)
    return str(chemin)


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #


def _une_carte(match: dict, etape: str = "") -> str:
    """Une ligne : compagnie, numéro, sens, et où monter / descendre."""
    numero = numero_de(match["ligne"])
    affiche = re.sub(r"^Ligne\s*", "", str(match["ligne"]))
    rappel = nombre_en_wolof(numero) if numero is not None else ""
    entete = f"{etape} · {match['compagnie']}" if etape else match["compagnie"]
    trajet = ""
    if match.get("monte_a") and match.get("descend_a"):
        trajet = (
            f"<div style='color:#17211C;font-size:15px;margin-top:6px;'>"
            f"Monte à <b>{match['monte_a']}</b> · descends à <b>{match['descend_a']}</b></div>"
        )
    return f"""
<div style="border:1px solid #D6E6DC;border-top:6px solid {VERT};
            border-radius:12px;padding:16px 20px;margin:8px 0;background:#F6FBF8;">
  <div style="color:{VERT};font-size:12px;font-weight:700;letter-spacing:.14em;
              text-transform:uppercase;">{entete}</div>
  <div style="color:{VERT};font-size:56px;font-weight:800;line-height:1.05;
              margin:4px 0 6px 0;">{affiche}</div>
  <div style="color:#17211C;font-size:20px;font-weight:600;">
    {match['depart']} → {match['arrivee']}</div>
  {trajet}
  <div style="color:#6B7A72;font-size:13px;margin-top:6px;">
    {" · ".join(x for x in (rappel, match.get("categorie", "")) if x)}</div>
</div>
"""


def _carte(resultat: dict, depart: str, arrivee: str) -> str:
    """La réponse en Markdown : compagnie et numéro de ligne mis en avant."""
    if not depart or not arrivee:
        return (
            "### 🤷 Lieu non détecté\n\n"
            "Je n'ai pas trouvé un départ **et** une arrivée dans ta phrase. "
            "Reformule, ou parle plus près du micro."
        )

    if resultat["found"]:
        return "".join(_une_carte(match) for match in resultat["lignes"])

    correspondances = resultat.get("correspondances") or []
    if correspondances:
        blocs = ["### 🔁 Pas de bus direct : un changement suffit\n"]
        for numero, trajet in enumerate(correspondances, start=1):
            if numero > 1:
                blocs.append(f"\n**Autre possibilité {numero}**\n")
            blocs.append(_une_carte(trajet["etape_1"], "1er bus"))
            blocs.append(
                f"<div style='text-align:center;color:#6B7A72;margin:2px 0;'>"
                f"🔁 Change à <b>{trajet['changement']}</b></div>"
            )
            blocs.append(_une_carte(trajet["etape_2"], "2e bus"))
        return "".join(blocs)

    inconnus = [
        f"**« {lieu} »**"
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
        f"Je connais **{depart}** et **{arrivee}**, mais aucune ligne ni aucun trajet "
        "avec un seul changement ne les relie dans le jeu de données."
    )


def _mention(intent: dict) -> str:
    """Rappelle que la détection est tombée sur le filet local, sans LLM."""
    if intent.get("source") == "local":
        return (
            "> ⚠️ **Extraction de secours (sans LLM)** — l'API NVIDIA était "
            "indisponible, la détection a été faite sur place."
        )
    if intent.get("erreur"):
        return f"> ⚠️ {intent['erreur']}"
    return ""


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


def trouver_le_bus(audio: str | None, phrase_ecrite: str) -> tuple:
    """Le pipeline complet, dans l'ordre de src/app/app.py.

    Le micro l'emporte sur le texte : si un enregistrement arrive, on le
    transcrit. Les cinq retours correspondent aux cinq sorties de l'interface.
    """
    vide = ("", "", _carte({}, "", ""), None, "")

    if audio:
        try:
            son = _decoder_audio(audio)
        except Exception as exc:
            return ("", "", f"### 🎤 Audio illisible\n\n{_court(exc)}", None, "")
        try:
            phrase = transcrire_wolof(son)
        except Exception as exc:
            # Panne côté Hugging Face (GPU non attribué, quota) : on ne laisse pas
            # l'utilisateur sans réponse, on transcrit sur CPU, plus lentement.
            print(f"[ASR] ZeroGPU en échec ({_court(exc)}), secours CPU", flush=True)
            phrase = ERREUR_ASR
        if phrase.startswith(ERREUR_ASR):
            try:
                phrase = _transcrire_cpu(son)
            except Exception as exc:
                return ("", "", f"### 🎤 Transcription impossible\n\n`{_court(exc)}`", None, "")
    else:
        phrase = (phrase_ecrite or "").strip()

    if not phrase:
        return vide

    # L'extraction gère elle-même son repli local : si l'API est saturée, elle
    # rend quand même un départ et une arrivée tant que la phrase les porte.
    intent = extract_intent(phrase, client=_client_llm())
    depart, arrivee = intent.get("depart") or "", intent.get("arrivee") or ""

    if not depart or not arrivee:
        return (phrase, "", _carte({}, depart, arrivee), None, _mention(intent))

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

    return (
        phrase,
        f"{depart} → {arrivee}",
        _carte(resultat, depart, arrivee),
        _voix_wolof(resultat["lignes"], resultat.get("correspondances")),
        _mention(intent),
    )


def _court(exc: Exception, longueur: int = 160) -> str:
    """Un message d'erreur court : les exceptions techniques font plusieurs lignes."""
    return f"{type(exc).__name__} : {exc}"[:longueur]


def trouver_le_bus_vocal(audio: str | None) -> tuple:
    """Raccourci pour les exemples audio : on part du micro, le texte est vide."""
    return trouver_le_bus(audio, "")


def trouver_le_bus_texte(phrase: str) -> tuple:
    """Raccourci pour les exemples texte : le micro est vide."""
    return trouver_le_bus(None, phrase)


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #


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


EXEMPLES_TEXTE = [
    "maa ngi Ouakam, bëgg naa dem Palais 2",
    "maa ngi ci Liberté 5, bëgg naa dem Palais 2",
]


def _construire():
    with gr.Blocks(title="GuindiMa AI 🚌") as interface:
        gr.Markdown("# GuindiMa AI 🚌\n### Wax ma fu nga jëm, ma won la bus bi")
        gr.Markdown(
            "Dis-moi où tu vas, je te montre le bus. "
            "Parle ou écris ton trajet en wolof, à Dakar."
        )

        # Les exemples ont besoin des sorties avant qu'elles soient affichées.
        # On les crée donc « hors écran » (render=False), et on les place plus bas,
        # sous le bouton, avec .render().
        transcription_out = gr.Textbox(label="Transcription", interactive=False, render=False)
        trajet_out = gr.Textbox(label="Départ → arrivée", interactive=False, render=False)
        mention_out = gr.Markdown(render=False)
        carte_out = gr.Markdown(render=False)
        audio_out = gr.Audio(label="Réponse en wolof", autoplay=True, render=False)
        sorties = [transcription_out, trajet_out, carte_out, audio_out, mention_out]

        with gr.Tab("Parler"):
            audio_in = gr.Audio(
                sources=["microphone", "upload"],
                type="filepath",
                label="Dis ton trajet en wolof",
            )
            audios_demo = sorted(DEMO_AUDIO_DIR.glob("*.wav"))
            if audios_demo:
                gr.Examples(
                    examples=[[str(chemin)] for chemin in audios_demo],
                    inputs=[audio_in],
                    fn=trouver_le_bus_vocal,
                    outputs=sorties,
                    cache_examples=False,
                    label="Ou alors, rejoue un enregistrement déjà prêt",
                )

        with gr.Tab("Écrire"):
            texte_in = gr.Textbox(
                label="Ton trajet en wolof",
                placeholder=EXEMPLES_TEXTE[0],
                lines=2,
            )
            gr.Examples(
                examples=[[phrase] for phrase in EXEMPLES_TEXTE],
                inputs=[texte_in],
                fn=trouver_le_bus_texte,
                outputs=sorties,
                cache_examples=False,
                label="Quelques phrases qui marchent",
            )

        bouton = gr.Button("Trouver mon bus", variant="primary", size="lg")

        with gr.Accordion("Ce que l'IA a compris", open=True):
            carte_out.render()
            audio_out.render()
            mention_out.render()
            transcription_out.render()
            trajet_out.render()

        gr.Markdown(
            "<div style='text-align:center;color:#8A968F;font-size:12px;"
            "border-top:1px solid #E3EAE6;padding-top:10px;margin-top:18px'>"
            f"Données : Dakar Dem Dikk, Tata AFTU · IA : {LIBELLE_ASR}, NVIDIA Build"
            "</div>"
        )

        # Le branchement du bouton doit rester dans le bloc « with gr.Blocks ».
        bouton.click(trouver_le_bus, inputs=[audio_in, texte_in], outputs=sorties)
    return interface


demo = _construire()


if __name__ == "__main__":
    # queue() est obligatoire pour ZeroGPU : la réservation du GPU ne fonctionne que
    # si les exécutions passent par la file. Sur un Space, Gradio règle tout seul
    # l'hôte et le port à lancer.
    # Depuis Gradio 6, le thème se passe au lancement et non plus au constructeur.
    demo.queue().launch(theme=_theme())
