"""Trouve les lignes de bus qui relient deux lieux de Dakar, arrêt par arrêt.

Données : data/lignes_dakar.csv (lignes et terminus officiels DDD et AFTU) et
data/itineraires_dakar.csv (arrêts de chaque ligne, dans l'ordre), construits
par data/sources/build_dataset.py.

Une ligne convient si l'un de ses arrêts correspond au départ et un autre à
l'arrivée : on n'exige plus que les deux lieux soient ses terminus. Le sens est
déduit de l'ordre des arrêts.
"""

from __future__ import annotations

import csv
from pathlib import Path

try:  # import à plat (app.py, Streamlit) ou en paquet (tests)
    from matching.lieux import score
except ImportError:  # pragma: no cover
    from .lieux import score

DATA = Path(__file__).resolve().parents[2] / "data"
LIGNES_CSV = DATA / "lignes_dakar.csv"
ITINERAIRES_CSV = DATA / "itineraires_dakar.csv"

# En dessous, l'arrêt n'est pas considéré comme le lieu demandé.
MIN_SCORE = 0.6
# Lignes gardées : celles dont la correspondance la plus faible (départ ou
# arrivée) est à moins de cet écart de la meilleure. « Yoff » exact écarte ainsi
# les lignes qui ne passent qu'à « Grand Yoff ».
TOLERANCE = 0.15
MAX_LIGNES = 4


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

    # ------------------------------------------------------------------ #

    @staticmethod
    def _meilleur(lieu: str, arrets: list[str]) -> tuple[float, int]:
        """Meilleur arrêt de la ligne pour ce lieu : (score, position)."""
        meilleur = (0.0, -1)
        for position, arret in enumerate(arrets):
            valeur = score(lieu, arret)
            if valeur > meilleur[0]:
                meilleur = (valeur, position)
        return meilleur

    def _reconnu(self, lieu: str) -> tuple[str, float]:
        """L'arrêt du réseau le plus proche du lieu demandé, et son score."""
        meilleur = ("", 0.0)
        for arret in self.tous_les_arrets:
            valeur = score(lieu, arret)
            if valeur > meilleur[1]:
                meilleur = (arret, valeur)
        return meilleur

    def find_line(self, depart: str, arrivee: str) -> dict:
        """Lignes reliant depart et arrivee, la meilleure en tête.

        Chaque ligne renvoyée porte : compagnie, ligne, categorie, depart et
        arrivee (les terminus dans le sens du trajet), sens, monte_a et
        descend_a (les arrêts où monter et descendre).
        """
        depart_arret, depart_score = self._reconnu(depart or "")
        arrivee_arret, arrivee_score = self._reconnu(arrivee or "")
        depart_valide = depart_score >= MIN_SCORE
        arrivee_valide = arrivee_score >= MIN_SCORE

        candidates = []
        if depart_valide and arrivee_valide:
            for cle, arrets in self.arrets.items():
                s_dep, i_dep = self._meilleur(depart, arrets)
                s_arr, i_arr = self._meilleur(arrivee, arrets)
                if s_dep < MIN_SCORE or s_arr < MIN_SCORE or i_dep == i_arr:
                    continue
                candidates.append((min(s_dep, s_arr), s_dep + s_arr, abs(i_arr - i_dep), cle, i_dep, i_arr))

        lignes = []
        if candidates:
            meilleur = max(c[0] for c in candidates)
            gardees = [c for c in candidates if c[0] >= meilleur - TOLERANCE]
            # Meilleure correspondance d'abord, puis le trajet le plus court en arrêts.
            gardees.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))
            for _, _, _, cle, i_dep, i_arr in gardees[:MAX_LIGNES]:
                info, arrets = self.lignes[cle], self.arrets[cle]
                direct = i_dep < i_arr
                lignes.append(
                    {
                        "compagnie": info["compagnie"],
                        "ligne": info["ligne"],
                        "categorie": info.get("categorie", ""),
                        "depart": info["terminus_a"] if direct else info["terminus_b"],
                        "arrivee": info["terminus_b"] if direct else info["terminus_a"],
                        "sens": "direct" if direct else "inverse",
                        "monte_a": arrets[i_dep],
                        "descend_a": arrets[i_arr],
                    }
                )

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
        }
