"""Synthèse vocale wolof : l'app répond aussi à l'oral.

On utilise un finetuning de SpeechT5 entraîné sur du wolof
(bilalfaye/speecht5_tts-wolof) : c'est le seul TTS wolof qui tourne sur CPU,
en local et hors ligne. MMS de Meta ne couvre pas le wolof, et gTTS comme
edge-tts n'ont pas de voix wolof.

Ce module ne dépend pas de Streamlit : l'app garde le modèle en mémoire, et on
peut aussi le tester seul en ligne de commande :

    python src/tts/speak.py "Jëlal bus bu Dakar Dem Dikk, numero juróom ñaar."
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
# Formes de liaison devant « téeméer » : 200 -> ñaari téeméer, 500 ->
# juróomi téeméer. Au-delà de 599 on garde la même construction.
CENTAINES = {
    2: "ñaari",
    3: "ñetti",
    4: "ñeenti",
    5: "juróomi",
    6: "juróom benni",
    7: "juróom ñaari",
    8: "juróom ñetti",
    9: "juróom ñeenti",
}

# Au-delà, on n'a pas de formulation : on lit les chiffres tels quels.
MAX_ECRIT = 999

# Audios pré-générés pour la démo (voir pregenerer.py). La synthèse est trop
# lente pour être faite devant un jury, alors on la prépare une fois pour toutes.
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "tts_cache"
# pregenerer.py n'écrit ce marqueur que si tous les fichiers sont là : l'app s'en
# sert pour savoir si elle peut se passer de charger le modèle.
MARQUEUR = CACHE_DIR / "cache_complet.txt"
AUCUNE_LIGNE = "aucune_ligne.wav"
WALLA = "walla.wav"
# « Walla, » sépare deux possibilités AVEC changement ; un fichier distinct de
# « walla » car la voix doit marquer une vraie pause avant la suivante.
WALLA_AUTRE = "walla_autre.wav"
LIAISON_CORRESPONDANCE = "correspondance_liaison.wav"

# Plafond commun à l'affichage (stops_matcher) et à la voix : au-delà de trois
# possibilités, l'oral devient trop long et l'usager décroche.
MAX_POSSIBILITES = 3

# Un silence entre deux morceaux, sinon « walla » se colle à la ligne d'avant.
SILENCE_ENTRE = 0.3


class Tts(NamedTuple):
    """Le trio chargé une seule fois : tokenizer, modèle et vociseur."""

    processor: object
    modele: object
    vocodeur: object


def nombre_en_wolof(n: int) -> str:
    """Écrit un numéro de 1 à 999 en mots wolof (221 -> « ñaari téeméer ak … »)."""
    n = int(n)
    if n < 1:
        return str(n)
    if n > MAX_ECRIT:
        return str(n)
    if n < 10:
        return UNITES[n]
    if n < 20:
        return "fukk" if n == 10 else f"fukk ak {UNITES[n - 10]}"
    if n < 100:
        dizaines = DIZAINES[n - n % 10]
        return dizaines if n % 10 == 0 else f"{dizaines} ak {UNITES[n % 10]}"
    centaines, reste = divmod(n, 100)
    tete = CENT if centaines == 1 else f"{CENTAINES[centaines]} {CENT}"
    return tete if reste == 0 else f"{tete} ak {nombre_en_wolof(reste)}"


def numero_de(ligne: object) -> int | None:
    """Le numéro d'une ligne du CSV (« Ligne 12 » -> 12), None s'il n'y en a pas."""
    trouve = re.search(r"\d+", str(ligne))
    return int(trouve.group()) if trouve else None


def suffixe_de(ligne: object) -> str:
    """La lettre qui suit le numéro (« Ligne 15A » -> « A »), vide sinon.

    Le CSV distingue 15A et 15B : à l'écran la carte affiche « 15A », donc la
    voix ne peut pas se contenter de « 15 », qui ferait prendre le mauvais bus.
    """
    trouve = re.search(r"\d+\s*([A-Za-z])\b", str(ligne))
    return trouve.group(1).upper() if trouve else ""


