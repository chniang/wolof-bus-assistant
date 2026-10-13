"""Installe la voix Adia_TTS dans data/tts_cache/.

À lancer en local, une fois `tts_cache_adia.zip` récupéré depuis le notebook
`notebooks/voix_adia_colab.ipynb`. Le script :

1. vérifie que l'archive contient bien tous les fichiers attendus
   (la liste est dans scripts/phrases_voix.json) ;
2. sauvegarde l'ancien cache (voix SpeechT5) dans un dossier horodaté ;
3. recopie les nouveaux WAV par-dessus ;
4. réécrit le marqueur qui autorise l'app à se passer du modèle en direct.

Il ne lance rien tout seul : c'est un outil qu'on exécute à la main.

    python scripts/installer_voix_adia.py tts_cache_adia.zip
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CACHE = RACINE / "data" / "tts_cache"
PLAN = RACINE / "scripts" / "phrases_voix.json"
MARQUEUR = CACHE / "cache_complet.txt"


def fichiers_attendus() -> list[str]:
    """Les noms de WAV que le cache doit contenir, d'après phrases_voix.json."""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    return [entree["fichier"] for entree in plan["phrases"]]


def main() -> int:
    parseur = argparse.ArgumentParser(description="Installe la voix Adia_TTS dans le cache TTS.")
    parseur.add_argument(
        "archive",
        nargs="?",
        default=str(RACINE / "tts_cache_adia.zip"),
        help="archive .zip produite par le notebook Colab",
    )
    parseur.add_argument(
        "--sans-sauvegarde",
        action="store_true",
        help="ne pas copier l'ancien cache avant de le remplacer",
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

        if not args.sans_sauvegarde and CACHE.exists():
            sauvegarde = RACINE / "data" / f"tts_cache_avant_adia_{time.strftime('%Y%m%d_%H%M%S')}"
            shutil.copytree(CACHE, sauvegarde)
            print(f"ancien cache sauvegardé : {sauvegarde}")

        # Tant que le marqueur est là, l'app croit le cache complet : on le retire
        # le temps de la copie pour qu'une interruption retombe sur la synthèse.
        MARQUEUR.unlink(missing_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        for nom in attendus:
            with boite.open(par_nom[nom]) as source, open(CACHE / nom, "wb") as cible:
                shutil.copyfileobj(source, cible)

    MARQUEUR.write_text(
        f"{len(attendus)} audios prêts, voix Adia_TTS (CONCREE), "
        f"installés le {time.strftime('%Y-%m-%d %H:%M')}\n",
        encoding="utf-8",
    )
    print(f"{len(attendus)} audios installés dans {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
