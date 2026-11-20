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
# Listes officielles qu'on ne sert pas, même si elles sont dans CORRECTIONS_DDD :
# la page demdikk.sn donne pour la 217 la liste de la 218 et pour la 233 celle de
# la 232, point pour point (data/audit/rapport_lignes_divergentes.md). Ces lignes
# gardent nos terminus de itineraires_dakar.csv.
LIGNES_EXCLUES = DATA / "corrections" / "lignes_officiel_exclues.csv"
# Terminus qu'une liste officielle omet mais qu'une autre page officielle donne :
# la liste de la 501 (demdikk.sn/reseau-urbain-dakar) finit à Leclerc, le
# catalogue (demdikk.sn/info-voyageurs) dit « Gare de Dakar → Palais 2 ». Sans
# ce terminus, « Gare de Dakar » ne trouvait jamais la navette TER. Le terminus
# est ajouté au bout de CETTE ligne seulement : Leclerc n'est pas relié à la gare
# pour les lignes 1, 2, 4 ou 121.
TERMINUS_DDD = DATA / "corrections" / "terminus_ddd_officiels.csv"
# Positions officielles retirées de la mesure d'une ligne : « Corniche ouest »
# de la TO1 était géocodée au Palais de Justice (Cap Manuel), à ~8 km du
# Monument de la Renaissance, et le bus « passait » par le Plateau avant la
# Corniche. L'arrêt reste sur la ligne, sans position : à confirmer.
POSITIONS_RETIREES = DATA / "corrections" / "positions_ddd_retirees.csv"
# Lignes Dem Dikk absentes de toutes nos listes d'arrêts mais connues par une
# page officielle : l'Express AIBD (demdikk.sn/offres-de-transport), navette
# HLM Grand Yoff -> AIBD par l'autoroute, sans arrêt intermédiaire.
LIGNES_AJOUTEES = DATA / "corrections" / "lignes_ddd_ajoutees.csv"
ARRETS_GEO = DATA / "arrets_geo.csv"
CATEGORIE_SANS_ARRET = "Navette express, sans arrêt"
STATUT_A_CONFIRMER = "à confirmer"
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


def lignes_officiel_exclues(chemin: Path = LIGNES_EXCLUES) -> frozenset[str]:
    """Les lignes (« Ligne 217 ») dont la liste officielle est écartée ; vide sans fichier."""
    if not Path(chemin).exists():
        return frozenset()
    return frozenset(nom_ligne_ddd(r["ligne"]) for r in _lire(chemin) if (r.get("ligne") or "").strip())


def _position_sure(arret: str, arrets_geo: Path) -> tuple[str, str]:
    """(lat, lon) de l'arrêt si arrets_geo.csv le situe avec une confiance « bonne », sinon vide."""
    if Path(arrets_geo).exists():
        for rangee in _lire(arrets_geo):
            if rangee.get("arret") == arret and rangee.get("confiance") == "bonne":
                return rangee.get("lat") or "", rangee.get("lon") or ""
    return "", ""


def _ajouter_terminus(rangees: list[dict], terminus: Path, arrets_geo: Path) -> list[dict]:
    """Ajoute au bout de leur ligne les terminus de terminus_ddd_officiels.csv.

    « fin » : après le dernier arrêt ; « debut » : avant le premier. La position
    vient d'arrets_geo.csv (confiance « bonne ») ou reste vide : jamais devinée.
    Une ligne absente des listes officielles, ou un terminus qu'elle a déjà, est
    laissée telle quelle.
    """
    if not Path(terminus).exists():
        return rangees
    for ajout in _lire(terminus):
        ligne, nom = nom_ligne_ddd(ajout["ligne"]), (ajout.get("terminus") or "").strip()
        de_la_ligne = [r for r in rangees if r["ligne"] == ligne]
        if not nom or not de_la_ligne or any(r["arret"] == nom for r in de_la_ligne):
            continue
        ordres = [float(r["ordre"]) for r in de_la_ligne]
        ordre = max(ordres) + 1 if ajout.get("cote", "fin").strip() != "debut" else min(ordres) - 1
        lat, lon = _position_sure(nom, arrets_geo)
        rangees.append({
            **{cle: "" for cle in de_la_ligne[0]},
            "compagnie": de_la_ligne[0].get("compagnie") or DEM_DIKK,
            "ligne": ligne,
            "ordre": str(int(ordre)),
            "arret": nom,
            "lat": lat,
            "lon": lon,
            # Hors SOURCES_SURES : le point sert à mesurer la ligne, pas à
            # situer l'arrêt pour d'autres lignes.
            "source": "terminus_catalogue_ddd" if lat and lon else "inconnu",
            "detail": ajout.get("source", ""),
        })
    return rangees


