"""Géolocalise les arrêts du réseau avec Nominatim (OpenStreetMap).

Pour chaque arrêt unique de data/itineraires_dakar.csv, on interroge Nominatim,
on garde latitude, longitude, quartier et commune, puis on écrit
data/arrets_geo.csv. Aucun CSV existant ni la recherche de ligne n'est modifié.

Robustesse de la recherche :
  - plusieurs requêtes avant d'abandonner un arrêt : nom nettoyé des préfixes
    (« Giratoire de Liberté VI » -> « Liberté 6 »), chiffres romains convertis,
    puis commune de voisinage (« Pikine », « Guédiawaye », « Rufisque ») quand
    les arrêts voisins de la ligne y sont ;
  - les arrêts toujours introuvables reçoivent une position estimée (milieu de
    leurs deux voisins connus sur la même ligne), confiance « estimee » ;
  - un arrêt n'est « douteuse » que s'il fait un détour anormal entre ses deux
    voisins : d(précédent, arrêt) + d(arrêt, suivant) > 2·d(précédent, suivant) + 2 km ;
  - un géocodage inverse (reverse, zoom 14) donne un quartier/commune homogène
    pour chaque position finale.

Politique d'usage Nominatim : au plus une requête par seconde, User-Agent
explicite, et cache local (data/sources/cache_nominatim.json) : une requête déjà
faite n'est jamais refaite.

Usage :
    python data/sources/geolocaliser_arrets.py              # collecte + rapport
    python data/sources/geolocaliser_arrets.py --limite 10  # essai sur 10 arrêts
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

RACINE = Path(__file__).resolve().parents[2]
DATA = RACINE / "data"
ITINERAIRES = DATA / "itineraires_dakar.csv"
SORTIE = DATA / "arrets_geo.csv"
CACHE = Path(__file__).resolve().parent / "cache_nominatim.json"

GEOCODE = "https://nominatim.openstreetmap.org/search"
REVERSE = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "GuindiMa-AI/1.0 (cheikhniang159@gmail.com)"
DELAI_SECONDES = 1.0
TIMEOUT = 30
ZOOM_REVERSE = 14
RAYON_DETOUR = 2000.0  # marge du contrôle « détour anormal », en mètres

CHAMPS_QUARTIER = ("neighbourhood", "quarter", "suburb")
CHAMPS_COMMUNE = ("city_district", "city", "municipality")

# Communes de la banlieue : si un voisin de la ligne y est, on retente avec cette
# commune au lieu de « Dakar ».
COMMUNES_BANLIEUE = {"pikine": "Pikine", "guediawaye": "Guédiawaye", "rufisque": "Rufisque"}

# Préfixes d'arrêt sans valeur pour Nominatim.
PREFIXES = re.compile(
    r"^\s*(?:terminus|arr[êe]t|giratoire(?:\s+de)?|rond[-\s]?point(?:\s+de)?|"
    r"croisement(?:\s+de)?|station|gare(?:\s+(?:de|routi[èe]re))?)\s+",
    re.I,
)

ROMAINS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6,
    "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12,
}


# --------------------------------------------------------------------------- #
# Nettoyage des noms
# --------------------------------------------------------------------------- #


def sans_accents(texte: str) -> str:
    normalise = unicodedata.normalize("NFD", str(texte).lower().replace("œ", "oe"))
    return "".join(c for c in normalise if unicodedata.category(c) != "Mn")


def nettoyer_prefixes(nom: str) -> str:
    """Retire les préfixes d'arrêt (« Terminus Gare de X » -> « X »)."""
    precedent = None
    while precedent != nom:
        precedent = nom
        nom = PREFIXES.sub("", nom).strip()
    return nom


def remplacer_romains(nom: str) -> str:
    """« Hamo VI » -> « Hamo 6 ». Ne touche qu'aux nombres romains entiers."""
    return re.sub(
        r"\b[IVXLCDMivxlcdm]{1,4}\b",
        lambda m: str(ROMAINS[m.group(0).lower()]) if m.group(0).lower() in ROMAINS else m.group(0),
        nom,
    )


