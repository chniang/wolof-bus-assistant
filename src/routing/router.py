"""Route search with direct trips first, then one or two transfers.

The search is Dijkstra over ``(line, direction, stop position)`` nodes.
The state also remembers how many transfers have been used and which
lines have been used, so we can return distinct line combinations and
never loop back onto a line we already rode.
"""

from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from dataclasses import dataclass

from .network import (
    WALK_SPEED_M_PER_MIN,
    Edge,
    LineKey,
    Network,
    Node,
    haversine_m,
)
from .places import (
    PlaceCandidate,
    PlaceIndex,
    normalize_name,
    prefer_exact_matches,
    representative_coordinates,
)

MAX_TRANSFERS = 2
ACCESS_WALK_RADIUS_M = 1200.0
NEARBY_EXACT_STOP_RADIUS_M = 900.0
MAX_NEARBY_STOPS = 14
MAX_LABELS_PER_STATE = 12
MAX_EXPANSIONS = 250_000
DETOUR_LIMIT = 1.8
DOWNTOWN_RADIUS_M = 1_500.0
MIN_LEG_MINUTES = 2.0
TRANSFER_SCORE_MINUTES = 15.0
DIRECT_ALLOWANCE_MINUTES = 15.0
MIN_TRANSFER_ADVANTAGE_MINUTES = 10.0
MAX_WALKABLE_BUS_LEG_M = 600.0
# La marche à pied suit rarement la ligne droite : 1,3 fois la distance
# vol d'oiseau, à 80 m/min (environ 4,8 km/h).
WALK_DETOUR_FACTOR = 1.3
MAX_WALK_ONLY_MINUTES = 40.0
# A trip three times slower than the best option is not a useful
# alternative.  This also catches routes with missing coordinates that
# escape the distance-based detour check.
MAX_TIME_VS_BEST = 3.0


