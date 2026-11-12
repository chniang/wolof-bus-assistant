r"""Audit de fiabilité F1/F2 : nos lignes et nos réponses face aux données de référence.

F1 — une rangée par ligne de nos données (Dem Dikk et Tata) : d'où viennent
ses arrêts, combien sont situés par une position mesurée, si la ligne est
réduite à ses deux terminus, et si data/reference/lignes_reference.csv la
connaît avec les mêmes terminus.

F2 — chaque trajet de data/reference/trajets_reference.csv passe dans notre
moteur, sous « Tous » puis sous le filtre de la compagnie de référence, sans
réseau (positions des CSV seulement). Statuts :

    OK            la ligne de référence est proposée
    AUTRE_LIGNE   seulement d'autres lignes, plausibles
    LIGNE_FAUSSE  une ligne proposée ne passe pas par le lieu, d'après la référence
    ABSENT        pas de réponse, ou lieu non reconnu

Lecture seule : aucun CSV de data/ n'est modifié, aucune requête réseau.

    .\.venv\Scripts\python.exe scripts\audit_fiabilite.py
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

REFERENCE = RACINE / "data" / "reference"
AUDIT = RACINE / "data" / "audit"
SORTIE_LIGNES = AUDIT / "fiabilite_lignes.csv"
SORTIE_TRAJETS = AUDIT / "verite_terrain.csv"

DEM_DIKK = "Dakar Dem Dikk"
TATA = "Tata AFTU"

# Ce qu'un usager appelle « Plateau » ou « UCAD » ne figure pas mot pour mot
# dans les listes d'arrêts de référence : sans ces équivalences, la ligne 1
# (Place de l'Indépendance, Ucad) passerait pour fausse vers « Plateau ».
EQUIVALENCES = {
    "plateau": ["plateau", "independance", "leclerc", "lat dior", "pompidou", "palais",
                "republique", "sandaga", "petersen", "gare de dakar", "embarcadere"],
    "ucad": ["ucad", "universite", "fann", "ecole normale", "canal 4"],
    "medina": ["medina", "tilene", "rue 6", "gueule tapee"],
    # Avenue Jean Jaurès et Lat Dior bordent le marché Sandaga (moins de 600 m).
    "sandaga": ["sandaga", "petersen", "pompidou", "jean jaures", "lat dior"],
    "colobane": ["colobane"],
    "parcelles assainies": ["parcelles", "unite", "grand medine", "acapes"],
    "guediawaye": ["guediawaye", "golf", "hamo", "wakhinane", "sahm notaire", "daroukhane"],
    "rufisque": ["rufisque"],
    "yoff": ["yoff", "aeroport lss", "ngor"],
    "aeroport lss": ["aeroport", "lss", "yoff"],
    "grand yoff": ["grand yoff", "grand-yoff", "scat urbam", "hlm grand yoff", "cto", "idrissa pouye"],
    "liberte 6": ["liberte 6", "liberte vi", "jvc", "camp penal"],
    "liberte 5": ["liberte 5", "dieuppeul"],
    "keur massar": ["keur massar"],
    "thiaroye": ["thiaroye"],
    "malika": ["malika"],
    "pikine": ["pikine", "icotaf"],
    "ouakam": ["ouakam"],
    "almadies": ["almadies", "ngor"],
    "maristes": ["maristes", "hann"],
    "hann": ["hann", "maristes", "bel air"],
}


def norm(texte: object) -> str:
    """Minuscules, sans accents ni ponctuation : pour comparer des noms."""
    texte = unicodedata.normalize("NFKD", str(texte or ""))
    texte = "".join(c for c in texte if not unicodedata.combining(c)).lower()
    texte = re.sub(r"[’'`\-–/,;.()]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def cle_ligne(nom: object) -> str:
    """« Ligne 16A », « 16A », « 16 A » -> « 16a » ; « TAF TAF OUAKAM (TO1) » garde son texte."""
    texte = norm(nom)
    texte = re.sub(r"^ligne ", "", texte)
    return re.sub(r"^(\d+) ([a-z])$", r"\1\2", texte)


def meme_ligne(cle_ref: str, cle_nous: str) -> bool:
    # « taf taf » (référence) couvre « taf taf ouakam to1 » (nos itinéraires officiels).
    return cle_ref == cle_nous or cle_nous.startswith(cle_ref + " ")


def operateur(texte: str) -> str:
    return TATA if "aftu" in norm(texte) or "tata" in norm(texte) else DEM_DIKK


def proche(a: str, b: str) -> bool:
    """Deux noms de terminus désignent-ils le même endroit ? Inclusion ou forte ressemblance."""
    a, b = norm(a).replace("terminus ", ""), norm(b).replace("terminus ", "")
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    mots_a, mots_b = set(a.split()) - {"de", "des", "la", "le", "du", "gare"}, set(b.split()) - {"de", "des", "la", "le", "du", "gare"}
    if mots_a & mots_b and len(mots_a & mots_b) >= min(len(mots_a), len(mots_b)) / 2:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.8


# ---------------------------------------------------------------- référence

def lire_csv(chemin: Path) -> list[dict]:
    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        return list(csv.DictReader(fichier))


def lignes_reference() -> dict[tuple[str, str], dict]:
    return {(operateur(r["operateur"]), cle_ligne(r["ligne"])): r for r in lire_csv(REFERENCE / "lignes_reference.csv")}


def chercher_reference(refs: dict, compagnie: str, cle: str) -> dict | None:
    for (op, cle_ref), rangee in refs.items():
        if op == compagnie and meme_ligne(cle_ref, cle):
            return rangee
    return None


# ---------------------------------------------------------------- F1

def audit_lignes() -> list[dict]:
    from routing.data import CORRECTIONS_DDD, CORRECTIONS_TATA, SOURCES_SURES, load_data

    data = load_data()
    refs = lignes_reference()

    # Source de chaque arrêt, ligne par ligne, telle que le moteur la lit.
    sources: dict[tuple[str, str], list[str]] = {}
    for chemin in (CORRECTIONS_DDD, CORRECTIONS_TATA):
        if not chemin.exists():
            continue
        for r in lire_csv(chemin):
            nom = r["ligne"] if r["compagnie"] == TATA else (
                f"Ligne {r['ligne']}" if r["ligne"][:1].isdigit() else r["ligne"])
            sources.setdefault((r["compagnie"], nom), []).append(r["source"])
    ddd_officielles = {cle for cle in sources if cle[0] == DEM_DIKK}
    confiance = dict(zip(data.arrets["arret"], data.arrets["confiance"]))

    rangees = []
    for ligne in data.lignes.itertuples(index=False):
        cle = (ligne.compagnie, ligne.ligne)
        arrets = data.itineraires[
            (data.itineraires["compagnie"] == ligne.compagnie) & (data.itineraires["ligne"] == ligne.ligne)
        ]["arret"].tolist()
        n = len(arrets)
        if cle in sources:
            src = sources[cle]
            mesures = sum(s in SOURCES_SURES for s in src)
            interpoles = sum(s.startswith("interpolation") for s in src)
            total = len(src)
        else:
            # Pas de position par ligne : la confiance d'arrets_geo.csv décide.
            total = n
            mesures = sum(confiance.get(a) == "bonne" for a in arrets)
            interpoles = 0
        if ligne.compagnie == TATA and ligne.ligne in data.traces:
            origine = "trace officielle AFTU"
        elif cle in ddd_officielles:
            origine = "itinéraire officiel DDD"
        elif cle in sources:
            origine = "OSM / corrections"
        else:
            origine = f"devinée ({ligne.source})" if str(ligne.source) not in ("", "nan") else "devinée"
        ref = chercher_reference(refs, ligne.compagnie, cle_ligne(ligne.ligne))
        if ref is None:
            dans_ref, meme_terminus = "non", ""
        else:
            nous = (str(ligne.terminus_a), str(ligne.terminus_b))
            eux = (ref["terminus_1"], ref["terminus_2"])
            meme = (proche(nous[0], eux[0]) and proche(nous[1], eux[1])) or (
                proche(nous[0], eux[1]) and proche(nous[1], eux[0]))
            dans_ref, meme_terminus = "oui", "oui" if meme else "non"
        rangees.append({
            "compagnie": ligne.compagnie,
            "ligne": ligne.ligne,
            "terminus_a": ligne.terminus_a,
            "terminus_b": ligne.terminus_b,
            "source": origine,
            "nb_arrets": n,
            "pct_mesure": round(100 * mesures / total) if total else 0,
            "pct_interpole": round(100 * interpoles / total) if total else 0,
            "pct_devine": round(100 * (total - mesures - interpoles) / total) if total else 100,
            "terminus_seulement": "oui" if n <= 2 else "non",
            "dans_reference": dans_ref,
            "meme_terminus": meme_terminus,
            "terminus_reference": f"{ref['terminus_1']} / {ref['terminus_2']}" if ref else "",
        })
    return rangees


# ---------------------------------------------------------------- F2

def moteur_hors_ligne():
    """Le moteur de l'app (v2, repli v1), sans géocodage réseau."""
    from matching.stops_matcher import StopsMatcher
    from routing.adapter import MoteurV2

    repli = StopsMatcher()
    repli.geo.point = repli.geo.point_connu
    return MoteurV2(repli)


