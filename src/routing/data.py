"""Chargement des quatre CSV locaux du réseau de bus de Dakar.

Le moteur de Koumba téléchargeait ses données depuis Hugging Face.  Ici on
lit directement les fichiers de ``data/`` : ce sont les mêmes colonnes, et
les CSV protégés ne sont jamais modifiés.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
DATA_DIR = RACINE / "data"

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


def _lire(nom: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / FICHIERS[nom], encoding="utf-8")


def load_data() -> NetworkData:
    """Lit les CSV locaux et applique les corrections d'orthographe revues."""

    data = NetworkData(
        lignes=_lire("lignes"),
        itineraires=_lire("itineraires"),
        arrets=_lire("arrets"),
        lieux=_lire("lieux"),
    )

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
