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
from .network import Network, haversine_m
from functools import lru_cache

from .corrections import STOP_NAME_ALIASES
from .places import PlaceIndex, normalize_name, terminus_forms
from .router import (
    Leg,
    NoRouteFoundError,
    ACCESS_WALK_RADIUS_M,
    PLACE_STOP_RADIUS_M,
    PlaceNotFoundError,
    ResolvedPlace,
    RouteEngine,
    Trip,
    direct_rank_key,
    keep_sensible_trips,
    rank_trips,
    remove_dominated_trips,
)

try:  # import à plat (app.py) ou en paquet
    from matching.geo import nom_generique, nom_rue_numerotee
    from matching.lieux import AEROPORT_LSS, AIBD, aeroport_ambigu, joli, relie, score
    from matching.lieux import nom_exact as cle_exacte
    from matching.stops_matcher import MIN_SCORE, TOLERANCE
except ImportError:  # pragma: no cover
    from ..matching.geo import nom_generique, nom_rue_numerotee
    from ..matching.lieux import AEROPORT_LSS, AIBD, aeroport_ambigu, joli, relie, score
    from ..matching.lieux import nom_exact as cle_exacte
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
        # Les noms du réseau, non embellis : l'écran montre « joli » (accents,
        # majuscules), mais mesurer la distance lieu→arrêt exige le nom exact
        # que _NETWORK.coords sait lire.
        "monte_a_reseau": leg.board_stop,
        "descend_a_reseau": leg.alight_stop,
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