def rangees_ddd_officielles(
    chemin: Path = CORRECTIONS_DDD,
    exclues: Path = LIGNES_EXCLUES,
    terminus: Path = TERMINUS_DDD,
    arrets_geo: Path = ARRETS_GEO,
) -> list[dict]:
    """Les rangées Dem Dikk officielles, avec la ligne et l'arrêt comme l'app les nomme.

    Les lignes de lignes_officiel_exclues.csv n'y sont pas : la nôtre reste servie.
    Les terminus de terminus_ddd_officiels.csv sont ajoutés au bout de leur ligne.
    """
    if not Path(chemin).exists():
        return []
    ecartees = lignes_officiel_exclues(exclues)
    rangees = (
        {**rangee, "ligne": nom_ligne_ddd(rangee["ligne"]), "arret": sans_terminus(rangee["arret"])}
        for rangee in _lire(chemin)
    )
    gardees = [rangee for rangee in rangees if rangee["ligne"] not in ecartees]
    return _retirer_positions(_ajouter_terminus(gardees, terminus, arrets_geo))


def _retirer_positions(rangees: list[dict], chemin: Path = POSITIONS_RETIREES) -> list[dict]:
    """Efface la position des arrêts de positions_ddd_retirees.csv (ligne + ordre + nom).

    Le nom doit correspondre aussi : si la liste officielle change, une ligne
    du fichier ne retire pas la position d'un autre arrêt.
    """
    if not Path(chemin).exists():
        return rangees
    retraits = {
        (nom_ligne_ddd(r["ligne"]), str(r["ordre"]).strip(), sans_terminus(r["arret"])): r.get("raison", "")
        for r in _lire(chemin)
    }
    for rangee in rangees:
        raison = retraits.get((rangee["ligne"], str(rangee["ordre"]).strip(), rangee["arret"]))
        if raison is not None:
            rangee.update(lat="", lon="", source="inconnu", detail=f"position retirée : {raison}")
    return rangees


def _arret_du_reseau(nom: str, connus: dict[str, str]) -> str | None:
    """Le nom d'arrêt du réseau pour un terminus de fiche, ou None s'il n'existe pas.

    « HLM Grand Yoff (face stade Léopold Sédar Senghor) » -> « HLM Grand Yoff » ;
    « Aéroport AIBD » -> « AIBD » (alias de la demande, matching/lieux.py).
    Jamais d'arrêt inventé : un terminus inconnu du réseau rend la ligne inutilisable.
    """
    try:
        from matching.lieux import ALIAS_DEMANDE
    except ImportError:  # pragma: no cover
        from .lieux import ALIAS_DEMANDE
    cle = cle_lieu(re.sub(r"\([^)]*\)", " ", nom))
    for essai in (cle, ALIAS_DEMANDE.get(cle, "")):
        if essai and essai in connus:
            return connus[essai]
    return None


def _nom_terminus(bout: str, arret: str) -> str:
    """Le nom d'arrêt d'un terminus de fiche : l'arrêt du réseau, plus le repère entre parenthèses.

    « HLM Grand Yoff (face stade Léopold Sédar Senghor) » devient « Terminus HLM
    Grand Yoff (Stade Léopold Sédar Senghor) » : routing/places.terminus_forms
    en tire les deux lieux, comme pour « Terminus liberté 5 (Dieuppeul) ». Sans
    cela, « Stade Léopold Sédar Senghor -> aéroport Blaise Diagne » ne trouvait
    pas l'Express AIBD, qui part pourtant en face du stade
    (demdikk.sn/offres-de-transport). Sans parenthèse, l'arrêt garde son nom.
    """
    trouve = re.search(r"\(([^()]*)\)", bout)
    repere = re.sub(r"^(?:en\s+)?face\s+(?:du\s+|de\s+la\s+|au\s+|à\s+)?", "", trouve.group(1).strip(),
                    flags=re.IGNORECASE) if trouve else ""
    if not repere:
        return arret
    return f"Terminus {arret} ({repere[0].upper()}{repere[1:]})"


