r"""Passe d'orthographe sur les transcriptions collectées, avant le fine-tuning.

Usage :
    .\.venv\Scripts\python.exe scripts\nettoyer_transcriptions.py
    .\.venv\Scripts\python.exe scripts\nettoyer_transcriptions.py --apercu
    .\.venv\Scripts\python.exe scripts\nettoyer_transcriptions.py chemin\metadata.csv
    .\.venv\Scripts\python.exe scripts\nettoyer_transcriptions.py --signaler

Ne touche JAMAIS aux fichiers audio. Ajoute (ou met à jour) la colonne
« transcription_propre » à côté de « transcription », qui garde la version
d'origine. Les noms de lieux y sont réécrits comme dans l'app
(data/lignes_dakar.csv, data/itineraires_dakar.csv) ; les mots wolof (maa ngi,
dama bëgg, dém, diougué...) ne sont jamais modifiés.

Pour les prochains vocaux : relancer ce script après scripts/preparer_collecte.py.
« --apercu » montre les changements sans écrire ; « --signaler » liste les mots
de lieux qui ne sont reconnus ni par la table ni par l'app, à valider à la main.
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------- #
# Table des remplacements, lisible : « forme entendue » -> « nom de l'app ».
# L'ordre n'importe pas : les expressions les plus longues passent d'abord, et
# un remplacement ne s'applique qu'une fois (pas d'enchaînement).
# La comparaison ignore la casse ET les accents ; « espace » et « tiret » sont
# interchangeables. Ne figure ici QUE des noms de lieux : les mots wolof sont
# laissés intacts.
# --------------------------------------------------------------------------- #
REMPLACEMENTS_LIEUX = {
    # --- Fass / Mbao -------------------------------------------------------
    "face mbao": "Fass Mbao",
    "fass mbao": "Fass Mbao",
    "face": "Fass",
    "fass": "Fass",
    # Whisper (variante sûre).
    "faas": "Fass",
    "grand mbao": "Grand Mbao",
    "petit mbao": "Petit Mbao",
    "sicap mbao": "SICAP Mbao",
    "mbao": "Mbao",
    # Whisper (variante « sûre », scripts/analyser_whisper.py étape 5) : ≥2
    # occurrences, ≥2 locuteurs, lieu confirmé comme le plus proche.
    "mbaaw": "Mbao",
    # --- Guédiawaye / Diamaguène -------------------------------------------
    "guediawaye": "Guédiawaye",
    "guediaway": "Guédiawaye",
    "gudiaway": "Guédiawaye",
    "guediewaye": "Guédiawaye",
    "diam gueun": "Diamaguène",
    "diamaguene": "Diamaguène",
    "diamagueune": "Diamaguène",
    # --- Jaxaay ------------------------------------------------------------
    "diakhay": "Jaxaay",
    "jaxaay": "Jaxaay",
    # --- Tally -------------------------------------------------------------
    "benneuh tally": "Bène Tally",
    "bene tally": "Bène Tally",
    "niary tally": "Niary Tally",
    "niarry tally": "Niary Tally",
    # --- Petersen ----------------------------------------------------------
    "patersen": "Petersen",
    "petersen": "Petersen",
    # --- Keur --------------------------------------------------------------
    "keur massar": "Keur Massar",
    "keur massa": "Keur Massar",
    "keur masar": "Keur Massar",
    "keur massare": "Keur Massar",
    # Whisper (variante sûre) : « ma » coupe le lieu en deux, d'où la forme.
    "ker ma saar": "Keur Massar",
    "keur mbaye fall": "Keur Mbaye Fall",
    "keurmbaye fall": "Keur Mbaye Fall",
    "keur ndiaye lo": "Keur Ndiaye Lo",
    # --- Foire -------------------------------------------------------------
    "nord foire": "Nord Foire",
    "nord foir": "Nord Foire",
    "ouest foire": "Ouest Foire",
    "ouest foir": "Ouest Foire",
    "west foire": "Ouest Foire",
    "foire": "Foire",
    # « foor » (Whisper, variante sûre) a besoin de contexte (jamais devant
    # « dem », « noor foor » reste Nord Foire) : géré à part par _nettoyer_foor,
    # pas dans cette table. Voir plus bas, avant REMPLACEMENTS_FORMULES.
    # --- Sacré-Cœur / Parcelles / HLM --------------------------------------
    "sacre coeur": "Sacré-Cœur",
    "scare coeur": "Sacré-Cœur",
    "sacre cour": "Sacré-Cœur",
    "sakkere ker": "Sacré-Cœur",
    "sakre ker": "Sacré-Cœur",
    "sakre keur": "Sacré-Cœur",
    "sacre keur": "Sacré-Cœur",
    # Whisper (variante sûre).
    "sakkari ker": "Sacré-Cœur",
    "parcelle assainie": "Parcelles Assainies",
    "parcelles assainies": "Parcelles Assainies",
    "parcelle": "Parcelles",
    "percelle": "Parcelles",
    "parcelles": "Parcelles",
    # Whisper (variante sûre).
    "parsel": "Parcelles",
    "hlm": "HLM",
    "assalem": "HLM",
    "asslem": "HLM",
    "asselem": "HLM",
    "asalem": "HLM",
    "aselem": "HLM",
    "achelem": "HLM",
    "as lm": "HLM",
    "a s l m": "HLM",
    # Whisper (variante sûre).
    "asoleem": "HLM",
    "aslem": "HLM",
    "oshlem": "HLM",
    # --- Yarakh / Almadies / Mamelles --------------------------------------
    "yaraakh": "Yarakh",
    "yarakh": "Yarakh",
    # Whisper (variante sûre).
    "yaraax": "Yarakh",
    "almadie": "Almadies",
    "almadies": "Almadies",
    "mamelle": "Mamelles",
    "mamelles": "Mamelles",
    # --- Grands quartiers --------------------------------------------------
    "grand yoff": "Grand Yoff",
    "grand yof": "Grand Yoff",
    "grend yoff": "Grand Yoff",
    "grand-yoff": "Grand Yoff",
    "grand medine": "HLM Grand Médine",
    "hlm grand medine": "HLM Grand Médine",
    "hlm grand yoff": "HLM Grand Yoff",
    "grand dakar": "Grand Dakar",
    "dakar plateau": "Dakar Plateau",
    "plateau": "Plateau",
    "sam": "Sam Notaire",
    "dalale diame": "Hôpital Dalal Diam",
    "dalal diam": "Hôpital Dalal Diam",
    # --- Centre / Plateaux -------------------------------------------------
    "medina": "Médina",
    "mermoz": "Mermoz",
    "ouakam": "Ouakam",
    "wakaam": "Ouakam",
    "wakam": "Ouakam",
    "ngor": "Ngor",
    "yoff tonghor": "Yoff",
    "yoff": "Yoff",
    # Whisper (variante sûre).
    "yoof": "Yoff",
    "point e": "Point E",
    "sandaga": "Sandaga",
    "colobane": "Colobane",
    "collobane": "Colobane",
    "claudel": "Claudel",
    # --- Gueule Tapée / Dieuppeul / Maristes -------------------------------
    "gueule tapee": "Gueule Tapée",
    "gueule tape": "Gueule Tapée",
    "geule tapee": "Gueule Tapée",
    "geule tape": "Gueule Tapée",
    "geul tapei": "Gueule Tapée",
    "dieuppeul": "Dieuppeul",
    "dieupeul": "Dieuppeul",
    # Whisper (variante sûre).
    "jeppal": "Dieuppeul",
    "maristes": "Maristes",
    "mariste": "Maristes",
    # --- Patte d'Oie -------------------------------------------------------
    "pattes d'oie": "Patte d'Oie",
    "patte d'oie": "Patte d'Oie",
    "pattee d'oie": "Patte d'Oie",
    "pates d'oie": "Patte d'Oie",
    "pate d'oie": "Patte d'Oie",
    "pattesd'oie": "Patte d'Oie",
    # --- Thiaroye / Tivaouane / Yeumbeul / Rufisque ------------------------
    "poste thiaroye": "Poste Thiaroye",
    "thiaroye": "Thiaroye",
    "thiaroy": "Thiaroye",
    "tivaouane peulh": "Tivaouane Peulh",
    "tivaouane peul": "Tivaouane Peulh",
    "yeumbeul": "Yeumbeul",
    # Whisper (variante sûre).
    "yembal": "Yeumbeul",
    "rufisque": "Rufisque",
    "sebikotane": "Sébikotane",
    "bargny": "Bargny",
    "diamniadio": "Diamniadio",
    "pikine": "Pikine",
    "zone de captage": "Zone de Captage",
    # Whisper (variante sûre).
    "sonde kaptas": "Zone de Captage",
    # --- Cité / Golf / Autres ---------------------------------------------
    "cite soprime": "Cité Soprim",
    "cite soprim": "Cité Soprim",
    "soprim": "Cité Soprim",
    "cite keur gorgui": "Cité Keur Gorgui",
    "cite keur gor gui": "Cité Keur Gorgui",
    "cite fadia": "Cité Fadia",
    "cite mixta": "Cité Mixta",
    "case beu": "Case Ba",
    "case ba": "Case Ba",
    "golf sud": "Golf Sud",
    "golf": "Golf",
    "castors": "Castors",
    "castor": "Castors",
    "boune": "Boune",
    "toubab diallaw": "Toubab Dialaw",
    "toubab dialaw": "Toubab Dialaw",
    "universite cheikh anta diop": "Université Cheikh Anta Diop",
    "universite": "UCAD",
    "camberene": "Cambérène",
    "wakhinane nimzatt": "Guédiawaye",
    "wakhinane nimzat": "Guédiawaye",
    "wakhinane": "Wakhinane",
    "sicap liberte": "Liberté",
    "liberte": "Liberté",
    "liberti": "Liberté",
}

# Formules (hors noms de lieux) ramenées à une orthographe unique, pour que les
# transcriptions de fine-tuning ne gardent pas les déformations de l'ASR. Aucune
# n'est un nom de lieu : « ban bus » (« quel bus ») n'est jamais une destination,
# et « kurdem » est « pour dém ». Les composés ne sont réécrits qu'accolés.
REMPLACEMENTS_FORMULES = {
    "ban bus": "ban bus",
    "bann bus": "ban bus",
    "bane bus": "ban bus",
    "ben bus": "ban bus",
    "ban bis": "ban bus",
    "ben bis": "ban bus",
    "ben biis": "ban bus",
    "kur dem": "pour dem",
    "kurdem": "pour dem",
    # Marqueur de départ (« partir de X ») : Whisper l'entend souvent « juge »,
    # « njuge », « njugée », « jooge » (jamais présent tel quel dans la
    # transcription propre humaine, qui écrit toujours « diougué »/« diogué »
    # — vérifié sur toute la collecte, voir scripts/analyser_whisper.py).
    # Variantes sûres : ≥2 occurrences, ≥2 locuteurs différents chacune.
    # « dem » annonce l'ARRIVÉE (voir CLAUDE.md) : il n'est et ne doit JAMAIS
    # être dans cette table.
    "joge": "diougué",
    "juge": "diougué",
    "jooge": "diougué",
    "njuge": "diougué",
    "njugee": "diougué",
}

# Variantes accentuées par lettre : la table est écrite sans accent, la
# comparaison accepte toutes ces formes.
_VARIANTES = {
    "a": "aàâäã",
    "c": "cç",
    "e": "eéèêë",
    "i": "iîïíì",
    "n": "nñ",
    "o": "oôöóòõ",
    "u": "uùûüú",
    "y": "yÿý",
}

COLONNE_PROPRE = "transcription_propre"


def _motif(forme: str) -> str:
    """Motif regex accent-insensible d'une forme de la table.

    « oe » devient « (?:oe|œ) », l'espace et le tiret sont interchangeables.
    """
    morceaux: list[str] = []
    i = 0
    while i < len(forme):
        car = forme[i]
        if forme[i : i + 2].lower() == "oe":
            morceaux.append("(?:oe|œ)")
            i += 2
            continue
        if car.isspace():
            morceaux.append(r"[-\s]+")
        elif car in "'’":
            morceaux.append("['’]")
        elif car == "-":
            morceaux.append(r"[-\s]+")
        elif car.lower() in _VARIANTES:
            classe = _VARIANTES[car.lower()]
            morceaux.append("[" + re.escape(classe + classe.upper()) + "]")
        else:
            morceaux.append(re.escape(car))
        i += 1
    return "".join(morceaux)


def _compiler(table: dict[str, str]):
    paires = sorted(table.items(), key=lambda kv: len(kv[0]), reverse=True)
    motif = "|".join(f"(?P<g{i}>{_motif(src)})" for i, (src, _) in enumerate(paires))
    regex = re.compile(r"(?<!\w)(?:" + motif + r")(?!\w)", re.IGNORECASE)
    return regex, paires


_REGEX, _PAIRES = _compiler({**REMPLACEMENTS_LIEUX, **REMPLACEMENTS_FORMULES})

# « foor » (Foire) a besoin de contexte que la table ci-dessus ne peut pas
# exprimer (une seule forme -> une seule cible, toujours) : « noor foor »
# reste Nord Foire, et « foor » juste avant « dem » est « pour dem », jamais
# Foire (même raisonnement que src/intent/extract_intent.py). Appliqué à part,
# AVANT la table : « west/ouest foor » devient Foire en premier, pour ne pas
# se faire bloquer ensuite par le garde-fou « pas devant dem ».
_FOOR_OUEST = re.compile(r"(?<!\w)(?:west|ouest)\s+foor(?!\w)", re.IGNORECASE)
_FOOR_SEUL = re.compile(r"(?<!\w)(?<!noor\s)foor(?!\w)(?!\s+dem(?!\w))", re.IGNORECASE)


def _nettoyer_foor(texte: str) -> str:
    texte = _FOOR_OUEST.sub("Foire", texte)
    return _FOOR_SEUL.sub("Foire", texte)


def nettoyer(texte: str) -> str:
    """Réécrit les noms de lieux d'une transcription, sans toucher aux mots wolof."""
    if not texte:
        return texte
    texte = _nettoyer_foor(texte)
    return _REGEX.sub(lambda m: _PAIRES[int(m.lastgroup[1:])][1], texte)