def _note_du_nom(lieu: str, arret: str, liens: bool = True) -> float:
    """La note de v1, ou celle d'un lieu que désigne ce terminus.

    Sans cela, « Terminus liberté 5 (Dieuppeul) » ne valait que 0,83 pour « Liberté 5 »,
    et les Dem Dikk 10 et 13 disparaissaient devant la 6 (« Liberté 5 », 1,0).
    """

    return max(
        (score(lieu, nom, liens) for nom in (arret, *terminus_forms(arret))),
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

    def reseau(arret: str) -> list[str]:
        """Les noms v2 de cet arrêt qui méritent sa note.

        Un arrêt AFTU relié à un lieu (« Avenue Cheikh Anta Diop » -> UCAD) ne
        transmet sa note qu'aux noms écrits pareil : le réseau v2 range sous le
        même nom normalisé « Av Cheikh Anta Diop », arrêt des Tata 42 (Ouakam)
        et 47, que rien ne relie à l'UCAD.
        """
        noms = _arrets_du_reseau(arret)
        if not relie(arret) or notes_v1[arret] <= max(
            _note_du_nom(lieu, arret, liens=False), geo_scores.get(arret, 0.0)
        ):
            return noms
        return [nom for nom in noms if cle_exacte(nom) == cle_exacte(arret)]

    def vers_reseau(arrets: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(nom for arret in arrets for nom in reseau(arret)))

    notes: dict[str, float] = {}
    par_son_nom: set[str] = set()
    for arret in tries:
        for nom in reseau(arret):
            notes.setdefault(nom, notes_v1[arret])
            if _note_du_nom(lieu, arret) >= MIN_SCORE:
                par_son_nom.add(nom)
    # Le point connu des CSV seulement : il sert à mesurer le vol d'oiseau, jamais
    # à décider où monter, et ne doit pas dépendre du réseau.
    # Un lieu qui est exactement un arrêt prend la position de cet arrêt sur le réseau :
    # celle de arrets_geo.csv peut être périmée (AIBD, placé à Grand Yoff).
    point = None if note >= 1.0 else matcher.geo.point_connu(lieu)

    # Le point fiable du lieu, pour juger si l'arrêt proposé est vraiment près de
    # lui (message vague sinon). Un lieu nommé exactement prend la position de
    # l'arrêt sur le réseau ; un quartier prend son point de lieux_geo.csv. Jamais
    # d'appel réseau ici : pas de position vaut mieux qu'une position devinée.
    # Un lieu qui porte exactement le nom d'un arrêt se définit par ces arrêts.
    # - point fiable : un de ces arrêts en position « bonne » ; sinon le point
    #   de lieux_geo.csv, s'il tombe à moins de 1 km de l'un d'eux (« Yoff » y
    #   est posé sur l'arrêt Grand Yoff, 2,8 km plus au sud) ; sinon la position
    #   estimée de l'arrêt. « Rond point Sandaga », estimé à 1,9 km du marché,
    #   ne sert donc jamais de point à lui seul.
    exacts = (
        [a for a in tries if _note_du_nom(lieu, a) >= 1.0]
        if meilleur and note >= 1.0
        else []
    )
    positions_exactes = [
        (nom, _NETWORK.coords(nom))
        for nom in _vers_reseau(exacts)
        if _NETWORK.coords(nom) is not None
    ]
    point_sur = next(
        (
            coords
            for nom, coords in positions_exactes
            if _NETWORK.stop_confidence.get(nom) == "bonne"
        ),
        None,
    )
    if point_sur is None:
        point_csv = matcher.geo.point_connu(lieu)
        if point_csv is not None and (
            not positions_exactes
            or any(
                haversine_m(point_csv, coords) <= ACCORD_POINT_LIEU_M
                for _, coords in positions_exactes
            )
        ):
            point_sur = point_csv
        elif positions_exactes:
            point_sur = positions_exactes[0][1]

    # Un lieu exact ne prend un arrêt par la géographie seule (commune,
    # quartier) que s'il est à distance de marche de l'un de ses arrêts : la
    # commune de Yoff couvre la Foire et les HLM Grand Yoff, et la Tata 2, qui
    # ne passe jamais à Yoff (trace AFTU à 2,2 km), était proposée depuis
    # « Route HLM Grand Médine ».
    reperes = [coords for _, coords in positions_exactes]
    if point_sur is not None:
        reperes.append(point_sur)
    if note >= 1.0 and reperes:
        for arret in tries:
            if _note_du_nom(lieu, arret) >= MIN_SCORE or notes_v1[arret] <= 0:
                continue
            positions = [
                _NETWORK.coords(nom)
                for nom in _arrets_du_reseau(arret)
                if _NETWORK.coords(nom) is not None
            ]
            if not positions or min(
                haversine_m(repere, position)
                for repere in reperes
                for position in positions
            ) > ACCESS_WALK_RADIUS_M:
                notes_v1[arret] = 0.0
        tries = sorted(notes_v1, key=lambda arret: -notes_v1[arret])

    def place(seuil: float) -> ResolvedPlace:
        # Pas de restriction ici : un arrêt loin du lieu dit garde sa ligne. La
        # carte, elle, passe en message vague au-delà de 600 m (_vague).
        return ResolvedPlace(
            stops=vers_reseau([a for a in tries if notes_v1[a] >= seuil]),
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
        "point_sur": point_sur,
        # Arrêts qui portent le nom exact du lieu : « Terminus Liberté 5
        # (Dieuppeul) » est Liberté 5, même à 1,3 km de l'autre arrêt Liberté 5.
        "nom_exact": {
            nom
            for arret in tries
            if _note_du_nom(lieu, arret) >= 1.0
            for nom in _arrets_du_reseau(arret)
        },
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
    # Entre bus directs, le plus rapide (marche + bus) d'abord, tant qu'on monte à
    # moins de 10 min à pied.  Le nom de l'arrêt ne prime plus : Dem Dikk 2 passait
    # devant Tata 55 pour Sandaga -> Pikine parce qu'elle s'arrête à « Sandaga ».
    classes = sorted(rank_trips(gardes), key=direct_rank_key)
    return remove_dominated_trips(classes, _NETWORK)


def _equilibrer(
    trajets: list[dict],
    compagnies_du_trajet,
    filtre_actif: bool,
) -> list[dict]:
    """Le meilleur Dem Dikk puis le meilleur Tata d'abord, le reste ensuite.

    « Tous » ne doit pas montrer trois Tata qui se suivent quand Dem Dikk a
    aussi sa ligne : sur Yoff -> Guédiawaye, la plus rapide n'était que Tata et
    le choix de l'usager disparaissait. Un filtre de compagnie actif, lui, n'a
    rien à équilibrer (il n'y a qu'un opérateur par définition).
    """

    if filtre_actif or len(trajets) <= 1:
        return trajets
    de_dem_dikk = next(
        (t for t in trajets if compagnies_du_trajet(t) == {"Dakar Dem Dikk"}), None
    )
    de_tata = next(
        (t for t in trajets if compagnies_du_trajet(t) == {"Tata AFTU"}), None
    )
    if de_dem_dikk is None and de_tata is None:
        return trajets
    ordre = [bus for bus in (de_dem_dikk, de_tata) if bus is not None]
    reste = [
        t for t in trajets if t is not de_dem_dikk and t is not de_tata
    ]
    return ordre + reste


# Une option bien plus lente que la meilleure n'aide personne : Yoff -> Sandaga
# montrait Tata 3 (88 min, sans arrêt de descente) à côté de DDD 8 (40 min).
# Écartée seulement si elle est à la fois 1,8 fois plus longue ET 30 min de plus :
# 15 min contre 30 min reste un vrai choix.
RAPPORT_TROP_LENT = 1.8
ECART_TROP_LENT_MIN = 30


def _sans_les_trop_lents(
    lignes: list[dict],
    correspondances: list[dict],
    trajets_2: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Retire les options bien plus lentes que la meilleure, tous types confondus.

    Sous un filtre Tata ou Dem Dikk, la meilleure est de la même compagnie et
    n'est jamais retirée : l'option seule de sa compagnie reste donc affichée.
    Sous « Tous », une compagnie peut disparaître si toutes ses options sont
    bien plus lentes — c'est voulu (Tata 3 à 88 min contre DDD 8 à 40 min).
    """
    toutes = lignes + correspondances + trajets_2
    minutes = [t["minutes"] for t in toutes if t.get("minutes") is not None]
    if len(minutes) <= 1:
        return lignes, correspondances, trajets_2
    meilleure = min(minutes)

    def trop_lent(trajet: dict) -> bool:
        duree = trajet.get("minutes")
        return (
            duree is not None
            and duree > RAPPORT_TROP_LENT * meilleure
            and duree - meilleure > ECART_TROP_LENT_MIN
        )

    garder = {id(t) for t in toutes if not trop_lent(t)}
    return (
        [t for t in lignes if id(t) in garder],
        [t for t in correspondances if id(t) in garder],
        [t for t in trajets_2 if id(t) in garder],
    )


def _vague(lieu: dict, arret: str) -> bool:
    """Arrêt non garanti près du lieu dit : la carte doit le dire.

    Un arrêt qui porte le nom exact du lieu n'est jamais vague. Sinon, sans
    point fiable pour le lieu (« Keur Massar » absent des CSV), ou avec un
    arrêt à plus de 600 m (arrêt sans position, arrêt voisin trop loin), on ne
    prétend pas connaître l'arrêt exact.
    """

    if arret in lieu.get("nom_exact", ()):
        return False
    point = lieu.get("point_sur")
    if point is None:
        return True
    coords = _NETWORK.coords(arret)
    if coords is None:
        return True
    return haversine_m(point, coords) > PLACE_STOP_RADIUS_M


# Le point d'un lieu (lieux_geo.csv) n'est cru que s'il est à 1 km au plus
# d'un arrêt du même nom.
ACCORD_POINT_LIEU_M = 1_000.0

# Un changement ne recule jamais vers le départ de plus de 1 km : Maristes ->
# Rufisque montait vers Liberté 6 (plus à l'ouest) pour reprendre la 213
# dans l'autre sens.
RECUL_MAX_M = 1_000.0


def _position_sure(leg: Leg, arret: str) -> tuple[float, float] | None:
    """La position de cet arrêt sur la ligne du tronçon, si elle est mesurée."""

    ligne = _NETWORK.lines.get((leg.operator, leg.line))
    if ligne is None or arret not in ligne.stops:
        return None
    index = ligne.stops.index(arret)
    if not _NETWORK.position_sure(ligne, index):
        return None
    return _NETWORK.position_on_line(ligne, index)


def _position_connue(leg: Leg, arret: str) -> tuple[float, float] | None:
    """La position de cet arrêt sur la ligne du tronçon, même devinée."""

    ligne = _NETWORK.lines.get((leg.operator, leg.line))
    if ligne is None or arret not in ligne.stops:
        return None
    return _NETWORK.position_on_line(ligne, ligne.stops.index(arret))


def _dans_le_lieu(lieu: dict, leg: Leg, arret: str) -> bool:
    """Vrai si cet arrêt fait partie du lieu dit (nom, ou position sûre à 600 m)."""

    if arret in lieu.get("nom_exact", ()) or arret in lieu.get("par_son_nom", ()):
        return True
    point, position = lieu.get("point_sur"), _position_sure(leg, arret)
    return (
        point is not None
        and position is not None
        and haversine_m(point, position) <= PLACE_STOP_RADIUS_M
    )


def _changements_coherents(trip: Trip, dep: dict, arr: dict) -> bool:
    """Un trajet avec changement qui avance vraiment.

    - jamais un bus de plus une fois arrivé : « Marché Colobane Rufisque » est
      déjà Rufisque, le 3e bus vers la Gare de Rufisque était de trop ;
    - jamais un premier bus pour rien : changer dans le lieu de départ veut dire
      que le 2e bus passait déjà là ;
    - jamais de recul : chaque changement (aux positions sûres) reste à peu près
      aussi près de l'arrivée que le précédent.
    """

    if len(trip.legs) < 2:
        return True
    for leg in trip.legs[:-1]:
        if _dans_le_lieu(arr, leg, leg.alight_stop):
            return False
    for leg in trip.legs[1:]:
        if _dans_le_lieu(dep, leg, leg.board_stop):
            return False

    cible = arr.get("point_sur") or _position_sure(trip.legs[-1], trip.legs[-1].alight_stop)
    if cible is None:
        return True
    precedent = dep.get("point_sur") or _position_sure(trip.legs[0], trip.legs[0].board_stop)
    for leg in trip.legs[1:]:
        # Le sens se juge avec la position connue, même approximative : la
        # marge de 1 km absorbe l'imprécision (« Rond Point Liberté 6 » de la
        # 213 n'est placé que par Nominatim, mais il est bien à l'ouest).
        position = _position_connue(leg, leg.board_stop)
        if position is None:
            continue
        if precedent is not None and (
            haversine_m(position, cible) > haversine_m(precedent, cible) + RECUL_MAX_M
        ):
            return False
        precedent = position
    return True


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
    trips = [trip for trip in trips if _changements_coherents(trip, dep, arr)]
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

    # « Tous » montre les deux compagnies : le meilleur Dem Dikk puis le
    # meilleur Tata passent devant le reste, qui suit l'ordre du temps. Le
    # plafond d'affichage vient après, sur la liste équilibrée.
    filtre_actif = compagnies is not None
    lignes, correspondances, trajets_2 = _sans_les_trop_lents(
        lignes, correspondances, trajets_2
    )
    lignes = _equilibrer(lignes, lambda t: {t["compagnie"]}, filtre_actif)
    correspondances = _equilibrer(
        correspondances,
        lambda t: {t["etape_1"]["compagnie"], t["etape_2"]["compagnie"]},
        filtre_actif,
    )

    lignes = lignes[:MAX_LIGNES]
    correspondances = correspondances[:MAX_CORRESPONDANCES]
    trajets_2 = trajets_2[:MAX_TRAJETS_2]

    # L'arrêt de montée / descente n'est garanti près du lieu dit que si le
    # point fiable le confirme : sinon la carte passe en message vague. Seuls
    # les deux bouts du trajet portent un lieu dit ; le changement de bus, lui,
    # est l'arrêt réel du réseau.
    for ligne in lignes:
        ligne["monte_a_vague"] = _vague(dep, ligne["monte_a_reseau"])
        ligne["descend_a_vague"] = _vague(arr, ligne["descend_a_reseau"])
    for corr in correspondances:
        corr["etape_1"]["monte_a_vague"] = _vague(
            dep, corr["etape_1"]["monte_a_reseau"]
        )
        corr["etape_2"]["descend_a_vague"] = _vague(
            arr, corr["etape_2"]["descend_a_reseau"]
        )
    for trajet in trajets_2:
        if trajet["etapes"]:
            trajet["etapes"][0]["monte_a_vague"] = _vague(
                dep, trajet["etapes"][0]["monte_a_reseau"]
            )
            trajet["etapes"][-1]["descend_a_vague"] = _vague(
                arr, trajet["etapes"][-1]["descend_a_reseau"]
            )
    # La voix lit le lieu de descente : pour un arrêt vague, elle dira le lieu
    # que l'usager a nommé, jamais l'arrêt lointain.
    for etape in list(lignes) + [
        c["etape_2"] for c in correspondances
    ] + [t["etapes"][-1] for t in trajets_2 if t["etapes"]]:
        etape["lieu_arrivee_dit"] = arrivee

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


# « aéroport » seul : les deux aéroports de Dakar, dans cet ordre, avec le nom
# affiché au-dessus de chaque possibilité.
AEROPORTS_POSSIBLES = (
    (AIBD, "Aéroport Blaise Diagne (AIBD, Diass)"),
    (AEROPORT_LSS, "Ancien aéroport Léopold Sédar Senghor (Yoff)"),
)


def _premiere_option(resultat: dict) -> tuple[str, dict] | None:
    """La meilleure possibilité d'un résultat : ligne directe, changement(s), ou marche."""

    for cle, genre in (
        ("lignes", "ligne"),
        ("correspondances", "correspondance"),
        ("trajets_2", "trajet_2"),
    ):
        if resultat.get(cle):
            return genre, resultat[cle][0]
    if resultat.get("a_pied"):
        return "a_pied", resultat["a_pied"]
    return None


def deux_aeroports(find_line, depart: str, arrivee: str, compagnies=None) -> dict | None:
    """« aéroport » seul est ambigu : la meilleure possibilité vers CHACUN des deux.

    L'AIBD (Diass) et l'ancien aéroport Léopold Sédar Senghor (Yoff, arrêt
    « Aéroport » de la Tata 35) portent le même mot : deviner serait répondre
    faux une fois sur deux. On cherche le trajet vers chacun avec
    ``find_line`` et on garde la meilleure possibilité de chaque : à l'écran,
    deux blocs titrés ; à la voix, « Walla, » entre les deux. Le résultat
    garde le format habituel (``lignes``, ``correspondances``, ``trajets_2``),
    plus ``lieux_possibles`` : une entrée par aéroport, dans l'ordre affiché.
    None si aucun des deux côtés n'est « aéroport » seul.
    """

    cote_arrivee = aeroport_ambigu(arrivee)
    if not cote_arrivee and not aeroport_ambigu(depart):
        return None
    possibles = []
    for nom, titre in AEROPORTS_POSSIBLES:
        dep, arr = (depart, nom) if cote_arrivee else (nom, arrivee)
        sous = find_line(dep, arr, compagnies)
        option = _premiere_option(sous)
        if option is None:
            continue
        genre, element = option
        possibles.append(
            {
                "lieu": nom,
                "titre": titre,
                "genre": genre,
                "option": element,
                "depart": dep,
                "arrivee": arr,
                "resultat": sous,
            }
        )
    if not possibles:
        return None
    if len(possibles) == 1:
        # Un seul aéroport desservi (filtre Tata : aucune Tata ne va à l'AIBD) :
        # on le dit par son titre, sans faire croire qu'il n'y en a qu'un.
        seul = dict(possibles[0]["resultat"])
        seul["lieux_possibles"] = possibles
        return seul
    resultat = dict(possibles[0]["resultat"])
    resultat.update(
        {
            "found": True,
            "depart": depart,
            "arrivee": arrivee,
            "lignes": [p["option"] for p in possibles if p["genre"] == "ligne"],
            "correspondances": [p["option"] for p in possibles if p["genre"] == "correspondance"],
            "trajets_2": [p["option"] for p in possibles if p["genre"] == "trajet_2"],
            "a_pied": next((p["option"] for p in possibles if p["genre"] == "a_pied"), None),
            "lieux_possibles": possibles,
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
        ambigu = deux_aeroports(self.find_line, depart, arrivee, compagnies)
        if ambigu is not None:
            return ambigu
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


__all__ = ["MoteurV2", "a_un_trajet", "chercher_v2", "deux_aeroports"]
