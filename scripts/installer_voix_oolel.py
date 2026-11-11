r"""Installe la voix native Oolel (8_1_c.wav) dans data/tts_cache_oolel/.

À lancer en local, une fois `tts_cache_oolel.zip` récupéré depuis le notebook
`notebooks/voix_oolel_complete.ipynb` (Colab) ou
`notebooks/voix_oolel_complete_brev.ipynb` (Brev — dans sortie_voix/) :
869 audios, les 637 du plan + les 232 ajouts, générés avec la voix du Space
soynade-research/Oolel-Voices-Demo. Le script vérifie que l'archive contient
bien chacun des fichiers attendus (la liste est dans
data/audit/voix_complete.csv), puis recopie les WAV.

data/tts_cache/ et data/tts_cache_ajouts/ ne sont jamais touchés : ils restent
en secours tant que data/tts_cache_oolel/ n'est pas complet (l'app lit les trois
dossiers dans cet ordre, voir src/tts/speak.py).

Le petit notebook voix_ajouts_conversation_brev.ipynb produit un zip séparé
(sortie_voix/ajouts_conversation.zip) : les 4 réponses de conversation récentes
+ des essais « Tata » à écouter. Avec --conversation, on n'installe que les
réponses de l'app, jamais les fichiers d'essai, et l'archive complète n'est pas
requise : les deux zips se posent l'un après l'autre dans le même cache.

Il ne lance rien tout seul : c'est un outil qu'on exécute à la main.

    python scripts/installer_voix_oolel.py tts_cache_oolel.zip              # Colab
    python scripts/installer_voix_oolel.py --zip sortie_voix/tts_cache_oolel.zip
    python scripts/installer_voix_oolel.py --conversation sortie_voix/ajouts_conversation.zip
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

# Les réponses de conversation du petit notebook : seuls ces noms-là sont des
# réponses de l'app. Tout le reste du zip (test_tata_*.wav) reste à écouter.
CONVERSATION = (
    "conversation_ci_lo_nekk.wav",
    "conversation_liggeey.wav",
    "conversation_dekk.wav",
    "conversation_wolof.wav",
)


def fichiers_attendus() -> list[str]:
    """Les noms de WAV que le nouveau cache doit contenir, d'après voix_complete.csv."""
    with LISTE.open(encoding="utf-8", newline="") as fichier:
        return [rangee["fichier_wav"] for rangee in csv.DictReader(fichier)]


def installer(archive: Path, attendus: list[str], cache: Path = CACHE) -> int:
    """Vérifie le contenu de l'archive puis l'installe ; 0 si tout va bien, 1 sinon.

    Les noms attendus sont passés en clair (voix_complete.csv par défaut) :
    ainsi les tests peuvent essayer le script sur une archive de deux WAV
    sans que rien ne se déverse un jour dans le vrai cache du dépôt.
    """
    with zipfile.ZipFile(archive) as boite:
        par_nom = {Path(nom).name: nom for nom in boite.namelist() if nom.lower().endswith(".wav")}
        manquants = [nom for nom in attendus if nom not in par_nom]
        if manquants:
            print(f"{len(manquants)} fichier(s) manquant(s) dans l'archive, ex. : {manquants[:5]}", file=sys.stderr)
            return 1

        cache.mkdir(parents=True, exist_ok=True)
        for nom in attendus:
            with boite.open(par_nom[nom]) as source, open(cache / nom, "wb") as cible:
                shutil.copyfileobj(source, cible)

    print(f"{len(attendus)} audios installés dans {cache} (voix native Oolel, 8_1_c.wav)")
    return 0


def installer_conversation(archive: Path, cache: Path = CACHE) -> int:
    """Installe le petit zip « ajouts_conversation » ; 0 si tout va bien, 1 sinon.

    Seules les 4 réponses de conversation (CONVERSATION) sont recopiées :
    les essais « Tata » et tout autre fichier du zip restent sur le côté.
    L'archive complète (873 noms) n'est pas exigée — c'est le but de ce zip
    séparé : poser les nouvelles réponses sans refaire la voix entière.
    """
    with zipfile.ZipFile(archive) as boite:
        par_nom = {Path(nom).name: nom for nom in boite.namelist() if nom.lower().endswith(".wav")}
        manquants = [nom for nom in CONVERSATION if nom not in par_nom]
        if manquants:
            print(f"{len(manquants)} fichier(s) manquant(s) dans l'archive, ex. : {manquants[:5]}", file=sys.stderr)
            return 1

        cache.mkdir(parents=True, exist_ok=True)
        for nom in CONVERSATION:
            with boite.open(par_nom[nom]) as source, open(cache / nom, "wb") as cible:
                shutil.copyfileobj(source, cible)

    ignores = sorted(nom for nom in par_nom if nom not in CONVERSATION)
    if ignores:
        print(f"ignoré(s), fichiers d'essai et non réponses de l'app : {', '.join(ignores)}")
    print(f"{len(CONVERSATION)} audios installés dans {cache} (voix native Oolel, 8_1_c.wav)")
    return 0


def main() -> int:
    parseur = argparse.ArgumentParser(
        description="Installe la voix native d'Oolel (8_1_c.wav) dans data/tts_cache_oolel/."
    )
    parseur.add_argument(
        "archive",
        nargs="?",
        default=None,
        help="archive .zip produite par le notebook (Colab ou Brev)",
    )
    parseur.add_argument(
        "--zip",
        dest="zip",
        default=None,
        help="même archive, orthographe du notebook Brev (--zip sortie_voix/tts_cache_oolel.zip)",
    )
    parseur.add_argument(
        "--conversation",
        dest="conversation",
        default=None,
        help="petit zip des réponses de conversation (--conversation sortie_voix/ajouts_conversation.zip)",
    )
    args = parseur.parse_args()

    if args.conversation:
        archive = Path(args.conversation)
        if not archive.is_file():
            print(f"archive introuvable : {archive}", file=sys.stderr)
            return 1
        return installer_conversation(archive)

    chemin = args.zip or args.archive or "tts_cache_oolel.zip"
    archive = Path(chemin)
    if not archive.is_file():
        print(f"archive introuvable : {archive}", file=sys.stderr)
        return 1

    return installer(archive, fichiers_attendus())


if __name__ == "__main__":
    sys.exit(main())
