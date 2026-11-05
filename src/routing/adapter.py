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
from functools import lru_cache

from .corrections import STOP_NAME_ALIASES
from .places import PlaceIndex, normalize_name, terminus_forms
from .router import (
    Leg,
    NoRouteFoundError,
    PlaceNotFoundError,
    ResolvedPlace,
    RouteEngine,
    Trip,
    keep_sensible_trips,
    rank_trips,
    remove_dominated_trips,
)

try:  # import à plat (app.py) ou en paquet
    from matching.geo import nom_generique, nom_rue_numerotee
    from matching.lieux import joli, score
    from matching.stops_matcher import MIN_SCORE, TOLERANCE
except ImportError:  # pragma: no cover
    from ..matching.geo import nom_generique, nom_rue_numerotee
    from ..matching.lieux import joli, score
    from ..matching.stops_matcher import MIN_SCORE, TOLERANCE

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
# Le graphe se construit ici, au démarrage (5 s) : sinon, c'est le premier usager
# qui attend.  app.py importe ce module au lancement.
_NETWORK.adjacency

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
    # Une boucle (Dem Dikk 502 : Gare Colobane -> Gare Colobane) a le même terminus
    # aux deux bouts : seul l'ordre des arrêts peut trancher le sens.
    boucle = bool(arrets) and arrets[0] == arrets[-1]
    if arrets and not boucle and arrets[-1] == leg.direction:
        direct = True
        ordre = arrets
    elif arrets and not boucle and arrets[0] == leg.direction:
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
        parcours = list(ordre[i_dep : i_arr + 1]) or [
            leg.board_stop,
            leg.alight_stop,
        ]

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
        "estimee": leg.estimated,
    }


def _direct(trip: Trip) -> dict:
    """Un bus direct : la carte montre la durée totale du trajet, plancher compris."""

    return {
        **_troncon(trip.legs[0]),
        "minutes": int(round(trip.total_minutes)),
    }


def _marches(trip: Trip) -> list[int]:
    """Les minutes à pied à chaque changement, 0 quand on reste au même arrêt."""

    minutes = [0] * (len(trip.legs) - 1)
    for walk in trip.walks:
        if walk.kind == "transfer" and 1 <= walk.after_leg <= len(minutes):
            if (walk.distance_m or 0) > 0:
                minutes[walk.after_leg - 1] = max(1, int(round(walk.minutes)))
    return minutes


def _correspondance(trip: Trip) -> dict:
    """Un trajet à un changement : etape_1, etape_2, changement."""

    etape_1 = _troncon(trip.legs[0])
    etape_2 = _troncon(trip.legs[1])
    return {
        "etape_1": etape_1,
        "etape_2": etape_2,
        "changement": joli(trip.legs[0].alight_stop),
        "marches": _marches(trip),
        "minutes": int(round(trip.total_minutes)),
    }


def _trajet_2(trip: Trip) -> dict:
    """Un trajet à deux changements : trois bus et deux arrêts de changement."""

    etapes = [_troncon(leg) for leg in trip.legs]
    return {
        "etapes": etapes,
        "changements": [joli(leg.alight_stop) for leg in trip.legs[:-1]],
        "marches": _marches(trip),
        "minutes": int(round(trip.total_minutes)),
    }


def _a_pied(trip: Trip) -> dict:
    """La marche seule : durée et distance, arrondies."""

    distance = sum(walk.distance_m or 0.0 for walk in trip.walks)
    return {
        "minutes": int(round(trip.total_minutes)),
        "distance_m": int(round(distance)),
    }


def _arrets_du_reseau(arret: str) -> list[str]:
    """Le nom de cet arrêt v1 dans le réseau v2, qui unifie certaines orthographes.

    « SAHM » devient « Sahm », et « Pattesd'oie » devient « Patte d'Oie ».
    """

    normalise = normalize_name(arret)
    noms = _NETWORK.stops_for_normalized(normalise)
    if noms:
        return list(noms)
    canonique = STOP_NAME_ALIASES.get(normalise)
    return list(_NETWORK.stops_for_normalized(normalize_name(canonique or "")))


@lru_cache(maxsize=4)
def _arrets_surs(matcher) -> frozenset[str]:
    """Les arrêts v2 que les règles de geo.py permettent de situer."""

    surs = {
        nom
        for arret in matcher.tous_les_arrets
        if matcher.geo.position_sure(arret)
        for nom in _arrets_du_reseau(arret)
    }
    # Les noms officiels de Dem Dikk : mêmes règles que geo.py.
    surs.update(
        nom
        for nom in _arrets_nouveaux(matcher)
        if _NETWORK.stop_confidence.get(nom) == "bonne"
        and not nom_generique(nom)
        and not nom_rue_numerotee(nom)
    )
    return frozenset(surs)


