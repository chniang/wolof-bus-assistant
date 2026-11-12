r"""Compare nos lignes aux listes d'arrêts officielles AFTU et Dem Dikk.

Pour chaque ligne de data/lignes_dakar.csv, on confronte les arrêts de
data/itineraires_dakar.csv aux fiches officielles copiées dans
data/reference/ (arrets_toutes_lignes_aftu.csv, arrets_toutes_lignes_ddd.csv).

Sortie : data/audit/comparaison_lignes_officielles.csv, une rangée par ligne
de nos données, plus une rangée par fiche officielle absente de nos données.

Classes :
    CONFORME            terminus identiques, au moins 80 % des points officiels
                        retrouvés, ordre cohérent
    A_COMPLETER         terminus identiques, mais moins de 80 % des points
                        officiels retrouvés (ou ordre non mesurable)
    TERMINUS_DIFFERENT  terminus différents, mais trajet concordant
                        (>= 80 % des points, ordre cohérent)
    DIVERGENTE          terminus différents avec trajet non concordant, ou
                        ordre incohérent
    DOUTEUSE            ligne signalée douteuse, terminus identiques
    SANS_SOURCE         aucune source exploitable : liste absente, ou fiche
                        réduite à ses 2 terminus en statut « indice »

Les fiches AFTU et Dem Dikk listent des rues et des repères dans un seul sens,
pas de vrais arrêts : la comparaison est indicative, pas une vérité de terrain.

Lecture seule, sans réseau :
    .\.venv\Scripts\python.exe scripts\comparer_lignes_officielles.py
"""

from __future__ import annotations

import csv
import re
import unicodedata
from bisect import bisect_left
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DATA = RACINE / "data"
REFERENCE = DATA / "reference"
SORTIE = DATA / "audit" / "comparaison_lignes_officielles.csv"

DEM_DIKK = "Dakar Dem Dikk"
TATA = "Tata AFTU"

FICHIERS_OFFICIELS = {
    DEM_DIKK: REFERENCE / "arrets_toutes_lignes_ddd.csv",
    TATA: REFERENCE / "arrets_toutes_lignes_aftu.csv",
}

# Ces quatre lignes Dem Dikk sont signalées douteuses par l'audit de fiabilité :
# les deux versions officielles ne disent pas la même chose, ou notre fiche
# ligne ne correspond pas à la fiche officielle. On garde la classe DOUTEUSE
# même quand la comparaison automatique trouverait un terminus.
DOUTEUSES = {
    DEM_DIKK: {
        "Ligne 6": "notre fiche dit Cambérène 2–Palais 2, l'officiel dit Guédiawaye–Palais 1",
        "Ligne 217": "notre fiche dit Thiaroye–Ouakam, l'officiel dit Dépôt Thiaroye–Aéroport LSS",
        "Ligne 220": "deux versions officielles se contredisent (Rufisque–Guédiawaye vs navette Guédiawaye–AIBD)",
        "Ligne 233": "notre fiche dit Baux Maraîchers–Palais 1, l'officiel dit Baux Maraîchers–Aéroport LSS",
    }
}

# La fiche officielle ne distingue pas 15A et 15B ; la 228 est rangée sous un
# titre sans numéro ; notre TAF TAF suit la variante AIBD, pas TO1 ni Sphère.
MAPPING_SPECIAL = {
    (DEM_DIKK, "15a"): "15 (15A & 15B non distinguées)",
    (DEM_DIKK, "15b"): "15 (15A & 15B non distinguées)",
    (DEM_DIKK, "228"): "228 (titre sans numéro : TERMINUS RUFISQUE <--> YENNE)",
    (DEM_DIKK, "taf taf"): "TAF TAF (vers AIBD)",
}

# Mots de fiche qui ne nomment pas un lieu : « Terminus Gare Petersen » et
# « Petersen » doivent se rencontrer. On ne retire pas « terminus » partout,
# car « Malika Terminus » est un arrêt à part entière : seul le terminus en
# tête de fiche est un préfixe.
MOTS_GENERIQUES = {
    "gare", "arret", "station", "rond", "point", "rondpoint", "face", "vers",
    "marche", "hopital", "poste", "route", "principale", "carrefour",
    "croisement", "de", "du", "des", "la", "le", "les", "l", "d", "a", "au",
    "aux", "et", "en", "sur", "sous", "par", "n",
}

