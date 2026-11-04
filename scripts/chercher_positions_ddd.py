r"""Cherche dans OpenStreetMap (Nominatim) les positions possibles des arrêts Dem Dikk.

Pour chaque arrêt de ddd_itineraires_officiels.csv, on garde jusqu'à 5 candidats dans la
région de Dakar. On ne choisit pas ici : le bon candidat sera celui qui garde la ligne
cohérente avec ses arrêts voisins (vérification faite ensuite).

Règles d'usage de Nominatim respectées : 1 requête par seconde, application identifiée,
résultats mis en cache (on peut relancer le script sans tout redemander).

Utilisation (ddd_itineraires_officiels.csv dans le même dossier) :
    .\.venv\Scripts\python.exe chercher_positions_ddd.py

Résultat : positions_ddd_candidats.json, à m'envoyer. Durée : environ 10 minutes.
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENTREE = Path("ddd_itineraires_officiels.csv")
SORTIE = Path("positions_ddd_candidats.json")
URL = "https://nominatim.openstreetmap.org/search"
ENTETES = {"User-Agent": "GuindiMa-AI/1.0 (projet etudiant, assistant vocal wolof)"}
# Région de Dakar : ouest, nord, est, sud
VIEWBOX = "-17.56,14.90,-17.10,14.55"


def nettoyer(nom: str) -> str:
    nom = re.sub(r"(?i)\b(terminus|termibus|arr[eê]t)\b", " ", nom)
    nom = nom.replace("’", "'").strip(" ()-–.")
    return re.sub(r"\s+", " ", nom).strip()


def chercher(texte: str) -> list[dict]:
    params = {
        "q": texte,
        "format": "jsonv2",
        "limit": 5,
        "countrycodes": "sn",
        "viewbox": VIEWBOX,
        "bounded": 1,
        "addressdetails": 1,
    }
    req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params), headers=ENTETES)
    with urllib.request.urlopen(req, timeout=30) as rep:
        res = json.loads(rep.read().decode("utf-8"))
    return [
        {
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "nom": r.get("display_name", ""),
            "type": f"{r.get('category', '')}/{r.get('type', '')}",
        }
        for r in res
    ]


def main() -> None:
    arrets = sorted({r["arret"] for r in csv.DictReader(open(ENTREE, encoding="utf-8"))})
    cache = json.loads(SORTIE.read_text(encoding="utf-8")) if SORTIE.exists() else {}
    a_faire = [a for a in arrets if a not in cache]
    print(f"{len(arrets)} arrêts, {len(a_faire)} à chercher.")
    for i, arret in enumerate(a_faire, 1):
        texte = nettoyer(arret)
        candidats = []
        for requete in (f"{texte}, Dakar", texte):
            try:
                candidats = chercher(requete)
            except Exception as err:
                print(f"  erreur sur {arret} : {err}")
                time.sleep(5)
            time.sleep(1.1)
            if candidats:
                break
        cache[arret] = {"recherche": texte, "candidats": candidats}
        if i % 20 == 0 or i == len(a_faire):
            SORTIE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            trouves = sum(1 for v in cache.values() if v["candidats"])
            print(f"[{i}/{len(a_faire)}] {trouves} arrêts avec au moins un candidat")
    print(f"\nFini. Envoie-moi {SORTIE}.")


if __name__ == "__main__":
    main()
