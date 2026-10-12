"""Précalcule data/lieux_geo.csv : la position de chaque lieu connu de l'extraction.

Pour que l'appli en ligne géocode vite un lieu dit, on précalcule sa position au
lieu d'appeler Nominatim au moment de la question. On réutilise d'abord ce qu'on
sait déjà (la position d'un arrêt, ou le centre d'un grand quartier), et on
n'appelle Nominatim que pour les lieux restants (cache, 1 requête/s, User-Agent
partagé avec data/sources/geolocaliser_arrets.py).

Usage : python data/sources/geolocaliser_lieux.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
sys.path.insert(0, str(DATA.parent / "src"))

from intent.extract_intent import LIEUX, LIEUX_SUPPLEMENTAIRES  # noqa: E402
from matching.geo import _Nominatim, normaliser  # noqa: E402
from matching.lieux import QUARTIERS, score  # noqa: E402

ARRETS_GEO = DATA / "arrets_geo.csv"
SORTIE = DATA / "lieux_geo.csv"


def positions_connues() -> dict[str, tuple[float, float]]:
    """Position des arrêts déjà localisés (hors douteux)."""
    positions: dict[str, tuple[float, float]] = {}
    with open(ARRETS_GEO, newline="", encoding="utf-8") as f:
        for rangee in csv.DictReader(f):
            if rangee.get("confiance") == "douteuse" or not rangee.get("lat"):
                continue
            try:
                positions[rangee["arret"]] = (float(rangee["lat"]), float(rangee["lon"]))
            except ValueError:
                continue
    return positions


def centre(points: list[tuple[float, float] | None]) -> tuple[float, float] | None:
    points = [p for p in points if p]
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def resoudre(lieu: str, positions: dict, client) -> tuple[tuple[float, float] | None, str]:
    """Position d'un lieu : quartier connu, puis nom d'arrêt, puis Nominatim."""
    # 1) Grand quartier (Plateau, Dakar Plateau) : centre de ses arrêts.
    for mot in normaliser(lieu).split():
        if mot in QUARTIERS:
            centre_quartier = centre([positions.get(arret) for arret in QUARTIERS[mot]])
            if centre_quartier:
                return centre_quartier, "quartier"

    # 2) Arrêt connu dont le nom correspond.
    meilleur, meilleur_score = None, 0.0
    for arret, point in positions.items():
        valeur = score(lieu, arret)
        if valeur > meilleur_score:
            meilleur, meilleur_score = point, valeur
    if meilleur is not None and meilleur_score >= 0.75:
        return meilleur, "arret"

    # 3) Nominatim, une seule fois.
    point = client.geocode(f"{lieu}, Dakar, Sénégal")
    if point:
        return point, "nominatim"
    return None, ""


def main() -> None:
    positions = positions_connues()
    client = _Nominatim()
    lieux = list(dict.fromkeys(list(LIEUX) + list(LIEUX_SUPPLEMENTAIRES)))

    lignes = []
    stats = {"quartier": 0, "arret": 0, "nominatim": 0, "echec": 0}
    for lieu in lieux:
        point, source = resoudre(lieu, positions, client)
        if point is None:
            stats["echec"] += 1
            continue
        stats[source] += 1
        lignes.append({"lieu": lieu, "lat": f"{point[0]:.6f}", "lon": f"{point[1]:.6f}"})

    with open(SORTIE, "w", newline="", encoding="utf-8") as f:
        ecrivain = csv.DictWriter(f, fieldnames=["lieu", "lat", "lon"])
        ecrivain.writeheader()
        ecrivain.writerows(lignes)

    print(f"{len(lignes)} lieux -> {SORTIE.relative_to(DATA.parent)}")
    print(f"  via quartier/commune : {stats['quartier']}")
    print(f"  via nom d'arrêt      : {stats['arret']}")
    print(f"  via Nominatim        : {stats['nominatim']}")
    print(f"  non localisés        : {stats['echec']}")
    print(f"{len(client.cache)} entrées en cache ({client.cache_path.name})")


if __name__ == "__main__":
    main()