@lru_cache(maxsize=4)
def _arrets_nouveaux(matcher) -> tuple[str, ...]:
    """Les arrêts du réseau v2 que v1 ne connaît pas (noms officiels de Dem Dikk)."""

    connus = {normalize_name(arret) for arret in matcher.tous_les_arrets}
    return tuple(
        nom for nom in _NETWORK.stop_names if normalize_name(nom) not in connus
    )


def _vers_reseau(arrets: list[str]) -> tuple[str, ...]:
    """Noms v1 -> noms v2, sans doublon et dans le même ordre."""

    noms: list[str] = []
    for arret in arrets:
        for nom in _arrets_du_reseau(arret):
            if nom not in noms:
                noms.append(nom)
    return tuple(noms)


def _note_du_nom(lieu: str, arret: str) -> float:
    """La note de v1, ou celle d'un lieu que désigne ce terminus.

    Sans cela, « Terminus liberté 5 (Dieuppeul) » ne valait que 0,83 pour « Liberté 5 »,
    et les Dem Dikk 10 et 13 disparaissaient devant la 6 (« Liberté 5 », 1,0).
    """

    return max(
        (score(lieu, nom) for nom in (arret, *terminus_forms(arret))),
        default=0.0,
    )


def _resoudre(matcher, lieu: str) -> dict:
    """Résout un lieu exactement comme ``StopsMatcher.find_line``.

    Le nom passe avant la position (« Liberté 5 » ne ramène pas « Liberté 6 »).
    ALIAS, FAUX_AMIS et règles géo sont ceux de v1 : on les appelle.  ``place``
    garde les arrêts à moins de TOLERANCE du meilleur, ``large`` tous les arrêts
    valides, et ``notes`` la note de chacun, sous son nom dans le réseau v2.

    Les noms officiels de Dem Dikk s'y ajoutent.  La position reste décidée sur les
    arrêts de v1 : « Sandaga » est désormais un arrêt, mais Petersen, à côté, doit
    rester proposé, comme avant (Tata 41).  Un arrêt sorti du réseau v2 ne compte plus.
    """

    _, par_nom = matcher._reconnu(lieu)
    geo_scores = matcher.geo.scores_lieu(lieu, proximite=par_nom < MIN_SCORE)

    notes_v1 = {
        arret: max(_note_du_nom(lieu, arret), geo_scores.get(arret, 0.0))
        for arret in matcher.tous_les_arrets
        if _arrets_du_reseau(arret)
    }
    notes_v1.update(
        (arret, _note_du_nom(lieu, arret)) for arret in _arrets_nouveaux(matcher)
    )
    tries = sorted(notes_v1, key=lambda arret: -notes_v1[arret])
    meilleur = tries[0] if tries and notes_v1[tries[0]] > 0 else ""
    note = notes_v1[meilleur] if meilleur else 0.0
    notes: dict[str, float] = {}
    par_son_nom: set[str] = set()
    for arret in tries:
        for nom in _arrets_du_reseau(arret):
            notes.setdefault(nom, notes_v1[arret])
            if _note_du_nom(lieu, arret) >= MIN_SCORE:
                par_son_nom.add(nom)
    # Le point connu des CSV seulement : il sert à mesurer le vol d'oiseau, jamais
    # à décider où monter, et ne doit pas dépendre du réseau.
    # Un lieu qui est exactement un arrêt prend la position de cet arrêt sur le réseau :
    # celle de arrets_geo.csv peut être périmée (AIBD, placé à Grand Yoff).
    point = None if note >= 1.0 else matcher.geo.point_connu(lieu)

    def place(seuil: float) -> ResolvedPlace:
        return ResolvedPlace(
            stops=_vers_reseau([a for a in tries if notes_v1[a] >= seuil]),
            coords=point,
        )

    return {
        "arret": meilleur,
        "score": round(note, 3),
        "valide": note >= MIN_SCORE,
        "place": place(max(MIN_SCORE, note - TOLERANCE)),
        "large": place(MIN_SCORE),
        "notes": notes,
        "par_son_nom": par_son_nom,
    }