def lignes_ddd_ajoutees(
    chemin: Path = LIGNES_AJOUTEES,
    itineraires_csv: Path = ITINERAIRES_CSV,
    corrections: Path = CORRECTIONS_DDD,
    arrets_geo: Path = ARRETS_GEO,
) -> list[dict]:
    """Les lignes de lignes_ddd_ajoutees.csv, prêtes pour le moteur : deux arrêts chacune.

    Position de chaque terminus, sans jamais la deviner :
    - celle d'une ligne officielle qui dessert déjà cet arrêt (AIBD : le repère
      de Diass du TAF TAF ; la position « bonne » d'arrets_geo.csv le met à
      Grand Yoff, erreur connue que le moteur corrige déjà) ;
    - sinon un arrêt « bonne » d'arrets_geo.csv (HLM Grand Yoff) ;
    - sinon rien, et la ligne est « à confirmer ».
    """
    if not Path(chemin).exists():
        return []
    officielles = rangees_ddd_officielles(corrections, arrets_geo=arrets_geo)
    noms = {r["arret"] for r in officielles}
    if Path(itineraires_csv).exists():
        noms |= {r["arret"] for r in _lire(itineraires_csv)}
    connus = {cle_lieu(nom): nom for nom in sorted(noms)}

    lignes = []
    for fiche in _lire(chemin):
        ligne = (fiche.get("ligne") or "").strip()
        compagnie = (fiche.get("compagnie") or "").strip() or DEM_DIKK
        bouts = [(fiche.get("terminus_depart") or "").strip(), (fiche.get("terminus_arrivee") or "").strip()]
        arrets = [_arret_du_reseau(bout, connus) for bout in bouts]
        if not ligne or None in arrets or arrets[0] == arrets[1]:
            continue
        rangees, statut = [], ""
        for ordre, (bout, arret) in enumerate(zip(bouts, arrets), start=1):
            nom = _nom_terminus(bout, arret)
            officielle = next(
                (r for r in officielles if r["arret"] == arret and r.get("lat") and r.get("lon")), None
            )
            if officielle is not None:
                lat, lon = officielle["lat"], officielle["lon"]
                source, detail = officielle.get("source", ""), f"position de la {officielle['ligne']}"
            else:
                lat, lon = _position_sure(arret, arrets_geo)
                source, detail = ("arrets_geo_bonne", "arrets_geo.csv") if lat and lon else ("inconnu", "")
            if not (lat and lon):
                statut = STATUT_A_CONFIRMER
            rangees.append({
                "compagnie": compagnie, "ligne": ligne, "ordre": str(ordre), "arret": nom,
                "lat": lat, "lon": lon, "source": source, "detail": detail,
            })
        sans_arret = "sans arrêt" in (fiche.get("type") or "").lower()
        lignes.append({
            "compagnie": compagnie,
            "ligne": ligne,
            "terminus_a": bouts[0],
            "terminus_b": bouts[1],
            "categorie": CATEGORIE_SANS_ARRET if sans_arret else (fiche.get("type") or "").strip(),
            "source": (fiche.get("source") or "").strip(),
            "statut": statut,
            "rangees": rangees,
        })
    return lignes


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
    ajoutees = [r for ligne in lignes_ddd_ajoutees(itineraires_csv=itineraires_csv, corrections=corrections)
                for r in ligne["rangees"]]
    return gardees + [
        {"compagnie": r["compagnie"], "ligne": r["ligne"], "ordre": r["ordre"], "arret": r["arret"]}
        for r in officielles + ajoutees
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
    # Les terminus des lignes ajoutées (« Terminus HLM Grand Yoff (Stade Léopold
    # Sédar Senghor) ») non plus : leur position vient de la fiche, pas d'un géocodage.
    noms_officiels |= {
        r["arret"]
        for ligne in lignes_ddd_ajoutees(itineraires_csv=itineraires_csv, corrections=corrections)
        for r in ligne["rangees"]
    }
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
