"""Synthèse vocale wolof : l'app répond aussi à l'oral.

On utilise un finetuning de SpeechT5 entraîné sur du wolof
(bilalfaye/speecht5_tts-wolof) : c'est le seul TTS wolof qui tourne sur CPU,
en local et hors ligne. MMS de Meta ne couvre pas le wolof, et gTTS comme
edge-tts n'ont pas de voix wolof.

Ce module ne dépend pas de Streamlit : l'app garde le modèle en mémoire, et on
peut aussi le tester seul en ligne de commande :

    python src/tts/speak.py "Jëlal bus bu Dakar Dem Dikk, ligne juróom ñaar."
"""

from __future__ import annotations

import io
import os
import re
import unicodedata
from pathlib import Path
from typing import NamedTuple

MODEL_TTS = "bilalfaye/speecht5_tts-wolof"
# Le vociseur est un modèle séparé, fourni par Microsoft.
VOCODEUR = "microsoft/speecht5_hifigan"

# torch sur un portable : 4 cœurs au maximum, sans surcharger la machine.
NB_THREADS = min(4, os.cpu_count() or 1)

# Le modèle lit les chiffres un peu n'importe comment, on les écrit donc en mots.
UNITES = {
    1: "benn",
    2: "ñaar",
    3: "ñett",
    4: "ñeent",
    5: "juróom",
    6: "juróom benn",
    7: "juróom ñaar",
    8: "juróom ñett",
    9: "juróom ñeent",
}
DIZAINES = {
    10: "fukk",
    20: "ñaar fukk",
    30: "fanweer",
    40: "ñeent fukk",
    50: "juróom fukk",
    60: "juróom benn fukk",
    70: "juróom ñaar fukk",
    80: "juróom ñett fukk",
    90: "juróom ñeent fukk",
}
CENT = "téeméer"

# Au-delà, on n'a pas de formulation : on lit les chiffres tels quels.
MAX_ECRIT = 199

# Audios pré-générés pour la démo (voir pregenerer.py). La synthèse est trop
# lente pour être faite devant un jury, alors on la prépare une fois pour toutes.
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "tts_cache"
# pregenerer.py n'écrit ce marqueur que si tous les fichiers sont là : l'app s'en
# sert pour savoir si elle peut se passer de charger le modèle.
MARQUEUR = CACHE_DIR / "cache_complet.txt"
AUCUNE_LIGNE = "aucune_ligne.wav"
WALLA = "walla.wav"

# Un silence entre deux morceaux, sinon « walla » se colle à la ligne d'avant.
SILENCE_ENTRE = 0.3


class Tts(NamedTuple):
    """Le trio chargé une seule fois : tokenizer, modèle et vociseur."""

    processor: object
    modele: object
    vocodeur: object


def nombre_en_wolof(n: int) -> str:
    """Écrit un numéro de 1 à 199 en mots wolof (ligne 22 -> « ñaar fukk ak ñaar »)."""
    n = int(n)
    if n < 1:
        return str(n)
    if n > MAX_ECRIT:
        return str(n)
    if n < 10:
        return UNITES[n]
    if n < 20:
        return "fukk" if n == 10 else f"fukk ak {UNITES[n - 10]}"
    if n == 100:
        return CENT
    if n < 100:
        dizaines = DIZAINES[n - n % 10]
        return dizaines if n % 10 == 0 else f"{dizaines} ak {UNITES[n % 10]}"
    return f"{CENT} ak {nombre_en_wolof(n - 100)}"


def numero_de(ligne: object) -> int | None:
    """Le numéro d'une ligne du CSV (« Ligne 12 » -> 12), None s'il n'y en a pas."""
    trouve = re.search(r"\d+", str(ligne))
    return int(trouve.group()) if trouve else None


def lignes_annoncees(lignes: list[dict]) -> list[tuple[str, int]]:
    """Les (compagnie, numéro) réellement dits à l'oral, deux au maximum.

    Deux lignes et pas plus, sinon la phrase devient interminable à écouter.
    """
    annoncees = []
    for match in lignes[:2]:
        numero = numero_de(match.get("ligne"))
        if numero is not None:
            annoncees.append((str(match.get("compagnie", "")).strip(), numero))
    return annoncees


