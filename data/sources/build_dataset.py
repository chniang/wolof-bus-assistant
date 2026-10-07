r"""Construit data/itineraires_dakar.csv à partir des sources relevées.

    python data/sources/build_dataset.py

Entrées (dans data/) :
- lignes_dakar.csv : toutes les lignes DDD et AFTU avec leurs terminus officiels ;
- sources/aftu_itineraires_2026-10-07.txt : itinéraires officiels AFTU ;
- sources/ddd_itineraires.txt : arrêts DDD relevés dans OpenStreetMap.

Sortie : data/itineraires_dakar.csv (compagnie, ligne, ordre, arret), une ligne
par arrêt, terminus compris. Une ligne sans itinéraire connu n'a que ses deux
terminus : on peut toujours la trouver d'un bout à l'autre.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA.parent / "src"))

from matching.lieux import joli, score  # noqa: E402

# Les tirets séparent les arrêts, sauf dans les noms composés (« YOFF-VILLAGE »,
# « ROND-POINT ») : un tiret ne coupe que s'il est entouré d'au moins une espace,
# le tiret long (–) coupe toujours.
SEPARATEUR = re.compile(r"\s*–+\s*|\s+-+\s*|\s*-+\s+")
# Morceaux coupés à tort dans la source (« LAT - DIOR », « CASE - BA »).
A_RECOLLER = {("lat", "dior"), ("case", "ba"), ("rond", "point"), ("grand", "yoff")}


def decouper(itineraire: str) -> list[str]:
    morceaux = [m.strip(" .") for m in SEPARATEUR.split(itineraire)]
    morceaux = [m for m in morceaux if m and not re.fullmatch(r"[\d\s:]+", m)]
    sortie: list[str] = []
    for morceau in morceaux:
        if sortie:
            precedent = sortie[-1].lower().split()[-1] if sortie[-1].split() else ""
            premier = morceau.lower().split()[0]
            if (precedent, premier) in A_RECOLLER and len(sortie[-1].split()) <= 2:
                sortie[-1] = f"{sortie[-1]}-{morceau}" if precedent == "rond" else f"{sortie[-1]} {morceau}"
                continue
        sortie.append(morceau)
    return [joli(m) for m in sortie]


def proche(x: str, y: str) -> float:
    """Ressemblance symétrique de deux noms d'arrêt (0 si on ne les confond pas)."""
    valeur = max(score(x, y), score(y, x))
    return valeur if valeur >= 0.6 else 0.0


def lire_sources(chemin: Path) -> dict[str, str]:
    sources = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne.strip() or ligne.startswith("#"):
            continue
        cle, _, texte = ligne.partition("|")
        sources[cle.strip()] = texte.strip()
    return sources


def main() -> None:
    with open(DATA / "lignes_dakar.csv", newline="", encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))
    aftu = lire_sources(DATA / "sources" / "aftu_itineraires_2026-10-07.txt")
    ddd = lire_sources(DATA / "sources" / "ddd_itineraires.txt")

    lignes_sortie = []
    for ligne in lignes:
        if ligne["compagnie"] == "Tata AFTU":
            texte = aftu.get(re.sub(r"\D", "", ligne["ligne"]), "")
            arrets = decouper(texte) if texte else []
        else:
            texte = ddd.get(ligne["ligne"], "")
            arrets = [a.strip() for a in texte.split(" - ")] if texte else []

        # Les terminus officiels encadrent toujours la liste, dans le sens
        # terminus_a -> terminus_b. Certaines pages AFTU décrivent l'itinéraire
        # dans l'autre sens : on le retourne d'abord.
        a, b = ligne["terminus_a"], ligne["terminus_b"]
        if arrets:
            direct = proche(arrets[0], a) + proche(arrets[-1], b)
            inverse = proche(arrets[0], b) + proche(arrets[-1], a)
            if inverse > direct:
                arrets.reverse()
        # Quand le terminus officiel est déjà en tête de liste, on garde la forme
        # la plus complète : « Gadaye (Guédiawaye) » plutôt que « Gadaye ».
        if arrets and proche(arrets[0], a):
            arrets[0] = max(arrets[0], a, key=len)
        else:
            arrets.insert(0, a)
        if proche(arrets[-1], b):
            arrets[-1] = max(arrets[-1], b, key=len)
        else:
            arrets.append(b)
        for ordre, arret in enumerate(arrets, start=1):
            lignes_sortie.append(
                {"compagnie": ligne["compagnie"], "ligne": ligne["ligne"], "ordre": ordre, "arret": arret}
            )

    with open(DATA / "itineraires_dakar.csv", "w", newline="", encoding="utf-8") as f:
        ecrivain = csv.DictWriter(f, fieldnames=["compagnie", "ligne", "ordre", "arret"])
        ecrivain.writeheader()
        ecrivain.writerows(lignes_sortie)
    print(f"{len(lignes)} lignes, {len(lignes_sortie)} arrêts -> data/itineraires_dakar.csv")


if __name__ == "__main__":
    main()
