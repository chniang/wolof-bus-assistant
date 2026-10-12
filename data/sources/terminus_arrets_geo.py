"""Localise les arrêts « terminus » restés introuvables dans data/arrets_geo.csv.

Un arrêt au bout d'une ligne n'a qu'un seul voisin : l'interpolation ne peut pas
l'estimer. Pour ces arrêts seulement :

1. on réessaie Nominatim sans le préfixe (« Lat Dior » pour « Gare Lat Dior ») ;
2. sinon, on prend la position du terminus correspondant : le nom officiel de
   data/lignes_dakar.csv, cherché d'abord parmi les arrêts déjà localisés, puis
   via Nominatim.

Les requêtes restent dans la région de Dakar (suffixe « , Dakar, Sénégal ») :
« Lat Dior, Sénégal » ramène sinon un stade de Thiès. Les arrêts « douteuse » ne
servent jamais de repère. Réécrit data/arrets_geo.csv et liste ce qui reste
introuvable.

Usage : python data/sources/terminus_arrets_geo.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
sys.path.insert(0, str(DATA.parent / "src"))

from geolocaliser_arrets import Nominatim, nettoyer_prefixes, SORTIE  # noqa: E402
from matching.lieux import score  # noqa: E402
COLONNES = ["arret", "lat", "lon", "quartier", "commune", "confiance"]


def charger() -> list[dict]:
    with open(SORTIE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ecrire(rangees: list[dict]) -> None:
    with open(SORTIE, "w", newline="", encoding="utf-8") as f:
        ecrivain = csv.DictWriter(f, fieldnames=COLONNES)
        ecrivain.writeheader()
        ecrivain.writerows({c: ligne.get(c, "") for c in COLONNES} for ligne in rangees)


def terminus_par_arret() -> dict[str, list[str]]:
    """Pour chaque arrêt terminus, le ou les noms de terminus officiels."""
    par_ligne: dict[tuple[str, str], list[tuple[float, str]]] = {}
    with open(DATA / "itineraires_dakar.csv", newline="", encoding="utf-8") as f:
        for rangee in csv.DictReader(f):
            par_ligne.setdefault((rangee["compagnie"], rangee["ligne"]), []).append(
                (float(rangee["ordre"]), rangee["arret"])
            )
    for arrets in par_ligne.values():
        arrets.sort()

    officiels = {}
    with open(DATA / "lignes_dakar.csv", newline="", encoding="utf-8") as f:
        for rangee in csv.DictReader(f):
            officiels[(rangee["compagnie"], rangee["ligne"])] = rangee

    resultat: dict[str, list[str]] = {}
    for cle, arrets in par_ligne.items():
        info = officiels.get(cle)
        if not info or not arrets:
            continue
        for index, cote in ((0, "terminus_a"), (len(arrets) - 1, "terminus_b")):
            arret, nom = arrets[index][1], info[cote]
            if nom and nom not in resultat.setdefault(arret, []):
                resultat[arret].append(nom)
    return resultat


def arret_connu(nom: str, connus: dict[str, dict]) -> dict | None:
    """Arrêt déjà localisé dont le nom correspond au terminus demandé."""
    if nom in connus:
        return connus[nom]
    meilleur, meilleur_score = None, 0.0
    for arret, ligne in connus.items():
        valeur = score(nom, arret)
        if valeur > meilleur_score:
            meilleur, meilleur_score = ligne, valeur
    return meilleur if meilleur_score >= 0.75 else None


def main() -> None:
    rangees = charger()
    connus = {
        ligne["arret"]: ligne
        for ligne in rangees
        if ligne["lat"] and ligne["confiance"] not in ("introuvable", "douteuse")
    }
    terminus = terminus_par_arret()
    client = Nominatim()

    introuvables = [ligne for ligne in rangees if ligne["confiance"] == "introuvable"]
    resolus: dict[str, str] = {}

    for ligne in introuvables:
        arret = ligne["arret"]
        noms = terminus.get(arret)
        if not noms:
            continue  # arrêt intérieur à la ligne : rien de plus à tenter

        position = None
        methode = ""

        # 1) Nominatim sans le préfixe.
        sans_prefixe = nettoyer_prefixes(arret).strip()
        if sans_prefixe and sans_prefixe != arret:
            info = client.geocode(f"{sans_prefixe}, Dakar, Sénégal")
            if info and info.get("trouve"):
                position = (info["lat"], info["lon"], info.get("quartier", ""), info.get("commune", ""))
                methode = f"sans préfixe « {sans_prefixe} » (Nominatim)"

        # 2) Position du terminus correspondant.
        if position is None:
            for nom in noms:
                cible = arret_connu(nom, connus)
                if cible:
                    position = (cible["lat"], cible["lon"], cible.get("quartier", ""), cible.get("commune", ""))
                    methode = f"terminus « {nom} » = arrêt {cible['arret']!r} déjà localisé"
                    break
                info = client.geocode(f"{nom}, Dakar, Sénégal")
                if info and info.get("trouve"):
                    position = (info["lat"], info["lon"], info.get("quartier", ""), info.get("commune", ""))
                    methode = f"terminus « {nom} » (Nominatim)"
                    break

        if position is None:
            continue

        lat, lon, quartier, commune = position
        if not (quartier or commune):
            inverse = client.reverse(float(lat), float(lon)) or {}
            if inverse.get("trouve"):
                quartier, commune = inverse.get("quartier", ""), inverse.get("commune", "")
        ligne["lat"], ligne["lon"] = f"{float(lat):.6f}", f"{float(lon):.6f}"
        ligne["quartier"] = quartier or ligne.get("quartier", "")
        ligne["commune"] = commune or ligne.get("commune", "")
        ligne["confiance"] = "estimee"
        connus[arret] = ligne
        resolus[arret] = methode

    ecrire(rangees)

    restants = [ligne["arret"] for ligne in rangees if ligne["confiance"] == "introuvable"]
    print("=== Terminus introuvables ===")
    print(f"au départ           : {len(introuvables)}")
    print(f"résolus             : {len(resolus)}")
    for arret, methode in resolus.items():
        print(f"  + {arret} : {methode}")
    print(f"encore introuvables : {len(restants)}")
    for arret in restants:
        print(f"  - {arret}")
    print(f"\n{client.requetes} requêtes Nominatim cette exécution")


if __name__ == "__main__":
    main()
