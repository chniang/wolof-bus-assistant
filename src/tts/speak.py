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
# Dans un changement : « … nga wàcc <lieu> » et « … moo lay yóbbu ba <lieu> ».
NGA_WACC = "nga_wacc.wav"
MOO_LAY_YOBBU_BA = "moo_lay_yobbu_ba.wav"

# Plafond commun à l'affichage (stops_matcher) et à la voix : au-delà de trois
# possibilités, l'oral devient trop long et l'usager décroche.
MAX_POSSIBILITES = 3

# Un silence entre deux morceaux, sinon « walla » se colle à la ligne d'avant.
SILENCE_ENTRE = 0.3
# Entre le connecteur et le nom du lieu, la pause doit être plus courte : on dit
# « nga wàcc Gadaye » d'un trait, pas avec un blanc de fin de phrase.
PAUSE_LIEU = 0.1


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


UNITES_FR = {
    0: "zéro",
    1: "un",
    2: "deux",
    3: "trois",
    4: "quatre",
    5: "cinq",
    6: "six",
    7: "sept",
    8: "huit",
    9: "neuf",
    10: "dix",
    11: "onze",
    12: "douze",
    13: "treize",
    14: "quatorze",
    15: "quinze",
    16: "seize",
}
DIZAINES_FR = {
    20: "vingt",
    30: "trente",
    40: "quarante",
    50: "cinquante",
    60: "soixante",
}


def nombre_en_francais(n: int) -> str:
    """Écrit un nombre en français pour les noms de lieux (« Liberté 6 »)."""
    n = int(n)
    if n < 17:
        return UNITES_FR[n]
    if n < 20:
        return f"dix-{UNITES_FR[n - 10]}"
    if n < 70:
        dizaine, reste = divmod(n, 10)
        mot = DIZAINES_FR[dizaine * 10]
        if reste == 0:
            return mot
        if reste == 1:
            return f"{mot} et un"
        return f"{mot}-{UNITES_FR[reste]}"
    if n < 80:
        if n == 71:
            return "soixante et onze"
        return f"soixante-{nombre_en_francais(n - 60)}"
    if n < 100:
        if n == 80:
            return "quatre-vingts"
        if n < 90:
            return f"quatre-vingt-{UNITES_FR[n - 80]}"
        if n == 90:
            return "quatre-vingt-dix"
        return f"quatre-vingt-{nombre_en_francais(n - 80)}"
    if n < 1000:
        centaines, reste = divmod(n, 100)
        tete = "cent" if centaines == 1 else f"{nombre_en_francais(centaines)} cent"
        if reste == 0:
            return tete + ("s" if centaines > 1 else "")
        return f"{tete} {nombre_en_francais(reste)}"
    return str(n)


def _mots_chiffres(chiffres: str) -> str:
    """« 02 » -> « zéro deux », pour ne pas perdre le zéro de « UE 02 »."""
    if len(chiffres) > 1 and chiffres.startswith("0"):
        return " ".join(UNITES_FR[int(caractere)] for caractere in chiffres)
    return nombre_en_francais(int(chiffres))


def nom_lieu_parle(arret: object) -> str:
    """Le nom d'un arrêt tel qu'on le dit à Dakar.

    « Av Hyacinthe Thiandoum (Grand-Yoff) » -> « Avenue Hyacinthe Thiandoum ».
    Les chiffres sont dits en français (« Palais 1 » -> « Palais un ») : c'est
    la langue des noms de rues, même quand la phrase autour est en wolof.
    """
    texte = str(arret if arret is not None else "")
    texte = re.sub(r"\s*\([^)]*\)", "", texte)
    texte = re.sub(r"\bAv\.?(?=\s|$)", "Avenue", texte, flags=re.IGNORECASE)
    texte = re.sub(r"\bBd\.?(?=\s|$)", "Boulevard", texte, flags=re.IGNORECASE)
    texte = re.sub(
        r"\d+",
        lambda trouve: f" {_mots_chiffres(trouve.group())} ",
        texte,
    )
    texte = texte.replace("&", " et ")
    return " ".join(texte.split())


def nom_fichier_lieu(arret: object) -> str:
    """Le WAV d'un arrêt ; deux noms qui se disent pareil partagent le fichier."""
    return f"lieu_{_slug(nom_lieu_parle(arret))}.wav"


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
    """Une possibilité avec changement, avec les lieux où l'on monte et descend.

    Exemple : « Jëlal bus bu Dem Dikk, numero …, nga wàcc Gadaye. Ci ginnaaw,
    jëlal bus bu Tata, numero …, moo lay yóbbu ba Malika. »
    """
    etape_1 = trajet["etape_1"]
    etape_2 = trajet["etape_2"]
    premier = _dit_etape(etape_1)
    second = _dit_etape(etape_2)
    changement = nom_lieu_parle(trajet.get("changement") or etape_1.get("descend_a"))
    descente = nom_lieu_parle(etape_2.get("descend_a"))

    debut = f"Jëlal {premier}"
    if changement:
        debut += f", nga wàcc {changement}"
    fin = f"Ci ginnaaw, jëlal {second}"
    if descente:
        fin += f", moo lay yóbbu ba {descente}"
    return f"{debut}. {fin}."


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


