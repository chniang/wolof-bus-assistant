"""Chargement des quatre CSV locaux du réseau de bus de Dakar.

Le moteur de Koumba téléchargeait ses données depuis Hugging Face.  Ici on
lit directement les fichiers de ``data/`` : ce sont les mêmes colonnes, et
les CSV protégés ne sont jamais modifiés.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .traces import charger_traces

RACINE = Path(__file__).resolve().parents[2]
DATA_DIR = RACINE / "data"

CORRECTIONS_TATA = DATA_DIR / "corrections" / "corrections_geo_tata_proposees.csv"
CORRECTIONS_DDD = DATA_DIR / "corrections" / "corrections_geo_ddd_proposees.csv"
DOSSIER_TRACES = DATA_DIR / "sources" / "aftu_traces"
DEM_DIKK = "Dakar Dem Dikk"

# Sources assez sûres pour situer un arrêt hors de sa ligne (correspondance, arrêt
# proche).  Une position interpolée ou géocodée ne sert qu'à mesurer la ligne.
SOURCES_SURES = {
    "ancre_tata",
    "guindima_origine",
    "osm_arret",
    "projection_sur_trace",
    "terminus_guindima",
    "terminus_officiel_aftu",
    # Arrêt « bonne » d'arrets_geo.csv, terminus d'une ligne ajoutée
    # (HLM Grand Yoff pour l'Express AIBD : data/corrections/lignes_ddd_ajoutees.csv).
    "arrets_geo_bonne",
}

# Positions posées le long d'une trace (AFTU ou OSM) : pas mesurées arrêt par
# arrêt, mais sur la route réelle. Une durée qui en part reste juste à peu près
# (Dem Dikk 8 : « Yoff Village », interpolé sur la trace OSM, 1,7 km après
# l'Aéroport LSS mesuré).
SOURCES_SUR_TRACE = {
    "interpolation_sur_trace",
    "interpolation_sur_trace_osm",
    "projection_sur_trace",
}

FICHIERS = {
    "lignes": "lignes_dakar.csv",
    "itineraires": "itineraires_dakar.csv",
    "arrets": "arrets_geo.csv",
    "lieux": "lieux_geo.csv",
}


@dataclass
class NetworkData:
    """Les quatre tables, gardées séparées pour rester faciles à inspecter."""

    lignes: pd.DataFrame
    itineraires: pd.DataFrame
    arrets: pd.DataFrame
    lieux: pd.DataFrame
    # Position d'un arrêt SUR UNE LIGNE : (compagnie, ligne) -> ordre -> position.
    # Le même nom peut être à deux endroits selon la ligne ; position None : connu
    # de la ligne mais pas situé, il ne compte pas dans les distances.
    positions_ligne: dict = field(default_factory=dict)
    # (compagnie, ligne) -> ordre -> vrai si la source permet de situer l'arrêt.
    positions_sures: dict = field(default_factory=dict)
    # (compagnie, ligne) -> ordre -> vrai si la position est posée le long d'une
    # trace (AFTU ou OSM) : approximative, mais sur la route réelle du bus.
    positions_sur_trace: dict = field(default_factory=dict)
    # « Ligne N » (Tata) -> points de la trace officielle AFTU.
    traces: dict = field(default_factory=dict)


def _lire(nom: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / FICHIERS[nom], encoding="utf-8")


# La règle de nommage vit dans matching/itineraires_app.py : l'extraction des
# lieux et geo.py la partagent, pour voir les mêmes arrêts Dem Dikk que l'app.
try:  # import à plat (app.py) ou en paquet
    from matching.itineraires_app import nom_ligne_ddd as _nom_ligne_ddd
    from matching.itineraires_app import cle_lieu as _cle_lieu
    from matching.itineraires_app import lignes_ddd_ajoutees, rangees_ddd_officielles
    from matching.itineraires_app import positions_corrigees, positions_estimees, terminus_ddd_revus
    from matching.itineraires_app import sans_terminus as _sans_terminus
except ImportError:  # pragma: no cover
    from ..matching.itineraires_app import nom_ligne_ddd as _nom_ligne_ddd
    from ..matching.itineraires_app import cle_lieu as _cle_lieu
    from ..matching.itineraires_app import lignes_ddd_ajoutees, rangees_ddd_officielles
    from ..matching.itineraires_app import positions_corrigees, positions_estimees, terminus_ddd_revus
    from ..matching.itineraires_app import sans_terminus as _sans_terminus


def _charger_positions(data: NetworkData, frame: pd.DataFrame) -> None:
    for rangee in frame.itertuples(index=False):
        cle = (str(rangee.compagnie), str(rangee.ligne))
        ordre = int(rangee.ordre)
        lat = pd.to_numeric(rangee.lat, errors="coerce")
        lon = pd.to_numeric(rangee.lon, errors="coerce")
        connue = str(rangee.source) != "inconnu" and pd.notna(lat) and pd.notna(lon)
        data.positions_ligne.setdefault(cle, {})[ordre] = (
            (float(lat), float(lon)) if connue else None
        )
        data.positions_sures.setdefault(cle, {})[ordre] = (
            connue and str(rangee.source) in SOURCES_SURES
        )
        data.positions_sur_trace.setdefault(cle, {})[ordre] = (
            connue and str(rangee.source) in SOURCES_SUR_TRACE
        )


def _integrer_dem_dikk_officiel(data: NetworkData) -> None:
    """Remplace en mémoire nos itinéraires Dem Dikk par les listes officielles.

    Nos lignes absentes du fichier (15A, 15B, 502A/B, 503A/B, 504A/B) restent telles
    quelles.  Une ligne officielle que nous n'avions pas (311, 319…) est ajoutée.
    """

    if not CORRECTIONS_DDD.exists():
        return
    # Même lecture que l'extraction et geo.py (matching/itineraires_app.py) :
    # noms de ligne et d'arrêt, listes écartées (217 et 233, copies de la 218 et
    # de la 232) et terminus ajoutés (Gare de Dakar pour la 501).
    officiel = pd.DataFrame(rangees_ddd_officielles(CORRECTIONS_DDD))
    if officiel.empty:
        return
    officiel["ordre"] = pd.to_numeric(officiel["ordre"])
    remplacees = set(officiel["ligne"])

    def officielle(frame: pd.DataFrame) -> pd.Series:
        return (frame["compagnie"] == DEM_DIKK) & frame["ligne"].isin(remplacees)

    data.itineraires = pd.concat(
        [
            data.itineraires[~officielle(data.itineraires)],
            officiel.reindex(columns=data.itineraires.columns),
        ],
        ignore_index=True,
    )

    # Les terminus affichés suivent le nouvel ordre : l'ancien pouvait être inversé.
    # Une ligne nouvelle n'a ni catégorie ni source, sans « nan » à l'écran.
    ordonne = officiel.sort_values(["ligne", "ordre"]).groupby("ligne")["arret"]
    terminus = pd.DataFrame(
        {
            "compagnie": DEM_DIKK,
            "terminus_a": ordonne.first(),
            "terminus_b": ordonne.last(),
        }
    ).reset_index()
    anciennes = data.lignes[officielle(data.lignes)].drop(
        columns=["terminus_a", "terminus_b"]
    )
    nouvelles = terminus.merge(anciennes, on=["compagnie", "ligne"], how="left")
    data.lignes = pd.concat(
        [
            data.lignes[~officielle(data.lignes)],
            nouvelles.reindex(columns=data.lignes.columns).fillna(""),
        ],
        ignore_index=True,
    )
    _charger_positions(data, officiel)


def _integrer_lignes_ajoutees(data: NetworkData) -> None:
    """Lignes absentes de nos CSV mais connues officiellement (Express AIBD).

    Deux arrêts, les terminus de la fiche à l'écran, une catégorie qui dit
    « Navette express, sans arrêt » et un statut « à confirmer » si un terminus
    n'a pas de position. Aucune durée n'est fixée ici : le moteur la calcule,
    et adapter.duree_devinee la cache quand la portion n'est pas mesurée
    (AIBD n'a qu'un repère, à ~40 km de HLM Grand Yoff).
    """

    ajoutees = lignes_ddd_ajoutees()
    if not ajoutees:
        return
    cles = {(fiche["compagnie"], fiche["ligne"]) for fiche in ajoutees}

    def deja(frame: pd.DataFrame) -> pd.Series:
        return pd.Series(
            [cle in cles for cle in zip(frame["compagnie"], frame["ligne"])],
            index=frame.index,
            dtype=bool,
        )

    rangees = pd.DataFrame([r for fiche in ajoutees for r in fiche["rangees"]])
    rangees["ordre"] = pd.to_numeric(rangees["ordre"])
    data.itineraires = pd.concat(
        [
            data.itineraires[~deja(data.itineraires)],
            rangees.reindex(columns=data.itineraires.columns),
        ],
        ignore_index=True,
    )
    champs = ("compagnie", "ligne", "terminus_a", "terminus_b", "categorie", "source", "statut")
    lignes = pd.DataFrame([{cle: fiche[cle] for cle in champs} for fiche in ajoutees])
    colonnes = list(data.lignes.columns)
    if "statut" not in colonnes:
        colonnes.append("statut")
    data.lignes = pd.concat(
        [data.lignes[~deja(data.lignes)], lignes.reindex(columns=colonnes)],
        ignore_index=True,
    )
    data.lignes["statut"] = data.lignes["statut"].fillna("")
    _charger_positions(data, rangees)


def _terminus_dem_dikk_revus(data: NetworkData) -> None:
    """Terminus affichés d'après les pages officielles (data/corrections/statut_lignes_ddd.csv).

    Seulement l'affichage : la liste d'arrêts et le sens ne changent pas. La 6
    commence à Camberene mais son terminus est Cambérène 2 ; la 311 est une
    boucle « Lac Rose (croisement Niague) -> Croisement Keur Massar ».
    """

    revus = terminus_ddd_revus()
    if not revus:
        return
    lignes = data.lignes.copy()
    for index, rangee in lignes.iterrows():
        if rangee["compagnie"] == DEM_DIKK and rangee["ligne"] in revus:
            lignes.at[index, "terminus_a"], lignes.at[index, "terminus_b"] = revus[rangee["ligne"]]
    data.lignes = lignes


def _integrer_donnees_fiables(data: NetworkData) -> None:
    """Itinéraires officiels, positions par ligne et traces : tout reste en mémoire."""

    _integrer_dem_dikk_officiel(data)
    _integrer_lignes_ajoutees(data)
    _terminus_dem_dikk_revus(data)
    if CORRECTIONS_TATA.exists():
        _charger_positions(data, pd.read_csv(CORRECTIONS_TATA, encoding="utf-8"))
    data.traces = charger_traces(DOSSIER_TRACES)


def _corriger_terminus(data: NetworkData) -> None:
    """Terminus Tata des fiches officielles AFTU (data/corrections/terminus_tata_officiels.csv)."""

    try:
        from matching.terminus import corrections_terminus
    except ImportError:  # pragma: no cover
        from ..matching.terminus import corrections_terminus

    corrections = corrections_terminus()
    if not corrections:
        return
    lignes = data.lignes.copy()
    for index, rangee in lignes.iterrows():
        corrige = corrections.get((rangee["compagnie"], rangee["ligne"]))
        if corrige is not None:
            lignes.at[index, "terminus_a"], lignes.at[index, "terminus_b"] = corrige
    data.lignes = lignes


def load_data() -> NetworkData:
    """Lit les CSV locaux et applique les corrections d'orthographe revues."""

    data = NetworkData(
        lignes=_lire("lignes"),
        itineraires=_lire("itineraires"),
        arrets=_lire("arrets"),
        lieux=_lire("lieux"),
    )

    _integrer_donnees_fiables(data)
    _corriger_terminus(data)

    # Les corrections de noms s'appliquent aux DataFrames en mémoire, jamais
    # aux fichiers : tout le monde voit ainsi le même nom d'arrêt.
    from .corrections import canonicalize_data_stop_names

    canonicalize_data_stop_names(data)
    _appliquer_positions_revues(data)
    _validate(data)
    return data


