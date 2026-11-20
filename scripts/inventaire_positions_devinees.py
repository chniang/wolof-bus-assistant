"""Inventaire des positions d'arrêts non mesurées, et positions fiables déjà dans le dépôt.

Lot F4. AUCUN réseau : on lit les CSV du dépôt et le réseau tel que le moteur v2
le construit en mémoire (src/routing/adapter.py). Rien n'est écrit dans les CSV
existants ; le script produit seulement :

- data/audit/positions_devinees.csv : chaque arrêt d'une ligne dont la position
  sur cette ligne n'est pas mesurée (interpolée à vue, géocodée, inconnue), ou
  « bonne » mais loin de tous ses voisins (homonyme géocodé ailleurs) ;
- data/audit/positions_candidates.csv : pour ces arrêts, une position fiable
  trouvée ailleurs dans le dépôt, et si elle est cohérente avec la ligne.

Sources fiables admises (jamais un géocodage) :
- un arrêt OSM nommé (data/sources/osm_bus_dakar/arrets_osm.csv), si tous les
  arrêts OSM de ce nom tiennent dans 300 m ;
- un arrêt identique de confiance « bonne » dans data/arrets_geo.csv, que
  matching/geo.py ne juge pas douteux.

Cohérence : sur CHAQUE ligne qui dessert l'arrêt, entre ses deux voisins
mesurés, le détour par la position candidate ne dépasse pas 1,5 fois la
distance directe + 1 km ; avec un seul voisin mesuré, la candidate est à moins
de 3 km de lui. Un nom de quartier ou de commune (lieux_geo.csv : « Médina »,
« Rufisque ») n'est jamais situé par un arrêt du même nom : il couvre une zone.

Avec --ecrire, les candidates retenues (cohérentes, hors noms de zone) et le
repère de l'AIBD sont écrits dans data/corrections/positions_corrigees.csv,
que l'app charge en mémoire. Ce fichier est nouveau : aucun CSV existant n'est
touché.

Usage (PowerShell) :
    $env:PYTHONIOENCODING='utf-8'
    .\\.venv\\Scripts\\python.exe scripts\\inventaire_positions_devinees.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from matching.geo import arrets_non_fiables  # noqa: E402
from matching.itineraires_app import rangees_ddd_officielles  # noqa: E402
from routing import adapter  # noqa: E402
from routing.network import haversine_m  # noqa: E402
from routing.places import normalize_name  # noqa: E402

DATA = RACINE / "data"
SORTIE_INVENTAIRE = DATA / "audit" / "positions_devinees.csv"
SORTIE_CANDIDATES = DATA / "audit" / "positions_candidates.csv"
OSM = DATA / "sources" / "osm_bus_dakar" / "arrets_osm.csv"
TATA = DATA / "corrections" / "corrections_geo_tata_proposees.csv"
ARRETS_GEO = DATA / "arrets_geo.csv"
LIEUX_GEO = DATA / "lieux_geo.csv"
SORTIE_CORRIGEES = DATA / "corrections" / "positions_corrigees.csv"
DATE = "2026-11-20"

# Noms différents, même arrêt : liens revus un par un.
# - « Rond point JVC » (Dem Dikk 319) : l'arrêt OSM « Arret JVC » (deux nœuds à
#   10 m) est au rond-point JVC ; notre point était interpolé à vue.
# - « Croisement Tivaouane Peulh » : l'arrêt OSM « Croisement tivavouane Peulh »
#   (faute d'OSM). arrets_geo.csv le met à 1,6 km au nord, au même point que
#   « Apix » de la 327 (géocodage « Croisement Apix »).
LIENS_OSM = {
    "Rond point JVC": "Arret JVC",
    "Croisement Tivaouane Peulh": "Croisement tivavouane Peulh",
    "Croissement Tivaoune Peulh": "Croisement tivavouane Peulh",
}
# AIBD : arrets_geo.csv et lieux_geo.csv la placent à Grand Yoff (« bonne »,
# fausse). Le repère de Diass est celui que le TAF TAF utilise déjà
# (corrections_geo_ddd_proposees.csv, source repere_connu).
AIBD = ("AIBD", 14.67, -17.0733, "repere_connu",
        "Aéroport International Blaise Diagne (Diass), repère du TAF TAF")
# Liens retenus malgré le contrôle de cohérence, avec la raison.
# - « Croissement Tivaoune Peulh » (Dem Dikk 227 et 327) : la 311 place déjà ce
#   même nom à l'arrêt OSM. La 327 fait l'aller-retour Keur Massar -> Tivaouane
#   Peulh -> Malika : le détour par le croisement est réel, pas une erreur.
FORCES = {
    "Croissement Tivaoune Peulh": "même nom déjà à l'arrêt OSM sur la Dem Dikk 311 ; "
    "aller-retour réel de la 327 vers Tivaouane Peulh",
}
# Voies longues : une position « bonne » n'y est qu'un point quelconque de la
# voie (Avenue Cheikh Anta Diop : 5 km, de Fann à Ouakam). Jamais situées par
# leur nom, comme les noms génériques de matching/geo.py.
MOTS_DE_VOIE = {"route", "avenue", "av", "boulevard", "bd", "bld", "rue", "rocade",
                "autoroute", "corniche", "allees", "voie", "nationale"}

GROUPE_OSM_M = 300.0
SEUIL_HOMONYME_M = 3_000.0
UN_VOISIN_MAX_M = 3_000.0


def _lire(chemin: Path) -> list[dict]:
    with open(chemin, newline="", encoding="utf-8-sig") as fichier:
        return list(csv.DictReader(fichier))


def sources_par_ligne() -> dict[tuple[str, str], dict[int, str]]:
    """(compagnie, ligne) -> ordre -> source de la position (fichiers de corrections)."""
    sources: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    for r in _lire(TATA):
        sources[(r["compagnie"], r["ligne"])][int(float(r["ordre"]))] = r["source"]
    for r in rangees_ddd_officielles():
        sources[(r["compagnie"], r["ligne"])][int(float(r["ordre"]))] = r["source"] or "inconnu"
    for (compagnie, ligne), rangees in adapter._DATA.itineraires.groupby(["compagnie", "ligne"]):
        cle = (str(compagnie), str(ligne))
        for ordre in rangees["ordre"]:
            sources[cle].setdefault(int(ordre), "arrets_geo")
    return sources


def ordres_par_ligne() -> dict[tuple[str, str], list[int]]:
    ordres = {}
    for (compagnie, ligne), rangees in adapter._DATA.itineraires.groupby(["compagnie", "ligne"]):
        ordres[(str(compagnie), str(ligne))] = [int(o) for o in rangees.sort_values("ordre")["ordre"]]
    return ordres


def voisins_mesures(ligne, index: int) -> tuple[tuple | None, tuple | None]:
    """Positions du voisin mesuré précédent et suivant sur la ligne."""
    reseau = adapter._NETWORK

    def cherche(pas: int):
        j = index + pas
        while 0 <= j < len(ligne.stops):
            if reseau.position_sure(ligne, j) and reseau.position_on_line(ligne, j) is not None:
                return reseau.position_on_line(ligne, j)
            j += pas
        return None

    return cherche(-1), cherche(1)


def coherente(candidate, avant, apres) -> bool:
    if avant is not None and apres is not None:
        direct = haversine_m(avant, apres)
        detour = haversine_m(avant, candidate) + haversine_m(candidate, apres)
        return detour <= 1.5 * direct + 1_000.0
    seul = avant or apres
    return seul is not None and haversine_m(seul, candidate) <= UN_VOISIN_MAX_M


def positions_osm() -> dict[str, tuple[float, float]]:
    """Nom normalisé -> centre des arrêts OSM de ce nom, s'ils tiennent dans 300 m."""
    groupes: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in _lire(OSM):
        nom = normalize_name(r.get("name", ""))
        if nom and r.get("lat") and r.get("lon"):
            groupes[nom].append((float(r["lat"]), float(r["lon"])))
    centres = {}
    for nom, points in groupes.items():
        if all(haversine_m(a, b) <= GROUPE_OSM_M for a in points for b in points):
            centres[nom] = (
                round(sum(p[0] for p in points) / len(points), 6),
                round(sum(p[1] for p in points) / len(points), 6),
            )
    return centres