def formes(arret: str) -> list[str]:
    """Requêtes possibles pour un arrêt, de la plus fidèle à la plus nettoyée."""
    resultat: list[str] = []

    def ajouter(nom: str) -> None:
        nom = nom.strip()
        if nom and nom not in resultat:
            resultat.append(nom)

    ajouter(arret)
    ajouter(nettoyer_prefixes(arret))
    ajouter(remplacer_romains(arret))
    ajouter(remplacer_romains(nettoyer_prefixes(arret)))
    return resultat


# --------------------------------------------------------------------------- #
# Nominatim
# --------------------------------------------------------------------------- #


def _champs(objet: dict) -> dict:
    """Latitude, longitude, quartier, commune d'un objet Nominatim."""
    adresse = objet.get("address") or {}
    quartier = next((adresse[c] for c in CHAMPS_QUARTIER if adresse.get(c)), "")
    commune = next((adresse[c] for c in CHAMPS_COMMUNE if adresse.get(c)), "")
    return {
        "lat": float(objet["lat"]),
        "lon": float(objet["lon"]),
        "quartier": quartier,
        "commune": commune,
        "pays": str(adresse.get("country_code") or "").lower(),
        "display_name": objet.get("display_name", ""),
    }


def _resultat_geocode(brut) -> dict:
    return {"trouve": True, **_champs(brut[0])} if brut else {"trouve": False}


def _resultat_reverse(brut) -> dict:
    if not brut or brut.get("error"):
        return {"trouve": False}
    return {"trouve": True, **_champs(brut)}


class Nominatim:
    """Client poli : cache d'abord, puis au plus une requête réseau par seconde."""

    def __init__(self) -> None:
        self.cache = charger_cache()
        self.session = requests.Session()
        self.derniere = 0.0
        self.requetes = 0

    def _sauver(self) -> None:
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    def _attendre(self) -> None:
        attente = DELAI_SECONDES - (time.monotonic() - self.derniere)
        if attente > 0:
            time.sleep(attente)

    def _appeler(self, url: str, params: dict, cle: str, convertir):
        """Cache d'abord, puis une requête (1/s). None si échec réseau (non mis en cache)."""
        if cle in self.cache:
            return self.cache[cle]
        self._attendre()
        try:
            reponse = self.session.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            reponse.raise_for_status()
            donnees = reponse.json()
        except Exception as exc:
            self.derniere = time.monotonic()
            print(f"    [échec réseau] {cle} : {type(exc).__name__} : {exc}", flush=True)
            return None
        self.derniere = time.monotonic()
        self.requetes += 1
        self.cache[cle] = convertir(donnees)
        self._sauver()
        return self.cache[cle]

    def geocode(self, requete: str) -> dict | None:
        params = {"q": requete, "format": "jsonv2", "addressdetails": "1", "limit": "1"}
        return self._appeler(GEOCODE, params, f"fwd|{requete}", _resultat_geocode)

    def reverse(self, lat: float, lon: float) -> dict | None:
        params = {"lat": f"{lat}", "lon": f"{lon}", "format": "jsonv2", "zoom": str(ZOOM_REVERSE), "addressdetails": "1"}
        return self._appeler(REVERSE, params, f"rev|{lat:.5f},{lon:.5f}", _resultat_reverse)


def distance_metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    rayon = 6_371_000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * rayon * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------- #
# Données
# --------------------------------------------------------------------------- #


