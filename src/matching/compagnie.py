"""Choix de compagnie : étiquettes et message quand elle ne dessert pas le trajet.

Ce module ne porte que de la mise en forme de texte, sans dépendance lourde :
l'application Gradio et les tests locaux partagent donc exactement le même
bandeau, sans charger le modèle vocal.
"""

from __future__ import annotations

import csv
from pathlib import Path

# Étiquettes courtes affichées à l'utilisateur ; le CSV et le bouton portent le
# nom complet (« Tata AFTU », « Dakar Dem Dikk »).
LIBELLES_COMPAGNIES = {"Tata AFTU": "Tata", "Dakar Dem Dikk": "Dem Dikk"}


# Lignes Dem Dikk dont l'itinéraire n'est pas sûr (data/audit/fiabilite_rapport.md,
# puis data/audit/rapport_lignes_divergentes.md du 20/11/2026) : à l'audit, la 6
# partait chez nous de Guédiawaye, la référence disait Cambérène 2 ; la 208
# partait de Gorom 01 dans la liste officielle, de Bayakh dans notre fiche ; la
# 217 et la 233 sont réduites à leurs terminus (liste officielle copiée d'une
# autre ligne, écartée) ; la 220 mêlait deux versions (Rufisque–Guédiawaye,
# navette AIBD). Elles restent proposées, mais la carte le dit et elles passent
# toujours après une ligne confirmée qui fait le même trajet.
_A_CONFIRMER_AUDIT = ("6", "208", "217", "220", "233")
# Lot B-sources (20/11/2026) : data/corrections/statut_lignes_ddd.csv tranche
# ligne par ligne d'après les pages officielles. « confirmé » retire la ligne
# (208 : Bayakh ↔ Rufisque, arrêts bien placés ; 220 : Rufisque ↔ Guédiawaye,
# sans navette AIBD), « à confirmer » l'ajoute ou la garde (6, 233), vide ne
# change rien. La 217 n'y figure pas : elle reste à confirmer.
STATUT_LIGNES_DDD = Path(__file__).resolve().parents[2] / "data" / "corrections" / "statut_lignes_ddd.csv"


def _lignes_a_confirmer(chemin: Path = STATUT_LIGNES_DDD) -> frozenset[tuple[str, str]]:
    numeros = set(_A_CONFIRMER_AUDIT)
    if chemin.exists():
        with open(chemin, newline="", encoding="utf-8-sig") as fichier:
            for rangee in csv.DictReader(fichier):
                numero, statut = (rangee.get("ligne") or "").strip(), (rangee.get("statut") or "").strip()
                if statut == "confirmé":
                    numeros.discard(numero)
                elif statut == "à confirmer":
                    numeros.add(numero)
    return frozenset(("Dakar Dem Dikk", f"Ligne {numero}") for numero in numeros)


LIGNES_A_CONFIRMER = _lignes_a_confirmer()
MENTION_A_CONFIRMER = "itinéraire à confirmer"


def ligne_a_confirmer(etape: dict) -> bool:
    """Vrai si cette étape (une ligne de résultat) emprunte une ligne douteuse."""
    return (etape.get("compagnie"), etape.get("ligne")) in LIGNES_A_CONFIRMER


def libelle_compagnie(compagnie: str) -> str:
    return LIBELLES_COMPAGNIES.get(compagnie, compagnie)


def autre_compagnie(resultat: dict) -> str:
    """Noms des compagnies présentes dans le résultat de secours, dans l'ordre."""
    noms: list[str] = []

    def ajouter(compagnie: str) -> None:
        if compagnie and compagnie not in noms:
            noms.append(compagnie)

    for ligne in resultat.get("lignes") or []:
        ajouter(ligne.get("compagnie", ""))
    for trajet in resultat.get("correspondances") or []:
        ajouter(trajet["etape_1"].get("compagnie", ""))
        ajouter(trajet["etape_2"].get("compagnie", ""))
    for trajet in resultat.get("trajets_2") or []:
        for etape in trajet.get("etapes") or []:
            ajouter(etape.get("compagnie", ""))
    return " et ".join(libelle_compagnie(nom) for nom in noms) or "autres compagnies"


def message_autre_compagnie(compagnie: str, resultat: dict) -> str:
    """Le bandeau quand la compagnie demandée ne dessert pas le trajet."""
    return (
        f"Je n'ai pas trouvé de ligne {libelle_compagnie(compagnie)} pour ce trajet "
        f"dans mes données (même avec un changement). "
        f"Voici les lignes {autre_compagnie(resultat)} :"
    )
