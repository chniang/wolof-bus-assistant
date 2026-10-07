"""Transcription wolof pour l'app : audio -> texte, avec whisper-small-wolof.

On reprend exactement le modèle et les réglages validés dans test_asr_models.py
(M9and2M/whisper-small-wolof, CPU, décodage glouton). SpeechBrain reste écarté :
wav2vec2-large ne tient pas dans les 8 Go de RAM du laptop.

Ce module ne dépend pas de Streamlit : c'est l'app qui se charge de garder le
modèle en mémoire (st.cache_resource), pour qu'on puisse aussi le tester seul
en ligne de commande.
"""

from __future__ import annotations

import io
import os
import re

import numpy as np

MODEL_WHISPER = "M9and2M/whisper-small-wolof"

# Sur GPU (Hugging Face Space), on utilise Kiriku-Wolof-ASR de l'AI Hub Sénégal :
# au banc d'essai du 07/10/2026 il a reconnu ~9 noms d'arrêts sur 10 au micro,
# contre 1 sur 10 pour whisper-small-wolof, à vitesse égale (~1,5 s sur GPU).
# Taille Whisper large (6 Go en float32) : trop lourd pour le CPU du laptop, qui
# garde whisper-small. Modèle protégé : il faut le secret HF_TOKEN d'un compte
# ayant accepté ses conditions. Surchargeable par la variable ASR_MODEL_GPU.
MODEL_ASR_GPU = os.getenv("ASR_MODEL_GPU", "AIHubSN/Kiriku-Wolof-ASR")

# torch sur un portable : 4 cœurs au maximum, sans surcharger la machine.
NB_THREADS = min(4, os.cpu_count() or 1)

# Whisper a été entraîné en 16 kHz mono : tout ce qu'on lui donne doit être
# ramené à ce format, sinon la transcription part n'importe où.
SAMPLE_RATE = 16000

# Une question de trajet tient en une phrase. 48 tokens suffisent et évitent que
# le modèle se mette à « halluciner » une suite quand l'audio finit par du silence.
MAX_NEW_TOKENS = 48


def load_model():
    """Charge le pipeline Whisper quantifié en int8 sur CPU. Long la première fois (~1 min)."""
    import torch
    from transformers import pipeline

    torch.set_num_threads(NB_THREADS)

    modele = pipeline(
        "automatic-speech-recognition",
        model=MODEL_WHISPER,
        device=-1,
    )
    # Quantification dynamique des Linear en int8 : poids 4 fois plus légers et
    # calcul plus rapide sur CPU, pour une transcription quasi identique.
    modele.model = torch.quantization.quantize_dynamic(
        modele.model, {torch.nn.Linear}, dtype=torch.qint8
    )
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


if __name__ == "__main__":
    # Petit test à la main : python src/asr/transcribe.py chemin/vers/audio.wav
    import sys
    import time

    if len(sys.argv) < 2:
        print("Usage : python src/asr/transcribe.py fichier_audio.wav")
        sys.exit(1)

    print(f"Chargement de {MODEL_WHISPER} …")
    modele = load_model()
    with open(sys.argv[1], "rb") as fichier:
        audio = load_audio(fichier.read())
    debut = time.perf_counter()
    print(f"Transcription : {transcrire(modele, audio)!r}")
    print(f"({time.perf_counter() - debut:.1f}s)")
