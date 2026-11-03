"""Passerelle entre le moteur d'itinéraires v2 et l'interface historique.

``StopsMatcher.find_line`` renvoie un dictionnaire que toute l'application
connaît (cartes, partage, voix).  Le moteur v2, lui, rend des objets ``Trip``
plus riches.  Ce module traduit les uns dans l'autre, sans modifier ni le
moteur v1 ni les CSV.

Le réseau est construit une seule fois, à l'import, comme ``MATCHER`` dans
``app.py`` : plusieurs requêtes ne doivent pas relire les fichiers.
"""

from __future__ import annotations

from .data import load_data
from .network import Network
from .places import (
    MATCH_THRESHOLD,
    PlaceIndex,
    prefer_exact_matches,
)
from .router import (
    Leg,
    NoRouteFoundError,
    PlaceNotFoundError,
    RouteEngine,
    Trip,
)

try:  # import à plat (app.py) ou en paquet
    from matching.lieux import joli
except ImportError:  # pragma: no cover
    from ..matching.lieux import joli

# Les mêmes plafonds que l'affichage v1 : trois lignes directes, deux
# correspondances.  Pour un trajet à deux changements, deux possibilités
# suffisent aussi.
MAX_LIGNES = 3
MAX_CORRESPONDANCES = 2
MAX_TRAJETS_2 = 2
# Le moteur v2 classe et filtre les trajets.  On lui en demande un peu plus que
# l'affichage pour ne pas perdre une catégorie entière (direct / 1 / 2
# changements) avant de la répartir.
MAX_TRIPS = 4

_DATA = load_data()
_NETWORK = Network.from_data(_DATA)
_ENGINE = RouteEngine(_NETWORK, PlaceIndex.from_data(_DATA))

# La catégorie (« Express », « Urbain »…) ne sert qu'à l'affichage : le moteur
# v2 ne la garde pas dans ses objets Line.
_CATEGORIES = {
    (str(rangee.compagnie), str(rangee.ligne)): str(
        getattr(rangee, "categorie", "") or ""
    )
    for rangee in _DATA.lignes.itertuples(index=False)
}


def _troncon(leg: Leg) -> dict:
    """Un bus du moteur v2 au format exact de ``StopsMatcher._troncon``."""

    ligne = _NETWORK.lines[(leg.operator, leg.line)]
    arrets = ligne.stops
    if arrets and arrets[-1] == leg.direction:
        direct = True
        ordre = arrets
    elif arrets and arrets[0] == leg.direction:
        direct = False
        ordre = tuple(reversed(arrets))
    else:
        # Repli : l'ordre des arrêts sur la ligne tranche le sens.
        positions = {arret: index for index, arret in enumerate(arrets)}
        direct = positions.get(leg.board_stop, 0) < positions.get(
            leg.alight_stop, 0
        )
        ordre = arrets if direct else tuple(reversed(arrets))

    try:
        i_dep = ordre.index(leg.board_stop)
        i_arr = ordre.index(leg.alight_stop)
    except ValueError:
        parcours = [leg.board_stop, leg.alight_stop]
    else:
        parcours = list(ordre[i_dep : i_arr + 1])

    if direct:
        depart = ligne.terminus_a or (arrets[0] if arrets else "")
        arrivee = ligne.terminus_b or (arrets[-1] if arrets else "")
    else:
        depart = ligne.terminus_b or (arrets[-1] if arrets else "")
        arrivee = ligne.terminus_a or (arrets[0] if arrets else "")

    return {
        "compagnie": leg.operator,
        "ligne": leg.line,
        "categorie": _CATEGORIES.get((leg.operator, leg.line), ""),
        "depart": depart,
        "arrivee": arrivee,
        "sens": "direct" if direct else "inverse",
        "monte_a": joli(leg.board_stop),
        "descend_a": joli(leg.alight_stop),
        "arrets_trajet": [joli(arret) for arret in parcours],
        "minutes": int(round(leg.minutes)),
    }


def _correspondance(trip: Trip) -> dict:
    """Un trajet à un changement : etape_1, etape_2, changement."""

    etape_1 = _troncon(trip.legs[0])
    etape_2 = _troncon(trip.legs[1])
    return {
        "etape_1": etape_1,
        "etape_2": etape_2,
        "changement": joli(trip.legs[0].alight_stop),
        "minutes": int(round(trip.total_minutes)),
    }


def _trajet_2(trip: Trip) -> dict:
    """Un trajet à deux changements : trois bus et deux arrêts de changement."""

    etapes = [_troncon(leg) for leg in trip.legs]
    return {
        "etapes": etapes,
        "changements": [joli(leg.alight_stop) for leg in trip.legs[:-1]],
        "minutes": int(round(trip.total_minutes)),
    }


def _a_pied(trip: Trip) -> dict:
    """La marche seule : durée et distance, arrondies."""

    distance = sum(walk.distance_m or 0.0 for walk in trip.walks)
    return {
        "minutes": int(round(trip.total_minutes)),
        "distance_m": int(round(distance)),
    }


def _endpoint(query: str) -> tuple[str, float, bool]:
    """Le meilleur arrêt connu pour un lieu, son score v1 (0 à 1), sa validité."""

    texte = query or ""
    candidats = prefer_exact_matches(_ENGINE.place_index.match(texte), texte)
    if candidats:
        return candidats[0].name, round(candidats[0].score / 100.0, 3), True
    suggestions = _ENGINE.place_index.suggestions(texte, limit=1)
    if suggestions:
        nom, score = suggestions[0]
        return nom, round(score / 100.0, 3), score >= MATCH_THRESHOLD
    return "", 0.0, False


