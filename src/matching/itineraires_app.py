"""Itinéraires tels que l'app les sert, et noms d'arrêts Dem Dikk qu'un usager dit.

Le moteur v2 (src/routing/data.py) remplace en mémoire les lignes Dem Dikk de
data/itineraires_dakar.csv par les listes officielles de
data/corrections/corrections_geo_ddd_proposees.csv. L'extraction des lieux et
geo.py lisaient encore le CSV brut : « Sapeur Pompiers » ou « Ecole Dior »,
arrêts servis par l'app, n'étaient donc pas reconnus quand l'usager les disait.

Ce module porte la règle commune (sans pandas, pour rester léger à l'import) :
src/routing/data.py l'importe, l'extraction et geo.py aussi. Rien n'est écrit :
les CSV restent intacts, tout se passe en mémoire.

Seuls les noms qu'un usager dirait vraiment deviennent des lieux : les notes de
fiche (« Itinéraire 213 »), les indications de trajet (« vers Camp Leclerc »),
les fautes de frappe et les noms qui écraseraient un lieu existant plus large
(« Ville de Rufisque » face à Rufisque) sont écartés, avec leur raison.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

try:  # import à plat (app.py) ou en paquet
    from matching.lieux import lieux_reconnaissables, sans_accents
except ImportError:  # pragma: no cover
    from .lieux import lieux_reconnaissables, sans_accents

DATA = Path(__file__).resolve().parents[2] / "data"
ITINERAIRES_CSV = DATA / "itineraires_dakar.csv"
CORRECTIONS_DDD = DATA / "corrections" / "corrections_geo_ddd_proposees.csv"
DEM_DIKK = "Dakar Dem Dikk"


def nom_ligne_ddd(ligne: object) -> str:
    """« 1 » -> « Ligne 1 », « 16A » -> « Ligne 16A » ; « TAF TAF » reste tel quel."""
    texte = str(ligne).strip()
    return f"Ligne {texte}" if texte[:1].isdigit() else texte


def sans_terminus(nom: object) -> str:
    """« Terminus keur Massar » -> « Keur Massar » : le même arrêt que nos autres lignes.

    « Terminus X (Y) » garde son nom complet : il désigne deux lieux, et le
    renommer en perdrait un.
    """
    texte = str(nom).strip()
    trouve = re.fullmatch(r"terminus\s+([^()]+)", texte, flags=re.IGNORECASE)
    if not trouve:
        return texte
    reste = trouve.group(1).strip()
    return reste[0].upper() + reste[1:] if not reste.isdigit() else texte


def _lire(chemin: Path) -> list[dict]:
    with open(chemin, newline="", encoding="utf-8-sig") as fichier:
        return list(csv.DictReader(fichier))


def rangees_ddd_officielles(chemin: Path = CORRECTIONS_DDD) -> list[dict]:
    """Les rangées Dem Dikk officielles, avec la ligne et l'arrêt comme l'app les nomme."""
    if not Path(chemin).exists():
        return []
    return [
        {**rangee, "ligne": nom_ligne_ddd(rangee["ligne"]), "arret": sans_terminus(rangee["arret"])}
        for rangee in _lire(chemin)
    ]


def rangees_itineraires(
    itineraires_csv: Path = ITINERAIRES_CSV, corrections: Path = CORRECTIONS_DDD
) -> list[dict]:
    """Les itinéraires vus par l'app : chaque ligne Dem Dikk officielle remplace la brute."""
    brutes = _lire(itineraires_csv) if Path(itineraires_csv).exists() else []
    officielles = rangees_ddd_officielles(corrections)
    remplacees = {rangee["ligne"] for rangee in officielles}
    gardees = [
        rangee for rangee in brutes
        if not (rangee.get("compagnie") == DEM_DIKK and rangee.get("ligne") in remplacees)
    ]
    return gardees + [
        {"compagnie": r["compagnie"], "ligne": r["ligne"], "ordre": r["ordre"], "arret": r["arret"]}
        for r in officielles
    ]