def _variantes_connues() -> set[str]:
    """Formes de lieux déjà connues de la table et de lieux.py (pour --signaler)."""
    connues = {sans_accents(mot) for forme in REMPLACEMENTS_LIEUX.values() for mot in forme.split()}
    racine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(racine / "src"))
    try:
        from matching.lieux import forme, lieux_reconnaissables

        with open(racine / "data" / "itineraires_dakar.csv", newline="", encoding="utf-8") as fichier:
            arrets = sorted({r["arret"] for r in csv.DictReader(fichier)})
        for lieu in lieux_reconnaissables(arrets):
            connues.update(forme(lieu).split())
    except Exception:
        pass
    return connues


def signaler_candidats(lignes: list[dict]) -> list[tuple[str, str]]:
    """Mots qui ressemblent à des lieux sans être reconnus : (mot, contexte).

    Un mot est candidat s'il est capitalisé, isolé, absent des lieux connus de
    la table et de lieux.py, et absent de l'extraction locale. À valider à la
    main : ce sont les noms que la table ne couvre pas encore.
    """
    connues = _variantes_connues()
    # Petits mots usuels (français et wolof) qui ne sont jamais des lieux.
    ignores = {
        "maa", "ngi", "mangi", "mangui", "dama", "damaa", "ban", "bane", "bus", "moy",
        "mo", "lay", "la", "wara", "warra", "dieul", "dioul", "diougue", "diogue",
        "pour", "dem", "beugga", "beug", "beugue", "beugg", "bëgg", "nekk", "nek",
        "ak", "ci", "man", "gui", "de", "du", "mofay", "mofaye", "bann", "boguonn",
        "beugua", "beuguonn", "dé", "deeme", "démé", "déme", "collobane", "hlm",
    }
    candidats: list[tuple[str, str]] = []
    vus: set[str] = set()
    for ligne in lignes:
        propre = ligne.get(COLONNE_PROPRE) or ligne.get("transcription") or ""
        for mot in re.findall(r"[A-Za-zÀ-ÿ''-]+", propre):
            if not mot[:1].isupper():
                continue
            cle = sans_accents(mot).strip("'-")
            if not cle or cle in vus or cle in ignores or cle in connues:
                continue
            vus.add(cle)
            candidats.append((mot, propre))
    return candidats