def assembler(
    fichiers: list[Path], pauses: list[float] | None = None
) -> bytes:
    """Colle des WAV bout à bout avec un silence entre chaque, et renvoie les octets.

    `pauses[i]` est le silence après `fichiers[i]`. Sans liste, on garde le
    silence standard de 0,3 s partout. Tout vient du même modèle, donc tous les
    fichiers partagent la même fréquence : on reprend celle du premier.
    """
    import numpy as np
    import soundfile as sf

    morceaux = []
    for i, chemin in enumerate(fichiers):
        audio, sr = sf.read(str(chemin), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        morceaux.append(audio)
        if i < len(fichiers) - 1:
            pause = pauses[i] if pauses is not None else SILENCE_ENTRE
            morceaux.append(np.zeros(int(sr * pause), dtype="float32"))
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


def _ajoute_segment(
    morceaux: list[tuple[Path, float]], dossier: Path, nom: str, pause: float
) -> None:
    """Ajoute un WAV et la pause qui le suit ; signale le fichier absent."""
    chemin = dossier / nom
    if chemin.is_file():
        morceaux.append((chemin, pause))
    else:
        _segment_manquant(nom)


def _ajoute_lieu(
    morceaux: list[tuple[Path, float]],
    dossier: Path,
    connecteur: str,
    arret: object,
    pause_lieu: float,
) -> None:
    """Ajoute « connecteur + lieu », ou saute les deux si le lieu manque.

    Le connecteur seul (« nga wàcc ») ne veut rien dire : mieux vaut le taire
    que de laisser l'usager attendre un nom d'arrêt qui n'arrive pas.
    """
    if not str(arret if arret is not None else "").strip():
        return
    nom_lieu = nom_fichier_lieu(arret)
    chemin_lieu = dossier / nom_lieu
    if not chemin_lieu.is_file():
        _segment_manquant(nom_lieu)
        return
    _ajoute_segment(morceaux, dossier, connecteur, PAUSE_LIEU)
    morceaux.append((chemin_lieu, pause_lieu))


def plan_correspondance(
    trajet: dict, cache_dir: Path | None = None
) -> list[tuple[Path, float]]:
    """Les morceaux d'une possibilité avec changement, dans l'ordre à dire.

    Chaque élément porte la pause qui le suit : 0,1 s après « nga wàcc » et
    « moo lay yóbbu ba », 0,3 s ailleurs. Le premier bus et le second restent
    joués même si un lieu manque.
    """
    dossier = cache_dir or CACHE_DIR
    etape_1 = trajet["etape_1"]
    etape_2 = trajet["etape_2"]
    changement = trajet.get("changement") or etape_1.get("descend_a")
    descente = etape_2.get("descend_a")

    morceaux: list[tuple[Path, float]] = []
    _ajoute_segment(morceaux, dossier, nom_cache_match(etape_1), SILENCE_ENTRE)
    _ajoute_lieu(morceaux, dossier, NGA_WACC, changement, SILENCE_ENTRE)
    _ajoute_segment(
        morceaux, dossier, LIAISON_CORRESPONDANCE, SILENCE_ENTRE
    )
    _ajoute_segment(morceaux, dossier, nom_cache_match(etape_2), SILENCE_ENTRE)
    _ajoute_lieu(
        morceaux, dossier, MOO_LAY_YOBBU_BA, descente, SILENCE_ENTRE
    )
    return morceaux


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

    Chaque possibilité : 1er bus, « nga wàcc », lieu de changement,
    « Ci ginnaaw, », 2e bus, « moo lay yóbbu ba », lieu de descente.
    « Walla, » sépare deux possibilités. Un morceau absent est sauté et
    journalisé, jamais remplacé par la voix SpeechT5.
    """
    dossier = cache_dir or CACHE_DIR
    morceaux: list[tuple[Path, float]] = []
    for trajet in correspondances[:MAX_POSSIBILITES]:
        if morceaux:
            _ajoute_segment(morceaux, dossier, WALLA_AUTRE, SILENCE_ENTRE)
        morceaux.extend(plan_correspondance(trajet, dossier))
    if not morceaux:
        return None
    fichiers = [chemin for chemin, _ in morceaux]
    pauses = [pause for _, pause in morceaux[:-1]]
    return assembler(fichiers, pauses)


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