def variantes(lieu: str) -> list[str]:
    """« Liberté 5 (Dieuppeul) » -> le nom entier, puis « Liberté 5 », puis « Dieuppeul »."""
    sortie = [lieu.strip()]
    avant = re.sub(r"\(.*?\)", "", lieu).strip()
    dedans = re.findall(r"\((.*?)\)", lieu)
    if avant:
        sortie.append(avant)
    for morceau in dedans:
        sortie += [m.strip() for m in morceau.split(",") if m.strip()]
    return list(dict.fromkeys(sortie))


def lignes_attendues(texte: str, op_ref: str) -> list[list[tuple[str, str]]]:
    """« 15A / 15B » -> deux possibilités ; « 75 puis DDD 18 » -> une suite de deux bus."""
    possibilites = []
    for choix in texte.split(" / "):
        etapes = []
        for morceau in re.split(r"\s+puis\s+", choix.strip()):
            morceau = morceau.strip()
            if morceau.upper().startswith("DDD "):
                etapes.append((DEM_DIKK, cle_ligne(morceau[4:])))
            else:
                op = TATA if "aftu" in norm(op_ref) else DEM_DIKK
                etapes.append((op, cle_ligne(morceau)))
        possibilites.append(etapes)
    return possibilites


def options(resultat: dict) -> list[dict]:
    """Chaque option proposée : ses bus (compagnie, ligne), ses arrêts de montée/descente, ses minutes."""
    sortie = []
    for t in resultat.get("lignes") or []:
        sortie.append({"etapes": [t], "minutes": t.get("minutes")})
    for c in resultat.get("correspondances") or []:
        sortie.append({"etapes": [c["etape_1"], c["etape_2"]], "minutes": c.get("minutes")})
    for t in resultat.get("trajets_2") or []:
        sortie.append({"etapes": list(t.get("etapes") or []), "minutes": t.get("minutes")})
    return sortie