def _resultat_vide(depart: str, arrivee: str) -> dict:
    depart_arret, depart_score, depart_valide = _endpoint(depart)
    arrivee_arret, arrivee_score, arrivee_valide = _endpoint(arrivee)
    return {
        "found": False,
        "depart": depart,
        "depart_matched": depart_arret,
        "depart_score": depart_score,
        "depart_valide": depart_valide,
        "arrivee": arrivee,
        "arrivee_matched": arrivee_arret,
        "arrivee_score": arrivee_score,
        "arrivee_valide": arrivee_valide,
        "lignes": [],
        "correspondances": [],
        "trajets_2": [],
        "a_pied": None,
    }


def chercher_v2(
    depart: str,
    arrivee: str,
    compagnies: set[str] | None = None,
) -> dict:
    """Le trajet au format de ``StopsMatcher.find_line``, calculé par v2.

    Les trajets directs vont dans ``lignes``, ceux à un changement dans
    ``correspondances``, ceux à deux changements dans ``trajets_2``, et la
    marche seule dans ``a_pied``.  Chaque ligne et chaque trajet portent aussi
    ``minutes`` (total arrondi).
    """

    depart, arrivee = depart or "", arrivee or ""
    depart_arret, depart_score, depart_valide = _endpoint(depart)
    arrivee_arret, arrivee_score, arrivee_valide = _endpoint(arrivee)
    resultat = _resultat_vide(depart, arrivee)

    if not depart or not arrivee:
        return resultat

    operateur = (
        next(iter(compagnies))
        if compagnies is not None and len(compagnies) == 1
        else None
    )
    try:
        trips = _ENGINE.find_trips(
            depart,
            arrivee,
            max_trips=MAX_TRIPS,
            operator=operateur,
        )
    except (PlaceNotFoundError, NoRouteFoundError):
        return resultat
    except Exception:
        # Le repli v1 se fait dans app.py ; ici on garde le contrat de retour.
        return resultat

    if compagnies is not None:
        trips = [
            trip
            for trip in trips
            if all(leg.operator in compagnies for leg in trip.legs)
        ]
    if not trips:
        return resultat

    lignes: list[dict] = []
    correspondances: list[dict] = []
    trajets_2: list[dict] = []
    a_pied: dict | None = None

    for trip in trips:
        if not trip.legs:
            a_pied = _a_pied(trip)
        elif len(trip.legs) == 1:
            lignes.append(_troncon(trip.legs[0]))
        elif len(trip.legs) == 2:
            correspondances.append(_correspondance(trip))
        elif len(trip.legs) == 3:
            trajets_2.append(_trajet_2(trip))

    lignes = lignes[:MAX_LIGNES]
    correspondances = correspondances[:MAX_CORRESPONDANCES]
    trajets_2 = trajets_2[:MAX_TRAJETS_2]

    resultat.update(
        {
            "found": bool(lignes or correspondances or trajets_2 or a_pied),
            "depart_matched": lignes[0]["monte_a"] if lignes else depart_arret,
            "depart_score": depart_score,
            "depart_valide": depart_valide,
            "arrivee_matched": (
                lignes[0]["descend_a"] if lignes else arrivee_arret
            ),
            "arrivee_score": arrivee_score,
            "arrivee_valide": arrivee_valide,
            "lignes": lignes,
            "correspondances": correspondances,
            "trajets_2": trajets_2,
            "a_pied": a_pied,
        }
    )
    return resultat


def a_un_trajet(resultat: dict | None) -> bool:
    """Vrai dès qu'un résultat contient une ligne, une correspondance ou une marche."""

    if not resultat:
        return False
    return bool(
        resultat.get("lignes")
        or resultat.get("correspondances")
        or resultat.get("trajets_2")
        or resultat.get("a_pied")
    )


class MoteurV2:
    """Même interface que ``StopsMatcher.find_line``, avec repli sur v1.

    Les appels passent par ``chercher_v2``.  Si le moteur v2 lève une erreur ou
    ne trouve rien, on rend exactement ce que ``StopsMatcher`` aurait rendu.
    Les autres attributs (``geo``, ``arrets``…) restent ceux de v1 : les tests et
    l'affichage continuent de les utiliser sans changement.
    """

    def __init__(self, repli) -> None:
        self._repli = repli

    def __getattr__(self, nom: str):
        return getattr(self._repli, nom)

    def find_line(
        self, depart: str, arrivee: str, compagnies: set[str] | None = None
    ) -> dict:
        try:
            resultat = chercher_v2(depart, arrivee, compagnies)
        except Exception as exc:  # pragma: no cover - garde-fou de production
            print(
                f"[moteur] v2 indisponible ({type(exc).__name__}), repli v1",
                flush=True,
            )
        else:
            if a_un_trajet(resultat):
                return resultat
        return self._repli.find_line(depart, arrivee, compagnies)

    def find_line_compagnie(
        self, depart: str, arrivee: str, compagnie: str
    ) -> tuple[dict, bool]:
        """Trajet réservé à une compagnie, avec le même repli que v1."""

        restreint = self.find_line(depart, arrivee, compagnies={compagnie})
        if a_un_trajet(restreint):
            return restreint, True
        return self.find_line(depart, arrivee), False


__all__ = ["MoteurV2", "a_un_trajet", "chercher_v2"]
