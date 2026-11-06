r"""Installe la voix native Oolel (8_1_c.wav) dans data/tts_cache_oolel/.

À lancer en local, une fois `tts_cache_oolel.zip` récupéré depuis le notebook
`notebooks/voix_oolel_complete.ipynb` (869 audios : les 637 du plan + les 232
ajouts, générés avec la voix du Space soynade-research/Oolel-Voices-Demo). Le
script vérifie que l'archive contient bien chacun des fichiers attendus (la
liste est dans data/audit/voix_complete.csv), puis recopie les WAV.

data/tts_cache/ et data/tts_cache_ajouts/ ne sont jamais touchés : ils restent
en secours tant que data/tts_cache_oolel/ n'est pas complet (l'app lit les trois
dossiers dans cet ordre, voir src/tts/speak.py).

Il ne lance rien tout seul : c'est un outil qu'on exécute à la main.

    python scripts/installer_voix_oolel.py tts_cache_oolel.zip
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CACHE = RACINE / "data" / "tts_cache_oolel"
LISTE = RACINE / "data" / "audit" / "voix_complete.csv"


def fichiers_attendus() -> list[str]:
    """Les noms de WAV que le nouveau cache doit contenir, d'après voix_complete.csv."""
    with LISTE.open(encoding="utf-8", newline="") as fichier:
        return [rangee["fichier_wav"] for rangee in csv.DictReader(fichier)]


def main() -> int:
    parseur = argparse.ArgumentParser(
        description="Installe la voix native d'Oolel (8_1_c.wav) dans data/tts_cache_oolel/."
    )
    parseur.add_argument(
        "archive",
        nargs="?",
        default=str(RACINE / "tts_cache_oolel.zip"),
        help="archive .zip produite par le notebook Colab",
    )
    args = parseur.parse_args()

    archive = Path(args.archive)
    if not archive.is_file():
        print(f"archive introuvable : {archive}", file=sys.stderr)
        return 1

    attendus = fichiers_attendus()
    with zipfile.ZipFile(archive) as boite:
        par_nom = {Path(nom).name: nom for nom in boite.namelist() if nom.lower().endswith(".wav")}
        manquants = [nom for nom in attendus if nom not in par_nom]
        if manquants:
            print(f"{len(manquants)} fichier(s) manquant(s) dans l'archive, ex. : {manquants[:5]}", file=sys.stderr)
            return 1

        CACHE.mkdir(parents=True, exist_ok=True)
        for nom in attendus:
            with boite.open(par_nom[nom]) as source, open(CACHE / nom, "wb") as cible:
                shutil.copyfileobj(source, cible)

    print(f"{len(attendus)} audios installés dans {CACHE} (voix native Oolel, 8_1_c.wav)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
