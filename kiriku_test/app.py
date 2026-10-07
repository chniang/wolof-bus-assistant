"""Banc d'essai ASR : le Whisper actuel de GuindiMa contre Kiriku-Wolof-ASR.

Les deux modèles reçoivent exactement le même audio (micro, fichier ou démo).
On compare la transcription, le temps de calcul et, si on donne la phrase
réellement prononcée, le taux d'erreur par mot (WER).

Kiriku-Wolof-ASR est un modèle protégé : le Space lit le secret HF_TOKEN d'un
compte qui a accepté ses conditions sur Hugging Face.
"""

import os
import re
import time
from pathlib import Path

import gradio as gr
import jiwer
import numpy as np
import spaces
import torch
from transformers import pipeline

HF_TOKEN = os.getenv("HF_TOKEN")
SAMPLE_RATE = 16000
MAX_NEW_TOKENS = 64
DOSSIER_DEMO = Path(__file__).parent / "demo_audio"

MODELES = {
    "Actuel : whisper-small-wolof": "M9and2M/whisper-small-wolof",
    "Kiriku : Kiriku-Wolof-ASR": "AIHubSN/Kiriku-Wolof-ASR",
}


def _charger(depot):
    """Charge un pipeline en float16 sur GPU. En cas d'échec, garde le message."""
    try:
        return pipeline(
            "automatic-speech-recognition",
            model=depot,
            device=0,
            dtype=torch.float16,
            token=HF_TOKEN,
        )
    except Exception as erreur:  # modèle protégé, token absent, etc.
        return f"Chargement impossible : {erreur}"


PIPELINES = {nom: _charger(depot) for nom, depot in MODELES.items()}


def _vers_16k_mono(audio):
    """Gradio donne (taux, tableau int16 ou float) : on ramène tout en 16 kHz mono float32."""
    taux, donnees = audio
    donnees = np.asarray(donnees)
    if donnees.ndim == 2:
        donnees = donnees.mean(axis=1)
    if np.issubdtype(donnees.dtype, np.integer):
        donnees = donnees.astype(np.float32) / np.iinfo(donnees.dtype).max
    donnees = donnees.astype(np.float32)
    if taux != SAMPLE_RATE:
        import torchaudio.functional as F

        donnees = F.resample(torch.from_numpy(donnees).unsqueeze(0), taux, SAMPLE_RATE)
        donnees = donnees.squeeze(0).numpy()
    return donnees


def _normaliser(texte):
    texte = texte.lower()
    texte = re.sub(r"[^\w\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


@spaces.GPU(duration=60)
def comparer(audio, reference):
    if audio is None:
        return [["—", "Enregistre ou choisis un audio d'abord.", "", ""]]
    son = _vers_16k_mono(audio)
    reference = _normaliser(reference or "")
    lignes = []
    for nom, pipe in PIPELINES.items():
        if isinstance(pipe, str):
            lignes.append([nom, pipe, "", ""])
            continue
        debut = time.perf_counter()
        try:
            sortie = pipe(
                {"raw": son, "sampling_rate": SAMPLE_RATE},
                generate_kwargs={"max_new_tokens": MAX_NEW_TOKENS},
            )
            texte = sortie["text"].strip()
        except Exception as erreur:
            texte = f"Erreur : {erreur}"
        duree = f"{time.perf_counter() - debut:.1f} s"
        wer = ""
        if reference and not texte.startswith("Erreur"):
            wer = f"{jiwer.wer(reference, _normaliser(texte) or '-') * 100:.0f} %"
        lignes.append([nom, texte, duree, wer])
    return lignes


with gr.Blocks(title="Kiriku vs Whisper wolof") as demo:
    gr.Markdown(
        "# 🎙️ Banc d'essai ASR wolof\n"
        "Le même audio passe dans le modèle actuel de GuindiMa AI et dans "
        "Kiriku-Wolof-ASR. Tape la phrase réellement prononcée pour obtenir le "
        "taux d'erreur par mot (WER, plus bas = mieux)."
    )
    audio = gr.Audio(sources=["microphone", "upload"], type="numpy", label="Audio en wolof")
    reference = gr.Textbox(label="Phrase prononcée (facultatif, pour le WER)")
    bouton = gr.Button("Comparer", variant="primary")
    resultat = gr.Dataframe(
        headers=["Modèle", "Transcription", "Temps", "WER"],
        wrap=True,
        interactive=False,
    )
    exemples = sorted(str(p) for p in DOSSIER_DEMO.glob("*.wav"))
    if exemples:
        gr.Examples(examples=[[e, ""] for e in exemples], inputs=[audio, reference], cache_examples=False)
    bouton.click(comparer, inputs=[audio, reference], outputs=resultat)

if __name__ == "__main__":
    demo.queue().launch()