def _directs_comme_v1(trips: list[Trip], dep: dict, arr: dict) -> list[Trip]:
    """Le filtre de ``find_line`` : la note d'une ligne est celle de son moins bon
    arrêt, et on garde les lignes à moins de TOLERANCE de la meilleure.

    Aucune ligne ne relie Liberté 5 à un arrêt nommé Guédiawaye, mais Tata 78 va à
    Golf, dans ce département.  Et « Yoff » exact écarte les lignes de Grand Yoff.
    """

    def note(trip: Trip) -> float:
        leg = trip.legs[0]
        return min(
            dep["notes"].get(leg.board_stop, 0.0),
            arr["notes"].get(leg.alight_stop, 0.0),
        )

    def somme(trip: Trip) -> float:
        leg = trip.legs[0]
        return dep["notes"].get(leg.board_stop, 0.0) + arr["notes"].get(
            leg.alight_stop, 0.0
        )

    bus = [trip for trip in trips if trip.legs]
    if not bus:
        return []
    # Sur chaque ligne, le meilleur arrêt seulement (``_meilleur`` de v1), jamais
    # le plus rapide : Tata 62 va à Colobane, on ne descend pas à Fass parce que
    # c'est plus tôt sur le parcours.
    meilleure_somme: dict = {}
    for trip in bus:
        meilleure_somme[trip.line_combo] = max(
            meilleure_somme.get(trip.line_combo, 0.0), somme(trip)
        )
    bus = [
        trip for trip in bus if somme(trip) >= meilleure_somme[trip.line_combo]
    ]
    seuil = max(note(trip) for trip in bus) - TOLERANCE
    gardes = keep_sensible_trips([trip for trip in bus if note(trip) >= seuil])
    # Règle 1 de v1 : une ligne trouvée par le nom du lieu passe avant une ligne
    # trouvée seulement par la position, puis la plus rapide.  Sinon le « Stade Amadou
    # Barry », voisin de Guédiawaye, passait devant les arrêts qui portent ce nom.
    def par_nom(trip: Trip) -> int:
        leg = trip.legs[0]
        return int(leg.board_stop in dep["par_son_nom"]) + int(
            leg.alight_stop in arr["par_son_nom"]
        )

    classes = sorted(rank_trips(gardes), key=lambda trip: -par_nom(trip))
    return remove_dominated_trips(classes, _NETWORK)


def _resultat_vide(depart: str, arrivee: str, dep: dict, arr: dict) -> dict:
    return {
        "found": False,
        "depart": depart,
        "depart_matched": dep["arret"],
        "depart_score": dep["score"],
        "depart_valide": dep["valide"],
        "arrivee": arrivee,
        "arrivee_matched": arr["arret"],
        "arrivee_score": arr["score"],
        "arrivee_valide": arr["valide"],
        "lignes": [],
        "correspondances": [],
        "trajets_2": [],
        "a_pied": None,
    }


def chercher_v2(
    matcher,
    depart: str,
    arrivee: str,
    compagnies: set[str] | None = None,
) -> dict:
    """Le trajet au format de ``StopsMatcher.find_line``, calculé par v2.

    ``matcher`` (le ``StopsMatcher`` de v1) résout les lieux ; v2 ne cherche que
    le chemin.  Les trajets directs vont dans ``lignes``, ceux à un changement
    dans ``correspondances``, ceux à deux changements dans ``trajets_2``, et la
    marche seule dans ``a_pied``.  Chaque ligne et chaque trajet portent aussi
    ``minutes`` (total arrondi).
    """

    depart, arrivee = depart or "", arrivee or ""
    dep = _resoudre(matcher, depart)
    arr = _resoudre(matcher, arrivee)
    resultat = _resultat_vide(depart, arrivee, dep, arr)

    # Lieu non reconnu par GuindiMa : on ne devine pas, MoteurV2 rendra v1.
    if not dep["valide"] or not arr["valide"]:
        return resultat

    operateur = (
        next(iter(compagnies))
        if compagnies is not None and len(compagnies) == 1
        else None
    )
    surs = _arrets_surs(matcher)

    def chercher(cle: str, direct_only: bool = False) -> list[Trip]:
        # En direct seul, tous les bus : c'est _directs_comme_v1 qui les trie.
        # Toute autre erreur remonte à MoteurV2.find_line, qui la journalise avant
        # le repli v1.  L'avaler ici ferait passer un moteur cassé pour un moteur
        # juste : avec v2 en panne, les tests affichaient 274/274 grâce au repli.
        try:
            return _ENGINE.find_trips(
                depart,
                arrivee,
                max_trips=100_000 if direct_only else MAX_TRIPS,
                operator=operateur,
                origin_place=dep[cle],
                destination_place=arr[cle],
                nearby_stop_ok=surs.__contains__,
                direct_only=direct_only,
            )
        except (PlaceNotFoundError, NoRouteFoundError):
            return []

    # Comme v1 : une ligne directe entre arrêts valides passe avant un changement.
    # Le trajet à pied, lui, n'est proposé que s'il bat le bus (voir find_trips).
    larges = chercher("large", direct_only=True)
    directs = _directs_comme_v1(larges, dep, arr)
    trips = (
        [trip for trip in larges if not trip.legs][:1] + directs
        if directs
        else chercher("place")
    )

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
            lignes.append(_direct(trip))
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
            "depart_matched": lignes[0]["monte_a"] if lignes else dep["arret"],
            "arrivee_matched": lignes[0]["descend_a"] if lignes else arr["arret"],
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
        # Calculé une fois pour toutes, avant la première requête.
        _arrets_surs(repli)

    def __getattr__(self, nom: str):
        return getattr(self._repli, nom)

    def find_line(
        self, depart: str, arrivee: str, compagnies: set[str] | None = None
    ) -> dict:
        try:
            resultat = chercher_v2(self._repli, depart, arrivee, compagnies)
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
