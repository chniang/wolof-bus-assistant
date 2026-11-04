r"""Télécharge les tracés officiels des lignes AFTU (Tata) publiés sur aftu-senegal.org.

Chaque page de ligne (https://aftu-senegal.org/map/<slug>/) contient, dans son code,
la carte Waymark au format GeoJSON : le tracé de la ligne et ses terminus.
On récupère la liste des pages dans les sitemaps du site, puis on extrait le GeoJSON
de chaque page.

Utilisation (depuis le dossier du projet) :
    .\.venv\Scripts\python.exe telecharger_traces_aftu.py

Résultat : un dossier aftu_traces/ avec un .geojson par ligne, un index.csv,
et un fichier aftu_traces.zip à m'envoyer.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import time
import urllib.request
from pathlib import Path

SITE = "https://aftu-senegal.org"
SORTIE = Path("aftu_traces")
PAUSE_S = 2.0  # on reste poli avec le site : une page toutes les 2 secondes
ENTETES = {"User-Agent": "GuindiMa-AI/1.0 (projet etudiant, assistant vocal wolof)"}


def lire(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(req, timeout=30) as rep:
            return rep.read().decode("utf-8", errors="replace")
    except Exception as err:  # page absente ou site lent : on continue
        print(f"  (rien à {url} : {err})")
        return None


def pages_de_lignes() -> list[str]:
    """Toutes les URL /map/... trouvées dans les sitemaps du site."""
    a_lire = [f"{SITE}/sitemap_index.xml", f"{SITE}/wp-sitemap.xml"]
    vus, pages = set(), set()
    while a_lire:
        url = a_lire.pop()
        if url in vus:
            continue
        vus.add(url)
        xml = lire(url)
        time.sleep(PAUSE_S)
        if not xml:
            continue
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
            if loc.endswith(".xml"):
                a_lire.append(loc)
            elif "/map/" in loc:
                pages.add(loc.rstrip("/") + "/")
    if not pages:
        # Plan B si les sitemaps sont fermés : on essaie les adresses habituelles.
        print("Sitemaps vides : on teste dakar-urbain-ligne-1 à 120.")
        pages = {f"{SITE}/map/dakar-urbain-ligne-{n}/" for n in range(1, 121)}
    return sorted(pages)


def extraire_geojson(html: str) -> dict | None:
    """Le premier FeatureCollection du code de la page, accolades équilibrées."""
    i = html.find("FeatureCollection")
    if i < 0:
        return None
    debut = html.rfind("{", 0, i)
    profondeur = 0
    for j in range(debut, len(html)):
        if html[j] == "{":
            profondeur += 1
        elif html[j] == "}":
            profondeur -= 1
            if profondeur == 0:
                brut = html[debut : j + 1].replace("\\/", "/")
                try:
                    return json.loads(brut)
                except json.JSONDecodeError:
                    return None
    return None


def longueur_km(coords: list) -> float:
    total = 0.0
    for (lo1, la1), (lo2, la2) in zip(coords, coords[1:]):
        p1, p2 = math.radians(la1), math.radians(la2)
        h = (
            math.sin((p2 - p1) / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
        )
        total += 2 * 6371 * math.asin(math.sqrt(h))
    return total


def main() -> None:
    SORTIE.mkdir(exist_ok=True)
    pages = pages_de_lignes()
    print(f"{len(pages)} pages de lignes à lire.")
    lignes_index = []
    for n, url in enumerate(pages, 1):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        html = lire(url)
        time.sleep(PAUSE_S)
        if not html:
            continue
        titre = re.search(r"<title>(.*?)</title>", html, re.S)
        titre = titre.group(1).strip() if titre else ""
        itin = re.search(r'property="og:description" content="([^"]*)"', html)
        fc = extraire_geojson(html)
        if fc is None:
            print(f"[{n}/{len(pages)}] {slug} : pas de tracé")
            lignes_index.append([slug, titre, 0, 0, "", itin.group(1) if itin else ""])
            continue
        (SORTIE / f"{slug}.geojson").write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        traces = [f for f in fc.get("features", []) if f["geometry"]["type"] == "LineString"]
        points = sum(len(f["geometry"]["coordinates"]) for f in traces)
        km = sum(longueur_km(f["geometry"]["coordinates"]) for f in traces)
        terminus = " | ".join(
            (f.get("properties") or {}).get("title", "")
            for f in fc.get("features", [])
            if f["geometry"]["type"] == "Point"
        )
        print(f"[{n}/{len(pages)}] {slug} : {points} points, {km:.1f} km")
        lignes_index.append([slug, titre, points, round(km, 2), terminus, itin.group(1) if itin else ""])

    with open(SORTIE / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["slug", "titre", "points_trace", "longueur_km", "terminus", "itineraire_texte"])
        w.writerows(lignes_index)
    shutil.make_archive("aftu_traces", "zip", SORTIE)
    ok = sum(1 for l in lignes_index if l[2])
    print(f"\nFini : {ok} tracés sur {len(lignes_index)} pages. Envoie-moi aftu_traces.zip.")


if __name__ == "__main__":
    main()