def texte_option(option: dict) -> str:
    morceaux = []
    for e in option["etapes"]:
        op = "DDD" if e["compagnie"] == DEM_DIKK else "Tata"
        morceaux.append(f"{op} {cle_ligne(e['ligne']).upper()} ({e.get('monte_a_reseau', '?')} -> {e.get('descend_a_reseau', '?')})")
    return " puis ".join(morceaux) + (f" [{option['minutes']} min]" if option.get("minutes") is not None else "")


def sert_le_lieu(ref_ligne: dict | None, lieu: str, arret_nous: str) -> bool | None:
    """Selon la référence, la ligne passe-t-elle par ce lieu ? None : on ne sait pas."""
    if ref_ligne is None:
        return None
    texte = norm(" ; ".join([ref_ligne["terminus_1"], ref_ligne["terminus_2"], ref_ligne["arrets_principaux"]]))
    mots = []
    for v in variantes(lieu):
        cle = norm(v)
        mots += EQUIVALENCES.get(cle, [cle])
    mots.append(norm(arret_nous))
    if any(m and m in texte for m in mots):
        return True
    # 47 lignes de référence n'ont que leurs deux terminus : un lieu absent
    # de ces deux noms ne prouve rien (Tata 25 passe par bien plus que
    # « Parcelles Assainies / Petersen »). Faux seulement face à une vraie liste.
    return False if ref_ligne["arrets_principaux"].strip() else None


def classer(resultat: dict, attendues, refs, depart: str, arrivee: str) -> tuple[str, str]:
    opts = options(resultat)
    if not opts:
        return "ABSENT", ""
    for option in opts:
        suite = [(e["compagnie"], cle_ligne(e["ligne"])) for e in option["etapes"]]
        for attendu in attendues:
            if len(suite) == len(attendu) and all(
                op == op_a and meme_ligne(cle_a, cle) for (op, cle), (op_a, cle_a) in zip(suite, attendu)
            ):
                return "OK", ""
    fausses = []
    for option in opts:
        premiere, derniere = option["etapes"][0], option["etapes"][-1]
        for etape, lieu, arret in ((premiere, depart, premiere.get("monte_a_reseau", "")),
                                   (derniere, arrivee, derniere.get("descend_a_reseau", ""))):
            ref = chercher_reference(refs, etape["compagnie"], cle_ligne(etape["ligne"]))
            if sert_le_lieu(ref, lieu, arret) is False:
                fausses.append(f"{etape['ligne']} ne passe pas par {lieu}")
    if fausses:
        return "LIGNE_FAUSSE", " ; ".join(dict.fromkeys(fausses))
    return "AUTRE_LIGNE", ""


