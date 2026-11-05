r"""Audit du moteur d'itinéraires sur les lieux réels de Dakar.

Le script tire 300 paires de lieux de ``data/lieux_geo.csv`` (graine 7, en
sautant les paires à moins de 1,5 km), ajoute quatre trajets de référence,
puis résume la qualité des réponses.  Il écrit aussi un CSV dans
``data/audit/`` pour pouvoir relire les cas lents.

    .\.venv\Scripts\python.exe scripts\audit_itineraires.py
"""

from __future__ import annotations

import csv
import math
import random
import statistics
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from routing.data import NetworkData, load_data
from routing.network import Network, haversine_m
from routing.places import PlaceIndex, normalize_name
from routing.router import RouteEngine, RouteError, walking_minutes

GRAINE = 7
NB_PAIRES = 300
DISTANCE_MIN_M = 1_500.0
PAIRES_FIXES = (
    ("Ouakam", "Yoff"),
    ("Sahm", "Malika"),
    ("Parcelles Assainies", "UCAD"),
    ("Cambérène 2", "Sapeurs-Pompiers Parcelles"),
)
SORTIE = RACINE / "data" / "audit" / "audit_itineraires.csv"
COLONNES = (
    "origine",
    "destination",
    "type",
    "statut",
    "minutes",
    "distance_km",
    "min_par_km",
    "transferts",
    "marche",
    "absurde",
    "lignes",
    "erreur",
)


def lieux_avec_coordonnees(data: NetworkData) -> list[tuple[str, float, float]]:
    """Les lieux de ``lieux_geo.csv`` qui ont une position utilisable."""

    lieux: list[tuple[str, float, float]] = []
    for row in data.lieux.itertuples(index=False):
        try:
            lat = float(row.lat)
            lon = float(row.lon)
        except (TypeError, ValueError):
            continue
        if math.isnan(lat) or math.isnan(lon):
            continue
        lieux.append((str(row.lieu), lat, lon))
    return lieux


def paires_aleatoires(
    lieux: list[tuple[str, float, float]],
    nombre: int = NB_PAIRES,
) -> list[tuple[str, str]]:
    """Paires distinctes, séparées d'au moins 1,5 km, graine fixe."""

    random.seed(GRAINE)
    vues: set[tuple[str, str]] = set()
    paires: list[tuple[str, str]] = []
    tentatives = 0
    while len(paires) < nombre and tentatives < nombre * 200:
        tentatives += 1
        if len(lieux) < 2:
            break
        gauche, droite = random.sample(lieux, 2)
        cle = tuple(sorted((gauche[0], droite[0])))
        if cle in vues:
            continue
        distance = haversine_m((gauche[1], gauche[2]), (droite[1], droite[2]))
        if distance < DISTANCE_MIN_M:
            continue
        vues.add(cle)
        paires.append((gauche[0], droite[0]))
    return paires


def evaluer_paire(
    engine: RouteEngine,
    origine: str,
    destination: str,
    coords: dict[str, tuple[float, float]],
    type_paire: str = "aleatoire",
) -> dict[str, object]:
    """Une ligne d'audit : réponse, temps, distance et absurdité éventuelle."""

    resultat: dict[str, object] = {
        "origine": origine,
        "destination": destination,
        "type": type_paire,
        "statut": "echec",
        "minutes": "",
        "distance_km": "",
        "min_par_km": "",
        "transferts": "",
        "marche": False,
        "absurde": False,
        "lignes": "",
        "erreur": "",
    }

    try:
        trips = engine.find_trips(origine, destination, max_trips=3)
    except RouteError as exc:
        resultat["erreur"] = str(exc)
        return resultat
    if not trips:
        resultat["erreur"] = "aucun trajet"
        return resultat

    meilleur = trips[0]
    distance_m = meilleur.total_distance_m
    if distance_m is None or distance_m <= 0:
        distance_m = meilleur.straight_line_m
    distance_km = distance_m / 1_000.0 if distance_m else None
    min_par_km = (
        meilleur.total_minutes / distance_km
        if distance_km is not None and distance_km > 0
        else None
    )

    marche_seule = not meilleur.legs and len(meilleur.walks) == 1
    absurde = False
    depart = coords.get(normalize_name(origine))
    arrivee = coords.get(normalize_name(destination))
    if not marche_seule and depart is not None and arrivee is not None:
        temps_marche = walking_minutes(depart, arrivee)
        if temps_marche <= 40.0 and meilleur.total_minutes > 2.0 * temps_marche:
            absurde = True

    resultat.update(
        {
            "statut": "repondu",
            "minutes": round(meilleur.total_minutes, 1),
            "distance_km": (
                round(distance_km, 2) if distance_km is not None else ""
            ),
            "min_par_km": (
                round(min_par_km, 2) if min_par_km is not None else ""
            ),
            "transferts": meilleur.transfers,
            "marche": marche_seule,
            "absurde": absurde,
            "lignes": " | ".join(
                f"{leg.operator} {leg.line}" for leg in meilleur.legs
            ),
        }
    )
    return resultat