def cle_lieu(nom: str) -> str:
    """Forme de comparaison : minuscules, sans accents ni ponctuation (comme extract_intent)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", sans_accents(nom))).strip()


def noms_seulement_officiels(
    itineraires_csv: Path = ITINERAIRES_CSV, corrections: Path = CORRECTIONS_DDD
) -> frozenset[str]:
    """Clés des arrêts Dem Dikk servis par l'app mais absents du CSV brut.

    geo.py ne les géocode jamais : leur position officielle est le plus souvent
    une interpolation ou un géocodage (positions non sûres), et Nominatim les
    place parfois très loin. Vu au test : « Corniche Ouest » géocodé près de
    Sandaga, et le départ devenait Sandaga. Sans point, le moteur les trouve par
    leur nom sur leur ligne, ou ne répond pas : jamais une position inventée.
    """
    # Les formes dérivées comptent aussi : « Filaos » vient de « Gadaye
    # (Filaos) », « Mosquée Niakoul Rab » de « Jaxaay (Mosquée Niakoul Rab) ».
    def formes(noms: set[str]) -> set[str]:
        return {cle_lieu(nom) for nom in noms} | {cle_lieu(nom) for nom in lieux_reconnaissables(sorted(noms))}

    noms_bruts = {r["arret"] for r in _lire(itineraires_csv)} if Path(itineraires_csv).exists() else set()
    noms_officiels = {r["arret"] for r in rangees_ddd_officielles(corrections)}
    return frozenset(formes(noms_officiels - noms_bruts) - formes(noms_bruts))


# Noms officiels écartés un par un, avec la raison. Les règles générales
# (raison_ecart) couvrent le reste : sigles très courts, rues numérotées,
# « deux voies », indications de trajet, fautes de « croisement ».
ECARTES: dict[str, str] = {
    # Fautes de frappe ou doublons d'un nom déjà retenu sous sa bonne forme.
    "arsanel": "faute de frappe de « Arsenal » (gardé)",
    "gororm 02": "faute de frappe de « Gorom 02 »",
    "grands moulin de dakar": "doublon de « Grand Moulin de Dakar » (gardé)",
    "lycee de lafosse": "doublon de « Lycée Delafosse » (gardé)",
    "pharmacie cite aviaon": "faute de frappe (« Cité Avion »)",
    "pond foire": "faute de frappe de « Pont Foire »",
    "marche tilen": "faute de frappe de « Marché Tilène » (déjà connu)",
    "hopitale principale": "faute de frappe ; nom affiché faux",
    "direction general ascena": "faute de frappe (ASECNA) et nom administratif",
    "patte d oies": "variante de « Patte d'Oie » (déjà connu)",
    "rond point liberte6": "variante de « Rond Point Liberté 6 » (déjà connu)",
    "dakar sacre coeur": "variante de « Sacré-Cœur » (déjà connu)",
    "hamo6": "variante de « Hamo 6 » sans espace",
    "place de l independace avenue sarraut": "deux lieux collés, avec une faute",
    # Pas un lieu qu'un usager dit.
    "direction generale ddd": "siège de l'opérateur, pas un lieu demandé",
    "maison du partie": "nom incertain (faute probable), pas sûr",
    "scor liberte": "nom incertain, pas sûr",
    "case": "mot générique (« case ») seul",
    "ravin": "mot générique seul",
    "shell": "marque de station-service, il y en a partout",
    "national 1": "route nationale, pas un lieu",
    "case pa": "abréviation « PA » qu'on ne prononce pas",
    "police pa": "abréviation « PA » qu'on ne prononce pas",
    "eglise pa": "abréviation « PA » qu'on ne prononce pas",
    "police 4em": "abréviation (« 4e arrondissement ») qu'on ne prononce pas",
    # Écraseraient un meilleur lieu, ou une règle déjà en place.
    "blaise diagne": "« Blaise Diagne » seul désigne l'AIBD (règle d'extraction existante)",
    "hann maristes": "réécrit en « Maristes » par l'extraction (déjà connu)",
    "marche grand medine": "réécrit en « HLM Grand Médine » par l'extraction (déjà connu)",
    "ville de rufisque": "écraserait « Rufisque », lieu plus large et mieux desservi",
}


def raison_ecart(nom: str) -> str | None:
    """Pourquoi ce nom d'arrêt officiel ne devient pas un lieu, ou None s'il est gardé."""
    cle = cle_lieu(nom)
    if cle in ECARTES:
        return ECARTES[cle]
    if len(cle.replace(" ", "")) <= 3:
        return "trop court (3 lettres ou moins) : bruit de l'ASR, mots wolof (« bop », « daf »)"
    if re.search(r"\brue \d", cle):
        return "rue numérotée : ne dit pas le quartier"
    if re.match(r"(?:les )?(?:2|deux) voies\b", cle):
        return "« deux voies » : description de route, le lieu qu'elle porte est déjà connu"
    if re.match(r"(?:vers|sur le|ex|ancien|ancienne)\b", cle):
        return "indication de trajet ou ancien nom, pas un lieu"
    if re.fullmatch(r"(?:itineraire|national|nationale|autoroute|croisement|terminus)(?: \d+)?", cle):
        return "mot générique seul ou note de fiche"
    if "croissement" in cle:
        return "faute de frappe de « croisement » ; le lieu qu'il porte est déjà connu"
    return None
