"""Trouve les lignes de bus qui relient deux lieux de Dakar, arrêt par arrêt.

Données : data/lignes_dakar.csv (lignes et terminus officiels DDD et AFTU) et
data/itineraires_dakar.csv (arrêts de chaque ligne, dans l'ordre), construits
par data/sources/build_dataset.py.

Une ligne convient si l'un de ses arrêts correspond au départ et un autre à
l'arrivée : les deux lieux n'ont plus besoin d'être ses terminus. Le sens est
déduit de l'ordre des arrêts. Sans ligne directe, on cherche un trajet avec une
correspondance : deux lignes qui passent par un même arrêt.
"""

from __future__ import annotations

import csv
from pathlib import Path

try:  # import à plat (app.py, Streamlit) ou en paquet
    from matching.geo import LieuxGeo, distance_metres
    from matching.lieux import VOIES, _jetons, jetons, joli, score
except ImportError:  # pragma: no cover
    from .geo import LieuxGeo, distance_metres
    from .lieux import VOIES, _jetons, jetons, joli, score

DATA = Path(__file__).resolve().parents[2] / "data"
LIGNES_CSV = DATA / "lignes_dakar.csv"
ITINERAIRES_CSV = DATA / "itineraires_dakar.csv"

# En dessous, l'arrêt n'est pas considéré comme le lieu demandé.
MIN_SCORE = 0.6
# Lignes gardées : celles dont la correspondance la plus faible (départ ou
# arrivée) est à moins de cet écart de la meilleure. « Yoff » exact écarte ainsi
# les lignes qui ne passent qu'à « Grand Yoff ».
TOLERANCE = 0.15
# Plafond global de l'affichage, comme la voix (tts.speak.MAX_POSSIBILITES) :
# la réponse orale ne doit ni oublier une carte ni en annoncer une qui n'est pas
# affichée. Les correspondances restent plus rares : deux trajets en deux bus
# suffisent, et le troisième calculé n'était pas proposé aux usagers.
MAX_LIGNES = 3
MAX_CORRESPONDANCES = 2


