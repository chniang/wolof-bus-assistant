r"""Télécharge depuis OpenStreetMap les lignes de bus et les arrêts de la région de Dakar.

Deux requêtes à l'API Overpass (gratuite, données libres © OpenStreetMap, licence ODbL) :
1. toutes les lignes de bus (relations route=bus), avec leurs arrêts et leur tracé ;
2. tous les arrêts de bus (highway=bus_stop et public_transport=platform), avec leur nom.

Utilisation (depuis le dossier du projet) :
    .\.venv\Scripts\python.exe telecharger_osm_bus.py

Résultat : osm_bus_dakar.zip, à m'envoyer.
"""

from __future__ import annotations

import csv
import json
import shutil
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

# Région de Dakar, de Ngor à Diamniadio / Bambilor (sud, ouest, nord, est)
BBOX = "14.55,-17.56,14.90,-17.10"
SERVEURS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
ENTETES = {"User-Agent": "GuindiMa-AI/1.0 (projet etudiant, assistant vocal wolof)"}
SORTIE = Path("osm_bus_dakar")

REQ_LIGNES = f"""
[out:json][timeout:300];
relation["route"="bus"]({BBOX});
out geom;
"""

REQ_ARRETS = f"""
[out:json][timeout:300];
(
  node["highway"="bus_stop"]({BBOX});
  node["public_transport"="platform"]({BBOX});
  node["public_transport"="stop_position"]({BBOX});
);
out body;
"""


def overpass(requete: str) -> dict:
    corps = urllib.parse.urlencode({"data": requete}).encode()
    for url in SERVEURS:
        for essai in range(3):
            try:
                req = urllib.request.Request(url, data=corps, headers=ENTETES)
                with urllib.request.urlopen(req, timeout=360) as rep:
                    return json.loads(rep.read().decode("utf-8"))
            except Exception as err:
                print(f"  {url} essai {essai + 1} : {err}")
                time.sleep(20)
    raise SystemExit("Overpass ne répond pas. Réessaie dans un moment.")


def main() -> None:
    SORTIE.mkdir(exist_ok=True)

    print("1/2 Lignes de bus…")
    lignes = overpass(REQ_LIGNES)
    (SORTIE / "lignes_osm.json").write_text(json.dumps(lignes, ensure_ascii=False), encoding="utf-8")
    rels = [e for e in lignes.get("elements", []) if e["type"] == "relation"]
    with open(SORTIE / "lignes_osm.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["osm_id", "ref", "name", "network", "operator", "from", "to", "nb_arrets", "nb_troncons"])
        for r in rels:
            t = r.get("tags", {})
            membres = r.get("members", [])
            arrets = [m for m in membres if m["type"] == "node"]
            troncons = [m for m in membres if m["type"] == "way"]
            w.writerow([r["id"], t.get("ref", ""), t.get("name", ""), t.get("network", ""),
                        t.get("operator", ""), t.get("from", ""), t.get("to", ""), len(arrets), len(troncons)])
    reseaux = Counter((r.get("tags", {}).get("operator") or r.get("tags", {}).get("network") or "?") for r in rels)
    print(f"   {len(rels)} lignes trouvées. Par opérateur : {dict(reseaux.most_common(10))}")
    time.sleep(10)

    print("2/2 Arrêts de bus…")
    arrets = overpass(REQ_ARRETS)
    noeuds = [e for e in arrets.get("elements", []) if e["type"] == "node"]
    with open(SORTIE / "arrets_osm.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["osm_id", "name", "lat", "lon", "highway", "public_transport", "operator", "network", "route_ref"])
        for n in noeuds:
            t = n.get("tags", {})
            w.writerow([n["id"], t.get("name", ""), n["lat"], n["lon"], t.get("highway", ""),
                        t.get("public_transport", ""), t.get("operator", ""), t.get("network", ""),
                        t.get("route_ref", "")])
    nommes = sum(1 for n in noeuds if n.get("tags", {}).get("name"))
    print(f"   {len(noeuds)} arrêts, dont {nommes} avec un nom.")

    shutil.make_archive("osm_bus_dakar", "zip", SORTIE)
    print("\nFini. Envoie-moi osm_bus_dakar.zip.")


if __name__ == "__main__":
    main()