def sans_accents(texte: str) -> str:
    texte = unicodedata.normalize("NFD", str(texte).lower().replace("œ", "oe"))
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------- #
# Traitement du fichier
# --------------------------------------------------------------------------- #

def traiter(meta: Path, ecrire: bool = True) -> list[tuple[str, str, str]]:
    """Ajoute/actualise transcription_propre. Renvoie les changements.

    La colonne transcription (version d'origine) n'est jamais modifiée. Aucun
    fichier audio n'est lu ni touché.
    """
    with open(meta, "r", encoding="utf-8", newline="") as fichier:
        lecteur = csv.DictReader(fichier)
        champs = list(lecteur.fieldnames or [])
        lignes = list(lecteur)
    if not champs:
        return []

    changements: list[tuple[str, str, str]] = []
    for ligne in lignes:
        source = (ligne.get("transcription") or "").strip()
        propre = nettoyer(source)
        ancien = ligne.get(COLONNE_PROPRE) or ""
        if propre != ancien:
            changements.append((ligne.get("file_name") or "?", ancien, propre))
        ligne[COLONNE_PROPRE] = propre

    if COLONNE_PROPRE not in champs:
        champs.append(COLONNE_PROPRE)

    if ecrire:
        with open(meta, "w", encoding="utf-8", newline="") as fichier:
            redacteur = csv.DictWriter(fichier, fieldnames=champs, extrasaction="ignore")
            redacteur.writeheader()
            redacteur.writerows(lignes)
    return changements


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    racine = Path(__file__).resolve().parents[1]
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "fichier",
        nargs="?",
        default=str(racine / "data" / "collecte" / "metadata.csv"),
        help="metadata.csv à nettoyer (défaut : data/collecte/metadata.csv)",
    )
    analyseur.add_argument("--apercu", action="store_true", help="n'écrit pas le fichier.")
    analyseur.add_argument(
        "--signaler", action="store_true", help="liste les lieux non reconnus restants."
    )
    args = analyseur.parse_args(argv[1:])

    meta = Path(args.fichier)
    if not meta.exists():
        print(f"metadata.csv introuvable : {meta}")
        return 1

    changements = traiter(meta, ecrire=not args.apercu)
    print(f"{len(changements)} transcription(s) modifiée(s) sur {_compter(meta)}.")
    for nom, ancien, nouveau in changements:
        print(f"  {nom}")
        print(f"      avant : {ancien!r}")
        print(f"      apre  : {nouveau!r}")

    if args.signaler:
        with open(meta, "r", encoding="utf-8", newline="") as fichier:
            lignes = list(csv.DictReader(fichier))
        candidats = signaler_candidats(lignes)
        print(f"\n{len(candidats)} mot(s) de lieu non reconnu(s), à valider :")
        for mot, contexte in candidats:
            print(f"  {mot!r}  (dans « {contexte} »)")
    return 0


def _compter(meta: Path) -> int:
    with open(meta, "r", encoding="utf-8", newline="") as fichier:
        return sum(1 for _ in csv.DictReader(fichier))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