def lire_itineraires() -> list[dict]:
    with open(ITINERAIRES, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def arrets_uniques(rangees: list[dict]) -> list[str]:
    vus: dict[str, None] = {}
    for rangee in rangees:
        vus.setdefault(rangee["arret"], None)
    return list(vus)


def lignes_ordonnees(rangees: list[dict]) -> dict[tuple[str, str], list[str]]:
    par_ligne: dict[tuple[str, str], list[str]] = {}
    for rangee in rangees:
        par_ligne.setdefault((rangee["compagnie"], rangee["ligne"]), []).append(rangee["arret"])
    return par_ligne


def charger_cache() -> dict:
    """Charge le cache ; convertit l'ancien format (clé = arrêt) au nouveau."""
    if not CACHE.exists():
        return {}
    donnees = json.loads(CACHE.read_text(encoding="utf-8"))
    migre = {}
    for cle, valeur in donnees.items():
        if cle.startswith(("fwd|", "rev|")):
            migre[cle] = valeur
        else:  # la requête de base était « <arrêt>, Dakar, Sénégal »
            migre[f"fwd|{cle}, Dakar, Sénégal"] = valeur
    return migre


# --------------------------------------------------------------------------- #
# Collecte
# --------------------------------------------------------------------------- #


def geocoder_arret(arret: str, client: Nominatim, variantes: list[str]) -> dict | None:
    """Première requête qui trouve l'arrêt ; None si échec réseau ou aucune trouvaille."""
    for requete in variantes:
        info = client.geocode(requete)
        if info is None:  # échec réseau : on n'abandonne pas définitivement, on retente plus tard
            return None
        if info.get("trouve"):
            return {**info, "_requete": requete}
    return None


def communes_voisines(arret: str, par_ligne: dict, trouves: dict[str, dict]) -> list[str]:
    """Communes de banlieue où se trouvent les arrêts voisins de la ligne."""
    cibles: list[str] = []
    for arrets in par_ligne.values():
        if arret not in arrets:
            continue
        index = arrets.index(arret)
        for voisin in (index - 1, index + 1):
            if not 0 <= voisin < len(arrets):
                continue
            info = trouves.get(arrets[voisin])
            if not info:
                continue
            texte = sans_accents(f"{info.get('display_name', '')} {info.get('commune', '')}")
            for cle, nom in COMMUNES_BANLIEUE.items():
                if re.search(rf"\b{cle}\b", texte) and nom not in cibles:
                    cibles.append(nom)
    return cibles


def interpoler(
    par_ligne: dict[tuple[str, str], list[str]], positions: dict[str, tuple[float, float]]
) -> dict[str, list[tuple[float, float]]]:
    """Estimations : milieu des deux voisins connus sur la même ligne."""
    estimations: dict[str, list[tuple[float, float]]] = {}
    for arrets in par_ligne.values():
        connus = [i for i, a in enumerate(arrets) if a in positions]
        for i, arret in enumerate(arrets):
            if arret in positions:
                continue
            avant = max((j for j in connus if j < i), default=None)
            apres = min((j for j in connus if j > i), default=None)
            if avant is None or apres is None:
                continue
            pa, pb = positions[arrets[avant]], positions[arrets[apres]]
            estimations.setdefault(arret, []).append(((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2))
    return estimations


def detours_anormaux(
    par_ligne: dict[tuple[str, str], list[str]], positions: dict[str, tuple[float, float]]
) -> dict[str, str]:
    """Arrêts dont d(précédent, arrêt) + d(arrêt, suivant) > 2·d(précédent, suivant) + 2 km."""
    douteux: dict[str, str] = {}
    for (compagnie, ligne), arrets in par_ligne.items():
        for i in range(1, len(arrets) - 1):
            avant, arret, apres = arrets[i - 1], arrets[i], arrets[i + 1]
            if not all(a in positions for a in (avant, arret, apres)):
                continue
            d1 = distance_metres(positions[avant], positions[arret])
            d2 = distance_metres(positions[arret], positions[apres])
            d0 = distance_metres(positions[avant], positions[apres])
            if d1 + d2 > 2 * d0 + RAYON_DETOUR:
                douteux.setdefault(
                    arret,
                    f"{compagnie} {ligne} : {d1 / 1000:.1f} + {d2 / 1000:.1f} km "
                    f"au lieu de {d0 / 1000:.1f} km",
                )
    return douteux


# --------------------------------------------------------------------------- #
# Sortie et rapport
# --------------------------------------------------------------------------- #


def ecrire_csv(lignes: list[dict]) -> None:
    colonnes = ["arret", "lat", "lon", "quartier", "commune", "confiance"]
    with open(SORTIE, "w", newline="", encoding="utf-8") as f:
        ecrivain = csv.DictWriter(f, fieldnames=colonnes)
        ecrivain.writeheader()
        ecrivain.writerows({c: ligne[c] for c in colonnes} for ligne in lignes)


def arrets_de_ligne(rangees: list[dict], compagnie: str, ligne: str) -> list[str]:
    """Arrêts d'une ligne, dans l'ordre, dédoublonnés."""
    retenues = sorted(
        (r for r in rangees if r["compagnie"] == compagnie and r["ligne"] == ligne),
        key=lambda r: float(r["ordre"]),
    )
    vus: dict[str, None] = {}
    for rangee in retenues:
        vus.setdefault(rangee["arret"], None)
    return list(vus)


def afficher_ligne(titre: str, arrets: list[str], lignes: list[dict]) -> None:
    par_arret = {ligne["arret"]: ligne for ligne in lignes}
    print(f"\n--- {titre} ({len(arrets)} arrêts) ---")
    for arret in arrets:
        ligne = par_arret.get(arret, {})
        lieu = ligne.get("quartier") or ligne.get("commune") or ""
        coords = f"{ligne.get('lat', '')},{ligne.get('lon', '')}" if ligne.get("lat") else "—"
        print(f"  {arret:<38} {lieu:<20} {coords:<23} [{ligne.get('confiance', '')}]")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Géolocalise les arrêts du réseau avec Nominatim.")
    parser.add_argument("--limite", type=int, default=None, help="ne traiter que les N premiers arrêts")
    args = parser.parse_args()

    rangees = lire_itineraires()
    arrets = arrets_uniques(rangees)
    if args.limite:
        arrets = arrets[: args.limite]
    par_ligne = lignes_ordonnees(rangees)

    client = Nominatim()
    positions: dict[str, tuple[float, float]] = {}
    trouves: dict[str, dict] = {}

    # 1) Requêtes de base et nettoyées, sur Dakar.
    print(f"=== 1) Géocodage de {len(arrets)} arrêts ===")
    for i, arret in enumerate(arrets, start=1):
        variantes = [f"{forme}, Dakar, Sénégal" for forme in formes(arret)]
        info = geocoder_arret(arret, client, variantes)
        if info:
            positions[arret] = (info["lat"], info["lon"])
            trouves[arret] = info
        if i % 50 == 0 or i == len(arrets):
            print(f"  {i:3d}/{len(arrets)}  trouvés {len(positions)}  requêtes {client.requetes}", flush=True)

    # 2) Restants : on retente avec la commune des voisins (si banlieue).
    restants = [a for a in arrets if a not in positions]
    deja_trouves = len(positions)
    print(f"\n=== 2) {len(restants)} arrêts à retenter par commune de voisinage ===")
    for i, arret in enumerate(restants, start=1):
        communes = communes_voisines(arret, par_ligne, trouves)
        variantes = [f"{forme}, {commune}, Sénégal" for commune in communes for forme in formes(arret)]
        info = geocoder_arret(arret, client, variantes)
        if info:
            positions[arret] = (info["lat"], info["lon"])
            trouves[arret] = info
        if i % 50 == 0 or i == len(restants):
            print(f"  {i:3d}/{len(restants)}  trouvés en plus {len(positions) - deja_trouves}  requêtes {client.requetes}", flush=True)

    # 3) Interpolation des arrêts toujours introuvables.
    estimes: dict[str, tuple[float, float]] = {}
    for arret, liste in interpoler(par_ligne, positions).items():
        lat = sum(p[0] for p in liste) / len(liste)
        lon = sum(p[1] for p in liste) / len(liste)
        positions[arret] = estimes[arret] = (lat, lon)

    # 4) Détours anormaux.
    douteux = detours_anormaux(par_ligne, positions)

    # 5) Géocodage inverse : quartier/commune homogène pour chaque position.
    print(f"\n=== 3) Géocodage inverse de {len(positions)} positions ===")
    infos: dict[str, dict] = {}
    for i, (arret, (lat, lon)) in enumerate(positions.items(), start=1):
        infos[arret] = client.reverse(lat, lon) or {"trouve": False}
        if i % 100 == 0 or i == len(positions):
            print(f"  {i:3d}/{len(positions)}  requêtes {client.requetes}", flush=True)

    # 6) Fichier et bilan.
    lignes = []
    for arret in arrets:
        info = infos.get(arret) or {"trouve": False}
        if arret not in positions:
            confiance = "introuvable"
        elif arret in douteux:
            confiance = "douteuse"
        elif arret in estimes:
            confiance = "estimee"
        else:
            confiance = "bonne"
        lignes.append(
            {
                "arret": arret,
                "lat": f"{positions[arret][0]:.6f}" if arret in positions else "",
                "lon": f"{positions[arret][1]:.6f}" if arret in positions else "",
                "quartier": info.get("quartier", "") if info.get("trouve") else "",
                "commune": info.get("commune", "") if info.get("trouve") else "",
                "confiance": confiance,
            }
        )
    ecrire_csv(lignes)

    comptes = {"bonne": 0, "estimee": 0, "douteuse": 0, "introuvable": 0}
    for ligne in lignes:
        comptes[ligne["confiance"]] += 1

    print("\n=== Bilan ===")
    print(f"{len(lignes)} arrêts -> {SORTIE.relative_to(RACINE)}")
    for nom in ("bonne", "estimee", "douteuse", "introuvable"):
        print(f"  {nom:11s}: {comptes[nom]}")

    if douteux:
        print(f"\n--- Détours anormaux ({len(douteux)}) ---")
        for arret in douteux:
            print(f"  {arret} : {douteux[arret]}")
    if lignes and sum(1 for l in lignes if l["confiance"] == "introuvable"):
        print(f"\n--- Introuvables ({sum(1 for l in lignes if l['confiance'] == 'introuvable')}) ---")
        for arret in (l["arret"] for l in lignes if l["confiance"] == "introuvable"):
            print(f"  {arret}")

    # Deux lignes de référence : Médina doit apparaître sur « Avenue Blaise Diagne »
    # et Liberté 6 sur « Giratoire [de] Liberté VI ».
    for compagnie, ligne in (("Tata AFTU", "Ligne 1"), ("Dakar Dem Dikk", "Ligne 4")):
        afficher_ligne(f"{compagnie} {ligne}", arrets_de_ligne(rangees, compagnie, ligne), lignes)

    # Arrêts proches du Marché Sandaga (le marché est géocodé d'abord).
    marche = client.geocode("Marché Sandaga, Dakar, Sénégal")
    if marche and marche.get("trouve"):
        centre = (marche["lat"], marche["lon"])
        par_arret = {ligne["arret"]: ligne for ligne in lignes}
        proches = sorted((distance_metres(centre, p), a) for a, p in positions.items() if distance_metres(centre, p) <= 500)
        print(f"\n--- Arrêts à moins de 500 m du Marché Sandaga ({marche.get('display_name', '')}) ---")
        for distance, arret in proches:
            ligne = par_arret.get(arret, {})
            lieu = ligne.get("quartier") or ligne.get("commune") or ""
            print(f"  {arret:<38} {distance:4.0f} m  {lieu}")
        if not proches:
            print("  (aucun)")
    else:
        print("\n[Marché Sandaga] introuvable via Nominatim")

    print(f"\n{client.requetes} requêtes Nominatim cette exécution — {len(client.cache)} entrées en cache")


if __name__ == "__main__":
    main()
