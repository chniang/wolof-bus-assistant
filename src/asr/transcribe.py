"""Transcription wolof pour l'app : audio -> texte, avec notre whisper fine-tuné.

On charge d'abord TIJAANI/whisper-small-wolof-dakar-essai3, notre fine-tuning
de whisper-small sur les vocaux collectés par WhatsApp (WER 89,7 % -> 74,1 %
sur 22 vocaux de 3 voix jamais vues). Le dépôt est privé : il faut le secret
HF_TOKEN d'un compte du dépôt TIJAANI. S'il ne se charge pas (token absent,
erreur réseau), on retombe tout seul sur M9and2M/whisper-small-wolof, le modèle
de base wolof, public. Réglages inchangés : CPU, quantification int8,
décodage glouton. SpeechBrain reste écarté : wav2vec2-large ne tient pas dans
les 8 Go de RAM du laptop.

Ce module ne dépend pas de Streamlit : c'est l'app qui se charge de garder le
modèle en mémoire (st.cache_resource), pour qu'on puisse aussi le tester seul
en ligne de commande.
"""

from __future__ import annotations

import io
import os
import re

import numpy as np

# Notre fine-tuning sur les voix dakaroises (voir scripts/finetune_whisper.py
# et scripts/evaluer_modele.py) : les trajets compris passent de 5/22 à 10/22
# sur des voix jamais vues de l'entraînement.
MODEL_WHISPER = "TIJAANI/whisper-small-wolof-dakar-essai3"

# Repli automatique, public : si le dépôt fine-tuné n'est pas accessible, la
# transcription continue avec le modèle wolof de base plutôt que d'échouer.
MODEL_WHISPER_SECOURS = "M9and2M/whisper-small-wolof"

# Le dépôt fine-tuné contient les checkpoints de l'entraînement (checkpoint-32/,
# checkpoint-48/…, ~2 Go) : inutiles en production, on ne télécharge que les
# fichiers de la racine — poids, config, tokenizer. Les motifs passent par
# fnmatch, où « * » traverse les « / » : « */* » écarte tout sous-dossier et
# « checkpoint-* » un checkpoint éventuel rangé à la racine.
TELECHARGEMENT_RACINE = ["*/*", "checkpoint-*"]

# Sur GPU (Hugging Face Space), on utilise Kiriku-Wolof-ASR de l'AI Hub Sénégal :
# au banc d'essai du 07/10/2026 il a reconnu ~9 noms d'arrêts sur 10 au micro,
# contre 1 sur 10 pour le whisper wolof de base, à vitesse égale (~1,5 s sur GPU).
# Taille Whisper large (6 Go en float32) : trop lourd pour le CPU du laptop, qui
# garde notre whisper fine-tuné. Modèle protégé : il faut le secret HF_TOKEN
# d'un compte ayant accepté ses conditions. Surchargeable par la variable
# ASR_MODEL_GPU.
MODEL_ASR_GPU = os.getenv("ASR_MODEL_GPU", "AIHubSN/Kiriku-Wolof-ASR")

# torch sur un portable : 4 cœurs au maximum, sans surcharger la machine.
NB_THREADS = min(4, os.cpu_count() or 1)

# Whisper a été entraîné en 16 kHz mono : tout ce qu'on lui donne doit être
# ramené à ce format, sinon la transcription part n'importe où.
SAMPLE_RATE = 16000

# Une question de trajet tient en une phrase. 48 tokens suffisent et évitent que
# le modèle se mette à « halluciner » une suite quand l'audio finit par du silence.
MAX_NEW_TOKENS = 48


def _telecharger_modele(depot: str, token: str | None = None) -> str:
    """Télécharge les seuls fichiers de la racine d'un dépôt ; renvoie le dossier local.

    Le token (secret HF_TOKEN) ne sert que pour les dépôts privés ou protégés ;
    sans lui, la bibliothèque essaie quand même le jeton déjà connecté en local.
    """
    from huggingface_hub import snapshot_download

    return snapshot_download(
        repo_id=depot,
        token=token,
        ignore_patterns=TELECHARGEMENT_RACINE,
    )


