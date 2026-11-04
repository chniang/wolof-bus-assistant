"""Distances réelles le long des traces officielles AFTU.

Additionner les arrêts à vol d'oiseau sous-estime une route qui tourne, et une
seule position fausse suffit à la gonfler : Tata 54 affichait 157 min pour 18 km.
Les traces (``data/sources/aftu_traces/``) donnent le vrai parcours du bus : on
projette chaque arrêt dessus, et la distance d'un segment est la longueur de
route entre ses deux arrêts.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Sequence

Point = tuple[float, float]

# Un arrêt plus loin de la trace n'est pas sur ce parcours : il n'y compte pas.
MAX_ECART_TRACE_M = 1_000.0
# Une trace peut repasser au même endroit (aller-retour, boucle) : parmi les passages
# presque aussi proches, on garde le premier, pour ne pas sauter un tronçon.
MARGE_PASSAGE_M = 100.0
# Sous cette part d'arrêts bien placés, la trace et la ligne ne correspondent pas.
PART_MIN_ARRETS_SUR_TRACE = 0.5


def distance_m(a: Point, b: Point) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def charger_traces(dossier: str | Path) -> dict[str, list[Point]]:
    """« Ligne N » -> points (lat, lon) de la trace.  Dossier absent : aucune trace."""

    traces: dict[str, list[Point]] = {}
    chemin = Path(dossier)
    if not chemin.is_dir():
        return traces
    for fichier in sorted(chemin.glob("*.geojson")):
        trouve = re.search(r"ligne-(\d+)$", fichier.stem)
        if not trouve:
            continue
        contenu = json.loads(fichier.read_text(encoding="utf-8"))
        for element in contenu.get("features", []):
            geometrie = element.get("geometry") or {}
            if geometrie.get("type") == "LineString":
                # Le GeoJSON écrit (lon, lat).
                traces[f"Ligne {trouve.group(1)}"] = [
                    (float(lat), float(lon))
                    for lon, lat, *_ in geometrie["coordinates"]
                ]
                break
    return traces


def _projeter(point: Point, a: Point, b: Point) -> tuple[float, float]:
    """(écart en mètres, fraction du segment ab) du point projeté sur ab."""

    echelle_lon = math.cos(math.radians(point[0]))
    ax, ay = (a[1] - point[1]) * echelle_lon, a[0] - point[0]
    bx, by = (b[1] - point[1]) * echelle_lon, b[0] - point[0]
    dx, dy = bx - ax, by - ay
    longueur2 = dx * dx + dy * dy
    t = 0.0 if longueur2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / longueur2))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(px, py) * 111_320.0, t


def _abscisses(
    trace: Sequence[Point],
    positions: Sequence[Point | None],
) -> list[float | None]:
    """Abscisse de chaque arrêt sur la trace, toujours croissante le long de la ligne."""

    longueurs = [0.0]
    for a, b in zip(trace, trace[1:]):
        longueurs.append(longueurs[-1] + distance_m(a, b))

    sortie: list[float | None] = []
    debut = 0
    for position in positions:
        if position is None:
            sortie.append(None)
            continue
        candidats = [
            (*_projeter(position, trace[i], trace[i + 1]), i)
            for i in range(debut, len(trace) - 1)
        ]
        if not candidats:
            sortie.append(None)
            continue
        meilleur = min(ecart for ecart, _, _ in candidats)
        if meilleur > MAX_ECART_TRACE_M:
            sortie.append(None)
            continue
        ecart, t, i = next(
            c for c in candidats if c[0] <= meilleur + MARGE_PASSAGE_M
        )
        sortie.append(longueurs[i] + t * (longueurs[i + 1] - longueurs[i]))
        debut = i
    return sortie


def distances_sur_trace(
    trace: Sequence[Point],
    positions: Sequence[Point | None],
) -> tuple[float | None, ...] | None:
    """Longueur de route de chaque segment de la ligne, ou None si la trace ne convient pas.

    Le sens de la trace n'est pas forcément celui de nos arrêts : on essaie les deux
    et on garde celui qui place le plus d'arrêts.  Un arrêt hors trace ne compte
    pas : la longueur entre ses deux voisins est partagée à parts égales.
    """

    connus = sum(position is not None for position in positions)
    if len(trace) < 2 or connus < 2:
        return None

    abscisses = max(
        (_abscisses(trace, positions), _abscisses(trace[::-1], positions)),
        key=lambda valeurs: sum(valeur is not None for valeur in valeurs),
    )
    places = [i for i, valeur in enumerate(abscisses) if valeur is not None]
    if len(places) < 2 or len(places) < PART_MIN_ARRETS_SUR_TRACE * connus:
        return None

    segments: list[float | None] = [None] * (len(positions) - 1)
    for gauche, droite in zip(places, places[1:]):
        longueur = (abscisses[droite] - abscisses[gauche]) / (droite - gauche)
        for i in range(gauche, droite):
            segments[i] = longueur
    return tuple(segments)