def walking_minutes(
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Temps de marche estimé entre deux points, en minutes."""

    return haversine_m(a, b) * WALK_DETOUR_FACTOR / WALK_SPEED_M_PER_MIN


# These are the downtown / Plateau names.  A trip may pass through them
# when they are close to the start or the destination, but not as a random
# shortcut between two outer neighbourhoods.
DOWNTOWN_STOP_NAMES = {
    normalize_name(name)
    for name in (
        "Palais 1",
        "Palais 2",
        "Palais",
        "Centre-Ville",
        "Plateau",
        "Place Leclerc",
        "Place de l'Indépendance",
        "Médina",
    )
}


class RouteError(Exception):
    """Base class for route errors."""


class PlaceNotFoundError(RouteError):
    def __init__(self, query: str, suggestions: list[tuple[str, float]]) -> None:
        self.query = query
        self.suggestions = suggestions
        super().__init__(f"Unknown place: {query}")


class NoRouteFoundError(RouteError):
    pass


@dataclass(frozen=True)
class Walk:
    kind: str                      # "access", "transfer", or "egress"
    from_place: str
    to_place: str
    minutes: float
    distance_m: float | None = None
    after_leg: int = 0             # 0 = before the first leg


def _has_endpoint_walk(trip: Trip) -> bool:
    return any(
        walk.kind in {"access", "egress"} and walk.minutes > 0
        for walk in trip.walks
    )


@dataclass(frozen=True)
class Leg:
    operator: str
    line: str
    board_stop: str
    alight_stop: str
    direction: str                 # terminus shown on the bus
    num_stops: int
    minutes: float
    distance_m: float | None = None


@dataclass(frozen=True)
class Trip:
    legs: tuple[Leg, ...]
    walks: tuple[Walk, ...]
    total_minutes: float
    transfers: int
    line_combo: tuple[LineKey, ...]
    origin_name: str
    destination_name: str
    total_distance_m: float | None
    straight_line_m: float | None
    detour: bool
    via_downtown: bool
    ridden_stops: tuple[str, ...]

    @property
    def walked_minutes(self) -> float:
        return sum(walk.minutes for walk in self.walks)

    @property
    def score(self) -> float:
        return self.total_minutes + TRANSFER_SCORE_MINUTES * self.transfers


@dataclass(frozen=True)
class AccessPoint:
    stop: str
    walk: Walk


def _rank_key(trip: Trip) -> tuple[float, int, float, float]:
    distance = (
        trip.total_distance_m
        if trip.total_distance_m is not None
        else float("inf")
    )
    return trip.score, trip.total_minutes, distance, trip.transfers


def rank_trips(trips: list[Trip], max_trips: int | None = None) -> list[Trip]:
    """Order trips by score, promoting a direct trip within 15 minutes.

    Score is ``total_minutes + 15 * transfers``.  A direct trip is shown
    first when it is at most 15 minutes slower than the best score, because
    avoiding a transfer is worth a short wait.
    """

    unique: dict[tuple[LineKey, ...], Trip] = {}
    for trip in trips:
        current = unique.get(trip.line_combo)
        if current is None or _rank_key(trip) < _rank_key(current):
            unique[trip.line_combo] = trip

    ordered = sorted(unique.values(), key=_rank_key)
    if not ordered:
        return []

    best_score = ordered[0].score
    direct = [
        trip
        for trip in ordered
        if trip.transfers == 0
        and trip.score <= best_score + DIRECT_ALLOWANCE_MINUTES
    ]
    direct_keys = {trip.line_combo for trip in direct}
    rest = [trip for trip in ordered if trip.line_combo not in direct_keys]
    ranked = direct + rest
    return ranked if max_trips is None else ranked[:max_trips]


def _has_walkable_one_stop_leg(trip: Trip, network: Network) -> bool:
    """A one-stop bus ride under 600 m is not worth waiting for a bus."""

    for leg in trip.legs:
        if leg.num_stops != 1:
            continue
        distance = leg.distance_m
        if distance is None:
            board = network.coords(leg.board_stop)
            alight = network.coords(leg.alight_stop)
            if board is None or alight is None:
                continue
            distance = haversine_m(board, alight)
        if distance <= MAX_WALKABLE_BUS_LEG_M:
            return True
    return False


def remove_dominated_trips(trips: list[Trip], network: Network) -> list[Trip]:
    """Hide slow transfer-heavy trips and pointless one-stop bus rides.

    A trip with more transfers must save at least ten minutes over the best
    trip with fewer transfers.  One-stop bus legs under 600 m are hidden too.
    If every trip is filtered, keep the best one so the answer is never empty.
    """

    if not trips:
        return []

    candidates = [
        trip for trip in trips if not _has_walkable_one_stop_leg(trip, network)
    ]
    if not candidates:
        return trips[:1]

    kept: list[Trip] = []
    for trip in candidates:
        faster_fewer = [
            other.total_minutes
            for other in candidates
            if other.transfers < trip.transfers
        ]
        if faster_fewer:
            best_fewer = min(faster_fewer)
            advantage = best_fewer - trip.total_minutes
            if advantage < MIN_TRANSFER_ADVANTAGE_MINUTES - 1e-9:
                continue
        kept.append(trip)
    return kept or candidates[:1]


@dataclass(frozen=True)
class _Step:
    kind: str                      # "access", "ride", "transfer", "egress"
    from_stop: str
    to_stop: str
    minutes: float
    line: LineKey
    direction: int
    from_index: int | None
    to_index: int | None
    distance_m: float | None = None
    walk_minutes: float = 0.0
    walk_distance_m: float | None = None
    transfer_penalty: float = 0.0


@dataclass(frozen=True)
class _Label:
    node: Node
    transfers: int
    cost: float
    combo: tuple[LineKey, ...]
    steps: tuple[_Step, ...]
    rode_since_transfer: bool


class RouteEngine:
    def __init__(self, network: Network, place_index: PlaceIndex | None = None) -> None:
        self.network = network
        self.place_index = place_index or PlaceIndex.from_network(network)

    # ------------------------------------------------------------------
    # Endpoint preparation.
    # ------------------------------------------------------------------
    def _access_points(
        self,
        candidate: PlaceCandidate,
        kind: str,
        include_nearby: bool = True,
    ) -> list[AccessPoint]:
        """Stops the user can reach from this place, with the walk."""

        points: dict[str, AccessPoint] = {}

        # Exact normalized stop names win: "Malika" and "Sahm" board at the
        # stop itself, without an invented walk.
        exact_stops = self.network.stops_for_normalized(candidate.normalized)
        for stop in exact_stops:
            points[stop] = AccessPoint(
                stop=stop,
                walk=Walk(
                    kind=kind,
                    from_place=candidate.name,
                    to_place=stop,
                    minutes=0.0,
                    distance_m=0.0,
                    after_leg=0,
                ),
            )

        # Exact stops also open every stop within a short walk.  This lets a
        # neighbourhood such as Médina use a nearby avenue without losing the
        # exact stop itself.  The exact stop keeps its zero-minute walk.
        exact_coords = [
            coords
            for stop in exact_stops
            if (coords := self.network.coords(stop)) is not None
        ]
        if exact_coords and include_nearby:
            nearby: list[tuple[float, str]] = []
            for stop in self.network.stop_names:
                if stop in points:
                    continue
                stop_coords = self.network.coords(stop)
                if stop_coords is None:
                    continue
                distance = min(
                    haversine_m(coords, stop_coords) for coords in exact_coords
                )
                if distance > NEARBY_EXACT_STOP_RADIUS_M:
                    continue
                if (
                    distance <= 1.0
                    and normalize_name(stop) != candidate.normalized
                ):
                    continue
                nearby.append((distance, stop))
            nearby.sort()
            for distance, stop in nearby:
                points[stop] = AccessPoint(
                    stop=stop,
                    walk=Walk(
                        kind=kind,
                        from_place=candidate.name,
                        to_place=stop,
                        minutes=distance / WALK_SPEED_M_PER_MIN,
                        distance_m=distance,
                        after_leg=0,
                    ),
                )

        # A place that is not itself a stop (for example "Palais", which is
        # near Palais 1 and Palais 2) can use the nearest stops.
        if not points and candidate.has_coordinates:
            origin = (float(candidate.lat), float(candidate.lon))
            nearby: list[tuple[float, str]] = []
            for stop in self.network.stop_names:
                stop_coords = self.network.coords(stop)
                if stop_coords is None:
                    continue
                distance = haversine_m(origin, stop_coords)
                if distance <= ACCESS_WALK_RADIUS_M:
                    nearby.append((distance, stop))
            nearby.sort()
            for distance, stop in nearby[:MAX_NEARBY_STOPS]:
                points[stop] = AccessPoint(
                    stop=stop,
                    walk=Walk(
                        kind=kind,
                        from_place=candidate.name,
                        to_place=stop,
                        minutes=distance / WALK_SPEED_M_PER_MIN,
                        distance_m=distance,
                        after_leg=0,
                    ),
                )

        return list(points.values())

    def _endpoint_map(
        self,
        candidates: list[PlaceCandidate],
        kind: str,
        include_nearby: bool = True,
    ) -> dict[str, AccessPoint]:
        result: dict[str, AccessPoint] = {}
        for candidate in candidates:
            for point in self._access_points(candidate, kind, include_nearby):
                current = result.get(point.stop)
                if current is None or point.walk.minutes < current.walk.minutes:
                    result[point.stop] = point
        return result

    @staticmethod
    def _is_downtown_endpoint(
        candidates: list[PlaceCandidate],
        coords: tuple[float, float] | None,
        centre: tuple[float, float] | None,
    ) -> bool:
        if any(candidate.normalized in DOWNTOWN_STOP_NAMES for candidate in candidates):
            return True
        if centre is not None and coords is not None:
            return haversine_m(coords, centre) <= DOWNTOWN_RADIUS_M
        return False

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------
    def find_trips(
        self,
        origin: str,
        destination: str,
        max_trips: int = 3,
        operator: str | None = None,
        first_line: LineKey | None = None,
    ) -> list[Trip]:
        max_trips = max(1, max_trips)
        origin_matches = prefer_exact_matches(
            self.place_index.match(origin),
            origin,
        )
        if not origin_matches:
            raise PlaceNotFoundError(origin, self.place_index.suggestions(origin))

        destination_matches = prefer_exact_matches(
            self.place_index.match(destination),
            destination,
        )
        if not destination_matches:
            raise PlaceNotFoundError(
                destination, self.place_index.suggestions(destination)
            )

        origin_points = self._endpoint_map(
            origin_matches, "access", include_nearby=False
        )
        destination_points = self._endpoint_map(
            destination_matches, "egress", include_nearby=False
        )
        expanded_origin_points = self._endpoint_map(origin_matches, "access")
        expanded_destination_points = self._endpoint_map(
            destination_matches, "egress"
        )
        if not expanded_origin_points:
            raise PlaceNotFoundError(origin, self.place_index.suggestions(origin))
        if not expanded_destination_points:
            raise PlaceNotFoundError(
                destination, self.place_index.suggestions(destination)
            )

        origin_coords = representative_coordinates(origin_matches)
        destination_coords = representative_coordinates(destination_matches)

        # La marche peut battre le bus sur les courtes distances.  On garde
        # ce trajet à part : il ne remplace le bus que s'il est plus rapide.
        walk_trip: Trip | None = None
        if origin_coords is not None and destination_coords is not None:
            walk_time = walking_minutes(origin_coords, destination_coords)
            if walk_time <= MAX_WALK_ONLY_MINUTES:
                straight = haversine_m(origin_coords, destination_coords)
                walk_distance = straight * WALK_DETOUR_FACTOR
                walk_trip = Trip(
                    legs=(),
                    walks=(
                        Walk(
                            kind="walk",
                            from_place=origin,
                            to_place=destination,
                            minutes=walk_time,
                            distance_m=walk_distance,
                            after_leg=0,
                        ),
                    ),
                    total_minutes=walk_time,
                    transfers=0,
                    line_combo=(),
                    origin_name=origin,
                    destination_name=destination,
                    total_distance_m=walk_distance,
                    straight_line_m=straight,
                    detour=False,
                    via_downtown=False,
                    ridden_stops=(),
                )

        centre = self.network.downtown_centre
        origin_is_downtown = self._is_downtown_endpoint(
            origin_matches, origin_coords, centre
        )
        destination_is_downtown = self._is_downtown_endpoint(
            destination_matches, destination_coords, centre
        )

        def search(
            access_points: dict[str, AccessPoint],
            egress_points: dict[str, AccessPoint],
        ) -> list[Trip]:
            return self._search(
                origin_points=access_points,
                destination_points=egress_points,
                origin_name=origin,
                destination_name=destination,
                origin_coords=origin_coords,
                destination_coords=destination_coords,
                origin_is_downtown=origin_is_downtown,
                destination_is_downtown=destination_is_downtown,
                max_trips=max_trips,
                operator=operator,
                first_line=first_line,
            )

        trips = search(origin_points, destination_points)
        if (
            expanded_origin_points != origin_points
            or expanded_destination_points != destination_points
        ):
            trips += search(
                expanded_origin_points,
                expanded_destination_points,
            )
        # Extra guard for this network: do not cross downtown just to
        # connect two outer neighbourhoods.
        non_downtown = [trip for trip in trips if not trip.via_downtown]
        if non_downtown:
            trips = non_downtown

        # Do not offer an absurdly slow "alternative" just because it has
        # fewer transfers.  If every remaining trip is slow, keep them.
        if trips:
            fastest = min(trip.total_minutes for trip in trips)
            sane = [
                trip
                for trip in trips
                if trip.total_minutes <= fastest * MAX_TIME_VS_BEST
            ]
            if sane:
                trips = sane

        # The exact stop remains the primary choice.  A nearby stop may add a
        # direct option, but it must not replace a normal exact-stop route
        # with a walk plus extra transfers.
        if any(not _has_endpoint_walk(trip) for trip in trips):
            trips = [
                trip
                for trip in trips
                if trip.transfers == 0 or not _has_endpoint_walk(trip)
            ]

        ranked = rank_trips(trips)
        result = remove_dominated_trips(ranked, self.network)[:max_trips]

        if walk_trip is not None:
            fastest_bus = min(
                (trip.total_minutes for trip in trips), default=None
            )
            if fastest_bus is None or walk_trip.total_minutes < fastest_bus:
                result = [walk_trip] + result
                result = result[:max_trips]

        if not result:
            raise NoRouteFoundError(
                f"No bus trip found between {origin!r} and {destination!r}."
            )
        return result

    # ------------------------------------------------------------------
    # Search.
    # ------------------------------------------------------------------
    def _search(
        self,
        origin_points: dict[str, AccessPoint],
        destination_points: dict[str, AccessPoint],
        origin_name: str,
        destination_name: str,
        origin_coords: tuple[float, float] | None,
        destination_coords: tuple[float, float] | None,
        origin_is_downtown: bool,
        destination_is_downtown: bool,
        max_trips: int,
        operator: str | None = None,
        first_line: LineKey | None = None,
    ) -> list[Trip]:
        queue: list[tuple[float, int, float, int, _Label]] = []
        counter = itertools.count()
        best: dict[tuple[Node, int], list[_Label]] = defaultdict(list)
        recorded: dict[tuple[LineKey, ...], Trip] = {}
        accepted: list[Trip] = []

        for stop, access in origin_points.items():
            for node in self.network.nodes_at_stop(stop):
                if first_line is not None and node.line != first_line:
                    continue
                if operator is not None and node.line[0] != operator:
                    continue
                access_step = _Step(
                    kind="access",
                    from_stop=access.walk.from_place,
                    to_stop=stop,
                    minutes=access.walk.minutes,
                    line=node.line,
                    direction=node.direction,
                    from_index=None,
                    to_index=node.index,
                    walk_minutes=access.walk.minutes,
                    walk_distance_m=access.walk.distance_m,
                )
                label = _Label(
                    node=node,
                    transfers=0,
                    cost=access.walk.minutes,
                    combo=(node.line,),
                    steps=(access_step,),
                    rode_since_transfer=False,
                )
                self._push(queue, best, counter, label)

        expansions = 0
        while queue:
            score_so_far, _, _, _, label = heapq.heappop(queue)
            state = (label.node, label.transfers)
            if not any(existing is label for existing in best[state]):
                continue

            expansions += 1
            if expansions > MAX_EXPANSIONS:
                break

            # Queue order is score order, so this lower bound is final.
            if len(accepted) >= max_trips:
                worst_score = max(trip.score for trip in accepted)
                if score_so_far >= worst_score:
                    break

            stop = self.network.stop_for(label.node)
            destination = destination_points.get(stop)
            if destination is not None and label.rode_since_transfer:
                trip = self._build_trip(
                    label=label,
                    destination=destination,
                    origin_name=origin_name,
                    destination_name=destination_name,
                    origin_coords=origin_coords,
                    destination_coords=destination_coords,
                    origin_is_downtown=origin_is_downtown,
                    destination_is_downtown=destination_is_downtown,
                )
                current = recorded.get(trip.line_combo)
                if current is None or self._trip_rank(trip) < self._trip_rank(current):
                    recorded[trip.line_combo] = trip

                if not trip.via_downtown:
                    accepted.append(trip)
                    accepted = self._best_accepted(accepted, max_trips)

            for edge in self.network.adjacency[label.node]:
                if edge.kind == "ride":
                    self._push(
                        queue,
                        best,
                        counter,
                        self._advance_ride(label, edge),
                    )
                else:
                    if label.transfers >= MAX_TRANSFERS:
                        continue
                    if not label.rode_since_transfer:
                        continue
                    if operator is not None and edge.target.line[0] != operator:
                        continue
                    if edge.target.line in label.combo:
                        continue
                    self._push(
                        queue,
                        best,
                        counter,
                        self._advance_transfer(label, edge),
                    )

        return list(recorded.values())

    @staticmethod
    def _trip_rank(
        trip: Trip,
    ) -> tuple[bool, bool, float, int, float, float]:
        # Prefer a clean trip over a detour, and a non-downtown trip over a
        # downtown shortcut, even if the clean version is slightly slower.
        score, minutes, distance, transfers = _rank_key(trip)
        return (
            trip.detour,
            trip.via_downtown,
            score,
            transfers,
            minutes,
            distance,
        )

    @staticmethod
    def _best_accepted(trips: list[Trip], max_trips: int) -> list[Trip]:
        unique: dict[tuple[LineKey, ...], Trip] = {}
        for trip in trips:
            current = unique.get(trip.line_combo)
            if current is None or _rank_key(trip) < _rank_key(current):
                unique[trip.line_combo] = trip

        if not unique:
            return []
        fastest = min(trip.total_minutes for trip in unique.values())
        reasonable = [
            trip
            for trip in unique.values()
            if trip.total_minutes <= fastest * MAX_TIME_VS_BEST
        ]
        return rank_trips(reasonable, max_trips)

    def _push(
        self,
        queue: list[tuple[float, int, float, int, _Label]],
        best: dict[tuple[Node, int], list[_Label]],
        counter,
        label: _Label,
    ) -> None:
        state = (label.node, label.transfers)
        current = best[state]

        # A state can be reached with different line combinations.  Keep
        # a small set of them, but never keep the same combination twice.
        for existing in list(current):
            if (
                existing.combo == label.combo
                and existing.rode_since_transfer == label.rode_since_transfer
            ):
                if existing.cost <= label.cost + 1e-9:
                    return
                current.remove(existing)

        current.append(label)
        current.sort(key=lambda item: item.cost)
        if len(current) > MAX_LABELS_PER_STATE:
            del current[MAX_LABELS_PER_STATE:]

        heapq.heappush(
            queue,
            (
                label.cost + TRANSFER_SCORE_MINUTES * label.transfers,
                label.transfers,
                label.cost,
                next(counter),
                label,
            ),
        )

    def _advance_ride(self, label: _Label, edge: Edge) -> _Label:
        from_stop = self.network.stop_for(label.node)
        to_stop = self.network.stop_for(edge.target)
        step = _Step(
            kind="ride",
            from_stop=from_stop,
            to_stop=to_stop,
            minutes=edge.minutes,
            line=label.node.line,
            direction=label.node.direction,
            from_index=label.node.index,
            to_index=edge.target.index,
            distance_m=edge.distance_m,
        )
        return _Label(
            node=edge.target,
            transfers=label.transfers,
            cost=label.cost + edge.minutes,
            combo=label.combo,
            steps=label.steps + (step,),
            rode_since_transfer=True,
        )

    def _advance_transfer(self, label: _Label, edge: Edge) -> _Label:
        from_stop = self.network.stop_for(label.node)
        to_stop = self.network.stop_for(edge.target)
        step = _Step(
            kind="transfer",
            from_stop=from_stop,
            to_stop=to_stop,
            minutes=edge.minutes,
            line=edge.target.line,
            direction=edge.target.direction,
            from_index=label.node.index,
            to_index=edge.target.index,
            walk_minutes=edge.walk_minutes,
            walk_distance_m=edge.walk_distance_m,
            transfer_penalty=edge.transfer_penalty,
        )
        return _Label(
            node=edge.target,
            transfers=label.transfers + 1,
            cost=label.cost + edge.minutes,
            combo=label.combo + (edge.target.line,),
            steps=label.steps + (step,),
            rode_since_transfer=False,
        )

    # ------------------------------------------------------------------
    # Turning a search label into a friendly Trip.
    # ------------------------------------------------------------------
    def _build_trip(
        self,
        label: _Label,
        destination: AccessPoint,
        origin_name: str,
        destination_name: str,
        origin_coords: tuple[float, float] | None,
        destination_coords: tuple[float, float] | None,
        origin_is_downtown: bool,
        destination_is_downtown: bool,
    ) -> Trip:
        alight_stop = self.network.stop_for(label.node)
        egress_step = _Step(
            kind="egress",
            from_stop=alight_stop,
            to_stop=destination.walk.to_place,
            minutes=destination.walk.minutes,
            line=label.node.line,
            direction=label.node.direction,
            from_index=label.node.index,
            to_index=None,
            walk_minutes=destination.walk.minutes,
            walk_distance_m=destination.walk.distance_m,
        )
        steps = label.steps + (egress_step,)

        legs: list[Leg] = []
        walks: list[Walk] = []
        ridden_stops: list[str] = []
        current: dict | None = None
        minimum_leg_extra = 0.0

        def finish_leg() -> None:
            nonlocal current, minimum_leg_extra
            if current is None:
                return
            line = self.network.lines[current["line"]]
            billed_minutes = max(MIN_LEG_MINUTES, current["minutes"])
            minimum_leg_extra += billed_minutes - current["minutes"]
            legs.append(
                Leg(
                    operator=line.company,
                    line=line.name,
                    board_stop=current["board_stop"],
                    alight_stop=current["alight_stop"],
                    direction=line.terminus_for(current["direction"]),
                    num_stops=abs(
                        int(current["end_index"]) - int(current["start_index"])
                    ),
                    minutes=billed_minutes,
                    distance_m=current["distance"],
                )
            )
            current = None

        for step in steps:
            if step.kind == "access":
                if step.walk_minutes > 0 or (step.walk_distance_m or 0) > 0:
                    walks.append(
                        Walk(
                            kind="access",
                            from_place=step.from_stop,
                            to_place=step.to_stop,
                            minutes=step.walk_minutes,
                            distance_m=step.walk_distance_m,
                            after_leg=0,
                        )
                    )
            elif step.kind == "ride":
                if (
                    current is None
                    or current["line"] != step.line
                    or current["direction"] != step.direction
                ):
                    finish_leg()
                    current = {
                        "line": step.line,
                        "direction": step.direction,
                        "board_stop": step.from_stop,
                        "alight_stop": step.to_stop,
                        "start_index": step.from_index,
                        "end_index": step.to_index,
                        "minutes": step.minutes,
                        "distance": step.distance_m,
                    }
                else:
                    current["alight_stop"] = step.to_stop
                    current["end_index"] = step.to_index
                    current["minutes"] += step.minutes
                    if (
                        current["distance"] is None
                        or step.distance_m is None
                    ):
                        current["distance"] = None
                    else:
                        current["distance"] += step.distance_m
                for stop in (step.from_stop, step.to_stop):
                    if not ridden_stops or ridden_stops[-1] != stop:
                        ridden_stops.append(stop)
            elif step.kind == "transfer":
                finish_leg()
                if step.walk_minutes > 0 or (step.walk_distance_m or 0) > 0:
                    walks.append(
                        Walk(
                            kind="transfer",
                            from_place=step.from_stop,
                            to_place=step.to_stop,
                            minutes=step.walk_minutes,
                            distance_m=step.walk_distance_m,
                            after_leg=len(legs),
                        )
                    )
            elif step.kind == "egress":
                finish_leg()
                if step.walk_minutes > 0 or (step.walk_distance_m or 0) > 0:
                    walks.append(
                        Walk(
                            kind="egress",
                            from_place=step.from_stop,
                            to_place=step.to_stop,
                            minutes=step.walk_minutes,
                            distance_m=step.walk_distance_m,
                            after_leg=len(legs),
                        )
                    )

        finish_leg()

        total_minutes = sum(step.minutes for step in steps) + minimum_leg_extra

        total_distance: float | None = 0.0
        for step in steps:
            if step.kind == "ride":
                if step.distance_m is None:
                    total_distance = None
                    break
                total_distance += step.distance_m
            else:
                total_distance += step.walk_distance_m or 0.0

        straight_line: float | None = None
        if origin_coords is not None and destination_coords is not None:
            straight_line = haversine_m(origin_coords, destination_coords)

        detour = bool(
            total_distance is not None
            and straight_line is not None
            and total_distance > DETOUR_LIMIT * straight_line
        )
        via_downtown = self._passes_downtown(
            ridden_stops,
            origin_is_downtown=origin_is_downtown,
            destination_is_downtown=destination_is_downtown,
        )

        return Trip(
            legs=tuple(legs),
            walks=tuple(walks),
            total_minutes=total_minutes,
            transfers=label.transfers,
            line_combo=label.combo,
            origin_name=origin_name,
            destination_name=destination_name,
            total_distance_m=total_distance,
            straight_line_m=straight_line,
            detour=detour,
            via_downtown=via_downtown,
            ridden_stops=tuple(ridden_stops),
        )

    def _passes_downtown(
        self,
        ridden_stops: list[str],
        origin_is_downtown: bool,
        destination_is_downtown: bool,
    ) -> bool:
        if origin_is_downtown or destination_is_downtown:
            return False

        if any(normalize_name(stop) in DOWNTOWN_STOP_NAMES for stop in ridden_stops):
            return True

        centre = self.network.downtown_centre
        if centre is None:
            return False
        for stop in ridden_stops:
            coords = self.network.coords(stop)
            if coords is not None and haversine_m(coords, centre) <= DOWNTOWN_RADIUS_M:
                return True
        return False