def _charger_pipeline(dossier: str):
    """Construit le pipeline ASR sur CPU depuis un dossier déjà téléchargé."""
    import torch
    from transformers import pipeline

    modele = pipeline(
        "automatic-speech-recognition",
        model=dossier,
        device=-1,
    )
    # Quantification dynamique des Linear en int8 : poids 4 fois plus légers et
    # calcul plus rapide sur CPU, pour une transcription quasi identique.
    modele.model = torch.quantization.quantize_dynamic(
        modele.model, {torch.nn.Linear}, dtype=torch.qint8
    )
    return modele


def load_model():
    """Charge le pipeline Whisper quantifié en int8 sur CPU. Long la première fois (~1 min).

    Le modèle fine-tuné d'abord, le wolof public en repli : un dépôt privé sans
    secret HF_TOKEN ou une coupure réseau ne doivent pas empêcher la
    transcription. L'échec du premier est annoncé dans le journal ; seul un
    échec des deux à la fois lève une exception.
    """
    import torch

    torch.set_num_threads(NB_THREADS)

    # Secret d'un compte du dépôt TIJAANI ; vide ou absent, on reste anonyme et
    # la bibliothèque essaie quand même le jeton déjà connecté en local.
    token = os.getenv("HF_TOKEN", "").strip() or None
    for depot in (MODEL_WHISPER, MODEL_WHISPER_SECOURS):
        try:
            modele = _charger_pipeline(_telecharger_modele(depot, token))
        except Exception as exc:
            if depot != MODEL_WHISPER:
                raise RuntimeError(
                    f"ni {MODEL_WHISPER} ni {MODEL_WHISPER_SECOURS} ne se chargent"
                ) from exc
            detail = f"{type(exc).__name__} : {exc}"
            if not token:
                detail += " (secret HF_TOKEN absent de l'environnement)"
            print(
                f"[ASR] {depot} inaccessible ({detail}) -> repli sur {MODEL_WHISPER_SECOURS}",
                flush=True,
            )
            continue
        print(f"[ASR] {depot} chargé sur CPU (int8)", flush=True)
        return modele


def _resample(audio: np.ndarray, sr_origine: int) -> np.ndarray:
    """Ramène l'audio à 16 kHz.

    Le navigateur enregistre souvent en 44,1 ou 48 kHz. On passe par torchaudio
    (déjà installé avec torch) ; s'il manque, une interpolation linéaire fait
    l'affaire pour de la voix.
    """
    if sr_origine == SAMPLE_RATE:
        return audio
    try:
        import torch
        import torchaudio.functional as F

        tensor = torch.from_numpy(audio).unsqueeze(0)
        return F.resample(tensor, sr_origine, SAMPLE_RATE).squeeze(0).numpy()
    except Exception:
        duree = len(audio) / sr_origine
        n_cible = int(duree * SAMPLE_RATE)
        x_origine = np.linspace(0, duree, num=len(audio), endpoint=False)
        x_cible = np.linspace(0, duree, num=n_cible, endpoint=False)
        return np.interp(x_cible, x_origine, audio).astype(np.float32)


def load_audio(data: bytes) -> np.ndarray:
    """Décode des octets audio (WAV du micro, ou WAV/MP3 de démo) en 16 kHz mono float32."""
    import soundfile as sf

    audio, sr = sf.read(io.BytesIO(data), dtype="float32")
    # Un micro stéréo donne deux colonnes : on fait la moyenne pour avoir du mono.
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return _resample(np.asarray(audio, dtype=np.float32), sr)


