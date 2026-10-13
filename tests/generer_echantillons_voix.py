r"""Génère des échantillons de voix pour comparer les timbres, sans toucher à l'app.

Même phrase de réponse (ligne 46) lue de trois façons, pour choisir plus tard une
voix féminine plus jeune. On reprend le modèle de l'app tel quel et on ne change
que le « speaker embedding » de SpeechT5, qui porte le timbre :

    1. la voix actuelle : embedding nul, c'est ce que fait src/tts/speak.py ;
    2. + le x-vecteur CMU ARCTIC « slt » (voix féminine, US) ;
    3. + le x-vecteur CMU ARCTIC « clb » (voix féminine, US).

Les x-vecteurs viennent du jeu `Matthijs/cmu-arctic-xvectors` (512 nombres par
locuteur, licence MIT), ceux-là mêmes que la fiche du modèle wolof recommande.
Ils sont téléchargés et mis en cache par huggingface_hub.

    .\.venv\Scripts\python.exe tests\generer_echantillons_voix.py

Sortie : tests/echantillons_voix/*.wav
"""

from __future__ import annotations

import io
import os
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import torch

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from tts.speak import (  # noqa: E402
    Tts,
    load_tts,
    phrase_reponse,
    synthetiser,
)

SORTIE = Path(__file__).resolve().parent / "echantillons_voix"

# Un numéro de ligne à deux chiffres, comme demandé (46 -> « ñeent fukk ak juróom benn »).
PHRASE = phrase_reponse([{"compagnie": "Tata AFTU", "ligne": "Ligne 46"}])

# Voix féminines disponibles dans le jeu CMU ARCTIC (les seules : slt et clb ;
# bdl, rms, awb, ksp, jmk sont des voix masculines).
VOIX_FEMININES = [("slt", "02_feminine_slt.wav"), ("clb", "03_feminine_clb.wav")]

# Dossier déjà extrait du zip, pour ne pas retélécharger (facultatif).
CMU_DIR = os.environ.get("CMU_XVECTORS_DIR")


def charger_xvector(locuteur: str) -> torch.Tensor:
    """Le x-vecteur 512 d'un locuteur CMU ARCTIC (`slt`, `clb`), en tenseur (1, 512)."""
    if CMU_DIR and Path(CMU_DIR).is_dir():
        candidats = sorted(Path(CMU_DIR).glob(f"cmu_us_{locuteur}_arctic*.npy"))
        if candidats:
            return torch.tensor(np.load(candidats[0])).unsqueeze(0)

    from huggingface_hub import hf_hub_download

    archive = hf_hub_download(
        "Matthijs/cmu-arctic-xvectors", "spkrec-xvect.zip", repo_type="dataset"
    )
    with zipfile.ZipFile(archive) as fichier:
        nom = next(
            n
            for n in sorted(fichier.namelist())
            if f"cmu_us_{locuteur}_arctic" in n and n.endswith(".npy")
        )
        with fichier.open(nom) as donnees:
            return torch.tensor(np.load(io.BytesIO(donnees.read()))).unsqueeze(0)


def synthetiser_avec(tts: Tts, texte: str, embedding: torch.Tensor) -> bytes:
    """Comme synthetiser(), mais avec un speaker embedding choisi.

    On ne touche pas à src/tts/speak.py : cette variante sert uniquement à
    fabriquer les échantillons de comparaison.
    """
    import soundfile as sf

    entrees = tts.processor(text=texte, return_tensors="pt")
    with torch.no_grad():
        audio = tts.modele.generate_speech(
            input_ids=entrees.input_ids,
            attention_mask=entrees.attention_mask,
            speaker_embeddings=embedding,
            vocoder=tts.vocodeur,
        )
    frequence = tts.vocodeur.config.sampling_rate
    tampon = io.BytesIO()
    sf.write(
        tampon,
        audio.squeeze().detach().numpy().astype("float32"),
        frequence,
        format="WAV",
        subtype="PCM_16",
    )
    return tampon.getvalue()


def main() -> int:
    SORTIE.mkdir(parents=True, exist_ok=True)
    print(f"Phrase : {PHRASE!r}")
    print(f"Sortie : {SORTIE}")

    debut = time.perf_counter()
    tts = load_tts()
    print(f"Modèle chargé en {time.perf_counter() - debut:.1f}s")

    # 1. La voix actuelle de l'app : embedding nul.
    chemin = SORTIE / "01_actuelle.wav"
    debut = time.perf_counter()
    chemin.write_bytes(synthetiser(tts, PHRASE))
    print(f"  {chemin.name:26s} {time.perf_counter() - debut:5.1f}s  (embedding nul)")

    # 2 et 3. Même modèle, timbre d'une voix féminine CMU ARCTIC.
    for locuteur, nom in VOIX_FEMININES:
        chemin = SORTIE / nom
        debut = time.perf_counter()
        embedding = charger_xvector(locuteur)
        chemin.write_bytes(synthetiser_avec(tts, PHRASE, embedding))
        print(f"  {chemin.name:26s} {time.perf_counter() - debut:5.1f}s  (x-vecteur {locuteur})")

    print(f"\n3 échantillons écrits dans {SORTIE}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
