"""Positions des lieux dits : quartiers des arrêts et points géocodés.

Sert à la recherche de ligne quand un lieu dit par l'utilisateur (Médina,
Sandaga, Plateau…) ne se retrouve pas dans le nom des arrêts. Deux sources :

* ``data/arrets_geo.csv`` (produit par data/sources/geolocaliser_arrets.py) :
  pour chaque arrêt, sa position, son quartier et sa commune. Les arrêts
  « douteuse » sont ignorés (position non fiable).
* ``data/lieux_geo.csv`` (produit par data/sources/geolocaliser_lieux.py) : la
  position d'un lieu, précalculée pour éviter toute requête réseau sur un lieu
  connu de l'extraction. Un lieu absent y est géocodé une seule fois en direct
  (cache disque, au plus une requête par seconde, même User-Agent).

Candidats pour un lieu : les arrêts dont le quartier ou la commune correspond,
plus ceux à moins de 800 m du point du lieu. La note d'un arrêt proche décroît
avec la distance, si bien que l'arrêt conseillé est le candidat le plus proche.
"""

from __future__ import annotations

import csv
import json
import math
import re
import time
from pathlib import Path

try:  # import à plat (app.py) ou en paquet
    from matching.lieux import FAUX_AMIS, sans_accents
except ImportError:  # pragma: no cover
    from .lieux import FAUX_AMIS, sans_accents

DATA = Path(__file__).resolve().parents[2] / "data"
ARRETS_GEO = DATA / "arrets_geo.csv"
LIEUX_GEO = DATA / "lieux_geo.csv"
ITINERAIRES_CSV = DATA / "itineraires_dakar.csv"
CACHE_LIEUX = DATA / "sources" / "cache_lieux_nominatim.json"

GEOCODE = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GuindiMa-AI/1.0 (cheikhniang159@gmail.com)"
DELAI_SECONDES = 1.0
TIMEOUT = 15
RAYON_METRES = 800.0
# Le nom passe avant la position : une note géographique reste sous 0.75, donc
# toujours sous un arrêt trouvé par son nom (score 1.0, ou ≥ 0.85 après marge).
SCORE_QUARTIER = 0.7
SCORE_PROCHE_MIN = 0.6
SCORE_GEO_MAX = 0.75
CONFIANCE_IGNOREE = {"douteuse"}
# Seule une position de confiance « bonne » sert à la proximité : une position
# « estimee » peut tomber dans le mauvais quartier.
CONFIANCE_PROXIMITE = {"bonne"}

# Un arrêt isolé de tout son voisinage sur une ligne AFTU a une position fausse
# (nom d'arrêt retrouvé ailleurs par homonymie). Les lignes Dem Dikk, tracées sur
# OpenStreetMap, ne sont pas concernées.
SEUIL_VOISIN_METRES = 3000.0
COMPAGNIE_VOISINS = "Tata AFTU"
# « Rue 9 », « Rue 9bis », « Rue 34 » : le nom seul ne dit pas de quel quartier
# il s'agit, la position géocodée n'est donc jamais fiable. Une rue numérotée qui
# porte en plus une localité (« Rue 10 Pikine Ouest ») reste situable.
_RUE_NUMEROTEE = re.compile(r"^rue\s+\d+\s*(?:bis|ter)?$", re.IGNORECASE)


def nom_rue_numerotee(arret: str) -> bool:
    """Vrai si le nom d'arrêt est une rue numérotée seule (« Rue 9 », « Rue 9bis »)."""
    sans_annotation = re.sub(r"\([^)]*\)", " ", str(arret))
    return bool(_RUE_NUMEROTEE.match(normaliser(sans_annotation)))


def _hors_voisinage(
    positions: dict[str, tuple[float, float]],
    bonnes: set[str],
    itineraires_csv: Path,
) -> set[str]:
    """Arrêts « bonne » loin de TOUS leurs voisins connus sur une ligne Tata AFTU.

    Le précédent et le suivant qui ont une position servent de repères : un arrêt
    « bonne » à plus de 3 km de chacun est un homonyme géocodé ailleurs. Un arrêt
    sans voisin connu n'est pas jugé (isolé dans les données, pas forcément faux).
    """
    chemin = Path(itineraires_csv)
    if not chemin.exists():
        return set()
    lignes: dict[tuple[str, str], list[str]] = {}
    with open(chemin, newline="", encoding="utf-8") as f:
        rangees = [
            rangee
            for rangee in csv.DictReader(f)
            if rangee.get("compagnie") == COMPAGNIE_VOISINS
        ]
    for rangee in sorted(rangees, key=lambda r: int(r.get("ordre") or 0)):
        lignes.setdefault((rangee["compagnie"], rangee["ligne"]), []).append(rangee["arret"])
    ecartes: set[str] = set()
    for arrets in lignes.values():
        for i, arret in enumerate(arrets):
            # Un terminus n'a qu'un côté : il peut être loin du dernier arrêt connu
            # (tronçon de ligne long), ce n'est pas un indice d'homonymie.
            if not 0 < i < len(arrets) - 1:
                continue
            if arret not in bonnes:
                continue
            ici = positions.get(arret)
            if ici is None:
                continue
            voisins = [
                positions[arrets[j]]
                for j in (i - 1, i + 1)
                if arrets[j] in positions
            ]
            if voisins and all(
                distance_metres(ici, voisin) > SEUIL_VOISIN_METRES for voisin in voisins
            ):
                ecartes.add(arret)
    return ecartes