def lignes_annoncees(lignes: list[dict]) -> list[dict]:
    """Les lignes réellement dites, dans l'ordre affiché, au plus 3.

    Le plafond est celui de l'affichage (stops_matcher.MAX_LIGNES) : la voix ne
    doit ni oublier une carte ni en annoncer une qui n'est pas à l'écran. On
    garde aussi les lignes sans numéro (« TAF TAF ») : elles sont affichées et
    ont donc leur propre audio.
    """
    return [
        match
        for match in lignes[:MAX_POSSIBILITES]
        if str(match.get("ligne", "")).strip()
    ]


def compagnie_dite(compagnie: str) -> str:
    """Le nom de compagnie à l'oral : « Tata AFTU » se dit « Tata ».

    L'affichage, lui, garde le nom complet du CSV.
    """
    return {"Tata AFTU": "Tata", "Dakar Dem Dikk": "Dem Dikk"}.get(compagnie, compagnie)


def _dit_ligne(match: dict) -> str:
    """Un morceau de phrase pour une ligne : « Jëlal bus bu Tata, numero ñaar. »"""
    compagnie = compagnie_dite(str(match.get("compagnie", "")).strip())
    numero = numero_de(match.get("ligne"))
    if numero is None:
        return f"Jëlal bus bu {compagnie}, {str(match.get('ligne', '')).strip()}."
    suffixe = suffixe_de(match.get("ligne"))
    fin = f" {suffixe}" if suffixe else ""
    return f"Jëlal bus bu {compagnie}, numero {nombre_en_wolof(numero)}{fin}."


def phrase_reponse(lignes: list[dict]) -> str:
    """La phrase à dire pour des lignes directes, dans l'ordre affiché."""
    morceaux = [_dit_ligne(match) for match in lignes_annoncees(lignes)]
    if not morceaux:
        return "Baal ma, gisuma bus bu dem fa."
    return " walla ".join(morceaux)


def _dit_etape(etape: dict) -> str:
    """Un bus d'un trajet avec changement : « bus bu Tata, numero fanweer ». """
    compagnie = compagnie_dite(str(etape.get("compagnie", "")).strip())
    numero = numero_de(etape.get("ligne"))
    if numero is None:
        return f"bus bu {compagnie}, {str(etape.get('ligne', '')).strip()}"
    suffixe = suffixe_de(etape.get("ligne"))
    fin = f" {suffixe}" if suffixe else ""
    return f"bus bu {compagnie}, numero {nombre_en_wolof(numero)}{fin}"


def phrase_correspondance(trajet: dict) -> str:
    """Une possibilité avec changement : 1er bus, « Ci ginnaaw, », 2e bus."""
    premier = _dit_etape(trajet["etape_1"])
    second = _dit_etape(trajet["etape_2"])
    return f"Jëlal {premier}. Ci ginnaaw, jëlal {second}."


def phrase_correspondances(correspondances: list[dict]) -> str:
    """Toutes les possibilités avec changement, dans l'ordre affiché, au plus 3.

    Chaque possibilité garde son « Ci ginnaaw, » interne ; « Walla, » marque le
    passage à la possibilité suivante, comme les cartes « Autre possibilité ».
    """
    phrases = [
        phrase_correspondance(trajet)
        for trajet in correspondances[:MAX_POSSIBILITES]
    ]
    if not phrases:
        return "Baal ma, gisuma bus bu dem fa."
    return " Walla, ".join(phrases)


def _slug(texte: str) -> str:
    """Forme de fichier : accents retirés, espaces et ponctuation en soulignés."""
    sans_accent = unicodedata.normalize("NFKD", texte)
    en_ascii = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z0-9]+", "_", en_ascii).strip("_").lower()


