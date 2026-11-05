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
# Deux arrêts consécutifs retenus doivent avancer d'au moins cela sur la trace : des
# arrêts empilés au même point ne prouvent pas qu'on suit le bon sens.
PAS_MIN_M = 50.0
# Il faut au moins 3 arrêts cohérents, couvrant cette part de la trace.
MIN_ARRETS_COHERENTS = 3
PART_MIN_TRACE_COUVERTE = 0.5


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
) -> tuple[list[float | None], float]:
    """L'abscisse de chaque arrêt le plus proche de la trace, et la longueur de la trace."""

    longueurs = [0.0]
    for a, b in zip(trace, trace[1:]):
        longueurs.append(longueurs[-1] + distance_m(a, b))

    sortie: list[float | None] = []
    for position in positions:
        if position is None:
            sortie.append(None)
            continue
        ecart, t, i = min(
            (*_projeter(position, trace[i], trace[i + 1]), i)
            for i in range(len(trace) - 1)
        )
        sortie.append(
            None
            if ecart > MAX_ECART_TRACE_M
            else longueurs[i] + t * (longueurs[i + 1] - longueurs[i])
        )
    return sortie, longueurs[-1]


def _suite_croissante(abscisses: Sequence[float | None]) -> list[int]:
    """Les arrêts qui se suivent dans l'ordre de la trace : la plus longue suite."""

    indices = [i for i, valeur in enumerate(abscisses) if valeur is not None]
    meilleure: dict[int, list[int]] = {}
    for i in indices:
        precedentes = [
            meilleure[j]
            for j in indices
            if j < i and abscisses[j] + PAS_MIN_M <= abscisses[i]
        ]
        meilleure[i] = max(precedentes, key=len, default=[]) + [i]
    return max(meilleure.values(), key=len, default=[])


def distances_sur_trace(
    trace: Sequence[Point],
    positions: Sequence[Point | None],
) -> tuple[float | None, ...] | None:
    """Longueur de route de chaque segment de la ligne, ou None si la trace ne convient pas.

    Le sens de la trace n'est pas forcément celui de nos arrêts : on garde celui qui
    place le plus d'arrêts dans l'ordre.  Un arrêt incohérent est ignoré : Tata 35
    a plusieurs arrêts proposés au même point, près de Ngor.  La longueur entre ses
    deux voisins est alors partagée à parts égales.
    """

    if len(trace) < 2:
        return None

    meilleur: tuple[list[int], list[float | None], float] | None = None
    for sens in (trace, trace[::-1]):
        abscisses, longueur = _abscisses(sens, positions)
        retenus = _suite_croissante(abscisses)
        if meilleur is None or len(retenus) > len(meilleur[0]):
            meilleur = (retenus, abscisses, longueur)
    retenus, abscisses, longueur = meilleur
    if len(retenus) < MIN_ARRETS_COHERENTS:
        return None
    couvert = abscisses[retenus[-1]] - abscisses[retenus[0]]
    if couvert < PART_MIN_TRACE_COUVERTE * longueur:
        return None

    segments: list[float | None] = [None] * (len(positions) - 1)
    for gauche, droite in zip(retenus, retenus[1:]):
        part = (abscisses[droite] - abscisses[gauche]) / (droite - gauche)
        for i in range(gauche, droite):
            segments[i] = part
    return tuple(segments)
