"""The Dakar bus graph.

A node is a stop **as seen by one line in one direction**.  Keeping the
direction in the node is what lets the router produce a proper leg with a
terminus ("towards Palais 2") instead of just a pair of stop names.

Each line is usable in both directions.  Ride edges follow the ordered
itinerary; transfer edges connect different lines at the same normalized
stop name, or at two stops within 500 m.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, NamedTuple

from .places import normalize_name

# Modeling constants.  They are deliberately simple and easy to tune.
BUS_SPEED_M_PER_MIN = 250.0       # about 15 km/h in Dakar traffic
FIXED_MINUTES_PER_SEGMENT = 3.0    # fallback when a stop has no coordinates
TRANSFER_PENALTY_MIN = 6.0        # waiting / walking to the next line
WALK_SPEED_M_PER_MIN = 80.0
MAX_TRANSFER_WALK_M = 500.0

LineKey = tuple[str, str]          # (operator, line name)


class Node(NamedTuple):
    line: LineKey
    direction: int                 # 0 = itinerary order, 1 = reversed
    index: int


@dataclass(frozen=True)
class Line:
    company: str
    name: str
    stops: tuple[str, ...]
    terminus_a: str | None = None
    terminus_b: str | None = None

    @property
    def key(self) -> LineKey:
        return (self.company, self.name)

    def stops_for(self, direction: int) -> tuple[str, ...]:
        return self.stops if direction == 0 else tuple(reversed(self.stops))

    def terminus_for(self, direction: int) -> str:
        return self.stops_for(direction)[-1]


@dataclass(frozen=True)
class Edge:
    target: Node
    kind: str                      # "ride" or "transfer"
    minutes: float
    distance_m: float | None = None
    walk_minutes: float = 0.0
    walk_distance_m: float | None = None
    transfer_penalty: float = 0.0


def _number(value: object) -> float | None:
    """Convert a CSV value to a coordinate, or None when it is missing."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def haversine_m(
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Great-circle distance in metres."""

    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def interpolate_missing_coordinates(
    lines: Iterable[Line],
    stop_coords: dict[str, tuple[float, float]],
    stop_confidence: dict[str, str] | None = None,
    passes: int = 3,
) -> tuple[dict[str, tuple[float, float]], dict[str, str]]:
    """Place unlocated stops between the located stops around them.

    L'arrêt prend la position linéaire entre l'arrêt géolocalisé qui le
    précède et celui qui le suit sur la ligne.  Si plusieurs lignes le
    desservent, on moyenne leurs propositions.  Les trois passes permettent
    à un arrêt interpolé sur une ligne de servir d'ancre sur une autre.
    """

    coords = dict(stop_coords)
    confidence = dict(stop_confidence or {})

    for _ in range(max(1, passes)):
        proposals: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for line in lines:
            stops = line.stops
            for index, stop in enumerate(stops):
                if stop in coords:
                    continue

                previous = None
                for before in range(index - 1, -1, -1):
                    if stops[before] in coords:
                        previous = before
                        break
                following = None
                for after in range(index + 1, len(stops)):
                    if stops[after] in coords:
                        following = after
                        break
                if previous is None or following is None:
                    continue

                ratio = (index - previous) / (following - previous)
                start = coords[stops[previous]]
                end = coords[stops[following]]
                proposals[stop].append(
                    (
                        start[0] + (end[0] - start[0]) * ratio,
                        start[1] + (end[1] - start[1]) * ratio,
                    )
                )

        if not proposals:
            break
        for stop, points in proposals.items():
            if stop in coords:
                continue
            coords[stop] = (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
            )
            confidence[stop] = "interpolee"

    return coords, confidence


class Network:
    def __init__(
        self,
        lines: Iterable[Line],
        stop_coords: dict[str, tuple[float, float]],
        stop_confidence: dict[str, str] | None = None,
    ) -> None:
        self.lines = {line.key: line for line in lines}
        self.stop_coords = dict(stop_coords)
        self.stop_confidence = dict(stop_confidence or {})
        self.stop_names = sorted(
            {stop for line in self.lines.values() for stop in line.stops}
        )

        self._nodes_at_stop: dict[str, list[Node]] = defaultdict(list)
        self._nodes_at_norm: dict[str, list[Node]] = defaultdict(list)
        self._stops_by_norm: dict[str, list[str]] = defaultdict(list)
        self._all_nodes: list[Node] = []

        for line in self.lines.values():
            for direction in (0, 1):
                sequence = line.stops_for(direction)
                for index, stop in enumerate(sequence):
                    node = Node(line.key, direction, index)
                    self._all_nodes.append(node)
                    self._nodes_at_stop[stop].append(node)
                    self._nodes_at_norm[normalize_name(stop)].append(node)

        for stop in self.stop_names:
            self._stops_by_norm[normalize_name(stop)].append(stop)

        self._adjacency: dict[Node, list[Edge]] | None = None

    # ------------------------------------------------------------------
    # Small accessors used by the router and the CLI.
    # ------------------------------------------------------------------
    @property
    def all_nodes(self) -> list[Node]:
        return self._all_nodes

    def line_for(self, node: Node) -> Line:
        return self.lines[node.line]

    def stop_for(self, node: Node) -> str:
        return self.line_for(node).stops_for(node.direction)[node.index]

    def terminus_for(self, node: Node) -> str:
        return self.line_for(node).terminus_for(node.direction)

    def nodes_at_stop(self, stop: str) -> list[Node]:
        return self._nodes_at_stop.get(stop, [])

    def nodes_at_normalized(self, normalized: str) -> list[Node]:
        return self._nodes_at_norm.get(normalized, [])

    def stops_for_normalized(self, normalized: str) -> list[str]:
        return self._stops_by_norm.get(normalized, [])

    def coords(self, stop: str) -> tuple[float, float] | None:
        return self.stop_coords.get(stop)

    @property
    def downtown_centre(self) -> tuple[float, float] | None:
        """Approximate the city centre with the Palais stops."""

        points = [
            self.stop_coords[name]
            for name in ("Palais 1", "Palais 2", "Palais")
            if name in self.stop_coords
        ]
        if not points:
            return None
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    # ------------------------------------------------------------------
    # Graph construction.
    # ------------------------------------------------------------------
    @property
    def adjacency(self) -> dict[Node, list[Edge]]:
        if self._adjacency is None:
            self._adjacency = self._build_adjacency()
        return self._adjacency

    def _ride_estimate(
        self,
        from_stop: str,
        to_stop: str,
    ) -> tuple[float, float | None]:
        start = self.coords(from_stop)
        end = self.coords(to_stop)
        if start is None or end is None:
            return FIXED_MINUTES_PER_SEGMENT, None

        distance = haversine_m(start, end)
        minutes = max(0.5, distance / BUS_SPEED_M_PER_MIN)
        return minutes, distance

    def _build_adjacency(self) -> dict[Node, list[Edge]]:
        adjacency: dict[Node, list[Edge]] = {
            node: [] for node in self._all_nodes
        }

        # Ride along the ordered stops, in both directions.
        for line in self.lines.values():
            for direction in (0, 1):
                sequence = line.stops_for(direction)
                for index in range(len(sequence) - 1):
                    source = Node(line.key, direction, index)
                    target = Node(line.key, direction, index + 1)
                    minutes, distance = self._ride_estimate(
                        sequence[index], sequence[index + 1]
                    )
                    adjacency[source].append(
                        Edge(
                            target=target,
                            kind="ride",
                            minutes=minutes,
                            distance_m=distance,
                        )
                    )

        # Transfers at the same normalized stop name.  This also joins
        # spellings such as "Sahm" and "SAHM".
        for nodes in self._nodes_at_norm.values():
            for source in nodes:
                for target in nodes:
                    if source == target or source.line == target.line:
                        continue
                    adjacency[source].append(
                        Edge(
                            target=target,
                            kind="transfer",
                            minutes=TRANSFER_PENALTY_MIN,
                            walk_minutes=0.0,
                            walk_distance_m=0.0,
                            transfer_penalty=TRANSFER_PENALTY_MIN,
                        )
                    )

        # Short walking transfers between different stop names.
        stops_with_coords = [
            stop for stop in self.stop_names if stop in self.stop_coords
        ]
        for left_index, left_stop in enumerate(stops_with_coords):
            left_norm = normalize_name(left_stop)
            for right_stop in stops_with_coords[left_index + 1 :]:
                if normalize_name(right_stop) == left_norm:
                    continue
                distance = haversine_m(
                    self.stop_coords[left_stop], self.stop_coords[right_stop]
                )
                if distance > MAX_TRANSFER_WALK_M:
                    continue

                walk_minutes = distance / WALK_SPEED_M_PER_MIN
                cost = TRANSFER_PENALTY_MIN + walk_minutes
                for source in self._nodes_at_stop[left_stop]:
                    for target in self._nodes_at_stop[right_stop]:
                        if source.line == target.line:
                            continue
                        adjacency[source].append(
                            Edge(
                                target=target,
                                kind="transfer",
                                minutes=cost,
                                walk_minutes=walk_minutes,
                                walk_distance_m=distance,
                                transfer_penalty=TRANSFER_PENALTY_MIN,
                            )
                        )
                        adjacency[target].append(
                            Edge(
                                target=source,
                                kind="transfer",
                                minutes=cost,
                                walk_minutes=walk_minutes,
                                walk_distance_m=distance,
                                transfer_penalty=TRANSFER_PENALTY_MIN,
                            )
                        )

        # If the same (source, target) node pair was reached twice, keep
        # the cheapest way to make that change.
        for source, edges in adjacency.items():
            cheapest: dict[Node, Edge] = {}
            for edge in edges:
                current = cheapest.get(edge.target)
                if current is None or (edge.minutes, edge.walk_minutes) < (
                    current.minutes,
                    current.walk_minutes,
                ):
                    cheapest[edge.target] = edge
            adjacency[source] = list(cheapest.values())

        return adjacency

    # ------------------------------------------------------------------
    # Loading the real data.
    # ------------------------------------------------------------------
    @classmethod
    def from_data(cls, data, corrections_path=None) -> "Network":
        termini: dict[LineKey, tuple[str | None, str | None]] = {}
        for row in data.lignes.itertuples(index=False):
            key = (str(row.compagnie), str(row.ligne))
            if key not in termini:
                termini[key] = (str(row.terminus_a), str(row.terminus_b))

        lines: list[Line] = []
        grouped = data.itineraires.groupby(["compagnie", "ligne"], sort=False)
        for (company, name), group in grouped:
            ordered = group.sort_values("ordre")
            stops = tuple(str(stop) for stop in ordered["arret"])
            if len(stops) < 2:
                continue
            terminus_a, terminus_b = termini.get(
                (str(company), str(name)), (None, None)
            )
            lines.append(
                Line(
                    company=str(company),
                    name=str(name),
                    stops=stops,
                    terminus_a=terminus_a,
                    terminus_b=terminus_b,
                )
            )

        # Field corrections are layered on top of the downloaded itinerary
        # before coordinates and graph nodes are built.
        from .corrections import apply_corrections, load_corrections

        known_stops = {
            str(row.arret) for row in data.arrets.itertuples(index=False)
        }
        known_stops.update(
            stop for line in lines for stop in line.stops
        )
        corrected = apply_corrections(
            lines,
            load_corrections(corrections_path),
            known_stops,
        )
        lines = corrected.lines

        stop_coords: dict[str, tuple[float, float]] = {}
        stop_confidence: dict[str, str] = {}
        for row in data.arrets.itertuples(index=False):
            stop = str(row.arret)
            if stop not in stop_coords:
                lat = _number(row.lat)
                lon = _number(row.lon)
                if lat is not None and lon is not None:
                    stop_coords[stop] = (lat, lon)
            confidence = getattr(row, "confiance", None)
            if isinstance(confidence, str) and stop not in stop_confidence:
                stop_confidence[stop] = confidence

        # Some stops in itineraires have no coordinate row of their own.
        # If a place with the same normalized name exists in lieux_geo,
        # borrow its position.  This is still only a best effort.
        place_coords: dict[str, tuple[float, float]] = {}
        for row in data.lieux.itertuples(index=False):
            lat = _number(row.lat)
            lon = _number(row.lon)
            if lat is None or lon is None:
                continue
            normalized = normalize_name(row.lieu)
            place_coords.setdefault(normalized, (lat, lon))

        for stop in {stop for line in lines for stop in line.stops}:
            if stop in stop_coords:
                continue
            borrowed = place_coords.get(normalize_name(stop))
            if borrowed is not None:
                stop_coords[stop] = borrowed
                stop_confidence.setdefault(stop, "estimee")

        # Les arrêts restants sont placés à vol d'oiseau le long de leur
        # ligne, uniquement en mémoire : les CSV ne sont jamais modifiés.
        stop_coords, stop_confidence = interpolate_missing_coordinates(
            lines, stop_coords, stop_confidence
        )

        return cls(lines, stop_coords, stop_confidence)
