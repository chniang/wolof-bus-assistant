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

    def _candidats(self, requete: str) -> tuple[list[str], str, float, bool]:
        """Lieux candidats pour une saisie, meilleure correspondance, score, validité.

        Si la saisie est un préfixe strict d'au moins un lieu du CSV, elle est
        ambiguë : « Palais » peut vouloir dire « Palais 1 » comme « Palais 2 ».
        On propose alors tous les lieux compatibles, correspondance exacte en tête,
        et la saisie est jugée valide. Sinon on retombe sur la meilleure
        correspondance floue, retenue seulement si son score dépasse MIN_SCORE.
        """
        best, score = self._best_match(requete)
        prefixe = _normalize(requete)
        if prefixe:
            compatibles = [nom for norme, nom in self._stops.items() if norme.startswith(prefixe)]
            if len(compatibles) > 1:
                exactes = [nom for norme, nom in self._stops.items() if norme == prefixe]
                autres = sorted(nom for nom in compatibles if nom not in exactes)
                return [*exactes, *autres], best, score, True
        return [best], best, score, score >= MIN_SCORE

    @staticmethod
    def _cle(record: dict) -> tuple:
        """Identité d'une ligne du CSV, indépendante du sens demandé."""
        return tuple(sorted((str(cle), str(valeur)) for cle, valeur in record.items()))

    def _lignes_pour(self, depart: str, arrivee: str) -> list[tuple[tuple, dict]]:
        """Lignes reliant exactement ces deux lieux, sens direct ou inverse.

        Renvoie des (clé, enregistrement) : la clé identifie la ligne du CSV, ce
        qui permet de dédoublonner l'union quand deux candidats se recouvrent.
        Pour un trajet inverse, depart et arrivee sont échangés.
        """
        trouvees: list[tuple[tuple, dict]] = []
        for record in self.df.to_dict(orient="records"):
            dep = _normalize(record[self.depart_col])
            arr = _normalize(record[self.arrivee_col])
            if dep == depart and arr == arrivee:
                trouvees.append((self._cle(record), {**record, "sens": "direct"}))
            elif dep == arrivee and arr == depart:
                trouvees.append(
                    (
                        self._cle(record),
                        {
                            **record,
                            self.depart_col: record[self.arrivee_col],
                            self.arrivee_col: record[self.depart_col],
                            "sens": "inverse",
                        },
                    )
                )
        return trouvees

    def find_line(self, depart: str, arrivee: str) -> dict:
        """Retourne les lignes couvrant le trajet demandé, quel que soit le sens.

        Un lieu introuvable (score < MIN_SCORE) invalide le résultat : mieux vaut
        signaler le lieu inconnu que renvoyer un candidat hors sujet. Un lieu sans
        numéro (« Palais ») est cherché dans tous les lieux du CSV qui le
        contiennent, et les lignes trouvées sont réunies sans doublon.
        """
        departs, best_depart, depart_score, depart_valide = self._candidats(depart)
        arrivees, best_arrivee, arrivee_score, arrivee_valide = self._candidats(arrivee)

        depart_matched, arrivee_matched = best_depart, best_arrivee
        lignes: list[dict] = []
        vus: set[tuple] = set()
        if depart_valide and arrivee_valide:
            for nom_depart in departs:
                for nom_arrivee in arrivees:
                    trouvees = self._lignes_pour(_normalize(nom_depart), _normalize(nom_arrivee))
                    if not trouvees:
                        continue
                    if not lignes:
                        # Le premier couple qui aboutit est celui qu'on annonce.
                        depart_matched, arrivee_matched = nom_depart, nom_arrivee
                    for cle, record in trouvees:
                        if cle not in vus:
                            vus.add(cle)
                            lignes.append(record)

        return {
            "found": bool(lignes),
            "depart": depart,
            "depart_matched": depart_matched,
            "depart_score": round(depart_score, 3),
            "depart_valide": depart_valide,
            "arrivee": arrivee,
            "arrivee_matched": arrivee_matched,
            "arrivee_score": round(arrivee_score, 3),
            "arrivee_valide": arrivee_valide,
            "lignes": lignes,
        }
