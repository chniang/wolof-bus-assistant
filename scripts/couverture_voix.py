r"""Ce que le moteur v2 peut dire en wolof sans avoir l'audio correspondant.

Une réponse dit des noms de ligne (« bus bu Tata, numero … ») et, pour un trajet
avec changement, des noms d'arrêt (« nga wàcc X », « moo lay yóbbu ba Y »).  Tout
arrêt du réseau peut être un arrêt de descente ou de changement, dans un sens ou
dans l'autre.  Le script ne génère aucun audio.  Il écrit :

- ``data/audit/voix_manquantes.csv`` : chaque nom affiché sans audio ;
- ``data/audit/voix_a_generer.csv`` : un audio par prononciation, avec tous les
  noms affichés qui s'en servent (les variantes d'orthographe sont regroupées
  par les alias de ``tts.speak``).

Un audio compte comme présent dans ``data/tts_cache/`` ou ``data/tts_cache_ajouts/``.

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
from tts.speak import (
    CACHE_DIR,
    chemin_audio,
    nom_cache_match,
    nom_fichier_lieu,
    nom_lieu_parle,
    phrase_reponse,
)

MANQUANTES = RACINE / "data" / "audit" / "voix_manquantes.csv"
A_GENERER = RACINE / "data" / "audit" / "voix_a_generer.csv"


def _present(fichier: str) -> bool:
    return chemin_audio(CACHE_DIR, fichier).is_file()


def main() -> int:
    manquantes: list[dict[str, str]] = []
    # fichier -> (type, texte à prononcer, noms affichés)
    a_generer: dict[str, tuple[str, str, list[str]]] = {}

    lignes = sorted(_NETWORK.lines.values(), key=lambda l: (l.company, l.name))
    for ligne in lignes:
        match = {"compagnie": ligne.company, "ligne": ligne.name}
        fichier = nom_cache_match(match)
        if _present(fichier):
            continue
        nom = f"{ligne.company} {ligne.name}"
        texte = phrase_reponse([match])
        manquantes.append({"type": "ligne", "nom": nom, "dit": texte, "fichier": fichier})
        a_generer.setdefault(fichier, ("ligne", texte, []))[2].append(nom)

    for arret in sorted(_NETWORK.stop_names):
        # La voix dit le nom affiché (joli), comme les cartes.
        affiche = joli(arret)
        dit = nom_lieu_parle(affiche)
        if not dit:
            # « (SCOA) » : rien à dire, la voix saute déjà ce lieu.
            continue
        fichier = nom_fichier_lieu(affiche)
        if _present(fichier):
            continue
        manquantes.append({"type": "arret", "nom": affiche, "dit": dit, "fichier": fichier})
        noms = a_generer.setdefault(fichier, ("arret", dit, []))[2]
        if affiche not in noms:
            noms.append(affiche)

    MANQUANTES.parent.mkdir(parents=True, exist_ok=True)
    with MANQUANTES.open("w", encoding="utf-8", newline="") as sortie:
        ecrivain = csv.DictWriter(sortie, fieldnames=("type", "nom", "dit", "fichier"))
        ecrivain.writeheader()
        ecrivain.writerows(manquantes)

    with A_GENERER.open("w", encoding="utf-8", newline="") as sortie:
        ecrivain = csv.DictWriter(
            sortie,
            fieldnames=("type", "texte_a_prononcer", "fichier_wav", "utilise_par"),
        )
        ecrivain.writeheader()
        for fichier, (genre, texte, noms) in sorted(
            a_generer.items(), key=lambda item: (item[1][0] != "ligne", item[1][1])
        ):
            ecrivain.writerow(
                {
                    "type": genre,
                    "texte_a_prononcer": texte,
                    "fichier_wav": fichier,
                    "utilise_par": " | ".join(noms),
                }
            )

    nb_lignes = sum(1 for genre, _, _ in a_generer.values() if genre == "ligne")
    print(
        f"Noms affichés sans audio : {len(manquantes)}\n"
        f"Audios à générer : {len(a_generer)} ({nb_lignes} lignes, "
        f"{len(a_generer) - nb_lignes} arrêts)\n"
        f"Listes : {MANQUANTES} ; {A_GENERER}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
