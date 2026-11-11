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

Avec --tata, on ne remplace que les 72 phrases de ligne Tata (tata_aftu_*.wav),
régénérées avec « Tattaa », l'écriture choisie par un locuteur natif. Le CSV
de rapport du zip est ignoré, et aucun autre audio du cache n'est touché.

Il ne lance rien tout seul : c'est un outil qu'on exécute à la main.

    python scripts/installer_voix_oolel.py tts_cache_oolel.zip              # Colab
    python scripts/installer_voix_oolel.py --zip sortie_voix/tts_cache_oolel.zip
    python scripts/installer_voix_oolel.py --conversation sortie_voix/ajouts_conversation.zip
    python scripts/installer_voix_oolel.py --tata tata_tattaa.zip
    python scripts/installer_voix_oolel.py --liste sortie_voix/regen.zip data/audit/voix_gare.csv

Avec --liste, on remplace exactement les audios d'une liste (CSV : colonne
`fichier`), produits par notebooks/voix_regen_liste_brev.ipynb. Tout ou rien :
s'il en manque un seul dans le zip, rien n'est touché.
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


def fichiers_tata() -> list[str]:
    """Les 72 phrases de ligne Tata, d'après voix_complete.csv."""
    return [nom for nom in fichiers_attendus() if nom.startswith("tata_aftu_")]


def installer_tata(archive: Path, attendus: list[str], cache: Path = CACHE) -> int:
    """Remplace les phrases de ligne Tata ; 0 si tout va bien, 1 sinon.

    Tout ou rien : s'il manque une seule ligne dans le zip, on ne touche à rien,
    sinon la voix dirait « Tattaa » pour une ligne et « Tataa » pour la voisine.
    Seuls les noms tata_aftu_* attendus sont recopiés ; le reste du zip est ignoré.
    """
    if not attendus or not all(nom.startswith("tata_aftu_") for nom in attendus):
        print("liste Tata invalide : seuls les tata_aftu_*.wav sont remplaçables", file=sys.stderr)
        return 1
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

    ignores = sorted(nom for nom in boite.namelist() if Path(nom).name not in attendus)
    if ignores:
        print(f"ignoré(s) : {', '.join(ignores)}")
    print(f"{len(attendus)} lignes Tata installées dans {cache} (« Tattaa »)")
    return 0


def lire_liste(chemin_csv: Path) -> list[str]:
    """Les noms de la colonne « fichier » d'une liste à régénérer, sans doublon."""
    with chemin_csv.open(encoding="utf-8-sig", newline="") as fichier:
        lecteur = csv.DictReader(fichier)
        if "fichier" not in (lecteur.fieldnames or []):
            raise ValueError(f"{chemin_csv} : colonne « fichier » absente")
        noms = [rangee["fichier"].strip() for rangee in lecteur if rangee["fichier"].strip()]
    return list(dict.fromkeys(noms))


def installer_liste(
    archive: Path,
    noms: list[str],
    cache: Path = CACHE,
    connus: list[str] | None = None,
) -> int:
    """Remplace exactement les audios de la liste ; 0 si tout va bien, 1 sinon.

    Tout ou rien : un nom absent du zip, un nom inconnu de voix_complete.csv
    (faute de frappe qui créerait un fichier jamais joué) ou un nom qui n'est
    pas un simple .wav, et rien n'est copié. Le reste du zip (rapport,
    audios d'une autre liste) est ignoré.
    """
    if not noms:
        print("liste vide : rien à installer", file=sys.stderr)
        return 1
    mauvais = [nom for nom in noms if not nom.endswith(".wav") or Path(nom).name != nom]
    if mauvais:
        print(f"noms refusés (simple fichier .wav attendu) : {mauvais[:5]}", file=sys.stderr)
        return 1
    connus = fichiers_attendus() if connus is None else connus
    inconnus = [nom for nom in noms if nom not in set(connus)]
    if inconnus:
        print(f"{len(inconnus)} nom(s) absent(s) de voix_complete.csv, ex. : {inconnus[:5]}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(archive) as boite:
        par_nom = {Path(nom).name: nom for nom in boite.namelist() if nom.lower().endswith(".wav")}
        manquants = [nom for nom in noms if nom not in par_nom]
        if manquants:
            print(f"{len(manquants)} fichier(s) manquant(s) dans l'archive, ex. : {manquants[:5]}", file=sys.stderr)
            return 1
        cache.mkdir(parents=True, exist_ok=True)
        for nom in noms:
            with boite.open(par_nom[nom]) as source, open(cache / nom, "wb") as cible:
                shutil.copyfileobj(source, cible)
    print(f"{len(noms)} audios remplacés dans {cache} (liste)")
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
    parseur.add_argument(
        "--tata",
        dest="tata",
        default=None,
        help="zip des 72 lignes Tata régénérées avec « Tattaa » (--tata tata_tattaa.zip)",
    )
    parseur.add_argument(
        "--liste",
        dest="liste",
        nargs=2,
        metavar=("ZIP", "CSV"),
        default=None,
        help="zip du notebook voix_regen_liste_brev + la liste (colonne fichier) à remplacer",
    )
    args = parseur.parse_args()

    if args.liste:
        archive, liste = Path(args.liste[0]), Path(args.liste[1])
        for chemin in (archive, liste):
            if not chemin.is_file():
                print(f"introuvable : {chemin}", file=sys.stderr)
                return 1
        try:
            noms = lire_liste(liste)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        return installer_liste(archive, noms)

    if args.tata:
        archive = Path(args.tata)
        if not archive.is_file():
            print(f"archive introuvable : {archive}", file=sys.stderr)
            return 1
        return installer_tata(archive, fichiers_tata())

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
