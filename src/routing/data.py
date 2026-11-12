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
    # « Ligne N » (Tata) -> points de la trace officielle AFTU.
    traces: dict = field(default_factory=dict)


def _lire(nom: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / FICHIERS[nom], encoding="utf-8")


def _nom_ligne_ddd(ligne: object) -> str:
    """« 1 » -> « Ligne 1 », « 16A » -> « Ligne 16A » ; « TAF TAF » reste tel quel."""

    texte = str(ligne).strip()
    return f"Ligne {texte}" if texte[:1].isdigit() else texte


def _sans_terminus(nom: object) -> str:
    """« Terminus keur Massar » -> « Keur Massar » : le même arrêt que nos autres lignes.

    « Terminus X (Y) » garde son nom complet : il désigne deux lieux (voir
    ``terminus_forms``), et le renommer en perdrait un.
    """

    texte = str(nom).strip()
    trouve = re.fullmatch(r"terminus\s+([^()]+)", texte, flags=re.IGNORECASE)
    if not trouve:
        return texte
    reste = trouve.group(1).strip()
    return reste[0].upper() + reste[1:] if not reste.isdigit() else texte


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


def _integrer_dem_dikk_officiel(data: NetworkData) -> None:
    """Remplace en mémoire nos itinéraires Dem Dikk par les listes officielles.

    Nos lignes absentes du fichier (15A, 15B, 502A/B, 503A/B, 504A/B) restent telles
    quelles.  Une ligne officielle que nous n'avions pas (311, 319…) est ajoutée.
    """

    if not CORRECTIONS_DDD.exists():
        return
    officiel = pd.read_csv(CORRECTIONS_DDD, encoding="utf-8", dtype={"ligne": str})
    officiel["ligne"] = officiel["ligne"].map(_nom_ligne_ddd)
    officiel["ordre"] = pd.to_numeric(officiel["ordre"])
    officiel["arret"] = officiel["arret"].map(_sans_terminus)
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


def _integrer_donnees_fiables(data: NetworkData) -> None:
    """Itinéraires officiels, positions par ligne et traces : tout reste en mémoire."""

    _integrer_dem_dikk_officiel(data)
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
    _validate(data)
    return data


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