def _centile(valeurs: list[float], pourcent: float) -> float:
    """Centile simple, interpolation linéaire entre les deux voisins."""

    if not valeurs:
        return 0.0
    ordonnees = sorted(valeurs)
    if len(ordonnees) == 1:
        return ordonnees[0]
    rang = (len(ordonnees) - 1) * pourcent / 100.0
    bas = math.floor(rang)
    haut = math.ceil(rang)
    if bas == haut:
        return ordonnees[bas]
    return ordonnees[bas] + (ordonnees[haut] - ordonnees[bas]) * (rang - bas)


def resume(resultats: list[dict[str, object]]) -> None:
    """Affiche le résumé demandé et les 15 trajets les plus lents."""

    repondus = [item for item in resultats if item["statut"] == "repondu"]
    echecs = len(resultats) - len(repondus)
    print(
        f"Paires: {len(resultats)} | répondues: {len(repondus)} | "
        f"échecs: {echecs}"
    )
    if not repondus:
        return

    minutes = [float(item["minutes"]) for item in repondus]
    print(f"Temps moyen: {statistics.mean(minutes):.1f} min")

    min_km = [
        float(item["min_par_km"])
        for item in repondus
        if item["min_par_km"] != ""
    ]
    if min_km:
        print(
            "min/km: min {:.2f} | médiane {:.2f} | p75 {:.2f} | p90 {:.2f}".format(
                min(min_km),
                _centile(min_km, 50),
                _centile(min_km, 75),
                _centile(min_km, 90),
            )
        )

    for transferts in (0, 1, 2):
        nombre = sum(
            1 for item in repondus if item["transferts"] == transferts
        )
        print(
            f"  {transferts} correspondance(s): {nombre} "
            f"({100.0 * nombre / len(repondus):.1f} %)"
        )

    marche = sum(1 for item in repondus if item["marche"])
    absurdes = sum(1 for item in repondus if item["absurde"])
    print(f"Réponses à pied: {marche}")
    print(f"Réponses absurdes: {absurdes}")

    lents = sorted(
        repondus,
        key=lambda item: (
            float(item["min_par_km"]) if item["min_par_km"] != "" else -1.0
        ),
        reverse=True,
    )[:15]
    print("15 plus lents (min/km):")
    for item in lents:
        lignes = item["lignes"] or "à pied"
        print(
            f"  {item['origine']} -> {item['destination']}: "
            f"{item['minutes']} min, {item['min_par_km']} min/km, "
            f"{item['transferts']} corr., {lignes}"
        )


def main() -> int:
    data = load_data()
    lieux = lieux_avec_coordonnees(data)
    coords = {
        normalize_name(nom): (lat, lon) for nom, lat, lon in lieux
    }
    engine = RouteEngine(Network.from_data(data), PlaceIndex.from_data(data))

    paires = [
        ("aleatoire", origine, destination)
        for origine, destination in paires_aleatoires(lieux)
    ]
    if len(paires) < NB_PAIRES:
        print(
            f"Attention: seulement {len(paires)} paires aléatoires "
            f"sur {NB_PAIRES} demandées."
        )
    paires += [
        ("fixe", origine, destination)
        for origine, destination in PAIRES_FIXES
    ]

    resultats = []
    durees: list[tuple[float, str, str]] = []
    for type_paire, origine, destination in paires:
        debut = time.perf_counter()
        resultats.append(
            evaluer_paire(engine, origine, destination, coords, type_paire)
        )
        durees.append((time.perf_counter() - debut, origine, destination))

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    with SORTIE.open("w", encoding="utf-8-sig", newline="") as fichier:
        writer = csv.DictWriter(fichier, fieldnames=COLONNES)
        writer.writeheader()
        writer.writerows(resultats)

    resume(resultats)
    pire = max(durees)
    print(
        f"Temps de réponse: médiane {statistics.median(d[0] for d in durees):.2f} s | "
        f"pire {pire[0]:.2f} s ({pire[1]} -> {pire[2]})"
    )
    print(f"\nCSV: {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