# Un seul mot suffit quand il désigne un lieu assez net. « Colobane » est
# volontairement absent : sans « Rufisque », il peut être la gare de Dakar.
TOKENS_SURS = {
    "petersen", "leclerc", "medina", "ucad", "claudel", "apix", "sahm",
    "yoff", "ngor", "ouakam", "rufisque", "thiaroye", "diamniadio",
    "sebikotane", "bargny", "jaxaay", "yenne", "almadies", "gadaye",
    "parcelles", "mtoa", "comico",
}

# Expressions de plusieurs mots qui peuvent arriver en suffixe
# (« Police Grand Yoff », « Pharmacie Patte d'Oie », « Collège Sacré Cœur »).
PHRASES_SURES = {"grand yoff", "patte oie", "sacre coeur"}

CONTEXTES_ROMAINS = {"liberte", "palais", "unite", "zone", "cite", "phase",
                     "tranche", "lot", "hamo"}
ROMAINS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
    "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13,
    "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19,
    "xx": 20,
}

REMPLACEMENTS = [
    (r"\bterminnus\b", "terminus"),
    (r"\btermnus\b", "terminus"),
    (r"\bsebikhotane\b", "sebikotane"),
    (r"\bsebikhothane\b", "sebikotane"),
    (r"\bsham\b", "sahm"),
    (r"\btournalou\b", "tournal"),
    (r"\bbauxmaraichers\b", "baux maraichers"),
    (r"\bbeaux maraichers\b", "baux maraichers"),
    (r"\bbd\b", "boulevard"),
    (r"\bav\b", "avenue"),
    (r"\brte\b", "route"),
    (r"\bgd\b", "grand"),
    (r"\bste\b", "sainte"),
    (r"\bst\b", "saint"),
    (r"\bpl\b", "place"),
    (r"\bker\b", "keur"),
    (r"\bucad\b", "universite cheikh anta diop"),
    (r"\blss\b", "l s senghor"),
]


