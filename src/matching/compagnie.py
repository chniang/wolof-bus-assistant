"""Choix de compagnie : étiquettes et message quand elle ne dessert pas le trajet.

Ce module ne porte que de la mise en forme de texte, sans dépendance lourde :
l'application Gradio et les tests locaux partagent donc exactement le même
bandeau, sans charger le modèle vocal.
"""

from __future__ import annotations

# Étiquettes courtes affichées à l'utilisateur ; le CSV et le bouton portent le
# nom complet (« Tata AFTU », « Dakar Dem Dikk »).
LIBELLES_COMPAGNIES = {"Tata AFTU": "Tata", "Dakar Dem Dikk": "Dem Dikk"}


# Lignes Dem Dikk dont l'itinéraire n'est pas sûr (audit du 12/11/2026,
# data/audit/fiabilite_rapport.md) : la 6 finit chez nous à Guédiawaye, la
# référence dit Cambérène 2 ; la 217 à l'Aéroport LSS, la référence dit Ouakam ;
# la 220 n'a que 62 % d'arrêts situés ; la 233 est réduite à ses deux terminus.
# Elles restent proposées, mais la carte le dit et elles passent toujours après
# une ligne confirmée qui fait le même trajet.
LIGNES_A_CONFIRMER = frozenset(
    ("Dakar Dem Dikk", f"Ligne {numero}") for numero in ("6", "217", "220", "233")
)
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