def transcrire(model, audio_16k: np.ndarray) -> str:
    """Transcrit un audio déjà en 16 kHz mono. Renvoie une chaîne vide si rien d'audible."""
    import torch

    if audio_16k is None or len(audio_16k) < SAMPLE_RATE * 0.3:
        # Moins de 0,3 s : clic involontaire sur le micro, pas la peine d'appeler le modèle.
        return ""

    # inference_mode : aucun graphe d'autograd n'est construit, c'est plus rapide
    # que no_grad. Indispensable ici, le modèle est déjà quantifié.
    # task passe par generate_kwargs : en argument direct du pipeline,
    # transformers émet un avertissement « generation_config ».
    # Pas de language : Whisper ne connaît pas le wolof, « wo » le fait planter.
    reglages = {
        "task": "transcribe",
        "max_new_tokens": MAX_NEW_TOKENS,
        "num_beams": 1,
    }
    try:
        with torch.inference_mode():
            prediction = model(
                {"array": audio_16k, "sampling_rate": SAMPLE_RATE},
                generate_kwargs=reglages,
            )
    except Exception as premiere:
        # Kiriku n'accepte pas forcément « task » ni l'inference_mode : on relance
        # exactement comme au banc d'essai Colab (seul max_new_tokens, sans
        # inference_mode), qui a fonctionné.
        print(f"[ASR] 1er essai échoué ({type(premiere).__name__}: {premiere}), nouvel essai", flush=True)
        with torch.no_grad():
            prediction = model(
                {"raw": audio_16k, "sampling_rate": SAMPLE_RATE},
                generate_kwargs={"max_new_tokens": MAX_NEW_TOKENS},
            )
    texte = prediction.get("text", "") if isinstance(prediction, dict) else str(prediction)
    return re.sub(r"\s+", " ", texte).strip()


def transcrir_avec_seconde_chance(son, premier_essai, second_essai, rendu):
    """Réessaie de transcrire avec l'autre modèle ASR quand rien n'est trouvé.

    Le pipeline audio de l'app ne s'arrête pas à la première transcription : si
    elle ne mène à aucun trajet (lieu manquant, aucune ligne), on retranscrit une
    fois avec l'autre modèle — la meilleure façon de « sauver » un trajet quand
    un ASR a mal écrit un nom d'arrêt.

    - premier_essai(son) -> (phrase, libelle, duree) : l'essai principal.
    - second_essai(son, libelle_premier) -> (phrase, libelle, duree) : l'autre
      modèle, choisi par l'appelant d'après le libellé du premier essai. Il peut
      lever (ex. GPU de nouveau refusé) : on garde alors le premier résultat.
    - rendu(phrase) -> bool : vrai si la phrase mène à un trajet.

    Renvoie (phrase, libelle, duree, retente). `retente` est vrai dès qu'un
    second essai a eu lieu ; quand c'est lui qui mène à un trajet, `libelle`
    porte « (2e essai) » pour l'afficher dans les sorties de l'app.
    """
    phrase, libelle, duree = premier_essai(son)
    if rendu(phrase):
        return phrase, libelle, duree, False
    try:
        phrase2, libelle2, duree2 = second_essai(son, libelle)
    except Exception:
        return phrase, libelle, duree, True
    if rendu(phrase2):
        return phrase2, f"{libelle2} (2e essai)", duree2, True
    return phrase, libelle, duree, True


if __name__ == "__main__":
    # Petit test à la main : python src/asr/transcribe.py chemin/vers/audio.wav
    import sys
    import time

    if len(sys.argv) < 2:
        print("Usage : python src/asr/transcribe.py fichier_audio.wav")
        sys.exit(1)

    print(f"Chargement de {MODEL_WHISPER} (repli : {MODEL_WHISPER_SECOURS}) …")
    modele = load_model()
    with open(sys.argv[1], "rb") as fichier:
        audio = load_audio(fichier.read())
    debut = time.perf_counter()
    print(f"Transcription : {transcrire(modele, audio)!r}")
    print(f"({time.perf_counter() - debut:.1f}s)")