class StopsMatcher:
    """Charge les lignes et leurs arrêts, puis cherche les lignes d'un trajet."""

    def __init__(self, lignes_csv: str | Path = LIGNES_CSV, itineraires_csv: str | Path = ITINERAIRES_CSV) -> None:
        with open(lignes_csv, newline="", encoding="utf-8") as f:
            self.lignes = {(l["compagnie"], l["ligne"]): l for l in csv.DictReader(f)}
        self.arrets: dict[tuple[str, str], list[str]] = {cle: [] for cle in self.lignes}
        with open(itineraires_csv, newline="", encoding="utf-8") as f:
            for rangee in sorted(csv.DictReader(f), key=lambda r: int(r["ordre"])):
                self.arrets.setdefault((rangee["compagnie"], rangee["ligne"]), []).append(rangee["arret"])
        self.tous_les_arrets = sorted({a for arrets in self.arrets.values() for a in arrets})
        # Pour les correspondances : la forme de chaque arrêt, sans les voies
        # (on ne change pas de bus « sur l'autoroute »).
        # Sans les alias : on ne change pas de bus entre Palais 1 et Palais 2,
        # même si, pour un départ ou une arrivée, l'un vaut l'autre.
        self.formes: dict[tuple[str, str], list[str]] = {
            cle: [" ".join(_jetons(a)) if (jetons(a) and jetons(a)[0] not in VOIES) else "" for a in arrets]
            for cle, arrets in self.arrets.items()
        }
        # Un lieu dit (Médina, Sandaga, Plateau…) peut désigner un quartier où se
        # trouvent des arrêts dont le nom ne le dit pas : on s'appuie sur leurs
        # positions (data/arrets_geo.csv et data/lieux_geo.csv).
        self.geo = LieuxGeo()

    # ------------------------------------------------------------------ #

    def _distance_arret(self, arret: str, point: tuple[float, float]) -> float:
        """Distance du point au lieu dit, ou l'infini si l'arrêt n'a pas de position."""
        ici = self.geo.point_arret(arret)
        return distance_metres(point, ici) if ici else float("inf")

    def _meilleur(
        self,
        lieu: str,
        arrets: list[str],
        geo_scores: dict[str, float] | None = None,
        point: tuple[float, float] | None = None,
    ) -> tuple[float, int]:
        """Meilleur arrêt de la ligne pour ce lieu : (score, position).

        Le score d'un arrêt est le meilleur de deux : correspondance de nom, ou
        note géographique (l'arrêt est dans le quartier du lieu dit, ou proche de
        son point). À note égale, on conseille l'arrêt le plus proche du point.
        """
        geo_scores = geo_scores or {}
        meilleur = (0.0, -1)
        for position, arret in enumerate(arrets):
            geo = geo_scores.get(arret, 0.0)
            valeur = max(score(lieu, arret), geo)
            if valeur > meilleur[0]:
                meilleur = (valeur, position)
            elif (
                valeur > 0
                and valeur == meilleur[0]
                and point is not None
                and geo == valeur
                and self._distance_arret(arret, point) < self._distance_arret(arrets[meilleur[1]], point)
            ):
                meilleur = (valeur, position)
        return meilleur

    def _reconnu(self, lieu: str, geo_scores: dict[str, float] | None = None) -> tuple[str, float]:
        """L'arrêt du réseau le plus proche du lieu demandé, et son score."""
        geo_scores = geo_scores or {}
        meilleur = ("", 0.0)
        for arret in self.tous_les_arrets:
            valeur = max(score(lieu, arret), geo_scores.get(arret, 0.0))
            if valeur > meilleur[1]:
                meilleur = (arret, valeur)
        return meilleur

    def _troncon(self, cle: tuple[str, str], i_dep: int, i_arr: int) -> dict:
        """Une ligne parcourue de l'arrêt i_dep à l'arrêt i_arr."""
        info, arrets = self.lignes[cle], self.arrets[cle]
        direct = i_dep < i_arr
        # Tous les arrêts réellement parcourus, de la montée à la descente, dans
        # le sens du trajet : le voyageur peut monter à n'importe lequel d'entre
        # eux. On garde monte_a / descend_a tels quels (l'arrêt conseillé), mais
        # on ne laisse pas croire que c'est le seul possible.
        positions = range(i_dep, i_arr + 1) if direct else range(i_dep, i_arr - 1, -1)
        arrets_trajet = [joli(arrets[i]) for i in positions]
        return {
            "compagnie": info["compagnie"],
            "ligne": info["ligne"],
            "categorie": info.get("categorie", ""),
            "depart": info["terminus_a"] if direct else info["terminus_b"],
            "arrivee": info["terminus_b"] if direct else info["terminus_a"],
            "sens": "direct" if direct else "inverse",
            "monte_a": joli(arrets[i_dep]),
            "descend_a": joli(arrets[i_arr]),
            "arrets_trajet": arrets_trajet,
        }

    def _correspondances(
        self,
        depart: str,
        arrivee: str,
        cles: list[tuple[str, str]],
        dep_geo: dict[str, float],
        arr_geo: dict[str, float],
        dep_point: tuple[float, float] | None,
        arr_point: tuple[float, float] | None,
    ) -> list[dict]:
        """Trajets en deux bus quand aucune ligne ne relie directement les deux lieux.

        On ne parcourt que `cles` : restreindre la recherche à une compagnie se
        fait donc à la source, pas en filtrant un résultat déjà calculé.
        """
        cotes_dep, cotes_arr = [], []
        for cle in cles:
            arrets = self.arrets[cle]
            s, i = self._meilleur(depart, arrets, dep_geo, dep_point)
            if s >= MIN_SCORE:
                cotes_dep.append((s, cle, i))
            s, i = self._meilleur(arrivee, arrets, arr_geo, arr_point)
            if s >= MIN_SCORE:
                cotes_arr.append((s, cle, i))
        if not cotes_dep or not cotes_arr:
            return []
        seuil_dep = max(c[0] for c in cotes_dep) - TOLERANCE
        seuil_arr = max(c[0] for c in cotes_arr) - TOLERANCE

        trajets = []
        for s_dep, cle_a, i_dep in cotes_dep:
            if s_dep < seuil_dep:
                continue
            for s_arr, cle_b, i_arr in cotes_arr:
                if s_arr < seuil_arr or cle_a == cle_b:
                    continue
                positions_b: dict[str, int] = {}
                for j, f in enumerate(self.formes[cle_b]):
                    if f and j != i_arr:
                        positions_b.setdefault(f, j)
                meilleur = None
                for x, f in enumerate(self.formes[cle_a]):
                    if not f or x == i_dep or f not in positions_b:
                        continue
                    y = positions_b[f]
                    cout = abs(x - i_dep) + abs(i_arr - y)
                    if meilleur is None or cout < meilleur[0]:
                        meilleur = (cout, x, y)
                if meilleur:
                    cout, x, y = meilleur
                    trajets.append(
                        (-(s_dep + s_arr), cout, cle_a, cle_b, {
                            "etape_1": self._troncon(cle_a, i_dep, x),
                            "etape_2": self._troncon(cle_b, y, i_arr),
                            "changement": joli(self.arrets[cle_a][x]),
                        })
                    )
        trajets.sort(key=lambda t: t[:4])
        sortie, vus = [], set()
        for *_, trajet in trajets:
            cle = (trajet["etape_1"]["ligne"], trajet["etape_1"]["compagnie"],
                   trajet["etape_2"]["ligne"], trajet["etape_2"]["compagnie"])
            if cle not in vus:
                vus.add(cle)
                sortie.append(trajet)
            if len(sortie) == MAX_CORRESPONDANCES:
                break
        return sortie

    def find_line(
        self, depart: str, arrivee: str, compagnies: set[str] | None = None
    ) -> dict:
        """Lignes reliant depart et arrivee, la meilleure en tête.

        Chaque ligne renvoyée porte : compagnie, ligne, categorie, depart et
        arrivee (les terminus dans le sens du trajet), sens, monte_a et
        descend_a (les arrêts conseillés pour monter et descendre) et
        arrets_trajet (tous les arrêts parcourus, de la montée à la descente).
        Sans ligne directe, « correspondances » propose des trajets en deux bus.

        `compagnies` restreint la recherche à ces compagnies, dès la sélection
        des lignes candidates : une correspondance trouvée ainsi a forcément ses
        deux bus dans l'ensemble autorisé. None cherche dans tout le réseau.
        """
        depart, arrivee = depart or "", arrivee or ""
        cles = [cle for cle in self.arrets if compagnies is None or cle[0] in compagnies]
        # Le nom passe avant la position : si un arrêt porte déjà le nom du lieu,
        # on ne lui ajoute pas les arrêts seulement proches (« Liberté 5 » ne doit
        # pas ramener « Liberté 6 »). La correspondance de quartier/commune, elle,
        # reste utile (Médina → Avenue Blaise Diagne).
        _, dep_nom = self._reconnu(depart)
        _, arr_nom = self._reconnu(arrivee)
        dep_geo = self.geo.scores_lieu(depart, proximite=dep_nom < MIN_SCORE)
        arr_geo = self.geo.scores_lieu(arrivee, proximite=arr_nom < MIN_SCORE)
        dep_point = self.geo.point(depart)
        arr_point = self.geo.point(arrivee)
        depart_arret, depart_score = self._reconnu(depart, dep_geo)
        arrivee_arret, arrivee_score = self._reconnu(arrivee, arr_geo)
        depart_valide = depart_score >= MIN_SCORE
        arrivee_valide = arrivee_score >= MIN_SCORE

        candidates = []
        if depart_valide and arrivee_valide:
            for cle in cles:
                arrets = self.arrets[cle]
                s_dep, i_dep = self._meilleur(depart, arrets, dep_geo, dep_point)
                s_arr, i_arr = self._meilleur(arrivee, arrets, arr_geo, arr_point)
                if s_dep < MIN_SCORE or s_arr < MIN_SCORE or i_dep == i_arr:
                    continue
                # Combien des deux arrêts conseillés portent vraiment le nom du
                # lieu : une ligne trouvée par le nom passe avant une ligne
                # trouvée seulement par la position (règle 1).
                par_nom = int(score(depart, arrets[i_dep]) >= MIN_SCORE) + int(
                    score(arrivee, arrets[i_arr]) >= MIN_SCORE
                )
                candidates.append((min(s_dep, s_arr), par_nom, s_dep + s_arr, abs(i_arr - i_dep), cle, i_dep, i_arr))

        lignes = []
        if candidates:
            meilleur = max(c[0] for c in candidates)
            gardees = [c for c in candidates if c[0] >= meilleur - TOLERANCE]
            # Meilleure correspondance d'abord, puis les lignes trouvées par le
            # nom du lieu avant celles trouvées seulement par la position, puis
            # la ligne, enfin le trajet le plus court en arrêts.
            gardees.sort(key=lambda c: (-c[0], -c[1], -c[2], c[4], c[3]))
            lignes = [self._troncon(cle, i_dep, i_arr) for *_, cle, i_dep, i_arr in gardees[:MAX_LIGNES]]

        correspondances = []
        if not lignes and depart_valide and arrivee_valide:
            correspondances = self._correspondances(depart, arrivee, cles, dep_geo, arr_geo, dep_point, arr_point)

        return {
            "found": bool(lignes),
            "depart": depart,
            "depart_matched": lignes[0]["monte_a"] if lignes else depart_arret,
            "depart_score": round(depart_score, 3),
            "depart_valide": depart_valide,
            "arrivee": arrivee,
            "arrivee_matched": lignes[0]["descend_a"] if lignes else arrivee_arret,
            "arrivee_score": round(arrivee_score, 3),
            "arrivee_valide": arrivee_valide,
            "lignes": lignes,
            "correspondances": correspondances,
        }

    def find_line_compagnie(
        self, depart: str, arrivee: str, compagnie: str
    ) -> tuple[dict, bool]:
        """Trajet réservé à une compagnie, avec repli sur tout le réseau.

        Dans l'ordre : les lignes directes de la compagnie, puis les
        correspondances dont LES DEUX bus sont de cette compagnie (calculées sur
        ses seules lignes), et seulement si rien de tout cela n'existe, la
        recherche complète. Renvoie (résultat, exacte) : `exacte` vaut True quand
        la compagnie dessert le trajet par elle-même, False quand on est retombé
        sur les autres compagnies.
        """
        restreint = self.find_line(depart, arrivee, compagnies={compagnie})
        if restreint["found"] or restreint["correspondances"]:
            return restreint, True
        return self.find_line(depart, arrivee), False