def _non_fiables(arrets: dict[str, dict], itineraires_csv: Path) -> set[str]:
    """Arrêts à position non fiable : rues numérotées et isolés sur une ligne AFTU."""
    rues = {arret for arret in arrets if nom_rue_numerotee(arret)}
    positions = {
        arret: info["point"]
        for arret, info in arrets.items()
        if info.get("point") is not None
    }
    bonnes = {
        arret
        for arret, info in arrets.items()
        if info.get("confiance") == "bonne"
    }
    return rues | _hors_voisinage(positions, bonnes, itineraires_csv)


def arrets_non_fiables(
    arrets_geo: Path = ARRETS_GEO,
    itineraires_csv: Path = ITINERAIRES_CSV,
) -> set[str]:
    """Noms d'arrêts dont la position ne vaut ni pour le quartier ni pour la proximité.

    Partagé avec l'affichage (app.py) : les mêmes arrêts ne montrent pas de
    quartier entre parenthèses.
    """
    arrets: dict[str, dict] = {}
    chemin = Path(arrets_geo)
    if chemin.exists():
        with open(chemin, newline="", encoding="utf-8") as f:
            for rangee in csv.DictReader(f):
                point = None
                if rangee.get("lat") and rangee.get("lon"):
                    try:
                        point = (float(rangee["lat"]), float(rangee["lon"]))
                    except ValueError:
                        point = None
                arrets[rangee["arret"]] = {
                    "point": point,
                    "confiance": rangee.get("confiance", ""),
                }
    return _non_fiables(arrets, itineraires_csv)


# Mots de structure, retirés avant de comparer un lieu à un quartier/commune.
GENERIQUES = {
    "commune", "communes", "arrondissement", "arrondissements", "departement",
    "departements", "quartier", "quartiers", "region", "de", "du", "des", "d",
    "la", "le", "les", "l",
}

# Niveaux administratifs trop larges : « Département de Guédiawaye » ne dit pas
# que l'arrêt est dans la ville de Guédiawaye (il peut être à Pikine).
NIVEAUX_LARGES = ("arrondissement", "departement")


def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : « Dakar-Plateau » -> « dakar plateau »."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sans_accents(str(texte))).split())


def _mots(texte: str) -> list[str]:
    return [mot for mot in normaliser(texte).split() if mot not in GENERIQUES]


def _niveau_precis(valeur: str) -> bool:
    """Un quartier ou une commune, jamais « Département de » ni « Arrondissement de »."""
    return bool(valeur) and not normaliser(valeur).startswith(NIVEAUX_LARGES)


def distance_metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance à vol d'oiseau entre deux points (latitude, longitude)."""
    rayon = 6_371_000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * rayon * math.asin(math.sqrt(h))


