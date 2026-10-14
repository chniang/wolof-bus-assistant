r"""Transcrit les vocaux « ok » de data/collecte/metadata.csv avec Whisper wolof.

Utilisation :
    .\.venv\Scripts\python.exe scripts\transcrire_collecte.py

On reprend le modèle et les réglages de src/asr/transcribe.py (Whisper small
wolof quantifié, CPU) : pas de seconde implémentation, seulement la boucle qui
relie les vocaux de la collecte à cette fonction.

Le script REPREND là où il s'est arrêté : tout file_name déjà présent dans
data/collecte/asr_whisper.csv est sauté. Les nouveaux sont ajoutés à la fin du
fichier, une ligne à la fois, avec flush après chaque vocal : si la machine
s'arrête au milieu, les transcriptions déjà écrites sont conservées et le
prochain lancement repart du premier vocal manquant.

Seuls les vocaux de statut « ok » sont traités. Aucun fichier audio n'est
modifié : ils sont ouverts en lecture seule.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from asr.transcribe import load_audio, load_model, transcrire  # noqa: E402

COLLECTE = RACINE / "data" / "collecte"
META = COLLECTE / "metadata.csv"
SORTIE = COLLECTE / "asr_whisper.csv"
CHAMP = "transcription_whisper"


def _lire_ok(meta: Path) -> list[dict]:
    """Lignes de metadata.csv de statut « ok », dans l'ordre du fichier."""
    with open(meta, "r", encoding="utf-8", newline="") as fichier:
        return [
            ligne
            for ligne in csv.DictReader(fichier)
            if (ligne.get("statut") or "").strip() == "ok"
        ]


def _file_names_deja_faits(sortie: Path) -> set[str]:
    """file_name déjà transcrits (colonne file_name de asr_whisper.csv)."""
    if not sortie.exists():
        return set()
    with open(sortie, "r", encoding="utf-8", newline="") as fichier:
        return {
            (ligne.get("file_name") or "").strip()
            for ligne in csv.DictReader(fichier)
        }


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not META.exists():
        print(f"metadata.csv introuvable : {META}")
        return 1

    ok = _lire_ok(META)
    total = len(ok)
    faits = _file_names_deja_faits(SORTIE)
    a_faire = [
        (position, ligne)
        for position, ligne in enumerate(ok, start=1)
        if (ligne.get("file_name") or "").strip() not in faits
    ]

    if not a_faire:
        print(f"Rien à faire : les {total} vocaux « ok » sont déjà transcrits.")
        return 0

    print(f"{len(faits)} déjà transcrits, {len(a_faire)} à faire sur {total}.")
    print("Chargement du modèle (long la première fois, ~1 min) …")
    modele = load_model()

    nouveau = not SORTIE.exists()
    transcrits = 0
    try:
        with open(SORTIE, "a", encoding="utf-8", newline="") as fichier:
            redacteur = csv.writer(fichier)
            if nouveau:
                redacteur.writerow(["file_name", CHAMP])
                fichier.flush()

            for position, ligne in a_faire:
                nom = (ligne.get("file_name") or "").strip()
                chemin = COLLECTE / nom
                if not chemin.is_file():
                    print(f"{position}/{total} {nom} : audio introuvable, sauté", flush=True)
                    continue

                debut = time.perf_counter()
                with open(chemin, "rb") as audio_fichier:
                    audio = load_audio(audio_fichier.read())
                texte = transcrire(modele, audio)
                duree = time.perf_counter() - debut

                redacteur.writerow([nom, texte])
                fichier.flush()
                transcrits += 1
                print(f"{position}/{total} {nom} ({duree:.0f} s) -> {texte}", flush=True)
    except KeyboardInterrupt:
        print(f"\nInterrompu : {transcrits} vocal(aux) ajouté(s) avant l'arrêt.", flush=True)
        return 130

    print(f"\nTerminé : {transcrits} vocal(aux) ajouté(s) à {SORTIE.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
