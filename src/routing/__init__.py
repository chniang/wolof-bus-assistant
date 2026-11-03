"""Moteur d'itinéraires GuindiMa, repris de Koumba.

Le module n'est pas encore branché dans ``app.py`` : il s'utilise via
``Network.from_data(load_data())`` puis ``RouteEngine(network)``.
"""

from .data import NetworkData, load_data
from .network import Line, Network, haversine_m, interpolate_missing_coordinates
from .places import PlaceCandidate, PlaceIndex, normalize_name
from .router import (
    Leg,
    NoRouteFoundError,
    PlaceNotFoundError,
    RouteEngine,
    RouteError,
    Trip,
    Walk,
    walking_minutes,
)

__all__ = [
    "Leg",
    "Line",
    "Network",
    "NetworkData",
    "NoRouteFoundError",
    "PlaceCandidate",
    "PlaceIndex",
    "PlaceNotFoundError",
    "RouteEngine",
    "RouteError",
    "Trip",
    "Walk",
    "haversine_m",
    "interpolate_missing_coordinates",
    "load_data",
    "normalize_name",
    "walking_minutes",
]