class _Nominatim:
    """Géocodage direct, poli : cache disque d'abord, puis au plus 1 requête/s."""

    def __init__(self, cache: Path = CACHE_LIEUX) -> None:
        self.cache_path = cache
        self.cache: dict[str, list[float] | None] = {}
        if cache.exists():
            try:
                self.cache = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.cache = {}
        self.session = None
        self.derniere = 0.0

    def _sauver(self) -> None:
        try:
            self.cache_path.write_text(
                json.dumps(self.cache, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:  # disque en lecture seule (Space) : le cache reste en mémoire
            pass

    def _attendre(self) -> None:
        attente = DELAI_SECONDES - (time.monotonic() - self.derniere)
        if attente > 0:
            time.sleep(attente)

    def geocode(self, requete: str) -> tuple[float, float] | None:
        if requete in self.cache:
            valeur = self.cache[requete]
            return tuple(valeur) if valeur else None
        try:
            import requests
        except ImportError:  # sans requests, pas de géocodage direct : on continue sans
            return None
        if self.session is None:
            self.session = requests.Session()
        self._attendre()
        point = None
        try:
            reponse = self.session.get(
                GEOCODE,
                params={"q": requete, "format": "jsonv2", "limit": "1"},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            reponse.raise_for_status()
            resultats = reponse.json()
            if resultats:
                point = (float(resultats[0]["lat"]), float(resultats[0]["lon"]))
        except Exception:  # réseau, HTTP, JSON : on n'insiste pas, une autre fois
            self.derniere = time.monotonic()
            return None
        self.derniere = time.monotonic()
        self.cache[requete] = [point[0], point[1]] if point else None
        self._sauver()
        return point


class LieuxGeo:
    """Positions et quartiers des arrêts, et points des lieux dits."""

    def __init__(
        self,
        arrets_geo: Path = ARRETS_GEO,
        lieux_geo: Path = LIEUX_GEO,
        cache: Path = CACHE_LIEUX,
        itineraires_csv: Path = ITINERAIRES_CSV,
    ) -> None:
        self._arrets: dict[str, dict] = {}
        self._cible_mots: dict[str, set[str]] = {}
        self._lire_arrets(arrets_geo)
        # Les positions trompeuses (rues numérotées, homonymes isolés sur une
        # ligne AFTU) sont écartées en mémoire, sans toucher aux CSV.
        self._ecarter_non_fiables(itineraires_csv)

        self._lieux: dict[str, tuple[float, float]] = {}
        self._absents: set[str] = set()
        self._lire_lieux(lieux_geo)

        self._client = _Nominatim(cache)

    # -- chargement ------------------------------------------------------- #

    def _lire_arrets(self, chemin: Path) -> None:
        if not Path(chemin).exists():
            return
        with open(chemin, newline="", encoding="utf-8") as f:
            for rangee in csv.DictReader(f):
                point = None
                if rangee.get("lat") and rangee.get("lon"):
                    try:
                        point = (float(rangee["lat"]), float(rangee["lon"]))
                    except ValueError:
                        point = None
                arret = rangee["arret"]
                quartier = rangee.get("quartier", "")
                commune = rangee.get("commune", "")
                cible: set[str] = set()
                if _niveau_precis(quartier):
                    cible |= set(_mots(quartier))
                if _niveau_precis(commune):
                    cible |= set(_mots(commune))
                self._arrets[arret] = {
                    "point": point,
                    "quartier": quartier,
                    "commune": commune,
                    "confiance": rangee.get("confiance", ""),
                }
                self._cible_mots[arret] = cible

    def _ecarter_non_fiables(self, itineraires_csv: Path) -> None:
        """Neutralise les positions trompeuses, sans modifier les CSV."""
        for arret in _non_fiables(self._arrets, itineraires_csv):
            if arret in self._arrets:
                self._arrets[arret]["confiance"] = "douteuse"
                self._cible_mots[arret] = set()

    def _lire_lieux(self, chemin: Path) -> None:
        if not chemin.exists():
            return
        with open(chemin, newline="", encoding="utf-8") as f:
            for rangee in csv.DictReader(f):
                try:
                    self._lieux[normaliser(rangee["lieu"])] = (float(rangee["lat"]), float(rangee["lon"]))
                except (KeyError, ValueError):
                    continue

    # ------------------------------------------------------------------ #

    def point(self, lieu: str) -> tuple[float, float] | None:
        """Point du lieu dit : lieux_geo.csv, sinon Nominatim (une seule fois)."""
        if not lieu:
            return None
        cle = normaliser(lieu)
        if not cle:
            return None
        if cle in self._lieux:
            return self._lieux[cle]
        if cle in self._absents:
            return None
        trouve = self._client.geocode(f"{lieu}, Dakar, Sénégal")
        if trouve is not None:
            self._lieux[cle] = trouve
            return trouve
        self._absents.add(cle)
        return None

    def point_arret(self, arret: str) -> tuple[float, float] | None:
        info = self._arrets.get(arret)
        return info["point"] if info else None

    def scores_lieu(self, lieu: str, proximite: bool = True) -> dict[str, float]:
        """Arrêt -> note, pour les arrêts qui se trouvent au lieu dit.

        Un arrêt dont le quartier ou la commune correspond au lieu vaut
        SCORE_QUARTIER ; un arrêt à moins de 800 m vaut d'autant plus que le
        point est proche (au plus SCORE_GEO_MAX). La correspondance de quartier,
        comme la proximité, ne retient que la confiance « bonne » : un arrêt
        « estimee » peut tomber dans un quartier voisin. Les arrêts « douteuse »
        et les faux amis sont écartés. `proximite=False` n'utilise que le quartier
        ou la commune : quand le lieu est déjà reconnu par son nom, on ne veut pas
        y ajouter les arrêts simplement proches.
        """
        if not lieu:
            return {}
        point = self.point(lieu) if proximite else None
        cible = set(_mots(lieu))
        scores: dict[str, float] = {}
        for arret, info in self._arrets.items():
            if info["confiance"] in CONFIANCE_IGNOREE:
                continue
            # Un faux ami (« Sortie Pikine », « Garage Guédiawaye ») n'est jamais
            # un candidat géographique : son nom dit un quartier où il n'est pas.
            if normaliser(arret) in FAUX_AMIS:
                continue
            note = 0.0
            if (
                cible
                and info["confiance"] in CONFIANCE_PROXIMITE
                and cible <= self._cible_mots.get(arret, set())
            ):
                note = SCORE_QUARTIER
            if (
                proximite
                and info["confiance"] in CONFIANCE_PROXIMITE
                and point is not None
                and info["point"] is not None
            ):
                distance = distance_metres(point, info["point"])
                if distance <= RAYON_METRES:
                    note = max(
                        note,
                        SCORE_PROCHE_MIN
                        + (SCORE_GEO_MAX - SCORE_PROCHE_MIN) * (1 - distance / RAYON_METRES),
                    )
            if note > 0:
                scores[arret] = note
        return scores
