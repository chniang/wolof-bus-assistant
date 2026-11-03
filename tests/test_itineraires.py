r"""Tests du moteur d'itinéraires v2 (Koumba + corrections GuindiMa).

    .\.venv\Scripts\python.exe tests\test_itineraires.py

Les tests sur données réelles vérifient les trajets de référence et
l'absence de réponses absurdes.  Les petits réseaux factices isolent
l'interpolation des coordonnées et l'option « tout à pied ».
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "scripts"))

import pandas as pd

import audit_itineraires as audit
from routing.data import NetworkData, load_data
from routing.network import (
    Line,
    Network,
    haversine_m,
    interpolate_missing_coordinates,
)
from routing.places import PlaceIndex, normalize_name
from routing.router import RouteEngine, walking_minutes

BASE_LAT = 14.7
BASE_LON = -17.45

_DATA: NetworkData | None = None
_ENGINE: RouteEngine | None = None


def _point(north_m: float = 0.0, east_m: float = 0.0) -> tuple[float, float]:
    """Transforme un décalage en mètres en latitude/longitude."""

    lat = BASE_LAT + north_m / 111_320
    lon = BASE_LON + east_m / (111_320 * math.cos(math.radians(BASE_LAT)))
    return (lat, lon)


def _data() -> NetworkData:
    global _DATA
    if _DATA is None:
        _DATA = load_data()
    return _DATA


def _engine() -> RouteEngine:
    global _ENGINE
    if _ENGINE is None:
        data = _data()
        _ENGINE = RouteEngine(
            Network.from_data(data),
            PlaceIndex.from_data(data),
        )
    return _ENGINE


def _engine_factice(
    lines: list[Line],
    coords: dict[str, tuple[float, float]],
) -> RouteEngine:
    network = Network(lines, coords)
    return RouteEngine(network, PlaceIndex.from_network(network))


class _DonneesFactices:
    pass


def _donnees_interpolation() -> _DonneesFactices:
    """Deux lignes où Y ne peut être placé qu'à la deuxième passe."""

    donnees = _DonneesFactices()
    donnees.lignes = pd.DataFrame(
        [
            {
                "compagnie": "Op",
                "ligne": "L1",
                "terminus_a": "A",
                "terminus_b": "B",
                "categorie": "",
                "source": "",
            },
            {
                "compagnie": "Op",
                "ligne": "L2",
                "terminus_a": "X",
                "terminus_b": "Z",
                "categorie": "",
                "source": "",
            },
        ]
    )
    donnees.itineraires = pd.DataFrame(
        [
            {"compagnie": "Op", "ligne": "L1", "ordre": 1, "arret": "A"},
            {"compagnie": "Op", "ligne": "L1", "ordre": 2, "arret": "X"},
            {"compagnie": "Op", "ligne": "L1", "ordre": 3, "arret": "B"},
            {"compagnie": "Op", "ligne": "L2", "ordre": 1, "arret": "X"},
            {"compagnie": "Op", "ligne": "L2", "ordre": 2, "arret": "Y"},
            {"compagnie": "Op", "ligne": "L2", "ordre": 3, "arret": "Z"},
        ]
    )
    positions = {
        "A": _point(0, 0),
        "B": _point(2_000, 0),
        "Z": _point(3_000, 2_000),
    }
    donnees.arrets = pd.DataFrame(
        [
            {
                "arret": nom,
                "lat": position[0],
                "lon": position[1],
                "quartier": "",
                "commune": "",
                "confiance": "bonne",
            }
            for nom, position in positions.items()
        ]
    )
    donnees.lieux = pd.DataFrame(columns=["lieu", "lat", "lon"])
    return donnees


# ---------------------------------------------------------------------------
# Données réelles : les trajets de référence.
# ---------------------------------------------------------------------------
def test_ouakam_yoff_meilleur_trajet_sans_correspondance() -> None:
    trips = _engine().find_trips("Ouakam", "Yoff", max_trips=3)

    assert trips
    assert trips[0].transfers == 0
    assert trips[0].legs


def test_camberene_2_sapeurs_pompiers_parcelles_sous_35_minutes() -> None:
    trips = _engine().find_trips(
        "Cambérène 2", "Sapeurs-Pompiers Parcelles"
    )

    assert trips
    assert trips[0].total_minutes <= 35.0, trips[0]


def test_parcelles_assainies_ucad_dem_dikk_ligne_1_direct() -> None:
    trips = _engine().find_trips("Parcelles Assainies", "UCAD", max_trips=3)

    assert trips
    meilleur = trips[0]
    assert meilleur.transfers == 0
    assert len(meilleur.legs) == 1
    leg = meilleur.legs[0]
    assert leg.operator == "Dakar Dem Dikk"
    assert leg.line == "Ligne 1"
    assert leg.board_stop == "Parcelles Assainies"
    assert leg.alight_stop == "UCAD"


