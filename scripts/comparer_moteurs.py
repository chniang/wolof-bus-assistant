r"""Compare les réponses des moteurs v1 et v2 sur les trajets de référence.

Reprend les paires déjà présentes dans ``data/audit/comparaison_v1_v2.csv`` :
d'une version à l'autre, on compare ainsi toujours les mêmes trajets.

    .\.venv\Scripts\python.exe scripts\comparer_moteurs.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from matching.stops_matcher import StopsMatcher
from routing.adapter import MoteurV2, chercher_v2

SORTIE = RACINE / "data" / "audit" / "comparaison_v1_v2.csv"
COLONNES = ("depart", "arrivee", "lignes_v1", "lignes_v2", "minutes_v2")


def _bus(troncon: dict) -> str:
    return (
        f"{troncon['ligne']} ({troncon['compagnie']}) "
        f"[{troncon['monte_a']}>{troncon['descend_a']}]"
    )


def _trajets(resultat: dict) -> list[tuple[str, str, int | None]]:
    """Chaque possibilité : son texte, son nom court et sa durée (absente chez v1)."""

    trajets = [
        (_bus(ligne), ligne["ligne"], ligne.get("minutes"))
        for ligne in resultat["lignes"]
    ]
    for prefixe, etapes_et_minutes in (
        (
            "corr",
            [
                ((c["etape_1"], c["etape_2"]), c.get("minutes"))
                for c in resultat["correspondances"]
            ],
        ),
        (
            "2c",
            [
                (tuple(t["etapes"]), t.get("minutes"))
                for t in resultat.get("trajets_2") or []
            ],
        ),
    ):
        for etapes, minutes in etapes_et_minutes:
            trajets.append(
                (
                    f"{prefixe}:" + " > ".join(_bus(etape) for etape in etapes),
                    f"{prefixe}:" + ">".join(etape["ligne"] for etape in etapes),
                    minutes,
                )
            )
    a_pied = resultat.get("a_pied")
    if a_pied:
        trajets.insert(0, ("à pied", "à pied", a_pied.get("minutes")))
    return trajets


def main() -> int:
    with open(SORTIE, newline="", encoding="utf-8") as fichier:
        paires = [(r["depart"], r["arrivee"]) for r in csv.DictReader(fichier)]

    v1 = StopsMatcher()
    # Pas d'appel réseau : seuls les points déjà présents dans les CSV comptent.
    v1.geo.point = v1.geo.point_connu
    v2 = MoteurV2(v1)

    rangees = []
    replis = 0
    for depart, arrivee in paires:
        reponse_v1 = _trajets(v1.find_line(depart, arrivee))
        # Le moteur seul, sans repli : un v1 déguisé en v2 fausserait la comparaison.
        reponse_v2 = _trajets(chercher_v2(v1, depart, arrivee))
        if not reponse_v2:
            replis += 1
        rangees.append(
            {
                "depart": depart,
                "arrivee": arrivee,
                "lignes_v1": " | ".join(texte for texte, _, _ in reponse_v1),
                "lignes_v2": " | ".join(texte for texte, _, _ in reponse_v2),
                "minutes_v2": " ; ".join(
                    f"{nom}={minutes}" for _, nom, minutes in reponse_v2
                ),
            }
        )

    with open(SORTIE, "w", newline="", encoding="utf-8") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=COLONNES)
        ecrivain.writeheader()
        ecrivain.writerows(rangees)

    identiques = sum(r["lignes_v1"] == r["lignes_v2"] for r in rangees)
    print(
        f"{len(rangees)} paires | réponses identiques : {identiques} | "
        f"sans réponse v2 (repli v1 dans l'app) : {replis}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
