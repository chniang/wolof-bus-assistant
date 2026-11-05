r"""Ce que le moteur v2 peut dire en wolof sans avoir l'audio correspondant.

Une réponse dit des noms de ligne (« bus bu Tata, numero … ») et, pour un trajet
avec changement, des noms d'arrêt (« nga wàcc X », « moo lay yóbbu ba Y »).  Tout
arrêt du réseau peut être un arrêt de descente ou de changement, dans un sens ou
dans l'autre.  Le script ne génère aucun audio : il liste seulement les fichiers
absents de ``data/tts_cache/`` et écrit ``data/audit/voix_manquantes.csv``.

    .\.venv\Scripts\python.exe scripts\couverture_voix.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from matching.lieux import joli
from routing.adapter import _NETWORK
from tts.speak import CACHE_DIR, nom_cache_match, nom_fichier_lieu, nom_lieu_parle

SORTIE = RACINE / "data" / "audit" / "voix_manquantes.csv"


def main() -> int:
    rangees: list[dict[str, str]] = []
    vus: set[str] = set()

    lignes = sorted(_NETWORK.lines.values(), key=lambda l: (l.company, l.name))
    for ligne in lignes:
        fichier = nom_cache_match({"compagnie": ligne.company, "ligne": ligne.name})
        if fichier in vus:
            continue
        vus.add(fichier)
        if not (CACHE_DIR / fichier).is_file():
            rangees.append(
                {
                    "type": "ligne",
                    "nom": f"{ligne.company} {ligne.name}",
                    "dit": "",
                    "fichier": fichier,
                }
            )

    arrets_manquants = 0
    for arret in sorted(_NETWORK.stop_names):
        # La voix dit le nom affiché (joli), comme les cartes.
        affiche = joli(arret)
        fichier = nom_fichier_lieu(affiche)
        if fichier in vus:
            continue
        vus.add(fichier)
        if not (CACHE_DIR / fichier).is_file():
            arrets_manquants += 1
            rangees.append(
                {
                    "type": "arret",
                    "nom": affiche,
                    "dit": nom_lieu_parle(affiche),
                    "fichier": fichier,
                }
            )

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    with SORTIE.open("w", encoding="utf-8", newline="") as sortie:
        ecrivain = csv.DictWriter(sortie, fieldnames=("type", "nom", "dit", "fichier"))
        ecrivain.writeheader()
        ecrivain.writerows(rangees)

    lignes_manquantes = len(rangees) - arrets_manquants
    noms_lieux = sum(1 for nom in vus if nom.startswith("lieu_"))
    print(
        f"Lignes : {len(lignes)} au réseau, {lignes_manquantes} sans audio\n"
        f"Arrêts : {noms_lieux} noms prononçables, {arrets_manquants} sans audio\n"
        f"Liste : {SORTIE}"
    )
    for rangee in rangees:
        if rangee["type"] == "ligne":
            print(f"  ligne sans audio : {rangee['nom']} ({rangee['fichier']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