def test_audit_60_paires_sans_reponse_absurde() -> None:
    data = _data()
    lieux = audit.lieux_avec_coordonnees(data)
    coords = {
        normalize_name(nom): (lat, lon) for nom, lat, lon in lieux
    }
    paires = audit.paires_aleatoires(lieux, 60)

    assert len(paires) == 60
    resultats = [
        audit.evaluer_paire(_engine(), origine, destination, coords)
        for origine, destination in paires
    ]
    absurdes = [item for item in resultats if item["absurde"]]
    assert not absurdes, absurdes[:3]


# ---------------------------------------------------------------------------
# Petits réseaux factices.
# ---------------------------------------------------------------------------
def test_interpolation_average_sur_plusieurs_lignes() -> None:
    lines = [
        Line("Op", "L1", ("A", "X", "B")),
        Line("Op", "L2", ("X", "Y", "Z")),
    ]
    coords = {
        "A": _point(0, 0),
        "B": _point(2_000, 0),
        "Z": _point(3_000, 2_000),
    }

    remplis, confiance = interpolate_missing_coordinates(lines, coords)

    assert "X" in remplis
    assert "Y" in remplis
    assert confiance["X"] == "interpolee"
    assert confiance["Y"] == "interpolee"

    milieu_x = _point(1_000, 0)
    assert math.isclose(remplis["X"][0], milieu_x[0], rel_tol=1e-9)
    assert math.isclose(remplis["X"][1], milieu_x[1], rel_tol=1e-9)

    # Y se place seulement à la deuxième passe, entre X et Z.
    milieu_y = (
        (milieu_x[0] + coords["Z"][0]) / 2,
        (milieu_x[1] + coords["Z"][1]) / 2,
    )
    assert math.isclose(remplis["Y"][0], milieu_y[0], rel_tol=1e-9)
    assert math.isclose(remplis["Y"][1], milieu_y[1], rel_tol=1e-9)


def test_network_from_data_marque_les_coordonnees_interpolees() -> None:
    network = Network.from_data(_donnees_interpolation())

    assert "X" in network.stop_coords
    assert "Y" in network.stop_coords
    assert network.stop_confidence["X"] == "interpolee"
    assert network.stop_confidence["Y"] == "interpolee"


def test_marche_seule_quand_elle_bat_le_bus() -> None:
    depart = _point(0, 0)
    arrivee = _point(0, 1_000)
    engine = _engine_factice(
        [Line("Op", "Bus", ("Origin", "Far", "Dest"))],
        {
            "Origin": depart,
            "Far": _point(5_000, 0),
            "Dest": arrivee,
        },
    )

    trips = engine.find_trips("Origin", "Dest", max_trips=2)

    assert trips
    meilleur = trips[0]
    assert meilleur.legs == ()
    assert meilleur.transfers == 0
    assert len(meilleur.walks) == 1
    assert meilleur.walks[0].kind == "walk"
    attendu = walking_minutes(depart, arrivee)
    assert attendu <= 40.0
    assert math.isclose(meilleur.total_minutes, attendu, rel_tol=1e-9)


def test_marche_ne_remplace_pas_un_bus_plus_rapide() -> None:
    engine = _engine_factice(
        [Line("Op", "Bus", ("Origin", "Mid", "Dest"))],
        {
            "Origin": _point(0, 0),
            "Mid": _point(1_000, 0),
            "Dest": _point(2_000, 0),
        },
    )

    trips = engine.find_trips("Origin", "Dest", max_trips=2)

    assert trips
    assert trips[0].legs
    assert trips[0].total_minutes < walking_minutes(
        _point(0, 0), _point(2_000, 0)
    )


def test_walking_minutes_applique_le_facteur_de_detour() -> None:
    depart = _point(0, 0)
    arrivee = _point(800, 0)

    attendu = haversine_m(depart, arrivee) * 1.3 / 80.0
    assert math.isclose(walking_minutes(depart, arrivee), attendu, rel_tol=1e-9)


TESTS = (
    test_ouakam_yoff_meilleur_trajet_sans_correspondance,
    test_camberene_2_sapeurs_pompiers_parcelles_sous_35_minutes,
    test_parcelles_assainies_ucad_dem_dikk_ligne_1_direct,
    test_audit_60_paires_sans_reponse_absurde,
    test_interpolation_average_sur_plusieurs_lignes,
    test_network_from_data_marque_les_coordonnees_interpolees,
    test_marche_seule_quand_elle_bat_le_bus,
    test_marche_ne_remplace_pas_un_bus_plus_rapide,
    test_walking_minutes_applique_le_facteur_de_detour,
)


def main() -> int:
    echecs = 0
    for test in TESTS:
        try:
            test()
        except AssertionError as exc:
            echecs += 1
            print(f"ECHEC {test.__name__}: {exc}")
        else:
            print(f"OK {test.__name__}")
    print(f"\n{len(TESTS) - echecs}/{len(TESTS)} réussis")
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(main())