def norm(texte: object) -> str:
    """Minuscules, sans accents ni ponctuation : pour comparer des noms."""
    texte = str(texte or "")
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.lower().replace("œ", "oe").replace("æ", "ae").replace("ŋ", "n")
    texte = re.sub(r"[^a-z0-9]+", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def appliquer_remplacements(texte: str) -> str:
    for motif, remplacement in REMPLACEMENTS:
        texte = re.sub(motif, remplacement, texte)
    return texte


def convertir_romains(tokens: list[str]) -> list[str]:
    """« Liberté VI » -> « liberte 6 », mais « Tally Icotaf X » reste un X."""
    sortie = []
    for i, token in enumerate(tokens):
        if token in ROMAINS and i > 0 and tokens[i - 1] in CONTEXTES_ROMAINS:
            sortie.append(str(ROMAINS[token]))
        else:
            sortie.append(token)
    return sortie


def normaliser_nombres(tokens: list[str]) -> list[str]:
    """« 09 » et « 9 » sont le même numéro."""
    return [str(int(token)) if token.isdigit() else token for token in tokens]


@lru_cache(maxsize=None)
def formes(nom: str) -> frozenset[str]:
    """Toutes les écritures comparables d'un nom.

    On garde le nom complet, le nom sans parenthèses, et le contenu de chaque
    parenthèse : « Terminus Liberté 5 (Dieuppeul) » doit pouvoir rencontrer
    notre arrêt « Dieuppeul », sans quoi la ligne 18 paraît divergente.
    """
    brut = str(nom or "")
    variantes: set[str] = set()
    sources = [brut, re.sub(r"\([^)]*\)", " ", brut)]
    for contenu in re.findall(r"\(([^)]*)\)", brut):
        sources.extend(partie.strip() for partie in contenu.split(","))
    for source in sources:
        texte = appliquer_remplacements(norm(source))
        tokens = normaliser_nombres(convertir_romains(texte.split()))
        if tokens and tokens[0] == "terminus":
            tokens = tokens[1:]
        sans_generiques = [token for token in tokens if token not in MOTS_GENERIQUES]
        for choix in (tokens, sans_generiques):
            variante = " ".join(choix)
            if variante:
                variantes.add(variante)
    return frozenset(variantes)


def contient_phrase(tokens: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    if n == 0:
        return False
    return any(tokens[i:i + n] == phrase for i in range(len(tokens) - n + 1))


@lru_cache(maxsize=None)
def type_correspondance(a: str, b: str) -> str | None:
    """« fort », « souple » ou None. Le souple évite de perdre un lieu
    quand un côté est plus précis que l'autre (« Gadaye » / « Gadaye Filaos »)."""
    souple = None
    for x in formes(str(a or "")):
        for y in formes(str(b or "")):
            if x == y:
                return "fort"
            nombres_x = set(re.findall(r"\d+", x))
            nombres_y = set(re.findall(r"\d+", y))
            # « Liberté 5 » ne doit pas rencontrer « Liberté 6 ». En revanche
            # « Hamo 5 » peut rencontrer « Hamo V/VI » : un des ensembles
            # de numéros contient l'autre.
            if nombres_x and nombres_y and not (
                nombres_x <= nombres_y or nombres_y <= nombres_x
            ):
                continue
            tokens_x, tokens_y = x.split(), y.split()
            court, long = (tokens_x, tokens_y) if len(tokens_x) <= len(tokens_y) else (tokens_y, tokens_x)
            if len(court) >= 2 and long[:len(court)] == court:
                return "fort"
            if len(court) == 1 and court[0] in TOKENS_SURS and court[0] in long:
                if court[0] == "colobane" and "rufisque" in long:
                    continue
                if court[0] == "rufisque" and "colobane" in long:
                    continue
                souple = "souple"
            if (
                len(court) >= 2
                and " ".join(court) in PHRASES_SURES
                and contient_phrase(long, court)
            ):
                souple = "souple"
            if len(x) >= 4 and len(y) >= 4:
                if SequenceMatcher(None, x, y).ratio() >= 0.88:
                    return "fort"
    return souple


def correspond(a: str, b: str) -> bool:
    return type_correspondance(str(a or ""), str(b or "")) is not None


def cle_ligne(nom: object) -> str:
    """« Ligne 16A », « 16A », « 16 A » -> « 16a » ; « TAF TAF » garde son texte."""
    texte = norm(nom)
    texte = re.sub(r"^ligne ", "", texte)
    return re.sub(r"^(\d+) ([a-z])$", r"\1\2", texte)


def lire_csv(chemin: Path) -> list[dict]:
    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        return list(csv.DictReader(fichier))


def charger_officiels() -> dict[tuple[str, str], dict]:
    """Les fiches officielles, une entrée par (compagnie, clé brute)."""
    officiels = {}
    for compagnie, chemin in FICHIERS_OFFICIELS.items():
        par_ligne: dict[str, list[dict]] = defaultdict(list)
        for rangee in lire_csv(chemin):
            par_ligne[rangee["ligne"]].append(rangee)
        for cle, rangees in par_ligne.items():
            rangees.sort(key=lambda rangee: int(rangee["ordre"]))
            officiels[(compagnie, cle)] = {
                "cle": cle,
                "points": [rangee["arret"] for rangee in rangees],
                "statuts": [rangee["statut"] for rangee in rangees],
                "source": rangees[0]["source"],
            }
    return officiels


def trouver_officiel(officiels: dict[tuple[str, str], dict], compagnie: str, ligne: str) -> dict | None:
    cle = cle_ligne(ligne)
    special = MAPPING_SPECIAL.get((compagnie, cle))
    if special is not None:
        return officiels.get((compagnie, special))
    for (operateur, cle_officielle), fiche in officiels.items():
        if operateur == compagnie and cle_ligne(cle_officielle) == cle:
            return fiche
    return None


def lis_longueur(valeurs: list[int]) -> int:
    """Plus longue sous-séquence strictement croissante."""
    queues: list[int] = []
    for valeur in valeurs:
        position = bisect_left(queues, valeur)
        if position == len(queues):
            queues.append(valeur)
        else:
            queues[position] = valeur
    return len(queues)


def comparer_terminus(nos_extremites: tuple[str, str], officiels: list[str]) -> tuple[str, str, str]:
    """Retourne (oui/non/indéterminé, terminus souple oui/non, détail)."""
    if not officiels:
        return "indéterminé", "non", ""
    premier, dernier = officiels[0], officiels[-1]
    boucle = norm(premier) == norm(dernier)
    if boucle:
        types = [type_correspondance(str(x), str(premier)) for x in nos_extremites]
        types = [type_ for type_ in types if type_]
        if not types:
            return "non", "non", f"ligne circulaire officielle ({premier}) non retrouvée"
        souple = "oui" if "souple" in types else "non"
        return "oui", souple, f"ligne circulaire officielle (un seul terminus : {premier})"
    for a, b in (
        (nos_extremites[0], nos_extremites[1]),
        (nos_extremites[1], nos_extremites[0]),
    ):
        type_a = type_correspondance(str(a), str(premier))
        type_b = type_correspondance(str(b), str(dernier))
        if type_a and type_b:
            souple = "oui" if "souple" in (type_a, type_b) else "non"
            return "oui", souple, ""
    return "non", "non", ""


def doublons(points: list[str]) -> list[str]:
    """Points répétés dans une fiche, hors point de boucle des lignes circulaires."""
    corps = points
    if len(points) > 2 and norm(points[0]) == norm(points[-1]):
        corps = points[1:-1]
    comptes = Counter(norm(point) for point in corps)
    return list(dict.fromkeys(point for point in corps if comptes[norm(point)] > 1))[:3]


def signatures_officielles(officiels: dict[tuple[str, str], dict]) -> dict[tuple[str, str], list[str]]:
    """Fiches qui ont exactement la même suite d'arrêts (217/218, 232/233)."""
    par_signature: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    for (compagnie, cle), fiche in officiels.items():
        signature = (compagnie, tuple(norm(point) for point in fiche["points"]))
        par_signature[signature].append(cle)
    return {
        (compagnie, cle): [autre for autre in cles if autre != cle]
        for (compagnie, _), cles in par_signature.items()
        for cle in cles
    }


def construire_rangees() -> tuple[list[dict], dict[str, int]]:
    lignes = lire_csv(DATA / "lignes_dakar.csv")
    itineraires = lire_csv(DATA / "itineraires_dakar.csv")
    officiels = charger_officiels()
    signatures = signatures_officielles(officiels)
    utilisees: set[tuple[str, str]] = set()
    rangees: list[dict] = []
    stats = {"arrets_souples": 0, "lignes_souples": 0}

    for ligne in lignes:
        compagnie = ligne["compagnie"]
        nom_ligne = ligne["ligne"]
        arrets = [
            rangee["arret"]
            for rangee in sorted(
                (
                    rangee
                    for rangee in itineraires
                    if rangee["compagnie"] == compagnie and rangee["ligne"] == nom_ligne
                ),
                key=lambda rangee: int(rangee["ordre"]),
            )
        ]
        if not arrets:
            arrets = [ligne["terminus_a"], ligne["terminus_b"]]
        nos_extremites = (arrets[0], arrets[-1])
        fiche = trouver_officiel(officiels, compagnie, nom_ligne)

        if fiche is None:
            rangees.append({
                "type_ligne": "notre_ligne",
                "operateur": compagnie,
                "ligne": nom_ligne,
                "nom_officiel": "",
                "classe": "SANS_SOURCE",
                "source": "",
                "terminus_ok": "indéterminé",
                "terminus_fiche_ok": "indéterminé",
                "terminus_souple": "non",
                "ordre_coherent": "indéterminé",
                "sens_ordre": "indéterminé",
                "part_ordre": "",
                "points_officiels": 0,
                "points_officiels_trouves": 0,
                "part_points_officiels": "",
                "taux_correspondance": "",
                "nos_arrets": len(arrets),
                "nos_arrets_absents": 0,
                "part_nos_arrets_absents": "",
                "terminus_fiche": f"{ligne['terminus_a']} / {ligne['terminus_b']}",
                "terminus_itineraires": f"{nos_extremites[0]} / {nos_extremites[1]}",
                "terminus_officiels": "",
                "points_officiels_non_trouves": "",
                "arrets_absents": "",
                "remarque": "aucune liste officielle pour cette ligne",
            })
            continue

        utilisees.add((compagnie, fiche["cle"]))
        points_officiels = fiche["points"]
        if len(points_officiels) == 2 and all(statut == "indice" for statut in fiche["statuts"]):
            rangees.append({
                "type_ligne": "notre_ligne",
                "operateur": compagnie,
                "ligne": nom_ligne,
                "nom_officiel": fiche["cle"],
                "classe": "SANS_SOURCE",
                "source": fiche["source"],
                "terminus_ok": "indéterminé",
                "terminus_fiche_ok": "indéterminé",
                "terminus_souple": "non",
                "ordre_coherent": "indéterminé",
                "sens_ordre": "indéterminé",
                "part_ordre": "",
                "points_officiels": len(points_officiels),
                "points_officiels_trouves": "",
                "part_points_officiels": "",
                "taux_correspondance": "",
                "nos_arrets": len(arrets),
                "nos_arrets_absents": "",
                "part_nos_arrets_absents": "",
                "terminus_fiche": f"{ligne['terminus_a']} / {ligne['terminus_b']}",
                "terminus_itineraires": f"{nos_extremites[0]} / {nos_extremites[1]}",
                "terminus_officiels": f"{points_officiels[0]} / {points_officiels[-1]}",
                "points_officiels_non_trouves": "",
                "arrets_absents": "",
                "remarque": (
                    "fiche officielle réduite à ses 2 terminus (statut indice), "
                    "inutilisable pour comparer le trajet"
                ),
            })
            continue
        correspondances: list[list[int]] = []
        for arret in arrets:
            correspondances.append([
                index
                for index, point in enumerate(points_officiels)
                if correspond(arret, point)
            ])
        souples_ligne = False
        for arret, indices in zip(arrets, correspondances):
            if not indices:
                continue
            types = {
                type_correspondance(arret, points_officiels[index])
                for index in indices
            }
            if "fort" not in types:
                stats["arrets_souples"] += 1
                souples_ligne = True
        if souples_ligne:
            stats["lignes_souples"] += 1
        trouves = {index for indices in correspondances for index in indices}
        absents = [
            arret
            for arret, indices in zip(arrets, correspondances)
            if not indices
        ]
        non_trouves = [
            point
            for index, point in enumerate(points_officiels)
            if index not in trouves
        ]
        part_points = len(trouves) / len(points_officiels)
        part_absents = len(absents) / len(arrets) if arrets else 0.0

        indices_direct = [min(indices) for indices in correspondances if indices]
        indices_inverse = [max(indices) for indices in correspondances if indices]
        lis_direct = lis_longueur(indices_direct)
        lis_inverse = lis_longueur([-index for index in indices_inverse])
        if len(indices_direct) >= 2:
            part_ordre = max(lis_direct, lis_inverse) / len(indices_direct)
            ordre = "oui" if part_ordre >= 0.8 else "non"
            sens = "direct" if lis_direct > lis_inverse else (
                "inverse" if lis_inverse > lis_direct else "ambigu"
            )
        else:
            part_ordre = None
            ordre = "indéterminé"
            sens = "indéterminé"

        terminus_ok, terminus_souple, detail_boucle = comparer_terminus(nos_extremites, points_officiels)
        terminus_fiche_ok, _, _ = comparer_terminus(
            (ligne["terminus_a"], ligne["terminus_b"]), points_officiels
        )

        est_douteuse = compagnie in DOUTEUSES and nom_ligne in DOUTEUSES[compagnie]
        terminus_global_ok = terminus_ok == "oui" and terminus_fiche_ok == "oui"
        if not terminus_global_ok:
            # La règle stricte passe avant le marqueur DOUTEUSE : une ligne dont
            # les terminus diffèrent ne peut jamais être CONFORME.
            if part_points >= 0.8 and ordre == "oui":
                classe = "TERMINUS_DIFFERENT"
            else:
                classe = "DIVERGENTE"
        elif ordre == "non":
            classe = "DIVERGENTE"
        elif est_douteuse:
            classe = "DOUTEUSE"
        elif part_points >= 0.8 and ordre == "oui":
            classe = "CONFORME"
        else:
            classe = "A_COMPLETER"

        notes: list[str] = []
        if classe == "CONFORME":
            notes.append("itinéraire conforme à la fiche")
        elif classe == "TERMINUS_DIFFERENT":
            notes.append("trajet concordant, mais terminus différents")
        cle = cle_ligne(nom_ligne)
        if MAPPING_SPECIAL.get((compagnie, cle)) is not None:
            if cle in ("15a", "15b"):
                notes.append("liste officielle groupée 15A & 15B, pas de fiche séparée")
            elif cle == "228":
                notes.append("liste officielle au titre sans numéro (228)")
            elif cle == "taf taf":
                notes.append(
                    "liste officielle TAF TAF (vers AIBD) ; les variantes TO1 et "
                    "Sphère Ministérielle ne correspondent pas à cette ligne"
                )
        if compagnie in DOUTEUSES and nom_ligne in DOUTEUSES[compagnie]:
            notes.append("ligne douteuse : " + DOUTEUSES[compagnie][nom_ligne])
        if detail_boucle:
            notes.append(detail_boucle)
        if terminus_ok == "non":
            notes.append(
                f"terminus différents (nous : {nos_extremites[0]} / {nos_extremites[1]} ; "
                f"officiel : {points_officiels[0]} / {points_officiels[-1]})"
            )
        elif terminus_fiche_ok == "non":
            notes.append(
                "terminus de lignes_dakar.csv différents de l'itinéraire "
                f"(fiche : {ligne['terminus_a']} / {ligne['terminus_b']} ; "
                f"itinéraire : {nos_extremites[0]} / {nos_extremites[1]})"
            )
        if ordre == "non":
            notes.append("ordre des arrêts incohérent avec la fiche")
        if non_trouves:
            notes.append(f"{len(non_trouves)} point(s) officiel(s) non retrouvé(s)")
        if absents:
            notes.append(f"{len(absents)} arrêt(s) de notre itinéraire absent(s) de la fiche")
        doublons_fiche = doublons(points_officiels)
        if doublons_fiche:
            notes.append("la fiche officielle répète : " + ", ".join(doublons_fiche))
        autres_fiches = signatures.get((compagnie, fiche["cle"]), [])
        if autres_fiches:
            notes.append("fiche officielle identique à " + ", ".join(autres_fiches))
        if not notes:
            notes.append("rien à signaler")

        rangees.append({
            "type_ligne": "notre_ligne",
            "operateur": compagnie,
            "ligne": nom_ligne,
            "nom_officiel": fiche["cle"],
            "classe": classe,
            "source": fiche["source"],
            "terminus_ok": terminus_ok,
            "terminus_fiche_ok": terminus_fiche_ok,
            "terminus_souple": terminus_souple,
            "ordre_coherent": ordre,
            "sens_ordre": sens,
            "part_ordre": round(part_ordre, 3) if part_ordre is not None else "",
            "points_officiels": len(points_officiels),
            "points_officiels_trouves": len(trouves),
            "part_points_officiels": round(part_points, 3),
            "taux_correspondance": round(part_points * 100, 1),
            "nos_arrets": len(arrets),
            "nos_arrets_absents": len(absents),
            "part_nos_arrets_absents": round(part_absents, 3),
            "terminus_fiche": f"{ligne['terminus_a']} / {ligne['terminus_b']}",
            "terminus_itineraires": f"{nos_extremites[0]} / {nos_extremites[1]}",
            "terminus_officiels": (
                f"{points_officiels[0]} / {points_officiels[-1]}"
                if norm(points_officiels[0]) != norm(points_officiels[-1])
                else f"{points_officiels[0]} (boucle)"
            ),
            "points_officiels_non_trouves": " | ".join(non_trouves),
            "arrets_absents": " | ".join(absents),
            "remarque": " ; ".join(notes),
        })

    # Les fiches officielles qu'aucune de nos lignes ne couvre.
    for (compagnie, cle), fiche in officiels.items():
        if (compagnie, cle) in utilisees:
            continue
        points = fiche["points"]
        notes = ["ligne officielle absente de data/lignes_dakar.csv"]
        base = norm(cle).split()[0] if norm(cle) else ""
        proches = [
            autre["ligne"]
            for autre in lignes
            if autre["compagnie"] == compagnie and cle_ligne(autre["ligne"]).startswith(base)
            and cle_ligne(autre["ligne"]) != base
        ]
        if proches:
            notes.append(
                "nos lignes " + ", ".join(sorted(proches))
                + " existent, mais avec un libellé différent"
            )
        if cle.startswith("TAF TAF"):
            notes.append("notre TAF TAF suit la variante AIBD")
        rangees.append({
            "type_ligne": "ligne_officielle_absente",
            "operateur": compagnie,
            "ligne": "",
            "nom_officiel": cle,
            "classe": "ABSENTE_DE_NOS_DONNEES",
            "source": fiche["source"],
            "terminus_ok": "",
            "terminus_fiche_ok": "",
            "terminus_souple": "",
            "ordre_coherent": "",
            "sens_ordre": "",
            "part_ordre": "",
            "points_officiels": len(points),
            "points_officiels_trouves": "",
            "part_points_officiels": "",
            "taux_correspondance": "",
            "nos_arrets": 0,
            "nos_arrets_absents": "",
            "part_nos_arrets_absents": "",
            "terminus_fiche": "",
            "terminus_itineraires": "",
            "terminus_officiels": (
                f"{points[0]} / {points[-1]}"
                if norm(points[0]) != norm(points[-1])
                else f"{points[0]} (boucle)"
            ),
            "points_officiels_non_trouves": "",
            "arrets_absents": "",
            "remarque": " ; ".join(notes),
        })
    return rangees, stats


def ecrire(chemin: Path, rangees: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8-sig", newline="") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=list(rangees[0]))
        ecrivain.writeheader()
        ecrivain.writerows(rangees)


def couverture_f1() -> tuple[Counter, Counter, list[tuple[str, str]]]:
    """L'audit F1 couvre 119 lignes ; notre fichier de lignes en sert 112."""
    audit = lire_csv(DATA / "audit" / "fiabilite_lignes.csv")
    nos = lire_csv(DATA / "lignes_dakar.csv")
    cles_audit = {(rangee["compagnie"], rangee["ligne"]) for rangee in audit}
    cles_nos = {(rangee["compagnie"], rangee["ligne"]) for rangee in nos}
    return (
        Counter(rangee["compagnie"] for rangee in audit),
        Counter(rangee["compagnie"] for rangee in nos),
        sorted(cles_audit - cles_nos),
    )


def main() -> int:
    rangees, stats = construire_rangees()
    ecrire(SORTIE, rangees)
    nos_lignes = [rangee for rangee in rangees if rangee["type_ligne"] == "notre_ligne"]
    absentes = [rangee for rangee in rangees if rangee["type_ligne"] == "ligne_officielle_absente"]
    audit, nos, manquantes = couverture_f1()

    print(f"{len(nos_lignes)} lignes comparées -> {SORTIE.relative_to(RACINE)}")
    print()
    print("Couverture de l'audit F1 :")
    print(
        f"  audit F1 : {sum(audit.values())} lignes "
        f"({audit[DEM_DIKK]} Dem Dikk, {audit[TATA]} Tata)"
    )
    print(
        f"  comparées : {sum(nos.values())} lignes "
        f"({nos[DEM_DIKK]} Dem Dikk, {nos[TATA]} Tata)"
    )
    print(
        f"  non comparées : {len(manquantes)} ligne(s) de l'audit "
        "absente(s) de data/lignes_dakar.csv"
    )
    for compagnie, ligne in manquantes:
        print(f"    - {compagnie} | {ligne}")
    print()

    classes = [
        "CONFORME", "A_COMPLETER", "TERMINUS_DIFFERENT", "DIVERGENTE",
        "DOUTEUSE", "SANS_SOURCE",
    ]
    operateurs = [DEM_DIKK, TATA]
    largeur_classe = max(len("Classe"), *(len(classe) for classe in classes))
    largeur_op = max(len(DEM_DIKK), len(TATA))
    separateur = (
        "-" * largeur_classe + "-+-" + "-" * largeur_op + "-+-"
        + "-" * largeur_op + "-+-" + "-" * 5
    )
    print(
        f"{'Classe':<{largeur_classe}} | {DEM_DIKK:>{largeur_op}} | "
        f"{TATA:>{largeur_op}} | Total"
    )
    print(separateur)
    for classe in classes:
        comptes = [
            sum(1 for rangee in nos_lignes if rangee["operateur"] == operateur and rangee["classe"] == classe)
            for operateur in operateurs
        ]
        print(
            f"{classe:<{largeur_classe}} | {comptes[0]:>{largeur_op}} | "
            f"{comptes[1]:>{largeur_op}} | {sum(comptes):>5}"
        )
    totaux = [
        sum(1 for rangee in nos_lignes if rangee["operateur"] == operateur)
        for operateur in operateurs
    ]
    print(separateur)
    print(
        f"{'Total':<{largeur_classe}} | {totaux[0]:>{largeur_op}} | "
        f"{totaux[1]:>{largeur_op}} | {sum(totaux):>5}"
    )
    print()
    print(
        f"Appariements incertains (souple/fuzzy) : {stats['arrets_souples']} arrêt(s) "
        f"sur {stats['lignes_souples']} ligne(s)"
    )
    print()

    cibles = [
        (TATA, "Ligne 3"), (TATA, "Ligne 4"), (TATA, "Ligne 30"),
        (TATA, "Ligne 57"), (TATA, "Ligne 58"), (TATA, "Ligne 62"),
        (TATA, "Ligne 74"),
        (DEM_DIKK, "Ligne 1"), (DEM_DIKK, "Ligne 6"),
        (DEM_DIKK, "Ligne 18"), (DEM_DIKK, "Ligne 220"),
    ]
    print("Taux de correspondance (points officiels retrouvés) :")
    for operateur, ligne in cibles:
        rangee = next(
            (
                rangee
                for rangee in nos_lignes
                if rangee["operateur"] == operateur and rangee["ligne"] == ligne
            ),
            None,
        )
        if rangee is None:
            print(f"  {operateur} | {ligne} : absent")
        else:
            taux = rangee["taux_correspondance"]
            print(f"  {operateur} | {ligne:<8} : {taux if taux != '' else 'n/a'} %")
    print()

    print(f"Lignes officielles absentes de nos données : {len(absentes)}")
    for rangee in sorted(absentes, key=lambda rangee: (rangee["operateur"], rangee["nom_officiel"])):
        print(f"  - {rangee['nom_officiel']} ({rangee['points_officiels']} points)")
    sans_source = [
        rangee for rangee in nos_lignes if rangee["classe"] == "SANS_SOURCE"
    ]
    if sans_source:
        print(
            "Nos lignes SANS_SOURCE (liste absente ou réduite aux 2 terminus indice) : "
            + ", ".join(
                f"{rangee['ligne']}" for rangee in sorted(
                    sans_source, key=lambda rangee: (rangee["operateur"], rangee["ligne"])
                )
            )
        )
    else:
        print("Nos lignes SANS_SOURCE : aucune")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