def audit_trajets(moteur=None) -> list[dict]:
    moteur = moteur or moteur_hors_ligne()
    refs = lignes_reference()
    rangees = []
    for ref in lire_csv(REFERENCE / "trajets_reference.csv"):
        attendues = lignes_attendues(ref["ligne"], ref["operateur"])
        compagnies_ref = {op for suite in attendues for op, _ in suite}
        filtre = compagnies_ref if len(compagnies_ref) == 1 else None
        # Le premier couple de noms qui donne une réponse : nom entier, puis sans parenthèses…
        resultat_tous, noms = {}, (ref["depart"], ref["arrivee"])
        for dep in variantes(ref["depart"]):
            for arr in variantes(ref["arrivee"]):
                essai = moteur.find_line(dep, arr)
                if options(essai):
                    resultat_tous, noms = essai, (dep, arr)
                    break
            if resultat_tous:
                break
        statut_tous, detail_tous = classer(resultat_tous, attendues, refs, ref["depart"], ref["arrivee"])
        if filtre:
            resultat_filtre = moteur.find_line(noms[0], noms[1], filtre)
            statut_filtre, detail_filtre = classer(resultat_filtre, attendues, refs, ref["depart"], ref["arrivee"])
        else:
            # Trajet mixte Tata + Dem Dikk : aucun filtre d'une seule compagnie ne l'admet.
            resultat_filtre, statut_filtre, detail_filtre = resultat_tous, statut_tous, detail_tous
        rangees.append({
            "depart": ref["depart"],
            "arrivee": ref["arrivee"],
            "reference": f"{ref['operateur']} {ref['ligne']}",
            "reference_montee": ref["arret_montee"],
            "reference_descente": ref["arret_descente"],
            "statut_reference": ref["statut"],
            "noms_utilises": f"{noms[0]} -> {noms[1]}",
            "statut_tous": statut_tous,
            "reponse_tous": " | ".join(texte_option(o) for o in options(resultat_tous)),
            "filtre": " + ".join(sorted(filtre)) if filtre else "(mixte : Tous)",
            "statut_filtre": statut_filtre,
            "reponse_filtre": " | ".join(texte_option(o) for o in options(resultat_filtre)),
            "detail": " ; ".join(d for d in (detail_tous, detail_filtre) if d),
        })
    return rangees


def score(rangees: list[dict], colonne: str) -> Counter:
    return Counter(r[colonne] for r in rangees)


def ecrire(chemin: Path, rangees: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8-sig", newline="") as fichier:
        ecrivain = csv.DictWriter(fichier, fieldnames=list(rangees[0]))
        ecrivain.writeheader()
        ecrivain.writerows(rangees)


def main() -> int:
    lignes = audit_lignes()
    ecrire(SORTIE_LIGNES, lignes)
    print(f"F1 : {len(lignes)} lignes -> {SORTIE_LIGNES.relative_to(RACINE)}")
    for compagnie in (DEM_DIKK, TATA):
        sous = [r for r in lignes if r["compagnie"] == compagnie]
        print(f"  {compagnie} : {len(sous)} lignes ; sources {dict(Counter(r['source'].split(' (')[0] for r in sous))} ;"
              f" mesuré moyen {sum(r['pct_mesure'] for r in sous) / max(len(sous), 1):.0f} % ;"
              f" terminus seuls {sum(r['terminus_seulement'] == 'oui' for r in sous)} ;"
              f" absentes de la référence {sum(r['dans_reference'] == 'non' for r in sous)} ;"
              f" terminus différents {sum(r['meme_terminus'] == 'non' for r in sous)}")
    trajets = audit_trajets()
    ecrire(SORTIE_TRAJETS, trajets)
    print(f"F2 : {len(trajets)} trajets -> {SORTIE_TRAJETS.relative_to(RACINE)}")
    print("  Tous   :", dict(score(trajets, "statut_tous")))
    print("  Filtre :", dict(score(trajets, "statut_filtre")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