def noms_de_zone() -> set[str]:
    """Quartiers et communes de lieux_geo.csv : une zone, pas un arrêt."""
    return {normalize_name(r["lieu"]) for r in _lire(LIEUX_GEO)}


def sans_parenthese(nom: str) -> str:
    """« Maristes (Par Station Titan) » -> « maristes » (forme normalisée)."""
    import re

    return normalize_name(re.sub(r"\([^)]*\)", " ", nom))


def positions_bonnes() -> dict[str, tuple[str, tuple[float, float]]]:
    """Nom normalisé -> (nom, position) des arrêts « bonne » qu'aucune règle de geo.py n'écarte."""
    ecartes = arrets_non_fiables()
    bonnes = {}
    for r in _lire(ARRETS_GEO):
        if r.get("confiance") == "bonne" and r.get("lat") and r["arret"] not in ecartes:
            bonnes.setdefault(normalize_name(r["arret"]), (r["arret"], (float(r["lat"]), float(r["lon"]))))
    return bonnes


def main() -> None:
    reseau = adapter._NETWORK
    sources = sources_par_ligne()
    ordres = ordres_par_ligne()
    osm = positions_osm()
    bonnes = positions_bonnes()

    inventaire: list[dict] = []
    for cle, ligne in sorted(reseau.lines.items()):
        ordre_ligne = ordres.get(cle, [])
        for index, arret in enumerate(ligne.stops):
            position = reseau.position_on_line(ligne, index)
            sure = reseau.position_sure(ligne, index)
            avant, apres = voisins_mesures(ligne, index)
            distances = [haversine_m(position, v) for v in (avant, apres) if v is not None and position is not None]
            voisin_m = round(min(distances)) if distances else ""
            ordre = ordre_ligne[index] if len(ordre_ligne) == len(ligne.stops) else None
            source = sources.get(cle, {}).get(ordre, "") if ordre is not None else ""
            motif = ""
            if position is None:
                motif = "sans position"
            elif not sure:
                motif = "non mesurée"
            elif 0 < index < len(ligne.stops) - 1 and distances and min(distances) > SEUIL_HOMONYME_M:
                motif = "mesurée mais loin de ses voisins mesurés"
            if not motif:
                continue
            inventaire.append({
                "compagnie": cle[0], "ligne": cle[1], "index": index, "arret": arret,
                "lat": f"{position[0]:.6f}" if position else "", "lon": f"{position[1]:.6f}" if position else "",
                "source": source, "motif": motif, "distance_voisin_mesure_m": voisin_m,
                "confiance_arrets_geo": reseau.stop_confidence.get(arret, ""),
            })

    # Candidates, arrêt par arrêt : la même position doit convenir à CHAQUE
    # ligne qui dessert l'arrêt (le fichier de corrections vaut pour toutes).
    par_arret: dict[str, list[dict]] = defaultdict(list)
    for rangee in inventaire:
        par_arret[rangee["arret"]].append(rangee)
    zones = noms_de_zone()
    osm_bruts = {normalize_name(nom): nom for nom in LIENS_OSM.values()}
    candidates = []
    for arret, rangees in sorted(par_arret.items()):
        nom = normalize_name(arret)
        base = sans_parenthese(arret)
        trouvees = []
        if arret in LIENS_OSM and normalize_name(LIENS_OSM[arret]) in osm:
            trouvees.append(("osm_arret_nomme", osm[normalize_name(LIENS_OSM[arret])],
                             f"arrets_osm.csv « {LIENS_OSM[arret]} » (lien revu)"))
        for cle in dict.fromkeys((nom, base)):
            if cle in osm and cle not in osm_bruts:
                trouvees.append(("osm_arret_nomme", osm[cle], "arrets_osm.csv (même nom)"))
            if cle in bonnes:
                trouvees.append(("arret_identique_bonne", bonnes[cle][1], f"arrets_geo.csv « {bonnes[cle][0]} »"))
        for source, point, detail in trouvees:
            refus = []
            for cle_ligne, ligne in reseau.lines.items():
                for index, stop in enumerate(ligne.stops):
                    if stop != arret:
                        continue
                    avant, apres = voisins_mesures(ligne, index)
                    if not coherente(point, avant, apres):
                        refus.append(cle_ligne[1])
            zone = nom in zones or base in zones
            voie = bool(MOTS_DE_VOIE & set(nom.split()))
            force = arret in FORCES and source == "osm_arret_nomme"
            candidates.append({
                "arret": arret, "lat": point[0], "lon": point[1], "source": source, "detail": detail,
                "lignes": " ; ".join(sorted({r["ligne"] for r in rangees})),
                "coherente": "oui" if not refus else "non",
                "lignes_incoherentes": " ; ".join(sorted(set(refus))),
                "nom_de_zone": "oui" if zone else "non",
                "nom_de_voie": "oui" if voie else "non",
                "retenue": "oui" if force or (not refus and not zone and not voie) else "non",
                "remarque": FORCES[arret] if force else "",
            })

    if "--ecrire" in sys.argv:
        retenues, vus = [], set()
        for c in candidates:
            if c["retenue"] == "oui" and c["arret"] not in vus:
                vus.add(c["arret"])
                retenues.append({"arret": c["arret"], "lat": c["lat"], "lon": c["lon"],
                                 "source": f"{c['source']} : {c['detail']}", "date": DATE})
        retenues.append({"arret": AIBD[0], "lat": AIBD[1], "lon": AIBD[2],
                         "source": f"{AIBD[3]} : {AIBD[4]}", "date": DATE})
        # Fusion avec le fichier existant : une fois appliquée, une correction
        # rend l'arrêt « mesuré » et il sort de l'inventaire ; le relancer ne
        # doit pas l'effacer.
        if SORTIE_CORRIGEES.exists():
            nouveaux = {r["arret"] for r in retenues}
            retenues += [r for r in _lire(SORTIE_CORRIGEES) if r["arret"] not in nouveaux]
        with open(SORTIE_CORRIGEES, "w", newline="", encoding="utf-8") as fichier:
            ecrivain = csv.DictWriter(fichier, fieldnames=["arret", "lat", "lon", "source", "date"])
            ecrivain.writeheader()
            ecrivain.writerows(sorted(retenues, key=lambda r: r["arret"]))
        print(f"{len(retenues)} positions corrigées -> {SORTIE_CORRIGEES.relative_to(RACINE)}")

    for chemin, lignes in ((SORTIE_INVENTAIRE, inventaire), (SORTIE_CANDIDATES, candidates)):
        with open(chemin, "w", newline="", encoding="utf-8") as fichier:
            if lignes:
                ecrivain = csv.DictWriter(fichier, fieldnames=list(lignes[0]))
                ecrivain.writeheader()
                ecrivain.writerows(lignes)
    print(f"{len(inventaire)} positions non mesurées -> {SORTIE_INVENTAIRE.relative_to(RACINE)}")
    print(f"{len(candidates)} candidates ({sum(c['coherente'] == 'oui' for c in candidates)} cohérentes)"
          f" -> {SORTIE_CANDIDATES.relative_to(RACINE)}")


if __name__ == "__main__":
    main()
