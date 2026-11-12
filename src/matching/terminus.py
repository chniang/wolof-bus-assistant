"""Terminus des lignes Tata corrigés d'après les fiches officielles AFTU.

data/lignes_dakar.csv n'est jamais modifié : la correction vit dans
data/corrections/terminus_tata_officiels.csv (une ligne par ligne de bus, avec
l'URL et la date de la fiche) et s'applique en mémoire, à la lecture. Le
lot 2b (12/11/2026) y a mis les 15 lignes classées TERMINUS_DIFFERENT par
scripts/comparer_lignes_officielles.py : la Tata 74, par exemple, finit à
« Cité Cocehas », pas à « Tivaouane Peulh ».

Les terminus ne servent qu'à l'affichage (« Ligne : A → B ») et au sens du
trajet : la voix ne les prononce jamais (« Jëlal biis bu Tataa, numero … »,
puis seulement les arrêts de changement et de descente).
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

CORRECTIONS_TERMINUS = (
    Path(__file__).resolve().parents[2] / "data" / "corrections" / "terminus_tata_officiels.csv"
)


@lru_cache(maxsize=4)
def corrections_terminus(chemin: Path = CORRECTIONS_TERMINUS) -> dict[tuple[str, str], tuple[str, str]]:
    """(compagnie, ligne) -> (terminus_a, terminus_b), seulement les rangées sourcées."""
    if not chemin.exists():
        return {}
    sortie: dict[tuple[str, str], tuple[str, str]] = {}
    with open(chemin, newline="", encoding="utf-8-sig") as fichier:
        for rangee in csv.DictReader(fichier):
            if not (rangee.get("source") or "").startswith("https://") or not (rangee.get("date_fiche") or "").strip():
                continue
            sortie[(rangee["compagnie"], rangee["ligne"])] = (
                rangee["terminus_a"].strip(),
                rangee["terminus_b"].strip(),
            )
    return sortie


def corriger_terminus(rangee: dict) -> dict:
    """Une rangée de lignes_dakar.csv, avec ses terminus corrigés s'il y a lieu."""
    corrige = corrections_terminus().get((rangee.get("compagnie"), rangee.get("ligne")))
    if corrige is None:
        return rangee
    return {**rangee, "terminus_a": corrige[0], "terminus_b": corrige[1]}
