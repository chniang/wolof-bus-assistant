"""The Dakar bus graph.

A node is a stop **as seen by one line in one direction**.  Keeping the
direction in the node is what lets the router produce a proper leg with a
terminus ("towards Palais 2") instead of just a pair of stop names.

Each line is usable in both directions.  Ride edges follow the ordered
itinerary; transfer edges connect different lines at the same normalized
stop name, or at two stops within 500 m.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, NamedTuple

from .places import _GENERIC_TOKENS, normalize_name, terminus_forms
from .traces import distances_sur_trace

# Modeling constants.  They are deliberately simple and easy to tune.
BUS_SPEED_M_PER_MIN = 333.0       # 20 km/h, sur de vraies longueurs de route
FIXED_MINUTES_PER_SEGMENT = 3.0    # fallback when a stop has no coordinates
# Une ligne réduite à ses deux terminus, dont l'un sans position, n'a aucun
# arrêt pour borner la distance : Dem Dikk 11 (Keur Massar -> Lat Dior) coûtait
# 3 min et devenait une téléportation à travers toute la ville.
UNKNOWN_TWO_STOP_RIDE_MINUTES = 35.0
TRANSFER_PENALTY_MIN = 6.0        # waiting / walking to the next line
WALK_SPEED_M_PER_MIN = 80.0
MAX_TRANSFER_WALK_M = 500.0
# Correspondances à pied gardées pour deux lignes données : les plus courtes.  Toutes
# les garder faisait 126 000 arêtes et jusqu'à 44 s par requête, sans bus direct.
MAX_WALK_TRANSFERS_PER_LINE_PAIR = 2
# Un ancien nom absent des listes officielles (« Cambérène 2 ») vaut l'arrêt officiel
# le plus proche : portant le même nom de quartier, ou tout près s'il n'y en a pas.
LEGACY_SAME_NAME_RADIUS_M = 2_000.0
LEGACY_ANY_NAME_RADIUS_M = 500.0
POSITION_AGREEMENT_M = 500.0
SAME_NAME_MAX_APART_M = 1_000.0

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
    estimated: bool = False        # durée forfaitaire, pas de distance connue


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


def _name_tokens(name: str) -> set[str]:
    return {
        token
        for token in normalize_name(name).split()
        if token not in _GENERIC_TOKENS and not token.isdigit()
    }


def _legacy_stops(
    data,
    lines: list[Line],
    stop_coords: dict[str, tuple[float, float]],
    stop_confidence: dict[str, str],
) -> dict[str, str]:
    """Ancien nom bien situé -> arrêt officiel le plus proche de la même zone.

    Une position interpolée ne désigne jamais de zone, ni un ancien nom douteux :
    mieux vaut ne pas répondre que répondre à côté.
    """

    current = {stop for line in lines for stop in line.stops}
    norms = {normalize_name(stop) for stop in current}
    located = [
        (stop, stop_coords[stop], _name_tokens(stop))
        for stop in current
        if stop in stop_coords and stop_confidence.get(stop) in {"bonne", "estimee"}
    ]

    legacy: dict[str, str] = {}
    for row in data.arrets.itertuples(index=False):
        name = str(row.arret)
        if (
            normalize_name(name) in norms
            or getattr(row, "confiance", None) != "bonne"
        ):
            continue
        lat, lon = _number(row.lat), _number(row.lon)
        if lat is None or lon is None:
            continue
        tokens = _name_tokens(name)
        best: tuple[bool, float, str] | None = None
        for stop, coords, stop_tokens in located:
            distance = haversine_m((lat, lon), coords)
            same_area = bool(tokens & stop_tokens)
            limit = (
                LEGACY_SAME_NAME_RADIUS_M if same_area else LEGACY_ANY_NAME_RADIUS_M
            )
            if distance > limit:
                continue
            candidate = (not same_area, distance, stop)
            if best is None or candidate < best:
                best = candidate
        if best is not None:
            legacy[name] = best[2]
    return legacy


class Network:
    def __init__(
        self,
        lines: Iterable[Line],
        stop_coords: dict[str, tuple[float, float]],
        stop_confidence: dict[str, str] | None = None,
        line_positions: dict[LineKey, tuple] | None = None,
        line_distances: dict[LineKey, tuple] | None = None,
        legacy_stops: dict[str, str] | None = None,
    ) -> None:
        self.lines = {line.key: line for line in lines}
        self.stop_coords = dict(stop_coords)
        self.stop_confidence = dict(stop_confidence or {})
        # Position de chaque arrêt sur sa ligne, et longueur mesurée sur la trace.
        self.line_positions = dict(line_positions or {})
        self.line_distances = dict(line_distances or {})
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

        # « Dieuppeul » et « Liberté 5 » mènent aussi à « Terminus liberté 5
        # (Dieuppeul) », sans en faire le même arrêt pour les correspondances.
        for stop in self.stop_names:
            for form in terminus_forms(stop):
                names = self._stops_by_norm[normalize_name(form)]
                if stop not in names:
                    names.append(stop)
        for old_name, stop in (legacy_stops or {}).items():
            normalized = normalize_name(old_name)
            if not self._stops_by_norm.get(normalized):
                self._stops_by_norm[normalized] = [stop]

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
        return list(self._stops_by_norm.get(normalized, ()))

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

    def position_on_line(self, line: Line, index: int) -> tuple[float, float] | None:
        """La position de cet arrêt sur cette ligne (sa position générale par défaut)."""

        positions = self.line_positions.get(line.key)
        if positions is not None:
            return positions[index]
        return self.coords(line.stops[index])

    def _segment_distances(self, line: Line) -> tuple[float | None, ...]:
        """Longueur de chaque segment, dans l'ordre de la ligne.

        La trace d'abord, sinon les distances entre arrêts consécutifs.  Un arrêt
        sans position est sauté : la distance entre ses deux voisins est partagée.
        """

        mesurees = self.line_distances.get(line.key)
        if mesurees is not None:
            return mesurees

        positions = [
            self.position_on_line(line, index) for index in range(len(line.stops))
        ]
        connus = [i for i, position in enumerate(positions) if position is not None]
        segments: list[float | None] = [None] * (len(positions) - 1)
        for gauche, droite in zip(connus, connus[1:]):
            part = haversine_m(positions[gauche], positions[droite]) / (droite - gauche)
            for index in range(gauche, droite):
                segments[index] = part
        return tuple(segments)

    @staticmethod
    def _ride_estimate(
        distance: float | None,
        stops_on_line: int,
    ) -> float:
        if distance is None:
            if stops_on_line == 2:
                return UNKNOWN_TWO_STOP_RIDE_MINUTES
            return FIXED_MINUTES_PER_SEGMENT
        return max(0.5, distance / BUS_SPEED_M_PER_MIN)

    def _build_adjacency(self) -> dict[Node, list[Edge]]:
        adjacency: dict[Node, list[Edge]] = {
            node: [] for node in self._all_nodes
        }

        # Ride along the ordered stops, in both directions.
        for line in self.lines.values():
            forward = self._segment_distances(line)
            for direction in (0, 1):
                sequence = line.stops_for(direction)
                distances = forward if direction == 0 else forward[::-1]
                for index in range(len(sequence) - 1):
                    source = Node(line.key, direction, index)
                    target = Node(line.key, direction, index + 1)
                    distance = distances[index]
                    minutes = self._ride_estimate(distance, len(sequence))
                    adjacency[source].append(
                        Edge(
                            target=target,
                            kind="ride",
                            minutes=minutes,
                            distance_m=distance,
                            estimated=distance is None and len(sequence) == 2,
                        )
                    )

        # Transfers at the same normalized stop name.  This also joins
        # spellings such as "Sahm" and "SAHM".
        # Deux lignes peuvent donner le même nom à deux endroits éloignés : « VDN » est
        # une avenue de 15 km, et Tata 37 y passe loin de TAF TAF.  Sans ce contrôle,
        # on changeait de bus à « VDN » en se téléportant vers Malika.
        def node_position(node: Node) -> tuple[float, float] | None:
            line = self.lines[node.line]
            index = (
                node.index
                if node.direction == 0
                else len(line.stops) - 1 - node.index
            )
            return self.position_on_line(line, index)

        for nodes in self._nodes_at_norm.values():
            positions = {node: node_position(node) for node in nodes}
            for source in nodes:
                for target in nodes:
                    if source == target or source.line == target.line:
                        continue
                    here, there = positions[source], positions[target]
                    if (
                        here is not None
                        and there is not None
                        and haversine_m(here, there) > SAME_NAME_MAX_APART_M
                    ):
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

        # Short walking transfers between different stop names: only the closest
        # stop pairs of each pair of lines.
        lines_at_stop: dict[str, set[LineKey]] = defaultdict(set)
        nodes_on_line: dict[tuple[LineKey, str], list[Node]] = defaultdict(list)
        for stop, nodes in self._nodes_at_stop.items():
            for node in nodes:
                lines_at_stop[stop].add(node.line)
                nodes_on_line[(node.line, stop)].append(node)

        def position_for(line: LineKey, stop: str) -> tuple[float, float] | None:
            first = min(
                (node for node in nodes_on_line[(line, stop)] if node.direction == 0),
                key=lambda node: node.index,
            )
            return self.position_on_line(self.lines[line], first.index)

        by_line_pair: dict[
            tuple[LineKey, LineKey], list[tuple[float, str, str]]
        ] = defaultdict(list)
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
                for left_line in lines_at_stop[left_stop]:
                    for right_line in lines_at_stop[right_stop]:
                        # Là où chaque ligne passe vraiment : une position générale
                        # fausse mettait Pikine Texaco (Tata 80) à côté de Ngor.
                        left_here = position_for(left_line, left_stop)
                        right_here = position_for(right_line, right_stop)
                        if (
                            left_here is None
                            or right_here is None
                            or haversine_m(left_here, right_here) > MAX_TRANSFER_WALK_M
                        ):
                            continue
                        if left_line < right_line:
                            by_line_pair[(left_line, right_line)].append(
                                (distance, left_stop, right_stop)
                            )
                        elif right_line < left_line:
                            by_line_pair[(right_line, left_line)].append(
                                (distance, right_stop, left_stop)
                            )

        for (first_line, second_line), candidates in by_line_pair.items():
            closest = heapq.nsmallest(MAX_WALK_TRANSFERS_PER_LINE_PAIR, candidates)
            for distance, first_stop, second_stop in closest:
                walk_minutes = distance / WALK_SPEED_M_PER_MIN
                cost = TRANSFER_PENALTY_MIN + walk_minutes
                for source in nodes_on_line[(first_line, first_stop)]:
                    for target in nodes_on_line[(second_line, second_stop)]:
                        for start, end in ((source, target), (target, source)):
                            adjacency[start].append(
                                Edge(
                                    target=end,
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
        line_orders: dict[LineKey, list[int]] = {}
        grouped = data.itineraires.groupby(["compagnie", "ligne"], sort=False)
        for (company, name), group in grouped:
            ordered = group.sort_values("ordre")
            stops = tuple(str(stop) for stop in ordered["arret"])
            if len(stops) < 2:
                continue
            line_orders[(str(company), str(name))] = [
                int(ordre) for ordre in ordered["ordre"]
            ]
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

        # Une position fiable sur une ligne situe aussi un arrêt qui n'en avait pas
        # de bonne (« Sandaga », « Point E », nouveaux noms officiels de Dem Dikk).
        by_order = getattr(data, "positions_ligne", {})
        sure_by_order = getattr(data, "positions_sures", {})
        raw_positions: dict[LineKey, list] = {}
        proposals: dict[str, list[tuple[tuple[float, float], bool]]] = defaultdict(list)
        for line in lines:
            orders = line_orders.get(line.key)
            per_line = by_order.get(line.key)
            if not per_line or orders is None or len(orders) != len(line.stops):
                continue
            raw_positions[line.key] = [per_line.get(ordre, ...) for ordre in orders]
            for stop, ordre in zip(line.stops, orders):
                position = per_line.get(ordre)
                if position is not None:
                    proposals[stop].append(
                        (position, sure_by_order.get(line.key, {}).get(ordre, False))
                    )

        # Une ligne seule ne déplace pas un arrêt pour tout le réseau : sa position
        # peut être fausse (Tata 35 met Pikine Texaco près de Ngor, ce qui créait une
        # correspondance à pied entre les deux).  Il faut deux lignes d'accord, ou
        # que l'arrêt n'ait encore aucune position.  Si toutes les lignes qui le
        # desservent s'accordent, elles priment même sur une position « bonne » :
        # AIBD, seulement sur TAF TAF, restait à Grand Yoff dans arrets_geo.csv.
        served = Counter(stop for line in lines for stop in line.stops)
        for stop, proposed in proposals.items():
            position, sure, supporters = max(
                (
                    (
                        candidate,
                        is_sure,
                        sum(
                            haversine_m(candidate, other) <= POSITION_AGREEMENT_M
                            for other, _ in proposed
                        ),
                    )
                    for candidate, is_sure in proposed
                ),
                key=lambda item: (item[2], item[1]),
            )
            if stop not in stop_coords:
                stop_coords[stop] = position
                stop_confidence[stop] = (
                    "bonne" if sure and supporters >= 2 else "estimee"
                )
            elif (
                supporters == len(proposed) == served[stop]
                and haversine_m(position, stop_coords[stop]) > POSITION_AGREEMENT_M
            ):
                stop_coords[stop] = position
                stop_confidence[stop] = "bonne" if sure else "estimee"
            elif (
                sure
                and supporters >= 2
                and stop_confidence.get(stop) != "bonne"
            ):
                stop_coords[stop] = position
                stop_confidence[stop] = "bonne"

        # Les arrêts restants sont placés à vol d'oiseau le long de leur
        # ligne, uniquement en mémoire : les CSV ne sont jamais modifiés.
        stop_coords, stop_confidence = interpolate_missing_coordinates(
            lines, stop_coords, stop_confidence
        )

        # Sur chaque ligne : sa propre position si elle en a une, None si elle est
        # connue pour être inconnue, sinon la position générale de l'arrêt.
        line_positions = {
            key: tuple(
                stop_coords.get(stop) if position is ... else position
                for stop, position in zip(by_key[key].stops, positions)
            )
            for by_key in [{line.key: line for line in lines}]
            for key, positions in raw_positions.items()
        }

        # La vraie longueur de route pour les lignes Tata qui ont une trace.
        line_distances: dict[LineKey, tuple] = {}
        traces = getattr(data, "traces", {})
        for line in lines:
            trace = traces.get(line.name) if line.company == "Tata AFTU" else None
            if not trace:
                continue
            positions = line_positions.get(line.key) or tuple(
                stop_coords.get(stop) for stop in line.stops
            )
            measured = distances_sur_trace(trace, positions)
            if measured is not None:
                line_distances[line.key] = measured

        return cls(
            lines,
            stop_coords,
            stop_confidence,
            line_positions,
            line_distances,
            _legacy_stops(data, lines, stop_coords, stop_confidence),
        )