def nom_cache(compagnie: str, numero: int) -> str:
    """Nom de fichier d'une ligne : Tata AFTU 25 devient tata_aftu_25.wav."""
    return f"{_slug(compagnie)}_{numero}.wav"


def nom_cache_texte(compagnie: str, ligne: str) -> str:
    """Nom de fichier d'une ligne sans numéro : TAF TAF devient ..._taf_taf.wav."""
    return f"{_slug(compagnie)}_{_slug(ligne)}.wav"


def nom_cache_match(match: dict) -> str:
    """Le nom du WAV d'une ligne, qu'elle ait un numéro, une lettre ou non."""
    compagnie = str(match.get("compagnie", "")).strip()
    numero = numero_de(match.get("ligne"))
    if numero is None:
        return nom_cache_texte(compagnie, str(match.get("ligne", "")))
    suffixe = suffixe_de(match.get("ligne"))
    if suffixe:
        return f"{_slug(compagnie)}_{numero}{suffixe.lower()}.wav"
    return nom_cache(compagnie, numero)


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


def _segment_manquant(nom: str) -> None:
    """Signale un audio absent sans interrompre la réponse.

    On saute le segment : la voix perd un mot, mais l'usager n'attend pas une
    synthèse de plusieurs secondes et l'app ne plante pas. Le journal du Space
    dit quel fichier générer avec Adia.
    """
    print(f"[voix] segment manquant : {nom} (ignoré, à générer avec Adia)", flush=True)


def _separateur(dossier: Path, nom: str) -> list[Path]:
    """Le WAV de liaison s'il existe, sinon rien (le silence de 0,3 s suffit)."""
    chemin = dossier / nom
    if chemin.is_file():
        return [chemin]
    _segment_manquant(nom)
    return []


def voix_depuis_cache(
    lignes: list[dict], cache_dir: Path | None = None
) -> bytes | None:
    """L'audio des lignes directes, dans l'ordre affiché, au plus 3.

    Un segment absent est sauté et signalé : on assemble ce qui existe plutôt
    que de renvoyer None, car la synthèse en direct (ancienne voix) ne doit pas
    remplacer les nouveaux morceaux Adia.
    """
    dossier = cache_dir or CACHE_DIR
    if not lignes:
        chemin = dossier / AUCUNE_LIGNE
        if not chemin.is_file():
            _segment_manquant(AUCUNE_LIGNE)
            return None
        return assembler([chemin])

    fichiers: list[Path] = []
    for match in lignes_annoncees(lignes):
        chemin = dossier / nom_cache_match(match)
        if not chemin.is_file():
            _segment_manquant(chemin.name)
            continue
        if fichiers:
            fichiers.extend(_separateur(dossier, WALLA))
        fichiers.append(chemin)
    if not fichiers:
        return None
    return assembler(fichiers)


def voix_correspondances_depuis_cache(
    correspondances: list[dict], cache_dir: Path | None = None
) -> bytes | None:
    """L'audio de TOUTES les possibilités avec changement, au plus 3.

    Chaque possibilité : 1er bus, « Ci ginnaaw, », 2e bus. « Walla, » sépare
    deux possibilités. Un morceau absent est sauté et journalisé, jamais
    remplacé par la voix SpeechT5.
    """
    dossier = cache_dir or CACHE_DIR
    fichiers: list[Path] = []
    for trajet in correspondances[:MAX_POSSIBILITES]:
        if fichiers:
            fichiers.extend(_separateur(dossier, WALLA_AUTRE))
        etapes: list[Path] = []
        for etape in (trajet["etape_1"], trajet["etape_2"]):
            chemin = dossier / nom_cache_match(etape)
            if chemin.is_file():
                etapes.append(chemin)
            else:
                _segment_manquant(chemin.name)
        if len(etapes) == 2:
            etapes[1:1] = _separateur(dossier, LIAISON_CORRESPONDANCE)
        fichiers.extend(etapes)
    if not fichiers:
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