def phrase_reponse(lignes: list[dict]) -> str:
    """La phrase à dire pour un résultat de correspondance."""
    morceaux = [
        f"Jëlal bus bu {compagnie}, ligne {nombre_en_wolof(numero)}."
        for compagnie, numero in lignes_annoncees(lignes)
    ]
    if not morceaux:
        return "Baal ma, gisuma bus bu dem fa."
    return " walla ".join(morceaux)


def nom_cache(compagnie: str, numero: int) -> str:
    """Nom de fichier d'une ligne : Tata AFTU 25 devient tata_aftu_25.wav."""
    sans_accent = unicodedata.normalize("NFKD", compagnie)
    en_ascii = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return f"{re.sub(r'[^a-zA-Z0-9]+', '_', en_ascii).strip('_').lower()}_{numero}.wav"


def cache_complet() -> bool:
    """Le cache disque est-il prêt ? C'est pregenerer.py qui décide."""
    return MARQUEUR.is_file()


def assembler(fichiers: list[Path]) -> bytes:
    """Colle des WAV bout à bout avec un silence entre chaque, et renvoie les octets.

    Tout vient de synthetiser(), donc tous les fichiers partagent la même
    fréquence : on reprend celle du premier.
    """
    import numpy as np
    import soundfile as sf

    morceaux = []
    for chemin in fichiers:
        audio, sr = sf.read(str(chemin), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        morceaux.append(audio)
        if chemin != fichiers[-1]:
            morceaux.append(np.zeros(int(sr * SILENCE_ENTRE), dtype="float32"))
    if not morceaux:
        raise ValueError("aucun fichier à assembler")

    tampon = io.BytesIO()
    sf.write(tampon, np.concatenate(morceaux), sr, format="WAV", subtype="PCM_16")
    return tampon.getvalue()


def voix_depuis_cache(lignes: list[dict]) -> bytes | None:
    """L'audio déjà tout prêt pour ce résultat, ou None s'il manque un morceau.

    None veut dire « reviens à la synthèse en direct » : c'est le filet de
    sécurité si le cache n'a pas été généré ou s'il est incomplet.
    """
    if not lignes:
        fichiers = [CACHE_DIR / AUCUNE_LIGNE]
    else:
        fichiers = [CACHE_DIR / nom_cache(compagnie, numero) for compagnie, numero in lignes_annoncees(lignes)]
        if len(fichiers) == 2:
            fichiers.insert(1, CACHE_DIR / WALLA)
    if not fichiers or not all(chemin.is_file() for chemin in fichiers):
        return None
    return assembler(fichiers)


def load_tts() -> Tts:
    """Charge SpeechT5 et son vociseur. Long au premier appel (~3 min de téléchargement)."""
    import torch
    from transformers import (
        SpeechT5ForTextToSpeech,
        SpeechT5HifiGan,
        SpeechT5Processor,
    )

    torch.set_num_threads(NB_THREADS)

    return Tts(
        processor=SpeechT5Processor.from_pretrained(MODEL_TTS),
        modele=SpeechT5ForTextToSpeech.from_pretrained(MODEL_TTS),
        vocodeur=SpeechT5HifiGan.from_pretrained(VOCODEUR),
    )


def synthetiser(tts: Tts, texte: str) -> bytes:
    """Synthétise le texte et renvoie un WAV en octets, prêt pour st.audio."""
    import soundfile as sf
    import torch

    entrees = tts.processor(text=texte, return_tensors="pt")
    # Le modèle est mono-locuteur : un vecteur à zéro suffit, et on évite le
    # téléchargement du jeu de xvectors que suggère la fiche du modèle.
    embedding = torch.zeros(1, tts.modele.config.speaker_embedding_dim)
    with torch.no_grad():
        audio = tts.modele.generate_speech(
            input_ids=entrees.input_ids,
            attention_mask=entrees.attention_mask,
            speaker_embeddings=embedding,
            vocoder=tts.vocodeur,
        )

    # C'est le vociseur qui porte la fréquence de sortie (16 kHz), pas le modèle.
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


if __name__ == "__main__":
    # Petit test à la main : python src/tts/speak.py "Jëlal bus bu ..."
    import sys
    import time

    if len(sys.argv) < 2:
        print('Usage : python src/tts/speak.py "Jëlal bus bu ..."')
        sys.exit(1)

    tts = load_tts()
    debut = time.perf_counter()
    octets = synthetiser(tts, sys.argv[1])
    with open("test_tts.wav", "wb") as fichier:
        fichier.write(octets)
    print(f"{sys.argv[1]!r} -> test_tts.wav ({time.perf_counter() - debut:.1f}s)")
