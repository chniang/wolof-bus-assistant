"""Correspondance floue entre noms de quartiers et lignes de bus (CSV)."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "arrets_lignes_dakar.csv"

# En dessous de ce score de similarité, le lieu demandé n'est pas considéré comme
# présent dans le CSV. Sans seuil, SequenceMatcher renvoie toujours un « meilleur »
# candidat : « Rond-point Score » tombait sur « Aéroport LSS » à 0.50.
MIN_SCORE = 0.55


def _normalize(text: str) -> str:
    """Minuscule, insensible aux accents et aux espaces superflus."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", str(text))
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(without_accents.lower().split())


class StopsMatcher:
    """Charge le CSV des lignes et trouve la meilleure correspondance."""

    def __init__(self, csv_path: str | Path = DEFAULT_CSV) -> None:
        self.df = pd.read_csv(csv_path)
        self.df.columns = [c.strip().lower() for c in self.df.columns]

        required = {"compagnie", "ligne"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"Colonnes manquantes dans le CSV : {', '.join(sorted(missing))}.")

        self.depart_col = self._column_or("depart", "departure")
        self.arrivee_col = self._column_or("arrivee", "arrival")

        self._dep_norm = self.df[self.depart_col].map(_normalize)
        self._arr_norm = self.df[self.arrivee_col].map(_normalize)

        # Index des lieux uniques, colonnes confondues : dans le CSV un terminus
        # n'existe souvent que d'un seul côté (« Guédiawaye » n'est qu'un depart),
        # alors que l'utilisateur peut vouloir y aller ou en revenir.
        stops: dict[str, str] = {}
        for column in (self.depart_col, self.arrivee_col):
            for name, normalized in zip(self.df[column], self.df[column].map(_normalize)):
                if normalized:
                    stops.setdefault(normalized, str(name))
        self._stops = stops

    def _column_or(self, *names: str) -> str:
        for name in names:
            if name in self.df.columns:
                return str(name)
        raise ValueError(f"Aucune des colonnes {names} n'est présente.")

    def _best_match(self, query: str) -> tuple[str, float]:
        """Meilleure correspondance dans l'union des colonnes depart et arrivee.

        Le score est à comparer à MIN_SCORE : en dessous, le candidat renvoyé
        n'est pas un lieu du réseau.
        """
        normalized_query = _normalize(query)
        best_name = ""
        best_score = 0.0
        for normalized_name, name in self._stops.items():
            score = SequenceMatcher(None, normalized_query, normalized_name).ratio()
            if score > best_score:
                best_score = score
                best_name = name
        return best_name, best_score

    def _lines_covering(self, depart: str, arrivee: str) -> list[dict]:
        """Lignes desservant le trajet, dans le sens direct ou le sens inverse.

        Chaque enregistrement est rendu dans le sens demandé : pour un trajet
        inverse, depart et arrivee sont échangés.
        """
        direct = self.df[(self._dep_norm == depart) & (self._arr_norm == arrivee)]
        rows = [{**record, "sens": "direct"} for record in direct.to_dict(orient="records")]

        if depart != arrivee:
            inverse = self.df[(self._dep_norm == arrivee) & (self._arr_norm == depart)]
            rows += [
                {
                    **record,
                    self.depart_col: record[self.arrivee_col],
                    self.arrivee_col: record[self.depart_col],
                    "sens": "inverse",
                }
                for record in inverse.to_dict(orient="records")
            ]
        return rows

    def find_line(self, depart: str, arrivee: str) -> dict:
        """Retourne les lignes couvrant le trajet demandé, quel que soit le sens.

        Un lieu introuvable (score < MIN_SCORE) invalide le résultat : mieux vaut
        signaler le lieu inconnu que renvoyer un candidat hors sujet.
        """
        best_depart, depart_score = self._best_match(depart)
        best_arrivee, arrivee_score = self._best_match(arrivee)

        depart_valide = depart_score >= MIN_SCORE
        arrivee_valide = arrivee_score >= MIN_SCORE

        lignes: list[dict] = []
        if depart_valide and arrivee_valide:
            lignes = self._lines_covering(_normalize(best_depart), _normalize(best_arrivee))

        return {
            "found": bool(lignes),
            "depart": depart,
            "depart_matched": best_depart,
            "depart_score": round(depart_score, 3),
            "depart_valide": depart_valide,
            "arrivee": arrivee,
            "arrivee_matched": best_arrivee,
            "arrivee_score": round(arrivee_score, 3),
            "arrivee_valide": arrivee_valide,
            "lignes": lignes,
        }