def _appliquer_positions_revues(data: NetworkData) -> None:
    """positions_corrigees.csv et positions_estimees.csv, en mémoire seulement.

    Appliquées après les corrections de noms : un nom est reconnu sous toutes
    ses graphies (« Rond Point liberté 6 », « Rond point Liberté 6 »).
    - corrigée : la position vaut pour chaque ligne qui porte ce nom, et elle
      devient sûre (« bonne ») ; AIBD quitte ainsi Grand Yoff pour Diass ;
    - estimée : la position reste, mais n'est plus sûre nulle part (Avenue
      Cheikh Anta Diop, voie de 5 km ; Apix, homonyme du Plateau).
    """

    corrigees, estimees = positions_corrigees(), positions_estimees()
    if not corrigees and not estimees:
        return

    arrets = data.arrets.copy().reset_index(drop=True)
    cles_arrets = [_cle_lieu(nom) for nom in arrets["arret"]]
    for cle, (lat, lon, _source) in corrigees.items():
        lignes = [i for i, autre in enumerate(cles_arrets) if autre == cle]
        if lignes:
            for i in lignes:
                arrets.at[i, "lat"], arrets.at[i, "lon"], arrets.at[i, "confiance"] = lat, lon, "bonne"
        else:
            nom = next(
                (str(a) for a in data.itineraires["arret"] if _cle_lieu(a) == cle), None
            )
            if nom is not None:
                arrets = pd.concat(
                    [arrets, pd.DataFrame([{"arret": nom, "lat": lat, "lon": lon, "confiance": "bonne"}])],
                    ignore_index=True,
                )
    for i, cle in enumerate(cles_arrets):
        if cle in estimees and cle not in corrigees:
            arrets.at[i, "confiance"] = "estimee"
    data.arrets = arrets

    for rangee in data.itineraires.itertuples(index=False):
        cle = _cle_lieu(rangee.arret)
        ligne = (str(rangee.compagnie), str(rangee.ligne))
        ordre = int(rangee.ordre)
        if cle in corrigees:
            lat, lon, _source = corrigees[cle]
            data.positions_ligne.setdefault(ligne, {})[ordre] = (lat, lon)
            data.positions_sures.setdefault(ligne, {})[ordre] = True
        elif cle in estimees and ligne in data.positions_sures:
            data.positions_sures[ligne][ordre] = False


def _validate(data: NetworkData) -> None:
    required = {
        "lignes": ("compagnie", "ligne", "terminus_a", "terminus_b"),
        "itineraires": ("compagnie", "ligne", "ordre", "arret"),
        "arrets": ("arret", "lat", "lon", "confiance"),
        "lieux": ("lieu", "lat", "lon"),
    }
    frames = {
        "lignes": data.lignes,
        "itineraires": data.itineraires,
        "arrets": data.arrets,
        "lieux": data.lieux,
    }

    for name, columns in required.items():
        frame = frames[name]
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(f"{name} is missing columns: {missing}")
        if frame.empty:
            raise ValueError(f"{name} is empty")

    data.itineraires["ordre"] = pd.to_numeric(
        data.itineraires["ordre"], errors="coerce"
    )
    if data.itineraires["ordre"].isna().any():
        raise ValueError("itineraires has non-numeric order values")

    data.itineraires = data.itineraires.sort_values(
        ["compagnie", "ligne", "ordre"]
    ).reset_index(drop=True)

    for column in ("lat", "lon"):
        data.arrets[column] = pd.to_numeric(data.arrets[column], errors="coerce")
        data.lieux[column] = pd.to_numeric(data.lieux[column], errors="coerce")
