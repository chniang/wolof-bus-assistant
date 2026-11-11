r"""Vérifie que les trajets de référence trouvent la bonne ligne.

Deux modes :

    .\.venv\Scripts\python.exe tests\test_trajets.py            (local, quelques secondes)
    .\.venv\Scripts\python.exe tests\test_trajets.py --en-ligne (l'app publiée sur Hugging Face)

- local : extraction des lieux, recherche de ligne, interface Gradio et vidage
  du micro, sans modèle ni GPU ni LLM. À lancer après chaque modification.
- en ligne : envoie les phrases à l'app publiée, exactement comme un visiteur.
  À lancer après chaque déploiement, avant de partager le lien.

Code de sortie : 0 si tout passe, 1 sinon.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

SPACE = "TIJAANI/guindima-ai"

# Phrase (y compris telle que l'ASR l'écrit) -> lignes dont au moins une doit sortir.
# « corr: » = trajet avec changement attendu, dont le 1er bus est cette ligne.
TRAJETS = [
    ("maa ngi Liberté 6, bëgg naa dem Palais", {"Ligne 9"}),
    ("maa ngi liberti sis bëgg naa dem pale", {"Ligne 9"}),
    ("maa ngi liberti sënk bëgg naa dem pale dë", {"Ligne 10", "Ligne 13"}),
    ("Dama bëgg dem Palais, maa ngi Ouakam", {"Ligne 7"}),
    ("maa ngi wakaam dama bëgga dem pale", {"Ligne 7"}),
    ("Maa ngi Guédiawaye, dama bëgg dem Palais", {"Ligne 5", "Ligne 12"}),
    ("Maa ngi Thiaroye, bëgg naa dem Ouakam", {"Ligne 217"}),
    ("Maa ngi Pikine, dama bëgg dem Colobane", {"Ligne 48", "Ligne 50", "Ligne 75"}),
    ("Maa ngi Keur Massar, dama bëgg dem UCAD", {"Ligne 54", "Ligne 71"}),
    # Tata 62 passe désormais par Sahm, entre UCAD et Penc Mi : le trajet est
    # direct, sans correspondance à UCAD.
    ("Rond-Point Sahm, bëgg naa dem Colobane", {"Ligne 62"}),
    # Ligne 78 : Liberté 5 -> Golf (Guédiawaye), DIRECT. « Département de
    # Guédiawaye » compte pour Guédiawaye quand l'utilisateur dit « Guédiawaye »
    # (jamais « Dakar »), et une ligne directe passe avant une correspondance.
    # L'itinéraire officiel de Dem Dikk 6 relie aussi les deux directement.
    ("Maa ngi Liberté 5, dama bëgg dem Guédiawaye", {"Ligne 6", "Ligne 78"}),
    ("Maa ngi Pikine, bëgg naa dem Guédiawaye", {"Ligne 37", "Ligne 41", "Ligne 46"}),
]

# Trajets qui doivent rester DIRECTS, sans correspondance proposée :
# phrase -> lignes directes acceptées (au moins une).
TRAJETS_DIRECTS = {
    "Maa ngi Liberté 5, dama bëgg dem Guédiawaye": {"Ligne 6", "Ligne 78"},
    "Rond-Point Sahm, bëgg naa dem Colobane": {"Ligne 62"},
}

# Arrêts qui ne doivent jamais servir (montée ni descente) sur un trajet :
# le « Stade Amadou Barry » touche Pikine, il n'est pas une descente fiable pour
# Pikine -> Guédiawaye.
# (phrase, noms d'arrêt interdits comme montée ou descente).
TRAJETS_SANS_ARRET = [
    ("Maa ngi Pikine, bëgg naa dem Guédiawaye", {"Stade Amadou Barry"}),
]

# Noms d'équipement sans localité (« Préfecture ») : position non fiable, comme
# « Rue 9 ». Le « Préfecture » de la ligne 46 (banlieue) est géocodé au Plateau à
# tort : Sandaga -> Pikine ne doit donc pas y monter.
# (phrase, noms d'arrêt interdits comme montée).
TRAJETS_SANS_MONTEE_GENERIQUE = [
    ("Maa ngi Sandaga, dama bëgg dem Pikine", {"Préfecture"}),
]

# Lignes qui ne doivent surtout PAS sortir pour une phrase : « Garage Guédiawaye »
# (ligne 71) est à Dakar, pas dans le quartier Guédiawaye ; les lignes 30 et 49 ne
# montent pas dans Pikine (elles y arrivent par un arrêt hors quartier).
TRAJETS_EXCLUS = {
    "Maa ngi Pikine, bëgg naa dem Guédiawaye": {"Ligne 71", "Ligne 30", "Ligne 49"},
}

# Voies « faux amis » (voir FAUX_AMIS) : une voie nommée d'après un quartier ne doit
# jamais servir de montée. « Route de Rufisque » est à Dakar, à 16,7 km de Rufisque.
# (phrase, nom d'arrêt interdit comme montée).
TRAJETS_SANS_MONTEE_FAUSSE = [
    ("Maa ngi Rufisque, dama bëgg dem Colobane", "Route de Rufisque"),
]

# Homonymes géocodés ailleurs : « Rue 9 » et « Avenue Cheikh Anta Diop » ont été
# posés aux Almadies. Leur position ne doit jamais servir à conseiller la montée.
# (phrase, noms d'arrêt interdits comme montée).
TRAJETS_SANS_MONTEE_HOMONYME = [
    ("Maa ngi Almadies, dama bëgg dem Médina", {"Rue 9", "Avenue Cheikh Anta Diop"}),
]

# Phrases qui nomment un quartier que les noms d'arrêts ne portent pas (Médina,
# Sandaga) : la position des arrêts (arrets_geo.csv) doit faire trouver une ligne.
# (phrase, lignes attendues — au moins une —, lignes interdites).
TRAJETS_GEO = [
    # Compagnie nommée : n'importe quelle ligne de cette compagnie, et rien d'autre.
    ("Maa ngi Liberté 6, dama bëgg dem Médina ak Tata", frozenset(), frozenset()),
    ("Maa ngi Sandaga, dama bëgg dem Pikine", {"Ligne 27", "Ligne 55", "Ligne 56"}, frozenset()),
]

# Phrases qui nomment une compagnie : (phrase, compagnie attendue, lignes de
# cette compagnie attendues, compagnies interdites dans le résultat).
TRAJETS_COMPAGNIE = [
    ("Maa ngi Pikine, dama bëgg dem Colobane ak Tata", "Tata AFTU", {"Ligne 48", "Ligne 50", "Ligne 75"}, {"Dakar Dem Dikk"}),
    ("Maa ngi Liberté 6, bëgg naa dem Palais ci Dem Dikk", "Dakar Dem Dikk", {"Ligne 9"}, {"Tata AFTU"}),
    # Bug ASR réel : « liberation siis » (Liberté 6) et « madiina » (Médina).
    # Le chiffre dit « siis » ne doit pas devenir l'arrêt « SIPS », et Tata doit
    # tout de même trouver sa ligne 1.
    # Attendues vides : n'importe quelle ligne de la compagnie convient.
    ("maa ngi liberation siis dama bëgg a dem madiina ak tata", "Tata AFTU", frozenset(), {"Dakar Dem Dikk"}),
]

# Cas réel : « Liberté 5 -> Médina » avec Tata. Tata n'a pas de ligne directe ;
# l'app doit proposer un trajet entièrement Tata s'il existe, sinon afficher le
# bandeau « aucune ligne Tata, même avec un changement » et les lignes Dem Dikk.
TRAJET_COMPAGNIE_REEL = "Maa ngi Liberté 5, dama bëgg dem Médina ak Tata"

# Phrases dont un lieu contient « dakar » : le nom de compagnie ne doit pas
# l'éclipser. (phrase, départs acceptés, arrivées acceptées)
TRAJETS_LIEUX = [
    ("Maa ngi Dakar Plateau, dama bëgg dem Nord Foire", {"Dakar Plateau", "Plateau"}, {"Nord Foire"}),
    ("Maa ngi Grand Dakar, dama bëgg dem Parcelles", {"Grand Dakar"}, {"Parcelles"}),
]

# Grands quartiers qu'aucun arrêt ne nomme : nommer le quartier doit tout de même
# proposer au moins une ligne, directe ou avec changement.
TRAJETS_QUARTIER = [
    "Maa ngi Dakar Plateau, dama bëgg dem Nord Foire",
]

# Le marqueur de DÉPART « diougué / diogué / jóge » (« partir de X ») introduit le
# lieu d'où l'on part, où qu'il soit : dans « Ban bus moy diougué X pour dém Y », X
# est le départ et Y l'arrivée. Vérifie l'extraction seule (départ, arrivée).
# (phrase, départs acceptés, arrivée attendue)
TRAJETS_DIOUGUE = [
    ("Ban bus moy diougué Keur Mbaye Fall pour dém Rufisque", {"Keur Mbaye Fall"}, "Rufisque"),
    ("Ban bus mo diogué Grand Yoff dem Parcelles", {"Grand Yoff", "Grand-Yoff"}, "Parcelles"),
    ("Ban bus moy diougué Mermoz dém Ngor", {"Mermoz"}, "Ngor"),
    ("bëgg na diogué HLM dem Sacré-Cœur", {"HLM"}, "Sacré Cœur"),
    ("bëgg na diogué Liberté 6 dem Nord Foire", {"Liberté 6"}, "Nord Foire"),
]

# Faux matches à ne JAMAIS produire (passe d'orthographe sur la collecte) :
# (phrase, lieux interdits — ni départ ni arrivée).
LIEUX_INTERDITS = [
    # « Grand Médine » (HLM, à Grand Yoff) n'est pas la Médina de Dakar.
    ("maa ngi Grand Médine dama bëgg dem Parcelles", {"Médina", "Medina"}),
    # « Sicap Baobab » n'est ni « Banoba » ni « SICAP Mbao » : lieu non reconnu,
    # on laisse vide plutôt que de deviner.
    ("maa ngi Sicap Baobab dama bëgg dem Patte d'Oie", {"Banoba", "SICAP Mbao"}),
    # Un mot « sicap » seul ne désigne aucun lieu.
    ("sicap", {"SICAP Mbao"}),
]

# Variantes Whisper « sûres » (scripts/analyser_whisper.py, étape 5) : entendues
# ≥2 fois chez ≥2 locuteurs différents, lieu visé confirmé comme le plus proche.
# Un seul cas réel de la collecte peut couvrir plusieurs variantes à la fois.
# (phrase réelle ou reconstituée, départ attendu, arrivée attendue).
TRAJETS_VARIANTES_SURES = [
    ("maa ngi faas dama bëgg dem palais", "Fass", "Palais"),
    ("maa ngi liberte 6 dama bëgg dem foor", "Liberté 6", "Foire"),
    # « jëppal » (Dieuppeul) et « yoof » (Yoff) dans le même vocal réel.
    ("maa ngiy yoof damaa bëgga dem jëppal", "Yoff", "Dieuppeul"),
    # « ker ma saar » (Keur Massar) et « sakkari kër » (Sacré-Cœur) réels.
    ("mbaa ngiy kër ma saar te ba bëgg a leen sakkari kër", "Keur Massar", "Sacré Cœur"),
    ("maa ngi liberte 6 dama bëgg dem mbaaw", "Liberté 6", "Mbao"),
    ("maa ngi parsel dama bëgg dem ouakam", "Parcelles", "Ouakam"),
    ("ban biis laa man a jël pour dem madi na maa ngi sonde kaptas", "Zone de Captage", "Médina"),
    ("maa ngi yaraax dama bëgg dem ouakam", "Yarakh", "Ouakam"),
    ("maa ngi yembal dama begga dem geran yoof", "Yeumbeul", "Grand-Yoff"),
    # « asoleem », « aslem », « oshlem » (HLM) : cas réels de la collecte.
    ("maa ngi lekk sandaga bës ban lawara jël pour dem aslem", "Sandaga", "HLM"),
    ("maa ngi asoleem bëgg bislaa war jël wu dem parsel", "HLM", "Parcelles"),
    ("maa ngi liberation sanc bën biis la war a jël pour dem oshlem", "Liberté", "HLM"),
]

# Marqueur de départ, famille jóge/joge, juge, njuge, njugee (liste blanche
# MARQUEURS_DEPART_PROPRES, en plus de diougué/diogué couverts par
# TRAJETS_DIOUGUE). « dem » n'est JAMAIS un marqueur de départ (voir CLAUDE.md).
# (phrase, départs acceptés, arrivée attendue).
TRAJETS_MARQUEUR_ETENDU = [
    ("bël mbuus ma joge sanni dagay bu dem yoof", {"Sandaga"}, "Yoff"),
    ("bëgg bi naa juge hlm dem ouakam", {"HLM"}, "Ouakam"),
    ("man mbés mu njuge ka masar jëmme dinaa", {"Keur Massar"}, "Médina"),
    ("ban bis ma njuge keur mbaye fall per dem rufisque", {"Keur Mbaye Fall"}, "Rufisque"),
]

# Garde-fous : les nouvelles variantes ci-dessus ne doivent jamais faire perdre
# un lieu DÉJÀ bien reconnu (un match court mais exact qui l'emporterait sur un
# match plus long mais approximatif). (phrase réelle, départ attendu, arrivée).
TRAJETS_GARDES_VARIANTES = [
    # « gerana yoof » doit rester Grand-Yoff, pas juste Yoff.
    ("ma ngi naari tali dma begg a dem gerana yoof", "Taliboubess", "Grand-Yoff"),
    # « faas mbaaw » doit rester Fass Mbao, pas juste Mbao.
    ("maa ngi kér mbay fall dama bëgg a dem faas mbaaw", "Keur Mbaye Fall", "Fass Mbao"),
    # « noor foor » doit rester Nord Foire, pas juste Foire.
    ("bëgg naa jóge libertesis dem noor foor ban mbirus laa wara jël", "Liberté", "Nord Foire"),
    # « foor » juste avant « dem » est « pour dem », jamais « Foire ».
    ("maa ngi Yoff foor dem Parcelles", "Yoff", "Parcelles"),
    # « west foor dem » doit quand même devenir Foire (règle dédiée, avant le
    # garde-fou ci-dessus) : Ouest Foire n'est pas un lieu du réseau,
    # extract_local(propre) le réduit lui aussi à Foire.
    ("bëgg naa juge west foor dem garañ yoof man bislaw a jël", "Foire", "Grand-Yoff"),
]

# Corrections de faux matches : lieux qui doivent être reconnus correctement.
# (phrase, départ attendu, arrivée attendue).
TRAJETS_CORRIGES = [
    # « Zone de Captage » est l'arrêt, jamais « Zone B » : le « de » du nom ne
    # doit pas laisser le mot « zone » tomber seul sur un autre arrêt.
    ("maa ngi Bène Tally ban bus la warra dieul pour dém Zone de Captage", "Bène Tally", "Zone de Captage"),
    # L'arrêt « Banoba » (vrai) reste reconnu par son nom exact.
    ("maa ngi Banoba dama bëgg dem Patte d'Oie", "Banoba", "Patte d'Oie"),
]

# Cas réels ASR (Whisper secours) : la transcription fautive doit se réduire aux
# bons lieux. (phrase, départ attendu, arrivée attendue).
TRAJETS_ASR = [
    # « bën biis maa juge as lm kurdem sakkere kër » pour « Ban bus moy diougué
    # HLM pour dém Sacré-Cœur » : ne doit plus donner « Bene Baraque ».
    ("bën biis maa juge as lm kurdem sakkere kër", "HLM", "Sacré Cœur"),
    # « Bene Baraque » écrit correctement reste reconnu.
    ("Maa ngi Bene Baraque, dama bëgg dem Pikine", "Bene Baraque", "Pikine"),
    # « keur » ne doit pas être avalé par la règle Sacré-Cœur : Keur Massar et
    # Keur Mbaye Fall restent des lieux.
    ("maa ngi Keur Massar dama bëgg dem Pikine", "Keur Massar", "Pikine"),
    ("maa ngi Keur Mbaye Fall dama bëgg dem Rufisque", "Keur Mbaye Fall", "Rufisque"),
]

# Mots génériques (rond-point, marché, croisement, station, poste…) suivis d'un
# nom : c'est le nom qui doit choisir le lieu. Le générique seul ne vaut rien, et
# quand un lieu complet existe avec ce nom (« Rond-Point Colobane »), il passe
# avant l'arrêt réduit au nom seul (« Colobane »).
# (phrase, départs acceptés, arrivée attendue).
TRAJETS_MOTS_GENERIQUES = [
    # Bug réel : « rond point » se rapprochait de « Rond-Point École Mariste »
    # et passait avant Sahm, pourtant nommé juste après.
    ("dama nekk rond point sahm ma bëgg dem colobane", {"Sahm", "SAHM", "SHAM"}, "Colobane"),
    ("maa ngi rond point colobane dama bëgg dem palais", {"Rond-Point Colobane"}, "Palais"),
    ("maa ngi rond point liberté six dama bëgg dem palais", {"Rond-Point Liberté 6"}, "Palais"),
    ("maa ngi marché tilène dama bëgg dem palais", {"Marché Tilène"}, "Palais"),
    ("maa ngi croisement keur massar dama bëgg dem palais", {"Croisement Keur Massar"}, "Palais"),
    ("maa ngi station keur massar dama bëgg dem palais", {"Station Keur Massar"}, "Palais"),
    ("maa ngi cité assurance dama bëgg dem palais", {"Cité Assurance"}, "Palais"),
    ("maa ngi poste thiaroye dama bëgg dem palais", {"Poste Thiaroye"}, "Palais"),
    # Non-régression : un lieu complet dit en entier reste reconnu tel quel.
    ("maa ngi rond point école mariste dama bëgg dem palais", {"Rond-Point École Mariste"}, "Palais"),
    ("maa ngi rond point almadies dama bëgg dem palais", {"Rond-Point Almadies"}, "Palais"),
    # Variantes ASR de Sahm, toutes ramenées au même arrêt.
    ("maa ngi sahm dama bëgg dem palais", {"Sahm", "SAHM", "SHAM"}, "Palais"),
    ("maa ngi sam dama bëgg dem palais", {"Sahm", "SAHM", "SHAM"}, "Palais"),
    ("maa ngi saam dama bëgg dem palais", {"Sahm", "SAHM", "SHAM"}, "Palais"),
    ("maa ngi sham dama bëgg dem palais", {"Sahm", "SAHM", "SHAM"}, "Palais"),
]

# Phrases texte envoyées en plus à l'app publiée (--en-ligne) : elles traversent
# la vraie extraction (NVIDIA) et la carte affichée, pas seulement l'extraction locale.
TRAJETS_EN_LIGNE = [
    ("Maa ngi Liberté 6, dama bëgg dem Médina ak Tata", {"Ligne 1"}),
    ("Maa ngi Sandaga, dama bëgg dem Pikine", {"Ligne 27", "Ligne 41", "Ligne 50", "Ligne 55", "Ligne 56"}),
]

def _ok(trouvees: set[str], attendues: set[str], exclues: set[str] = frozenset()) -> bool:
    return bool(trouvees & attendues) and not (trouvees & exclues)


def _lignes(resultat: dict) -> set[str]:
    """Numéros de ligne trouvés, les correspondances préfixées « corr: »."""
    trouvees = {l["ligne"] for l in resultat["lignes"]}
    trouvees |= {"corr:" + c["etape_1"]["ligne"] for c in resultat["correspondances"]}
    return trouvees


def _arrets_utilises(resultat: dict) -> set[str]:
    """Arrêts conseillés comme montée ou descente, correspondances comprises."""
    arrets = set()
    for ligne in resultat["lignes"]:
        arrets.add(ligne["monte_a"])
        arrets.add(ligne["descend_a"])
    for trajet in resultat["correspondances"]:
        for etape in (trajet["etape_1"], trajet["etape_2"]):
            arrets.add(etape["monte_a"])
            arrets.add(etape["descend_a"])
    return arrets


def _detail(resultat: dict) -> str:
    """Détail à vérifier à la main : ligne, arrêt de montée, arrêt de descente."""
    morceaux = [
        f"{ligne['ligne']} : monte à {ligne['monte_a']} → descends à {ligne['descend_a']}"
        for ligne in resultat["lignes"]
    ]
    for trajet in resultat["correspondances"]:
        e1, e2 = trajet["etape_1"], trajet["etape_2"]
        morceaux.append(
            f"corr {e1['ligne']} : monte à {e1['monte_a']} → descends à {e1['descend_a']} "
            f"| puis {e2['ligne']} : monte à {e2['monte_a']} → descends à {e2['descend_a']}"
        )
    return "  ;  ".join(morceaux) or "rien"


def _matcher():
    """Le moteur choisi par GUINDIMA_MOTEUR (v1, ou v2 avec repli sur v1).

    Les attentes des tests ne changent pas : on vérifie seulement ce que l'app
    répond réellement, avec le moteur actif.
    """
    import os

    from matching.stops_matcher import StopsMatcher

    repli = StopsMatcher()
    if os.getenv("GUINDIMA_MOTEUR", "v2").strip().lower() == "v1":
        return repli
    from routing.adapter import MoteurV2

    return MoteurV2(repli)


def _matcher_hors_ligne():
    """Le même moteur, sans aucun appel Nominatim : seuls les points des CSV.

    Un lieu inconnu (« Guinaw Rails ») partait sinon en géocodage réseau, et
    le cache data/sources/cache_lieux_nominatim.json changeait pendant les tests.
    """
    matcher = _matcher()
    repli = getattr(matcher, "_repli", matcher)
    repli.geo.point = repli.geo.point_connu
    return matcher


def test_local() -> int:
    from intent.extract_intent import extract_local
    from matching.compagnie import message_autre_compagnie
    from matching.stops_matcher import StopsMatcher

    matcher = _matcher()
    echecs = 0
    for phrase, attendues in TRAJETS:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = _lignes(resultat)
        bon = _ok(trouvees, attendues, TRAJETS_EXCLUS.get(phrase, frozenset()))
        # Une ligne directe passe avant une correspondance : si le trajet est attendu
        # direct, aucune correspondance ne doit être proposée.
        directe = TRAJETS_DIRECTS.get(phrase)
        if directe:
            bon = bon and bool(directe & {l["ligne"] for l in resultat["lignes"]}) and not resultat["correspondances"]
        echecs += not bon
        print(f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n      {lieux.get('depart')} -> {lieux.get('arrivee')}")
        print(f"      {_detail(resultat) if (resultat['lignes'] or resultat['correspondances']) else 'rien'}")
    for phrase, compagnie, attendues, interdites in TRAJETS_COMPAGNIE:
        lieux = extract_local(phrase)
        # Le chemin réel de l'app quand une compagnie est nommée.
        resultat, _ = matcher.find_line_compagnie(
            lieux.get("depart") or "", lieux.get("arrivee") or "", compagnie
        )
        trouvees = {l["ligne"] for l in resultat["lignes"] if l["compagnie"] == compagnie}
        exclues = {l["ligne"] for l in resultat["lignes"] if l["compagnie"] in interdites}
        bon = lieux.get("compagnie") == compagnie and _ok(
            trouvees, attendues or trouvees, exclues
        )
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      compagnie={lieux.get('compagnie')!r} | {lieux.get('depart')} -> {lieux.get('arrivee')}"
        )
        print(f"      {_detail(resultat) if (resultat['lignes'] or resultat['correspondances']) else 'rien'}")
    # Des arrêts précis ne doivent jamais être utilisés (montée ni descente).
    for phrase, interdits in TRAJETS_SANS_ARRET:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        utilises = _arrets_utilises(resultat)
        bon = not (utilises & interdits)
        echecs += not bon
        print(f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (arrêts interdits)\n      {_detail(resultat)}")
    # Un nom d'équipement sans localité ne doit jamais servir de montée.
    for phrase, interdites in TRAJETS_SANS_MONTEE_GENERIQUE:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        montees = {ligne["monte_a"] for ligne in resultat["lignes"]}
        for trajet in resultat["correspondances"]:
            montees.add(trajet["etape_1"]["monte_a"])
            montees.add(trajet["etape_2"]["monte_a"])
        bon = not (montees & interdites)
        echecs += not bon
        print(f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (montée générique)\n      montées : {sorted(montees)}")
    # Cas réel : la compagnie demandée n'a pas forcément de ligne directe. On
    # reproduit le choix de l'app : trajet 100 % Tata s'il existe, sinon bandeau
    # « aucune ligne Tata » suivi des lignes des autres compagnies (Dem Dikk).
    lieux = extract_local(TRAJET_COMPAGNIE_REEL)
    resultat, exacte = matcher.find_line_compagnie(
        lieux.get("depart") or "", lieux.get("arrivee") or "", "Tata AFTU"
    )
    if exacte:
        compagnies = {ligne["compagnie"] for ligne in resultat["lignes"]}
        for trajet in resultat["correspondances"]:
            compagnies.add(trajet["etape_1"]["compagnie"])
            compagnies.add(trajet["etape_2"]["compagnie"])
        bon = bool(resultat["found"] or resultat["correspondances"]) and compagnies == {"Tata AFTU"}
        reponse = "Tata : " + (
            ", ".join(ligne["ligne"] for ligne in resultat["lignes"])
            or " ; ".join(
                f"{c['etape_1']['ligne']} puis {c['etape_2']['ligne']}"
                for c in resultat["correspondances"]
            )
        )
    else:
        trouvees = {ligne["ligne"] for ligne in resultat["lignes"]}
        trouvees |= {"corr:" + c["etape_1"]["ligne"] for c in resultat["correspondances"]}
        message = message_autre_compagnie("Tata AFTU", resultat)
        bon = (
            bool(trouvees)
            and "pas trouvé de ligne Tata" in message
            and "Dem Dikk" in message
        )
        reponse = f"{message} {sorted(trouvees)}"
    echecs += not bon
    print(
        f"{'OK ' if bon else 'ÉCHEC'} | {TRAJET_COMPAGNIE_REEL}\n"
        f"      compagnie=Tata AFTU | exacte={exacte} | {reponse}"
    )
    # « tata » ne doit jamais être pris pour un lieu.
    lieux = extract_local("tata")
    bon = (
        not lieux.get("depart")
        and not lieux.get("arrivee")
        and lieux.get("compagnie") == "Tata AFTU"
    )
    echecs += not bon
    print(
        f"{'OK ' if bon else 'ÉCHEC'} | « tata » n'est jamais un lieu "
        f"({lieux.get('depart')!r} -> {lieux.get('arrivee')!r}, compagnie={lieux.get('compagnie')!r})"
    )
    # « siis » (six, dit en wolof) ne doit jamais devenir l'arrêt « SIPS ».
    lieux = extract_local("siis")
    bon = not lieux.get("depart") and not lieux.get("arrivee")
    echecs += not bon
    print(
        f"{'OK ' if bon else 'ÉCHEC'} | « siis » n'est jamais un lieu "
        f"({lieux.get('depart')!r} -> {lieux.get('arrivee')!r})"
    )
    # Un lieu contenant « dakar » survit à la détection de compagnie.
    for phrase, departs, arrivees in TRAJETS_LIEUX:
        lieux = extract_local(phrase)
        bon = (
            lieux.get("depart") in departs
            and lieux.get("arrivee") in arrivees
            and not lieux.get("compagnie")
        )
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # « diougué / diogué » (partir de) : le lieu qui suit le marqueur est le départ.
    for phrase, departs, arrivee in TRAJETS_DIOUGUE:
        lieux = extract_local(phrase)
        bon = lieux.get("depart") in departs and lieux.get("arrivee") == arrivee
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # Un lieu ne doit jamais être confondu avec un autre (faux matches connus).
    for phrase, interdits in LIEUX_INTERDITS:
        lieux = extract_local(phrase)
        trouves = {lieux.get("depart"), lieux.get("arrivee")}
        bon = not (trouves & interdits)
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (lieux interdits)\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # Variantes Whisper « sûres » : départ et arrivée exacts attendus.
    for phrase, depart, arrivee in TRAJETS_VARIANTES_SURES:
        lieux = extract_local(phrase)
        bon = lieux.get("depart") == depart and lieux.get("arrivee") == arrivee
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (variante sûre)\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # Marqueur de départ étendu (jóge/joge, juge, njuge, njugee).
    for phrase, departs, arrivee in TRAJETS_MARQUEUR_ETENDU:
        lieux = extract_local(phrase)
        bon = lieux.get("depart") in departs and lieux.get("arrivee") == arrivee
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (marqueur étendu)\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # Garde-fous : les variantes sûres ne doivent pas écraser un lieu déjà reconnu.
    for phrase, depart, arrivee in TRAJETS_GARDES_VARIANTES:
        lieux = extract_local(phrase)
        bon = lieux.get("depart") == depart and lieux.get("arrivee") == arrivee
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (garde-fou variante)\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # Lieux corrigés : départ et arrivée exacts attendus.
    for phrase, depart, arrivee in TRAJETS_CORRIGES:
        lieux = extract_local(phrase)
        bon = lieux.get("depart") == depart and lieux.get("arrivee") == arrivee
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (lieu corrigé)\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # Cas réels ASR : départ et arrivée exacts attendus.
    for phrase, depart, arrivee in TRAJETS_ASR:
        lieux = extract_local(phrase)
        bon = lieux.get("depart") == depart and lieux.get("arrivee") == arrivee
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase} (ASR)\n"
            f"      {lieux.get('depart')!r} -> {lieux.get('arrivee')!r}"
        )
    # Un grand quartier (Plateau) doit trouver au moins une ligne.
    for phrase in TRAJETS_QUARTIER:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = {l["ligne"] for l in resultat["lignes"]}
        trouvees |= {"corr:" + c["etape_1"]["ligne"] for c in resultat["correspondances"]}
        bon = bool(trouvees)
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      {lieux.get('depart')} -> {lieux.get('arrivee')}"
        )
        print(f"      {_detail(resultat) if (resultat['lignes'] or resultat['correspondances']) else 'rien'}")
    # Un quartier dit tel quel (Médina, Sandaga) doit trouver une ligne grâce aux
    # positions des arrêts (data/arrets_geo.csv), pas seulement à leur nom.
    for phrase, attendues, exclues in TRAJETS_GEO:
        lieux = extract_local(phrase)
        compagnie = lieux.get("compagnie")
        if compagnie:
            resultat, _ = matcher.find_line_compagnie(
                lieux.get("depart") or "", lieux.get("arrivee") or "", compagnie
            )
        else:
            resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = {l["ligne"] for l in resultat["lignes"]}
        trouvees |= {"corr:" + c["etape_1"]["ligne"] for c in resultat["correspondances"]}
        bon = _ok(trouvees, attendues or trouvees, exclues) and (
            not compagnie
            or {l["compagnie"] for l in resultat["lignes"]} == {compagnie}
        )
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      {lieux.get('depart')} -> {lieux.get('arrivee')}"
        )
        print(f"      {_detail(resultat) if (resultat['lignes'] or resultat['correspondances']) else 'rien'}")
    # Une voie « Route de X » (faux ami) ne doit jamais servir de montée.
    for phrase, voie in TRAJETS_SANS_MONTEE_FAUSSE:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        montees = {ligne["monte_a"] for ligne in resultat["lignes"]}
        for trajet in resultat["correspondances"]:
            montees.add(trajet["etape_1"]["monte_a"])
            montees.add(trajet["etape_2"]["monte_a"])
        bon = voie not in montees
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      montées : {sorted(montees)}"
        )
    # Un homonyme géocodé ailleurs (Rue 9, Avenue Cheikh Anta Diop) ne doit jamais
    # être conseillé comme montée.
    for phrase, interdites in TRAJETS_SANS_MONTEE_HOMONYME:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        montees = {ligne["monte_a"] for ligne in resultat["lignes"]}
        for trajet in resultat["correspondances"]:
            montees.add(trajet["etape_1"]["monte_a"])
            montees.add(trajet["etape_2"]["monte_a"])
        bon = not (montees & interdites)
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      montées : {sorted(montees)}"
        )
    return echecs


def test_mots_generiques() -> tuple[int, int]:
    """Un mot générique ne choisit jamais le lieu : le nom qui suit décide.

    Reproduit le bug réel « dama nekk rond point sahm ma bëgg dem colobane »,
    où « rond point » s'accrochait à « Rond-Point École Mariste » au lieu de
    laisser Sahm (nommé juste après) devenir le départ. Vérifie l'extraction
    locale et le chemin LLM (réponse correcte, puis repli local si le LLM ne
    rend aucun lieu).
    """
    from intent.extract_intent import extract_intent, extract_local

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | génériques {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    for phrase, departs, arrivee in TRAJETS_MOTS_GENERIQUES:
        lieux = extract_local(phrase)
        bon = lieux.get("depart") in departs and lieux.get("arrivee") == arrivee
        verifie(
            phrase,
            bon,
            f"{lieux.get('depart')!r} -> {lieux.get('arrivee')!r}",
        )

    phrase = "dama nekk rond point sahm ma bëgg dem colobane"
    attendus = {"Sahm", "SAHM", "SHAM"}
    for contenu, source in (
        ('{"depart": "Sahm", "arrivee": "Colobane"}', "llm"),
        ('{"depart": "", "arrivee": ""}', "llm+local"),
    ):
        resultat = extract_intent(phrase, client=_FauxClient(contenu))
        bon = (
            resultat.get("depart") in attendus
            and resultat.get("arrivee") == "Colobane"
            and resultat.get("source") == source
        )
        verifie(
            f"chemin LLM simulé ({source})",
            bon,
            f"{resultat.get('depart')!r} -> {resultat.get('arrivee')!r} "
            f"(source={resultat.get('source')!r})",
        )
    return echecs, total


def test_distance_courte() -> tuple[int, int]:
    """La mention à pied sous 1 km, sans retirer les bus proposés.

    Les points viennent uniquement des CSV (jamais de géocodage réseau pendant
    les tests). Cas réel demandé : Sahm → Colobane mesure en fait ~1,42 km à vol
    d'oiseau, donc la mention ne doit PAS apparaître ; Médina → Marché Tilène
    (~125 m) la fait apparaître, avec les bus toujours affichés.
    """
    import os

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_distance")
    from matching.geo import distance_metres

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | distance {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    geo = app.MATCHER.geo

    # Cas demandé : Sahm → Colobane. La distance réelle dépasse 1 km, donc pas
    # de mention à pied ; les bus, eux, restent proposés.
    points = geo.point_connu("Sahm"), geo.point_connu("Colobane")
    distance = distance_metres(*points) if all(points) else None
    verifie(
        "Sahm → Colobane : 1,42 km, pas de mention sous 1 km",
        distance is not None
        and 1400 < distance < 1450
        and geo.minutes_a_pied("Sahm", "Colobane") is None,
        (distance, geo.minutes_a_pied("Sahm", "Colobane")),
    )
    resultat = app.MATCHER.find_line("Sahm", "Colobane")
    carte = app._carte(resultat, "Sahm", "Colobane")
    verifie(
        "Sahm → Colobane : bus conservés sans mention à pied",
        bool(resultat["found"] or resultat["correspondances"])
        and "C'est tout près" not in carte,
        carte[:200],
    )

    # Cas court positif : la mention apparaît en plus de la carte du bus.
    depart, arrivee = "Médina", "Marché Tilène"
    minutes = geo.minutes_a_pied(depart, arrivee)
    resultat = app.MATCHER.find_line(depart, arrivee)
    carte = app._carte(resultat, depart, arrivee)
    mention = (
        f"C'est tout près : environ {minutes} min à pied" if minutes else ""
    )
    verifie(
        "Médina → Marché Tilène : environ 2 min à pied",
        minutes == 2 and mention in carte,
        (minutes, carte[:300]),
    )
    verifie(
        "la mention à pied ne retire pas le bus",
        bool(resultat["found"]) and "Monte à" in carte,
        carte[:300],
    )
    return echecs, total


def test_sahm_ligne_62() -> tuple[int, int]:
    """Tata 62 passe par Sahm, et la recherche préfère le trajet direct.

    La correction terrain ajoute Sahm entre UCAD (17) et Penc Mi (19) sur la
    ligne 62. Sahm doit être reconnu comme sur les lignes 7, 23, 32 et 38, et
    Rond-Point Sahm -> Colobane doit sortir Tata 62 sans correspondance.
    """
    import csv

    from matching.lieux import score
    from matching.stops_matcher import StopsMatcher

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | Sahm/Tata 62 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    with open(
        RACINE / "data" / "itineraires_dakar.csv", newline="", encoding="utf-8"
    ) as fichier:
        rangees = list(csv.DictReader(fichier))
    ligne62 = [
        rangee
        for rangee in rangees
        if rangee["compagnie"] == "Tata AFTU" and rangee["ligne"] == "Ligne 62"
    ]
    ordres = {rangee["arret"]: int(rangee["ordre"]) for rangee in ligne62}
    verifie(
        "Sahm inséré entre UCAD et Penc Mi",
        ordres.get("UCAD") == 17
        and ordres.get("Sahm") == 18
        and ordres.get("Penc Mi (Gueule Tapée)") == 19,
        ordres,
    )

    matcher = _matcher()
    for compagnie, ligne in (
        ("Dakar Dem Dikk", "Ligne 7"),
        ("Dakar Dem Dikk", "Ligne 23"),
        ("Tata AFTU", "Ligne 32"),
        ("Tata AFTU", "Ligne 38"),
        ("Tata AFTU", "Ligne 62"),
    ):
        arrets = matcher.arrets[(compagnie, ligne)]
        verifie(
            f"{ligne} reconnaît Sahm",
            any(score("Sahm", arret) == 1.0 for arret in arrets),
            [arret for arret in arrets if "sahm" in arret.lower()],
        )

    verifie(
        "Rond-Point Sahm se résout comme Sahm",
        score("Rond-Point Sahm", "Sahm") == 1.0,
        score("Rond-Point Sahm", "Sahm"),
    )

    # Aucun appel réseau pendant les tests : on limite la géolocalisation aux
    # points déjà présents dans les CSV, comme le fait l'affichage.
    ancien_point = matcher.geo.point
    matcher.geo.point = matcher.geo.point_connu
    try:
        resultat = matcher.find_line("Rond-Point Sahm", "Colobane")
    finally:
        matcher.geo.point = ancien_point
    directes = [
        ligne
        for ligne in resultat["lignes"]
        if ligne["compagnie"] == "Tata AFTU" and ligne["ligne"] == "Ligne 62"
    ]
    verifie(
        "Rond-Point Sahm -> Colobane : Tata 62 direct, sans correspondance",
        resultat["found"]
        and not resultat["correspondances"]
        and bool(directes)
        and directes[0]["monte_a"] in {"Sahm", "SAHM"}
        and directes[0]["descend_a"] == "Colobane",
        (
            resultat["lignes"],
            resultat["correspondances"],
        ),
    )
    return echecs, total


def test_moteur_v2() -> tuple[int, int]:
    """Moteur v2 : lieux résolus comme v1, pas de téléportation, pas de repli caché.

    Ces cas n'ont de sens que pour v2 : sous v1 ils ne comptent pas, le total
    reste celui du moteur historique.
    """
    import os

    if os.getenv("GUINDIMA_MOTEUR", "v2").strip().lower() == "v1":
        return 0, 0

    from matching.stops_matcher import StopsMatcher
    from routing import adapter
    from routing.network import Line, Network
    from routing.router import Leg, ResolvedPlace, Trip, Walk

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | moteur v2 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    repli = StopsMatcher()
    repli.geo.point = repli.geo.point_connu
    moteur = adapter.MoteurV2(repli)

    # chercher_v2 est appelé en direct : une exception ferait échouer le test, au
    # lieu de passer inaperçue derrière le repli v1 (un v2 cassé affichait 274/274).
    ucad = adapter.chercher_v2(repli, "Keur Massar", "UCAD")
    verifie(
        "UCAD atteint « Université Cheikh Anta Diop » sur Tata 54",
        any(
            ligne["ligne"] == "Ligne 54"
            and ligne["descend_a"] == "Université Cheikh Anta Diop"
            for ligne in ucad["lignes"]
        ),
        ucad["lignes"],
    )
    verifie(
        "Keur Massar -> UCAD : direct, sans Dem Dikk 11 ni changement",
        ucad["lignes"]
        and not ucad["correspondances"]
        and not ucad["trajets_2"]
        and all(ligne["ligne"] != "Ligne 11" for ligne in ucad["lignes"]),
        ucad,
    )
    verifie(
        "Sandaga est reconnu (par sa position, comme v1)",
        adapter._resoudre(repli, "Sandaga")["valide"],
    )
    verifie(
        "lieu inconnu de GuindiMa : le résultat exact de v1",
        moteur.find_line("Zzzqwx", "Colobane") == repli.find_line("Zzzqwx", "Colobane"),
    )

    # Une ligne de 2 arrêts sans position : la durée est un forfait, et la carte le dit.
    reseau_vide = Network([Line("Op", "Bus", ("A", "B"))], {})
    arete = next(
        arete
        for aretes in reseau_vide.adjacency.values()
        for arete in aretes
        if arete.kind == "ride"
    )
    verifie(
        "2 arrêts sans position : 35 min, marquée estimée",
        arete.minutes == 35.0 and arete.estimated,
        arete,
    )
    forfaits = [
        ligne
        for ligne in adapter._NETWORK.lines.values()
        if len(ligne.stops) == 2
        and adapter._NETWORK._segment_distances(ligne) == (None,)
    ]
    verifie("le réseau réel compte de telles lignes", bool(forfaits))
    forfait = forfaits[0]
    trajet_forfait = adapter._ENGINE.find_trips(
        forfait.stops[0],
        forfait.stops[1],
        first_line=forfait.key,
        origin_place=ResolvedPlace(stops=(forfait.stops[0],)),
        destination_place=ResolvedPlace(stops=(forfait.stops[1],)),
        direct_only=True,
        max_trips=9,
    )
    bus_forfait = [trajet for trajet in trajet_forfait if trajet.legs]
    verifie(
        "la durée estimée arrive jusqu'à la carte",
        bool(bus_forfait)
        and bus_forfait[0].estimated
        and adapter._direct(bus_forfait[0])["estimee"]
        and "durée estimée" in (RACINE / "app.py").read_text(encoding="utf-8"),
        [forfait.key, bus_forfait],
    )

    # Un changement à pied : l'adaptateur transmet les minutes au message de partage.
    def _bus(ligne: str, depart: str, arrivee: str) -> Leg:
        return Leg(
            operator="Tata AFTU",
            line=ligne,
            board_stop=depart,
            alight_stop=arrivee,
            direction=adapter._NETWORK.lines[("Tata AFTU", ligne)].stops[-1],
            num_stops=1,
            minutes=10.0,
        )

    a_pied = Trip(
        legs=(_bus("Ligne 49", "Ngor", "Liberté 6"), _bus("Ligne 30", "Giratoire Liberté VI", "Gare de Colobane")),
        walks=(Walk("transfer", "Liberté 6", "Giratoire Liberté VI", 3.6, 290.0, after_leg=1),),
        total_minutes=30.0,
        transfers=1,
        line_combo=(),
        origin_name="Ngor",
        destination_name="Colobane",
        total_distance_m=None,
        straight_line_m=None,
        detour=False,
        via_downtown=False,
        ridden_stops=(),
    )
    verifie(
        "l'adaptateur donne les minutes de marche d'un changement",
        adapter._correspondance(a_pied)["marches"] == [4],
        adapter._correspondance(a_pied),
    )

    # Le départ des Maristes, jamais Keur Ngoor ; et les mêmes arrêts pour v1 et v2.
    resolu = adapter._resoudre(repli, "Rond-Point École Mariste")
    verifie(
        "Rond-Point École Mariste : les Maristes, jamais Keur Ngoor",
        resolu["arret"] == "Maristes"
        and "Maristes" in resolu["large"].stops
        and not any("Keur Ngoor" in arret for arret in resolu["large"].stops),
        resolu,
    )
    verifie(
        "v1 et v2 reconnaissent le même arrêt des Maristes",
        repli.find_line("Rond-Point École Mariste", "Palais")["depart_matched"]
        == "Maristes",
    )
    verifie(
        "« Keur Ngoor » dit tel quel trouve toujours son arrêt",
        adapter._resoudre(repli, "Keur Ngoor")["arret"]
        == "Keur Ngoor (Rond-Point École Mariste)",
    )

    # AIBD est à Diass : plus jamais « à pied » depuis Grand Yoff, où le plaçait le CSV.
    aibd = adapter._NETWORK.coords("AIBD")
    verifie(
        "AIBD situé à Diass, loin de Grand Yoff",
        aibd is not None and aibd[1] > -17.2,
        aibd,
    )
    verifie(
        "Grand Yoff -> AIBD ne se fait pas à pied",
        not adapter.chercher_v2(repli, "Grand Yoff", "AIBD")["a_pied"],
    )

    # Le chemin réel de l'app pour « ak Tata » : uniquement du Tata.
    tata, exacte = moteur.find_line_compagnie("Liberté 6", "Médina", "Tata AFTU")
    verifie(
        "Liberté 6 -> Médina ak Tata : uniquement des lignes Tata",
        exacte
        and bool(tata["lignes"])
        and {ligne["compagnie"] for ligne in tata["lignes"]} == {"Tata AFTU"},
        tata["lignes"],
    )
    verifie(
        "le graphe est construit dès l'import, avant le premier usager",
        adapter._NETWORK._adjacency is not None,
    )
    almadies = adapter.chercher_v2(repli, "Almadies", "Malika")
    troncons = [
        etape
        for trajet in almadies["correspondances"]
        for etape in (trajet["etape_1"], trajet["etape_2"])
    ]
    verifie(
        "sans plafond ni plancher : la durée annoncée est la somme réelle du trajet",
        almadies["correspondances"]
        and all(
            trajet["minutes"]
            >= trajet["etape_1"]["minutes"] + trajet["etape_2"]["minutes"] - 1
            for trajet in almadies["correspondances"]
        )
        and bool(troncons),
        almadies["correspondances"],
    )

    # Le choix du moteur se dit franchement : v2 par défaut, v1 sur demande
    # explicite, et surtout plus jamais un repli v1 en douce quand v2 casse.
    # On exécute la pellicule de app.py (l'assignation MOTEUR + la construction)
    # sous de faux modules : aucun réseau, aucun modèle chargé.
    import sys
    import types

    source_app = (RACINE / "app.py").read_text(encoding="utf-8")
    pellicule = source_app[source_app.index("MOTEUR = os.getenv") :]
    pellicule = pellicule[: pellicule.index("MATCHER = _construire_matcher()")]

    class V1Fausse:
        """Fausse classe de l'ancien moteur, juste un repère d'identité."""

    class V2Fausse:
        """Faux moteur v2 : sa construction fait semblant d'échouer."""

        def __init__(self, _repli):
            raise Exception("graphe impossible : dépendance absente")

    module_matching = types.ModuleType("matching")
    module_stops = types.ModuleType("matching.stops_matcher")
    module_stops.StopsMatcher = V1Fausse
    module_routing = types.ModuleType("routing")
    module_adapter = types.ModuleType("routing.adapter")
    module_adapter.MoteurV2 = V2Fausse

    anciens = {
        nom: sys.modules.get(nom)
        for nom in ("matching", "matching.stops_matcher", "routing", "routing.adapter")
    }
    env_ancien = os.environ.get("GUINDIMA_MOTEUR")
    recus: list[object] = []
    try:
        for nom, module in (
            ("matching", module_matching),
            ("matching.stops_matcher", module_stops),
            ("routing", module_routing),
            ("routing.adapter", module_adapter),
        ):
            sys.modules[nom] = module
        # Trois scénarios : variable absente (= défaut), « v1 », valeur inconnue.
        for scenario in (None, "v1", "v9"):
            if scenario is None:
                os.environ.pop("GUINDIMA_MOTEUR", None)
            else:
                os.environ["GUINDIMA_MOTEUR"] = scenario
            portee: dict = {"os": os, "StopsMatcher": V1Fausse}
            exec(pellicule, portee)
            try:
                recus.append(portee["_construire_matcher"]())
            except Exception as plantage:
                recus.append(plantage)
    finally:
        # On rend tout : les vrais modules, l'environnement tel qu'il était.
        for nom, module in anciens.items():
            if module is None:
                sys.modules.pop(nom, None)
            else:
                sys.modules[nom] = module
        if env_ancien is None:
            os.environ.pop("GUINDIMA_MOTEUR", None)
        else:
            os.environ["GUINDIMA_MOTEUR"] = env_ancien

    verifie(
        "sans GUINDIMA_MOTEUR : v2 démarre, sinon l'échec est franc (jamais v1 en douce)",
        isinstance(recus[0], RuntimeError)
        and "v2" in str(recus[0])
        and recus[0].__cause__ is not None,
        recus[0],
    )
    verifie(
        "GUINDIMA_MOTEUR=v1 : l'ancien moteur, exprès",
        recus[1].__class__ is V1Fausse,
        recus[1],
    )
    verifie(
        "GUINDIMA_MOTEUR=v9 : valeur inconnue, défaut v2 et son échec franc",
        isinstance(recus[2], RuntimeError) and "v2" in str(recus[2]),
        recus[2],
    )
    return echecs, total


def test_conversation() -> tuple[int, int]:
    """Petite conversation : les 12 phrases validées, et un trajet gagne toujours.

    Les phrases de réponse sont celles validées par un locuteur natif : elles sont
    recopiées ici pour qu'aucune modification ne passe inaperçue.
    """
    import contextlib
    import csv
    import io
    import json
    import re
    import tempfile

    import tts.speak as speak
    from intent.conversation import HORS_SUJET, INTENTIONS, detecter

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | conversation {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    reponses = {
        "salutation": "Maalekum salaam ! Fan nga bëgga dem ?",
        "ca_va": "Maa ngi fi rekk, jërëjëf. Yaw nag ? Fan nga bëgga dem ?",
        "ci_lo_nekk": "Maa ngi ci jàmm, alxamdulilaay. Yaw nag ?",
        "liggeey": "Sama liggéey mooy won nit ñi biis bi ñuy jël ci Ndakaaru.",
        "role": "Maa ngi tudd GuindiMa. Damay won nit ñi bus bi ñuy jël ci Ndakaaru.",
        "dekk": "Ci Ndakaaru laa dëkk, ci biir sa telefon.",
        "wolof": "Waaw, dégg naa wolof. Wax ma fan nga bëgga dem.",
        "merci": "Ñoo ko bokk ! Soo ma soxlaa, maa ngi lay déglu.",
        "createur": "Cheikh Niang moo ma defar.",
        "capacites": "Wax ma fan nga nekk ak fan nga bëgga dem, ma won la bus bi nga wara jël.",
        "au_revoir": "Ba beneen yoon !",
        "hors_sujet": "Baal ma, bus yi rekk laa xam. Wax ma fan nga nekk ak fan nga bëgga dem.",
    }
    obtenues = {i.nom: i.reponse for i in INTENTIONS + (HORS_SUJET,)}
    verifie("les 12 phrases validées, mot pour mot", obtenues == reponses, obtenues)

    exemples = {
        "salutation": [
            "salam", "Salamaleykoum", "asalaa maalekum", "Bonjour", "salut", "hello",
            "salaam aleekum", "salam alaykum", "Salamalekum", "assalamou alaykoum",
            "assalamu alaykum",
        ],
        "ca_va": [
            "nanga def", "na nga def", "naka nga def", "naka waa", "ça va ?",
            "comment tu vas", "nangadef", "mbaa jamm nga am", "jamm nga am",
        ],
        "ci_lo_nekk": ["silo nekk", "silo neh", "si lo nekk", "ci lo nekk", "silo nex"],
        "liggeey": ["lan mooy sa liggeey", "lan mooy sa ligeey", "lane mooy sa ligeey", "lan ngay def"],
        "role": [
            "kan nga", "naka nga tudd", "noo tudd", "yaay kan", "yaay kane",
            "yaw la kan", "yaw la kane", "qui es-tu", "tu fais quoi", "c'est quoi ton rôle",
        ],
        "dekk": ["fan nga dekk"],
        "wolof": ["ndax danga degg wolof", "ndax degg nga wolof", "degg nga wolof", "ndakh danga degg wolof"],
        "merci": ["jërëjëf", "jerejef", "jaajëf", "merci", "dieuredieuf"],
        "createur": ["kan moo la defar", "kan moo la sos", "qui t'a créé", "qui t'a fait"],
        "capacites": ["lan nga mëna def", "qu'est-ce que tu peux faire"],
        "au_revoir": ["ba beneen", "ba beneen yoon", "ba suba", "mangi dem", "maa ngi dem", "au revoir", "bye"],
    }
    for nom, phrases in exemples.items():
        for phrase in phrases:
            trouve = detecter(phrase)
            verifie(f"{phrase!r} -> {nom}", trouve is not None and trouve.nom == nom, trouve and trouve.nom)
    verifie("« quel temps fait-il » : aucune petite conversation", detecter("quel temps fait-il") is None)
    verifie("« qu'est-ce que tu peux faire » n'est pas un trajet vers la Foire",
            not extract_local_sans_lieu("qu'est-ce que tu peux faire"))
    # Une demande de trajet n'est JAMAIS une petite conversation, même par
    # ressemblance floue : l'app n'appelle detecter que sans lieu, mais le
    # détecteur doit aussi refuser tout seul.
    verifie("« Maa ngi Ouakam, bëgg naa dem Médina » : jamais une conversation",
            detecter("Maa ngi Ouakam, bëgg naa dem Médina") is None)

    app = _charger_module(RACINE / "app.py", "app_guindima_conversation")
    with contextlib.redirect_stdout(io.StringIO()):
        salam, salam_ok = app._pipeline("salam", "", 0.0)
        mixte, _ = app._pipeline("salam, maa ngi Ouakam dama bëgg dem Médina", "", 0.0)
        mixte_arrivee, _ = app._pipeline("salam, dama bëgga dem Médina", "", 0.0)
        hors, hors_ok = app._pipeline("quel temps fait-il", "", 0.0)
        trajet, trajet_ok = app._pipeline("Maa ngi Ouakam, bëgg naa dem Médina", "", 0.0)
    verifie(
        "« salam » : la salutation à l'écran",
        salam_ok and reponses["salutation"] in salam[2],
        salam[2],
    )
    verifie(
        "salutation + trajet : le trajet gagne",
        "Maalekum" not in mixte[2] and "Ouakam" in mixte[1] and "Médina" in mixte[1],
        (mixte[1], mixte[2][:120]),
    )
    verifie(
        "« salam, dama bëgga dem Médina » : un trajet, jamais la salutation",
        "Maalekum" not in mixte_arrivee[2],
        mixte_arrivee[2][:120],
    )
    verifie(
        "hors sujet : la phrase « bus yi rekk laa xam »",
        not hors_ok and reponses["hors_sujet"] in hors[2],
        hors[2],
    )
    verifie(
        "« Maa ngi Ouakam, bëgg naa dem Médina » : un trajet, pas de conversation",
        trajet_ok and "Maalekum" not in trajet[2] and "Ouakam" in trajet[1],
        (trajet[1], trajet[2][:120]),
    )
    verifie("« salam » compris : pas de seconde transcription", app._phrase_donne_un_trajet("salam"))

    # La voix de conversation suit le même ordre que le reste : oolel d'abord,
    # puis data/tts_cache_ajouts/. Les deux caches sont remplacés par des
    # dossiers temporaires : on teste l'ordre de lecture, pas ce qui est
    # installé sur le disque ce jour-là.
    ancien_ajouts = speak.CACHE_AJOUTS
    ancien_oolel = speak.CACHE_OOLEL
    with tempfile.TemporaryDirectory() as brut_ajouts, tempfile.TemporaryDirectory() as brut_oolel:
        dossier_ajouts, dossier_oolel = Path(brut_ajouts), Path(brut_oolel)
        speak.CACHE_AJOUTS = dossier_ajouts
        speak.CACHE_OOLEL = dossier_oolel
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                absent = speak.voix_conversation("conversation_salutation.wav")
                # La voix native et les ajouts ont des copies différentes.
                contenu = (speak.CACHE_DIR / "aucune_ligne.wav").read_bytes()
                (dossier_oolel / "conversation_salutation.wav").write_bytes(contenu)
                (dossier_ajouts / "conversation_salutation.wav").write_bytes(contenu)
                natif = speak.voix_conversation("conversation_salutation.wav")
                chemin_natif = speak.chemin_audio(
                    speak.CACHE_DIR,
                    "conversation_salutation.wav",
                )
                (dossier_oolel / "conversation_salutation.wav").unlink()
                en_ajout = speak.voix_conversation("conversation_salutation.wav")
        finally:
            speak.CACHE_AJOUTS = ancien_ajouts
            speak.CACHE_OOLEL = ancien_oolel
    verifie(
        "conversation : cache oolel d'abord, sinon data/tts_cache_ajouts/",
        absent is None
        and natif is not None
        and natif.startswith(b"RIFF")
        and chemin_natif == Path(dossier_oolel) / "conversation_salutation.wav"
        and en_ajout is not None
        and en_ajout.startswith(b"RIFF"),
    )

    # La liste complète des audios (data/audit/voix_complete.csv, alimentée par
    # scripts/preparer_regen_oolel.py) a remplacé voix_a_generer.csv, vide
    # depuis que rien ne manque : les 12 réponses de conversation y figurent
    # avec leur phrase exacte.
    with (RACINE / "data" / "audit" / "voix_complete.csv").open(encoding="utf-8") as fichier:
        liste = list(csv.DictReader(fichier))
    # Les réponses écran contiennent encore « bus » ; le texte de la voix
    # (voix_complete.csv) passe par le lexique de prononciation, donc « biis ».
    from tts.lexique_prononciation import appliquer

    conversation = {r["fichier_wav"]: r["texte_a_prononcer"] for r in liste if r["type"] == "conversation"}
    verifie(
        "les 12 phrases sont dans la liste complète des audios",
        conversation == {i.fichier: appliquer(i.reponse) for i in INTENTIONS + (HORS_SUJET,)},
        conversation,
    )

    # Notebook des audios manquants : à jour, mêmes réglages, aucun secret écrit.
    chemin_nb = RACINE / "notebooks" / "voix_ajouts_colab.ipynb"
    notebook = json.loads(chemin_nb.read_text(encoding="utf-8"))
    sources = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    plan = next(s for s in sources if s.startswith("PLAN = "))
    portee: dict = {}
    exec(plan, portee)
    verifie(
        "notebook : ce sont les 236 ajouts (ligne à ligne de la liste complète)",
        [(p["fichier"], appliquer(p["phrase"])) for p in portee["PHRASES"]]
        == [
            (r["fichier_wav"], r["texte_a_prononcer"])
            for r in liste
            if r["origine"] == "tts_cache_ajouts"
        ],
        len(portee["PHRASES"]),
    )
    origine = json.loads((RACINE / "notebooks" / "voix_oolel_colab.ipynb").read_text(encoding="utf-8"))
    generation = "".join(origine["cells"][7]["source"])
    verifie(
        "notebook : génération identique aux 637 (mêmes paramètres, reprise)",
        generation in sources and portee["GRAINE"] == 1234,
    )
    tout = "\n".join(sources)
    verifie(
        "notebook : jeton lu dans les secrets Colab, jamais écrit",
        "userdata.get(\"HF_TOKEN\")" in tout and not re.search(r"hf_[A-Za-z0-9]{20,}", tout),
    )
    verifie(
        "notebook : écrit dans Drive guindima_ajouts/tts_cache_ajouts",
        "/content/drive/MyDrive/guindima_ajouts" in tout and "tts_cache_ajouts" in tout,
    )
    for numero, source in enumerate(sources):
        lignes = [ligne for ligne in source.splitlines() if not ligne.lstrip().startswith("!")]
        try:
            compile("\n".join(lignes), f"cellule {numero}", "exec")
        except SyntaxError as exc:
            verifie(f"notebook : cellule {numero} valide", False, exc)
    return echecs, total


def extract_local_sans_lieu(phrase: str) -> bool:
    """Vrai si l'extraction locale trouve un lieu dans la phrase."""
    from intent.extract_intent import extract_local

    lieux = extract_local(phrase)
    return bool(lieux.get("depart") or lieux.get("arrivee"))


def test_alias_lieux() -> tuple[int, int]:
    """Noms dits à l'oral : « Anne Mariste » -> Maristes, « Teungedj » -> Rufisque.

    Les formes parlées (hann écrit « anne » ou « hane » par l'ASR, Teunguej en
    graphies phonétiques) rejoignent les arrêts qui existent dans les données.
    « Hann Bel Air », lui, n'a pas d'arrêt dans les données (les seuls « Bel
    Air » du réseau sont les « Rocade Fann Bel-Air », à Fann, plusieurs
    kilomètres plus au sud) : aucune réécriture, mieux vaut ne rien répondre
    que d'envoyer l'usager à Fann.
    """
    from intent.extract_intent import extract_local
    from matching.lieux import score

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | alias lieux {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    maristes = ("hane mariste", "hann mariste", "anne mariste", "hann maristes")
    for forme_dite in maristes:
        lieux = extract_local(f"Maa ngi {forme_dite}, bëgg naa dem Médina")
        verifie(f"{forme_dite} -> Maristes", lieux.get("depart") == "Maristes", lieux)

    teungedj = ("teungedj", "teungueth", "tengeej", "tëngéej", "tengedj")
    for forme_dite in teungedj:
        lieux = extract_local(f"Maa ngi Ouakam, bëgg naa dem {forme_dite}")
        verifie(f"{forme_dite} -> Rufisque", lieux.get("arrivee") == "Rufisque", lieux)

    # Le chemin LLM renvoie la forme entendue : l'alias du matcher la ramène
    # à l'arrêt du réseau.
    verifie("alias matcher : « Anne Mariste » vaut « Maristes »", score("Anne Mariste", "Maristes") == 1.0)
    verifie("alias matcher : « Hann Maristes » vaut « Maristes »", score("Hann Maristes", "Maristes") == 1.0)
    verifie("alias matcher : « Teungedj » vaut « Rufisque »", score("Teungedj", "Rufisque") == 1.0)

    bel_air = extract_local("Maa ngi hann bel air, dama bëgga dem")
    verifie(
        "« hann bel air » : rien n'est inventé (l'arrêt n'existe pas)",
        not bel_air.get("depart") and not bel_air.get("arrivee"),
        bel_air,
    )

    matcher = _matcher()
    ancien_point = matcher.geo.point
    matcher.geo.point = matcher.geo.point_connu
    try:
        lieux = extract_local("Maa ngi Anne Mariste, bëgg naa dem Teungedj")
        resultat = matcher.find_line(lieux["depart"], lieux["arrivee"])
        verifie(
            "Maa ngi Anne Mariste -> Teungedj : un trajet existe",
            resultat["depart_valide"]
            and resultat["arrivee_valide"]
            and lieux["depart"] == "Maristes"
            and lieux["arrivee"] == "Rufisque"
            and (resultat["found"] or resultat.get("correspondances")),
            (lieux, _detail(resultat)),
        )
    finally:
        matcher.geo.point = ancien_point

    return echecs, total


def test_universite_fac() -> tuple[int, int]:
    """L'université comme les étudiants la disent : nom complet, « la fac », ASR.

    « Université Cheikh Anta Diop » dit en entier doit donner l'UCAD d'un seul
    lieu : avant, la fenêtre des 3 n-grammes coupait le nom, et le reste de la
    phrase partait en « Cheikh Bethio ». « la fac » (réécriture « ucad »,
    alias de lieux.py) et les graphies ASR (« yuniversite », « univesite »)
    mènent au même arrêt, d'où partent les lignes vers Rufisque et la banlieue.
    """
    from intent.extract_intent import extract_local
    from matching.lieux import score

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | université {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    lieux = extract_local("Maa ngi Université Cheikh Anta Diop, bëgg naa dem Rufisque")
    verifie(
        "nom complet -> UCAD, sans troncature",
        lieux.get("depart") == "UCAD",
        lieux,
    )
    verifie("nom complet : l'arrivée reste Rufisque", lieux.get("arrivee") == "Rufisque", lieux)

    # « la fac » et sa variante écrite, graphies ASR comprises : tout mène à l'UCAD.
    for forme in ("fac", "Faculté", "yuniversite", "univesite"):
        lieux = extract_local(f"Maa ngi {forme}, bëgg naa dem Rufisque")
        verifie(
            f"« {forme} » -> UCAD",
            lieux.get("depart") == "UCAD" and lieux.get("arrivee") == "Rufisque",
            lieux,
        )
    verifie("alias matcher : « Fac » vaut l'UCAD", score("Fac", "UCAD") == 1.0)
    verifie("alias matcher : « Faculté » vaut l'UCAD", score("Faculté", "UCAD") == 1.0)

    # De l'UCAD à Rufisque, un trajet existe.
    matcher = _matcher()
    ancien_point = matcher.geo.point
    matcher.geo.point = matcher.geo.point_connu
    try:
        resultat = matcher.find_line("UCAD", "Rufisque")
        verifie(
            "UCAD -> Rufisque : un trajet existe",
            resultat["depart_valide"]
            and resultat["arrivee_valide"]
            and (resultat["found"] or resultat.get("correspondances")),
            _detail(resultat),
        )
    finally:
        matcher.geo.point = ancien_point

    return echecs, total


def test_equilibre_compagnies() -> tuple[int, int]:
    """« Tous » montre les deux compagnies : le meilleur Dem Dikk puis le meilleur Tata.

    Le plus rapide ne doit pas remplir seul les trois cartes : quand les deux
    opérateurs desservent le trajet, l'usager doit voir son choix des deux
    côtés, puis les autres dans l'ordre du temps. Un filtre de compagnie, lui,
    ne renvoie que cette compagnie ; un trajet sans l'autre opérateur n'invente
    rien.
    """
    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | équilibre {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    matcher = _matcher_hors_ligne()
    cas = (
        ("Pikine", "Thiaroye"),
        ("Yoff", "Médina"),
        ("Colobane", "UCAD"),
        ("Médina", "Petersen"),
    )
    for dep, arr in cas:
        resultat = matcher.find_line(dep, arr)
        lignes = resultat.get("lignes") or []
        compagnies = {ligne["compagnie"] for ligne in lignes}
        verifie(
            f"{dep} -> {arr} : les deux compagnies en tête des directs",
            len(lignes) >= 2
            and {lignes[0]["compagnie"], lignes[1]["compagnie"]}
            == {"Dakar Dem Dikk", "Tata AFTU"},
            _detail(resultat),
        )
        verifie(
            f"{dep} -> {arr} : noms d'arrêts inchangés par l'équilibre",
            all(ligne["monte_a_reseau"] and ligne["descend_a_reseau"] for ligne in lignes),
        )

    # Un filtre actif ne mélange rien et n'équilibre pas : une seule compagnie.
    for compagnie in ("Tata AFTU", "Dakar Dem Dikk"):
        resultat = matcher.find_line("Pikine", "Thiaroye", compagnies={compagnie})
        lignes = resultat.get("lignes") or []
        verifie(
            f"filtre {compagnie} : rien d'autre que cette compagnie",
            bool(lignes)
            and all(ligne["compagnie"] == compagnie for ligne in lignes),
            _detail(resultat),
        )

    # Une paire desservie par un seul opérateur : rien d'inventé, l'ordre du
    # temps reste tel quel.
    resultat = matcher.find_line("Pikine", "Yeumbeul")
    lignes = resultat.get("lignes") or []
    verifie(
        "Pikine -> Yeumbeul : que des Tata, dans l'ordre du temps",
        bool(lignes)
        and all(ligne["compagnie"] == "Tata AFTU" for ligne in lignes)
        and [ligne["minutes"] for ligne in lignes] == sorted(
            ligne["minutes"] for ligne in lignes
        ),
        _detail(resultat),
    )

    return echecs, total


def test_trajets_etudiants() -> tuple[int, int]:
    """Les trajets des étudiants, dans les deux sens, en moins de 2 h 30.

    Retour du terrain : « Université -> Rufisque » ne donnait rien. L'UCAD doit
    mener aux quartiers où vivent les étudiants, aller et retour, avec un temps
    raisonnable (au-delà de 2 h 30, la réponse est absurde).
    """
    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | étudiants {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    def plus_court(resultat: dict) -> int | None:
        temps = [
            trajet.get("minutes")
            for cle in ("lignes", "correspondances", "trajets_2")
            for trajet in resultat.get(cle) or []
        ]
        temps = [t for t in temps if t is not None]
        return min(temps) if temps else None

    matcher = _matcher_hors_ligne()
    quartiers = (
        "Rufisque", "Keur Massar", "Pikine", "Guédiawaye", "Parcelles Assainies",
        "Petersen", "Colobane", "Sandaga", "Liberté 6", "Yoff",
    )
    for quartier in quartiers:
        for dep, arr in (("UCAD", quartier), (quartier, "UCAD")):
            resultat = matcher.find_line(dep, arr)
            minutes = plus_court(resultat)
            verifie(
                f"{dep} -> {arr} : un bus en moins de 2 h 30 ({minutes} min)",
                minutes is not None and minutes <= 150,
                _detail(resultat),
            )

    resultat = matcher.find_line("Université", "Rufisque")
    minutes = plus_court(resultat)
    verifie(
        f"Université -> Rufisque : un bus ({minutes} min)",
        minutes is not None and minutes <= 150,
        _detail(resultat),
    )
    return echecs, total


def test_noms_proches() -> tuple[int, int]:
    """« Yoff » n'est pas « Grand Yoff », « Unité 1 » n'est pas « Unité 15 ».

    Retour du terrain : « Maa ngi Yoff » faisait monter à Grand Yoff, à 3 km.
    Le nom complet exact passe avant tout nom partiel ou approché ; les noms
    voisins (Liberté 5/6, unités des Parcelles, Pikine/Guinaw Rails/Thiaroye)
    ne se remplacent jamais l'un l'autre.
    """
    from intent.extract_intent import extract_local
    from matching.lieux import sans_accents, score

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | noms proches {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    for requete, arret in (
        ("Yoff", "Grand Yoff"), ("Yoff", "Mairie Grand Yoff"), ("Grand Yoff", "Yoff"),
        ("Grand Yoff", "Yoff Village"), ("Liberté 5", "Liberté 6"),
        ("Liberté 6", "Liberté 5"), ("Unité 1", "Unité 15"), ("Unité 15", "Unité 1"),
        ("Unité 2", "Unité 22"), ("Pikine", "Guinaw Rails"), ("Pikine", "Thiaroye"),
        ("Thiaroye", "Pikine"), ("Guinaw Rails", "Pikine"),
    ):
        verifie(f"« {requete} » ne vaut pas « {arret} »", score(requete, arret) == 0.0,
                score(requete, arret))
    verifie("« Yoff » reconnaît encore « Yoff Village »", score("Yoff", "Yoff Village") > 0.5)
    verifie("« Grand Yoff » reconnaît « Mairie Grand Yoff »",
            score("Grand Yoff", "Mairie Grand Yoff") > 0.5)

    lieux = extract_local("Maa ngi Yoff, bëgg naa dem Médina")
    verifie("phrase : Yoff reste Yoff", lieux.get("depart") == "Yoff", lieux)
    lieux = extract_local("Maa ngi Grand Yoff, bëgg naa dem Médina")
    verifie("phrase : Grand Yoff reste Grand Yoff",
            (lieux.get("depart") or "").replace("-", " ") == "Grand Yoff", lieux)

    # Départ inconnu : la seule destination dite ne devient jamais le départ.
    for phrase, arrivee in (
        ("Maa ngi Guinaw Rails, bëgg naa dem Pikine", "Pikine"),
        ("Maa ngi Unité 15, bëgg naa dem Liberté 5", "Liberté 5"),
    ):
        lieux = extract_local(phrase)
        verifie(
            f"phrase : « {phrase} » ne part pas de {arrivee}",
            lieux.get("depart") != arrivee and lieux.get("arrivee") == arrivee,
            lieux,
        )

    matcher = _matcher_hors_ligne()
    for dep, arr, interdit in (
        ("Yoff", "Médina", "grand yoff"),
        ("Grand Yoff", "Médina", "yoff village"),
        ("Liberté 5", "Palais", "liberte 6"),
        ("Liberté 6", "Palais", "liberte 5"),
    ):
        resultat = matcher.find_line(dep, arr)
        montees = {
            sans_accents(t["monte_a"]).replace("-", " ")
            for t in resultat.get("lignes") or []
        } | {
            sans_accents(c["etape_1"]["monte_a"]).replace("-", " ")
            for c in resultat.get("correspondances") or []
        }
        verifie(
            f"{dep} -> {arr} : jamais monté à « {interdit} »",
            bool(montees) and not any(interdit in m for m in montees),
            _detail(resultat),
        )
    return echecs, total


def test_arret_vague() -> tuple[int, int]:
    """Arrêt de montée / descente : le plus proche du lieu dit, sinon un conseil.

    Au-delà de 600 m du lieu, ou sans position fiable, la carte ne nomme plus
    d'arrêt : « Monte à X : cherche l'arrêt de la ligne N le plus proche ».
    Un arrêt qui porte le nom exact du lieu reste nommé.
    """
    import os

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_arret_vague")
    from routing import adapter

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | arrêt vague {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    yoff = adapter._resoudre(_matcher_hors_ligne()._repli, "Yoff")
    verifie("arrêt au nom exact : jamais vague", not adapter._vague(yoff, "Yoff"))
    verifie("lieu sans position : vague", adapter._vague({"point_sur": None}, "Yoff"))
    verifie(
        "arrêt à 3 km (Grand Yoff pour Yoff) : vague",
        adapter._vague(yoff, "Grand Yoff"),
    )

    # Liberté 5 : le terminus de Dieuppeul porte le nom, il reste nommé.
    resultat = _matcher_hors_ligne().find_line("Liberté 5", "Palais")
    verifie(
        "Liberté 5 -> Palais : arrêts nommés, pas de conseil vague",
        bool(resultat["lignes"])
        and not any(ligne["monte_a_vague"] for ligne in resultat["lignes"]),
        _detail(resultat),
    )

    match = {
        "ligne": "Ligne 62", "compagnie": "Tata AFTU",
        "monte_a": "UCAD", "descend_a": "Fass Rufisque",
        "monte_a_vague": False, "descend_a_vague": True,
        "depart": "UCAD", "arrivee": "Rufisque", "arrets_trajet": [],
    }
    carte = app._une_carte(match, depart="UCAD", arrivee="Rufisque")
    verifie(
        "carte : descente vague -> « cherche l'arrêt de la ligne 62 le plus proche »",
        "Rufisque</b> <span" in carte
        and ": cherche l'arrêt de la ligne 62 le plus proche" in carte
        and "Fass Rufisque" not in carte.split("Descends à")[1].split("</div>")[0],
        carte,
    )
    verifie("carte : montée sûre -> arrêt conseillé nommé", "arrêt conseillé : <b" in carte)
    return echecs, total


def test_trajets_frequents() -> tuple[int, int]:
    """Chaque choix de l'onglet « Écrire » mène vraiment à un bus.

    Le test relit le JSON, refuse les doublons et rejoue le vrai pipeline local
    (extraction + StopsMatcher) sans géocodage réseau. Un lieu mal reconnu ou un
    trajet sans ligne doit être retiré du fichier, pas proposé à l'usager.
    """
    import json

    from intent.extract_intent import extract_local
    from matching.lieux import sans_accents
    from matching.stops_matcher import StopsMatcher

    def normalise(nom: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", sans_accents(nom or "").lower()))

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | trajets fréquents {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    chemin = RACINE / "data" / "trajets_frequents.json"
    trajets = json.loads(chemin.read_text(encoding="utf-8"))
    verifie(
        "fichier JSON valide, 33 trajets",
        isinstance(trajets, list) and len(trajets) == 33,
        len(trajets) if isinstance(trajets, list) else type(trajets),
    )
    verifie(
        "schéma depart/arrivee uniquement",
        isinstance(trajets, list)
        and all(
            isinstance(trajet, dict)
            and set(trajet) == {"depart", "arrivee"}
            and all(isinstance(trajet[cle], str) and trajet[cle].strip() for cle in trajet)
            for trajet in trajets
        ),
        trajets[:2],
    )
    cles = [(trajet.get("depart"), trajet.get("arrivee")) for trajet in trajets]
    verifie("aucun doublon", len(cles) == len(set(cles)), len(cles) - len(set(cles)))

    matcher = _matcher()
    ancien_point = matcher.geo.point
    matcher.geo.point = matcher.geo.point_connu
    try:
        for trajet in trajets:
            depart, arrivee = trajet["depart"], trajet["arrivee"]
            phrase = f"Maa ngi {depart}, bëgg naa dem {arrivee}"
            lieux = extract_local(phrase)
            dep, arr = lieux.get("depart") or "", lieux.get("arrivee") or ""
            resultat = matcher.find_line(dep, arr)
            directes = bool(resultat["found"])
            correspondances = bool(resultat.get("correspondances"))
            bon = (
                resultat["depart_valide"]
                and resultat["arrivee_valide"]
                and normalise(dep) == normalise(depart)
                and normalise(arr) == normalise(arrivee)
                and (directes or correspondances)
            )
            verifie(
                f"{depart} → {arrivee}",
                bon,
                {
                    "reconnu": f"{dep} → {arr}",
                    "lignes": _detail(resultat),
                },
            )
            print(
                f"      reconnu : {dep} → {arr} | "
                f"{_detail(resultat)}"
            )
    finally:
        matcher.geo.point = ancien_point

    return echecs, total


def test_partage() -> tuple[int, int]:
    """Le message WhatsApp : trajet direct, avec changement, aucun trajet, encodage.

    Le texte est vérifié mot pour mot : c'est lui que le contact lira, et une
    flèche ou un accent mal encodé casserait le lien wa.me.
    """
    from app.cartes import titre_autre_possibilite
    from app.partage import LIEN_APP, bouton_partage, lien_partage, texte_partage
    from matching.stops_matcher import StopsMatcher

    matcher = _matcher()
    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: str = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | partage {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # Le format du message, sur des trajets fixes : le choix de l'itinéraire n'est pas
    # le sujet de ces tests (il a sa place dans les tests de trajets).
    direct = {
        "found": True,
        "lignes": [
            {
                "compagnie": "Dakar Dem Dikk",
                "ligne": "Ligne 7",
                "monte_a": "Ouakam",
                "descend_a": "Palais 2",
            }
        ],
        "correspondances": [],
    }
    texte = texte_partage("Ouakam", "Palais", direct)
    attendu = (
        "🚌 GuindiMa : Ouakam → Palais\n"
        "Ligne 7 (Dakar Dem Dikk) : monte à Ouakam, descends à Palais 2.\n"
        f"{LIEN_APP}"
    )
    verifie("trajet direct", texte == attendu, texte)

    # Les deux lignes écrivent l'arrêt de changement différemment : le message garde
    # un seul nom, celui où l'on descend.
    corr = {
        "found": False,
        "lignes": [],
        "correspondances": [
            {
                "etape_1": {
                    "compagnie": "Tata AFTU",
                    "ligne": "Ligne 35",
                    "monte_a": "Ngor",
                    "descend_a": "Rond Point Patte d'Oie",
                },
                "etape_2": {
                    "compagnie": "Tata AFTU",
                    "ligne": "Ligne 48",
                    "monte_a": "Patte d'Oie",
                    "descend_a": "Colobane",
                },
                "changement": "Rond Point Patte d'Oie",
            }
        ],
    }
    attendu_corr = (
        "🚌 GuindiMa : Ngor → Colobane\n"
        "1. Ligne 35 (Tata AFTU) : monte à Ngor, descends à Rond Point Patte d'Oie.\n"
        "2. Ligne 48 (Tata AFTU) : monte à Rond Point Patte d'Oie, descends à Colobane.\n"
        f"{LIEN_APP}"
    )
    verifie(
        "trajet avec changement",
        texte_partage("Ngor", "Colobane", corr, corr["correspondances"][0]) == attendu_corr,
        texte_partage("Ngor", "Colobane", corr, corr["correspondances"][0]),
    )
    verifie(
        "changement sans possibilité précisée",
        texte_partage("Ngor", "Colobane", corr) == attendu_corr,
        texte_partage("Ngor", "Colobane", corr),
    )

    # Deux arrêts différents : où descendre, la marche, et où prendre le 2e bus.
    avec_marche = {
        "etape_1": {
            "compagnie": "Tata AFTU",
            "ligne": "Ligne 49",
            "monte_a": "Ngor",
            "descend_a": "Liberté 6",
        },
        "etape_2": {
            "compagnie": "Tata AFTU",
            "ligne": "Ligne 30",
            "monte_a": "Giratoire Liberté VI",
            "descend_a": "Gare de Colobane",
        },
        "changement": "Liberté 6",
        "marches": [4],
    }
    attendu_marche = (
        "🚌 GuindiMa : Ngor → Colobane\n"
        "1. Ligne 49 (Tata AFTU) : monte à Ngor, descends à Liberté 6.\n"
        "À pied : environ 4 min jusqu'à Giratoire Liberté VI.\n"
        "2. Ligne 30 (Tata AFTU) : monte à Giratoire Liberté VI, descends à Gare de Colobane.\n"
        f"{LIEN_APP}"
    )
    verifie(
        "changement à pied entre deux arrêts",
        texte_partage("Ngor", "Colobane", {"correspondances": [avec_marche]}, avec_marche)
        == attendu_marche,
        texte_partage("Ngor", "Colobane", {"correspondances": [avec_marche]}, avec_marche),
    )
    verifie(
        "changement à pied sans possibilité précisée",
        texte_partage("Ngor", "Colobane", {"correspondances": [avec_marche]})
        == attendu_marche,
        texte_partage("Ngor", "Colobane", {"correspondances": [avec_marche]}),
    )

    aucun = {"found": False, "lignes": [], "correspondances": []}
    verifie("aucun trajet", texte_partage("Ouakam", "Ngor", aucun) == "")
    verifie("aucun bouton", bouton_partage("Ouakam", "Ngor", aucun) == "")

    avec_accents = texte_partage("Liberté 5", "Médina", matcher.find_line("Liberté 5", "Médina"))
    lien = lien_partage(avec_accents)
    verifie(
        "lien encodé",
        lien.startswith("https://wa.me/?text=")
        and " " not in lien
        and "%0A" in lien
        and "%E2%86%92" in lien
        and "%C3%A9" in lien,
        lien,
    )
    bouton = bouton_partage(
        "Ngor", "Colobane", corr, corr["correspondances"][0]
    )
    verifie(
        "bouton dans le résultat",
        f"href='{lien_partage(attendu_corr)}'" in bouton
        and "Partager sur WhatsApp" in bouton,
        bouton,
    )

    titre = titre_autre_possibilite(2)
    verifie(
        "titre « Autre possibilité » en gras HTML",
        "Autre possibilité 2" in titre
        and "font-weight:700" in titre
        and "**" not in titre,
        titre,
    )
    return echecs, total


def test_voix() -> tuple[int, int]:
    """La voix dit exactement les possibilités affichées, trois au plus.

    Les cas réels qui ont motivé ces tests : Almadies -> Malika (2 possibilités
    avec changement, la voix n'en disait qu'une) et les trajets à 3 lignes
    directes (la voix s'arrêtait à 2, ou sautait « TAF TAF » faute de numéro).
    """
    import tempfile
    import wave

    from matching.stops_matcher import MAX_CORRESPONDANCES, MAX_LIGNES, StopsMatcher
    from tts.speak import (
        MAX_POSSIBILITES,
        lignes_annoncees,
        nom_cache_match,
        nombre_en_wolof,
        phrase_correspondances,
        phrase_reponse,
        voix_correspondances_depuis_cache,
        voix_depuis_cache,
    )

    matcher = _matcher()
    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | voix {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    verifie(
        "même plafond affichage/voix",
        MAX_POSSIBILITES == MAX_LIGNES == 3
        and MAX_CORRESPONDANCES <= MAX_POSSIBILITES,
        (MAX_POSSIBILITES, MAX_LIGNES, MAX_CORRESPONDANCES),
    )

    nombres = {
        100: "téeméer",
        121: "téeméer ak ñaar fukk ak benn",
        200: "ñaari téeméer",
        217: "ñaari téeméer ak fukk ak juróom ñaar",
        221: "ñaari téeméer ak ñaar fukk ak benn",
        300: "ñetti téeméer",
        502: "juróomi téeméer ak ñaar",
    }
    for nombre, attendu in nombres.items():
        obtenu = nombre_en_wolof(nombre)
        verifie(f"{nombre} en wolof", obtenu == attendu, obtenu)

    import json

    plan = json.loads(
        (RACINE / "scripts" / "phrases_voix.json").read_text(encoding="utf-8")
    )
    avec_chiffres = [
        entree["fichier"]
        for entree in plan["phrases"]
        if any(caractere.isdigit() for caractere in entree["phrase"])
    ]
    verifie(
        "aucun chiffre dans phrases_voix.json",
        not avec_chiffres,
        avec_chiffres,
    )
    entrees = {entree["fichier"]: entree for entree in plan["phrases"]}
    verifie(
        "221 écrit en wolof, sans point final, et à régénérer avec Oolel",
        entrees["dakar_dem_dikk_221.wav"]["phrase"]
        == "Jëlal bus bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn"
        and entrees["dakar_dem_dikk_221.wav"].get("a_regenerer") is True,
        entrees["dakar_dem_dikk_221.wav"],
    )

    une = [{"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 7"}]
    verifie(
        "1 ligne directe",
        phrase_reponse(une)
        == "Jëlal biis bu Dem Dikk, numero juróom ñaar.",
        phrase_reponse(une),
    )

    deux = [
        {"compagnie": "Tata AFTU", "ligne": "Ligne 7"},
        {"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 8"},
    ]
    verifie(
        "2 lignes directes",
        phrase_reponse(deux)
        == "Jëlal biis bu Tata, numero juróom ñaar. walla "
        "Jëlal biis bu Dem Dikk, numero juróom ñett.",
        phrase_reponse(deux),
    )

    trois = matcher.find_line("Pikine", "Colobane")["lignes"]
    phrase_trois = phrase_reponse(trois)
    verifie(
        "3 lignes directes",
        len(trois) == 3
        and phrase_trois.count("Jëlal") == 3
        and phrase_trois.count(" walla ") == 2,
        phrase_trois,
    )
    audio_trois = voix_depuis_cache(trois)
    verifie(
        "audio 3 lignes directes",
        audio_trois is not None and audio_trois.startswith(b"RIFF"),
        audio_trois,
    )

    taf_taf = [{"compagnie": "Dakar Dem Dikk", "ligne": "TAF TAF"}]
    verifie(
        "ligne sans numéro (TAF TAF)",
        phrase_reponse(taf_taf) == "Jëlal biis bu Dem Dikk, Taf Taf.",
        phrase_reponse(taf_taf),
    )
    # L'itinéraire officiel de TAF TAF ne dessert pas les Parcelles, mais Ngor et Yoff.
    ngor_yoff = matcher.find_line("Ngor", "Yoff")["lignes"]
    annoncees = [match["ligne"] for match in lignes_annoncees(ngor_yoff)]
    verifie(
        "TAF TAF annoncé quand il est affiché",
        "TAF TAF" in annoncees,
        annoncees,
    )

    # Une ligne dont le nom contient un chiffre n'est pas une ligne numérotée.
    to1 = [{"compagnie": "Dakar Dem Dikk", "ligne": "TAF TAF OUAKAM (TO1)"}]
    verifie(
        "TAF TAF OUAKAM (TO1) n'est jamais annoncée comme la ligne 1",
        "numero" not in phrase_reponse(to1)
        and nom_cache_match(to1[0]) != "dakar_dem_dikk_1.wav",
        (phrase_reponse(to1), nom_cache_match(to1[0])),
    )

    verifie(
        "TAF TAF OUAKAM (TO1) se dit « Taf Taf Wakaam »",
        phrase_reponse(to1) == "Jëlal biis bu Dem Dikk, Taf Taf Wakaam.",
        phrase_reponse(to1),
    )

    # Les variantes d'orthographe d'un lieu partagent un seul audio.
    import tts.speak as speak

    pompidou = {
        speak.nom_fichier_lieu(nom)
        for nom in (
            "Avenue George Pompidou",
            "Avenue Georges Pompidou",
            "Avenue Gorges Pompidou",
            "Avenue Pompidou",
        )
    }
    verifie("variantes de Pompidou : un seul audio", len(pompidou) == 1, pompidou)
    verifie(
        "Arsanel/Arsenal, Bop/Bopp, Bld/Boulevard : un seul audio chacun",
        speak.nom_fichier_lieu("Arsanel") == speak.nom_fichier_lieu("Arsenal")
        and speak.nom_fichier_lieu("Bop") == speak.nom_fichier_lieu("Bopp")
        and speak.nom_fichier_lieu("Bld de la République")
        == speak.nom_fichier_lieu("Boulevard de la République"),
    )
    # Un alias ne doit jamais faire perdre un audio qui existe déjà.
    from matching.lieux import joli
    from routing.adapter import _NETWORK

    perdus = []
    for arret in _NETWORK.stop_names:
        affiche = joli(arret)
        sans_alias = (
            f"lieu_{speak._slug(speak.nom_lieu_parle(affiche, avec_alias=False))}.wav"
        )
        avec_alias = speak.nom_fichier_lieu(affiche)
        if (
            sans_alias != avec_alias
            and speak.chemin_audio(speak.CACHE_DIR, sans_alias).is_file()
            and not speak.chemin_lieu(speak.CACHE_DIR, affiche).is_file()
        ):
            perdus.append((affiche, sans_alias, avec_alias))
    verifie("aucun alias ne fait perdre un audio existant", not perdus, perdus)
    verifie(
        "Gàddaay : l'ancien audio Gadaye sert tant que le nouveau n'existe pas",
        speak.chemin_lieu(speak.CACHE_DIR, "Gadaye").name
        in {"lieu_gaddaay.wav", "lieu_gadaye.wav"}
        and speak.chemin_lieu(speak.CACHE_DIR, "Gadaye").is_file(),
        speak.chemin_lieu(speak.CACHE_DIR, "Gadaye"),
    )
    verifie(
        "Stade Léopold Sédar Senghor retrouve son audio existant",
        speak.chemin_lieu(speak.CACHE_DIR, "Stade Léopold Sédar Senghor").name
        == "lieu_stade_l_s_s.wav",
    )

    # La voix lit trois caches dans cet ordre : data/tts_cache_oolel/ (voix
    # native), puis data/tts_cache_ajouts/, puis data/tts_cache/ en dernier.
    # Les deux premiers sont remplacés par des dossiers temporaires vides :
    # l'ordre doit tenir quel que soit ce qui est installé sur le disque le
    # jour du test, et le recours final courant reste data/tts_cache/.
    ancien_ajouts = speak.CACHE_AJOUTS
    ancien_oolel = speak.CACHE_OOLEL
    with tempfile.TemporaryDirectory() as brut_ajouts, tempfile.TemporaryDirectory() as brut_oolel:
        dossier_ajouts, dossier_oolel = Path(brut_ajouts), Path(brut_oolel)
        speak.CACHE_AJOUTS = dossier_ajouts
        speak.CACHE_OOLEL = dossier_oolel
        try:
            nom_to1 = speak.nom_cache_match(to1[0])
            sans_cache = speak.voix_depuis_cache(to1)
            # Seulement dans le cache des ajouts : l'audio est trouvé là.
            (dossier_ajouts / nom_to1).write_bytes(
                (speak.CACHE_DIR / "dakar_dem_dikk_taf_taf.wav").read_bytes()
            )
            avec_ajout = speak.voix_depuis_cache(to1)
            chemin_ajout = speak.chemin_audio(speak.CACHE_DIR, nom_to1)
            # Présent aux TROIS endroits : oolel gagne sur tout le monde…
            (dossier_ajouts / "dakar_dem_dikk_1.wav").write_bytes(b"ajout")
            (dossier_oolel / "dakar_dem_dikk_1.wav").write_bytes(b"oolel")
            natif_dabord = speak.chemin_audio(speak.CACHE_DIR, "dakar_dem_dikk_1.wav")
            # …puis l'ajouts gagne, et enfin l'ancien cache des 637 répond.
            (dossier_oolel / "dakar_dem_dikk_1.wav").unlink()
            ajouts_dapres = speak.chemin_audio(speak.CACHE_DIR, "dakar_dem_dikk_1.wav")
            (dossier_ajouts / "dakar_dem_dikk_1.wav").unlink()
            recours_final = speak.chemin_audio(speak.CACHE_DIR, "dakar_dem_dikk_1.wav")
            absent_partout = speak.chemin_audio(
                speak.CACHE_DIR, "fichier_test_absent.wav"
            )
        finally:
            speak.CACHE_AJOUTS = ancien_ajouts
            speak.CACHE_OOLEL = ancien_oolel
    verifie(
        "audio cherché dans tts_cache_oolel/, puis tts_cache_ajouts/, puis tts_cache/",
        sans_cache is None
        and avec_ajout is not None
        and avec_ajout.startswith(b"RIFF")
        and chemin_ajout == Path(dossier_ajouts) / nom_to1
        and natif_dabord == Path(dossier_oolel) / "dakar_dem_dikk_1.wav"
        and ajouts_dapres == Path(dossier_ajouts) / "dakar_dem_dikk_1.wav"
        and recours_final == speak.CACHE_DIR / "dakar_dem_dikk_1.wav"
        and recours_final.is_file()
        and absent_partout == speak.CACHE_DIR / "fichier_test_absent.wav",
        (sans_cache, chemin_ajout, natif_dabord, ajouts_dapres, recours_final, absent_partout),
    )

    # Le lexique de prononciation : mot entier, insensible à la casse, une
    # seule passe, et seulement pour le texte envoyé à la voix.
    from tts.lexique_prononciation import LEXIQUE, appliquer
    from tts.speak import nom_fichier_lieu, nom_lieu_parle

    verifie(
        "lexique de l'écoute : les 5 choix du locuteur natif",
        LEXIQUE
        == {
            "bus": "biis",
            "TAF TAF": "Taf Taf",
            "Acapes": "Akaapes",
            "Albert Sarraut": "Alber Saroo",
            "ASECNA": "Aseknaa",
        },
        LEXIQUE,
    )
    verifie(
        "la voix dit le lexique ; le nom affiché, lui, ne change jamais",
        appliquer("Terrain Acapes") == "Terrain Akaapes"
        and appliquer("Place de l'Indépendance Avenue Sarraut")
        == "Place de l'Indépendance Avenue Sarraut"
        and nom_lieu_parle("Terrain Acapes") == "Terrain Acapes"
        and nom_fichier_lieu("Terrain Acapes") == "lieu_terrain_acapes.wav",
        (
            appliquer("Terrain Acapes"),
            nom_lieu_parle("Terrain Acapes"),
            nom_fichier_lieu("Terrain Acapes"),
        ),
    )
    ancien_lexique = dict(LEXIQUE)
    try:
        LEXIQUE["biis"] = "bis"
        LEXIQUE["Taf Taf Wakaam"] = "Taaf Taaf Wakaam"
        tout_ou_rien = appliquer("Baal ma, Biis biisbiis yi rekk laa xam.")
        phrase_ligne = appliquer(phrase_reponse(to1))
    finally:
        LEXIQUE.clear()
        LEXIQUE.update(ancien_lexique)
    verifie(
        "lexique : mot entier, casse oubliée, phrase entière, une seule passe",
        tout_ou_rien == "Baal ma, bis biisbiis yi rekk laa xam."
        # phrase_reponse applique déjà le lexique une fois (biis, Taaf) ; le
        # second passage ne re-sellingue pas ce qui vient d'être remplacé,
        # mais « biis » reste un mot du vocabulaire dans la nouvelle phrase.
        and phrase_ligne == "Jëlal bis bu Dem Dikk, Taaf Taaf Wakaam.",
        (tout_ou_rien, phrase_ligne, dict(LEXIQUE) == ancien_lexique),
    )
    verifie(
        "lexique restauré : les 5 entrées du dépôt, la ligne Taf Taf dit ce qu'il faut",
        LEXIQUE == ancien_lexique
        and phrase_reponse(taf_taf) == "Jëlal biis bu Dem Dikk, Taf Taf.",
        (LEXIQUE, phrase_reponse(taf_taf)),
    )

    suffixe = [{"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 15A"}]
    verifie(
        "suffixe de ligne (15A) dit et fichier distinct",
        phrase_reponse(suffixe)
        == "Jëlal biis bu Dem Dikk, numero fukk ak juróom A."
        and nom_cache_match(suffixe[0]) == "dakar_dem_dikk_15a.wav",
        (phrase_reponse(suffixe), nom_cache_match(suffixe[0])),
    )

    quatre = [
        {"compagnie": "Dakar Dem Dikk", "ligne": f"Ligne {numero}"}
        for numero in (1, 2, 4, 5)
    ]
    phrase_quatre = phrase_reponse(quatre)
    verifie(
        "plus de 3 lignes directes coupées à 3",
        len(lignes_annoncees(quatre)) == 3
        and phrase_quatre.count("Jëlal") == 3
        and "numero juróom." not in phrase_quatre,
        phrase_quatre,
    )

    corr = matcher.find_line("Almadies", "Malika")["correspondances"]
    verifie(
        "Almadies -> Malika : 2 changements affichés, 221 + 37 ou 221 + 16A",
        len(corr) == 2
        and bool(
            {("Ligne 221", "Ligne 37"), ("Ligne 221", "Ligne 16A")}
            & {(c["etape_1"]["ligne"], c["etape_2"]["ligne"]) for c in corr}
        ),
        [(c["etape_1"]["ligne"], c["etape_2"]["ligne"]) for c in corr],
    )
    phrase_corr = phrase_correspondances(corr)
    attendu_corr = (
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Tata, numero fanweer ak "
        "juróom ñaar, moo lay yóbbu ba Malika. Walla, "
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Tata, numero juróom ñaar "
        "fukk ak juróom ñeent, moo lay yóbbu ba Malika."
    )
    # Moteur v2, itinéraires officiels de Dem Dikk (221 + 16A, 221 + 220).  Wolof
    # validé par l'équipe : « fukk ak juróom benn A », « Walla », et jamais
    # « Terminus » dans la phrase (« ba Malika »).
    attendu_corr_officiel = (
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Dem Dikk, numero fukk ak "
        "juróom benn A, moo lay yóbbu ba Malika. Walla, "
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Dem Dikk, numero ñaari "
        "téeméer ak ñaar fukk, moo lay yóbbu ba Malika."
    )
    verifie(
        "voix 2 changements",
        phrase_corr in {attendu_corr, attendu_corr_officiel},
        phrase_corr,
    )
    verifie(
        "jamais « Terminus » dans une phrase wolof",
        "Terminus" not in phrase_corr,
        phrase_corr,
    )
    audio_corr = voix_correspondances_depuis_cache(corr)
    verifie(
        "audio 2 changements (segments manquants sautés)",
        audio_corr is not None and audio_corr.startswith(b"RIFF"),
        audio_corr,
    )

    phrase_corr_quatre = phrase_correspondances(corr + corr)
    verifie(
        "plus de 3 changements coupés à 3",
        phrase_corr_quatre.count("Ci ginnaaw,") == 3
        and phrase_corr_quatre.count(" Walla, ") == 2,
        phrase_corr_quatre,
    )

    # Un séparateur absent ne doit ni planter ni faire durer le silence : on
    # assemble les lignes présentes et on journalise le manque.
    with tempfile.TemporaryDirectory() as dossier_temporaire:
        dossier = Path(dossier_temporaire)
        for nom in ("dakar_dem_dikk_1.wav", "dakar_dem_dikk_2.wav"):
            with wave.open(str(dossier / nom), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(b"\x00\x00" * 2400)
        partiel = voix_depuis_cache(
            [
                {"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 1"},
                {"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 2"},
            ],
            cache_dir=dossier,
        )
        verifie(
            "segment manquant sauté sans crash",
            partiel is not None and partiel.startswith(b"RIFF"),
            partiel,
        )

    # La voix ne doit jamais retomber sur une synthèse directe : les caches
    # audio (oolel d'abord, puis ajouts, puis le plan des 637) sont les seules
    # sources, même incomplets.
    import tts.speak as speak

    interdits = ("load_tts", "synthetiser", "Tts", "MODEL_TTS", "VOCODEUR")
    presents = [nom for nom in interdits if hasattr(speak, nom)]
    verifie(
        "aucune synthèse SpeechT5 dans le module de voix",
        not presents,
        presents,
    )
    source_app = (RACINE / "app.py").read_text(encoding="utf-8")
    synthese_app = [
        nom for nom in interdits if nom in source_app
    ]
    verifie(
        "l'app ne contient aucun appel de synthèse directe",
        not synthese_app,
        synthese_app,
    )
    with tempfile.TemporaryDirectory() as dossier_temporaire:
        dossier = Path(dossier_temporaire)
        absent = voix_depuis_cache(
            [{"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 1"}],
            cache_dir=dossier,
        )
        verifie(
            "segment manquant : aucun audio, aucune synthèse",
            absent is None,
            absent,
        )

    return echecs, total


def test_lieux() -> tuple[int, int]:
    """Le nouveau format des changements, avec des WAV factices (aucun audio réel)."""
    import contextlib
    import io
    import tempfile
    import wave

    from tts.speak import (
        MOO_LAY_YOBBU_BA,
        NGA_WACC,
        PAUSE_LIEU,
        SIGLES_EPELES,
        SILENCE_ENTRE,
        nom_fichier_lieu,
        nom_lieu_parle,
        phrase_correspondance,
        plan_correspondance,
        voix_correspondances_depuis_cache,
    )

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lieux {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    exemples = {
        "Liberté 6": "Liberté six",
        "Liberté VI": "Liberté six",
        "Giratoire de Liberté VI": "Giratoire de Liberté six",
        "Hamo III": "Hamo trois",
        "Hamo VIII": "Hamo huit",
        "Hamo IX": "Hamo neuf",
        "Hamo X": "Hamo dix",
        "Hamo V/vi": "Hamo cinq/six",
        "2 Voies de Liberté VI": "Deux Voies de Liberté six",
        "2 Voies Liberté 6": "Deux Voies Liberté six",
        "Av Hyacinthe Thiandoum (Grand-Yoff)": "Avenue Hyacinthe Thiandoum",
        "Palais 1": "Palais un",
        "30 & 42": "Trente et quarante-deux",
        # Prononciations validées par l'équipe (locuteur natif).
        "Croisement Gadaye": "Croisement Gàddaay",
        "Terminus 221 (Gadaye)": "Gàddaay",
        "Terminus 56": "Terminus cinquante-six",
        # Les mêmes, sous leur nom affiché (l'écran retire « Terminus »).
        "221 (Gadaye)": "Gàddaay",
        "56": "Terminus cinquante-six",
        "Police 4em": "Police quatrième",
        "National 1": "Nationale un",
        "Vdn-Foire": "V D N Foire",
        "Route Corniche de HLM Gd Médine": "Route Corniche de HLM Grand Médine",
        "Css": "C S S",
        "Direction Générale Ddd": "Direction Générale D D D",
        "BCEAO": "Béséyaawoo",
        "Enea": "Énéa",
        "Ena": "Énaa",
        "Ifan": "Ifan",
        "Daf": "Daf",
        "Hann Maristes": "Maristes",
        "Reubeuss": "Prison Rebeus",
        "Comico": "Cité Comico",
        "Iho": "Hôpital Iho",
        # Jamais « Terminus » dans une phrase wolof (validé par l'équipe).
        "Malika Terminus": "Malika",
        "Icotaf Villa": "Icotaf Villa",
        "Véto": "Véto",
        "Village VI": "Village six",
    }
    for arret, attendu in exemples.items():
        obtenu = nom_lieu_parle(arret)
        verifie(f"nom parlé : {arret}", obtenu == attendu, obtenu)

    verifie(
        "sigles : liste disponible",
        isinstance(SIGLES_EPELES, list),
        SIGLES_EPELES,
    )
    verifie(
        "sigle non épelé avec une liste vide",
        nom_lieu_parle("HLM Grand Yoff", []) == "HLM Grand Yoff",
        nom_lieu_parle("HLM Grand Yoff", []),
    )
    verifie(
        "sigle épelé quand il est dans la liste",
        nom_lieu_parle("HLM Grand Yoff", ["HLM"]) == "H L M Grand Yoff"
        and nom_lieu_parle("UCAD", ["UCAD"]) == "U C A D",
        (
            nom_lieu_parle("HLM Grand Yoff", ["HLM"]),
            nom_lieu_parle("UCAD", ["UCAD"]),
        ),
    )

    verifie(
        "deux arrêts au même slug partagent le fichier",
        nom_fichier_lieu("Av Hyacinthe Thiandoum (Grand-Yoff)")
        == nom_fichier_lieu("Av Hyacinthe Thiandoum")
        == "lieu_avenue_hyacinthe_thiandoum.wav",
        nom_fichier_lieu("Av Hyacinthe Thiandoum (Grand-Yoff)"),
    )

    trajet = {
        "etape_1": {
            "compagnie": "Dakar Dem Dikk",
            "ligne": "Ligne 221",
            "descend_a": "Gadaye",
        },
        "etape_2": {
            "compagnie": "Tata AFTU",
            "ligne": "Ligne 37",
            "descend_a": "Malika",
        },
        "changement": "Gadaye",
    }
    attendu_phrase = (
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Tata, numero fanweer ak "
        "juróom ñaar, moo lay yóbbu ba Malika."
    )
    verifie(
        "format de la phrase avec changement",
        phrase_correspondance(trajet) == attendu_phrase,
        phrase_correspondance(trajet),
    )

    with tempfile.TemporaryDirectory() as dossier_temporaire:
        dossier = Path(dossier_temporaire)
        noms = [
            "dakar_dem_dikk_221.wav",
            NGA_WACC,
            nom_fichier_lieu("Gadaye"),
            "correspondance_liaison.wav",
            "tata_aftu_37.wav",
            MOO_LAY_YOBBU_BA,
            nom_fichier_lieu("Malika"),
        ]
        for nom in noms:
            with wave.open(str(dossier / nom), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(b"\x00\x00" * 240)

        plan = plan_correspondance(trajet, dossier)
        verifie(
            "ordre des segments",
            [chemin.name for chemin, _ in plan] == noms,
            [chemin.name for chemin, _ in plan],
        )
        verifie(
            "pauses : 0,1 s après les connecteurs, 0,3 s ailleurs",
            [pause for _, pause in plan]
            == [
                SILENCE_ENTRE,
                PAUSE_LIEU,
                SILENCE_ENTRE,
                SILENCE_ENTRE,
                SILENCE_ENTRE,
                PAUSE_LIEU,
                SILENCE_ENTRE,
            ],
            [pause for _, pause in plan],
        )

        audio = voix_correspondances_depuis_cache([trajet], cache_dir=dossier)
        with wave.open(io.BytesIO(audio or b"")) as wav:
            frames = wav.getnframes()
        attendu_frames = 7 * 240 + 4 * 7200 + 2 * 2400
        verifie(
            "pause courte réellement assemblée",
            audio is not None and frames == attendu_frames,
            (frames, attendu_frames),
        )

        (dossier / nom_fichier_lieu("Gadaye")).unlink()
        flux = io.StringIO()
        with contextlib.redirect_stdout(flux):
            plan = plan_correspondance(trajet, dossier)
        noms_sans_lieu = [chemin.name for chemin, _ in plan]
        verifie(
            "lieu manquant : connecteur et lieu sautés, le reste gardé",
            NGA_WACC not in noms_sans_lieu
            and nom_fichier_lieu("Gadaye") not in noms_sans_lieu
            and "dakar_dem_dikk_221.wav" in noms_sans_lieu
            and "correspondance_liaison.wav" in noms_sans_lieu
            and "tata_aftu_37.wav" in noms_sans_lieu
            and MOO_LAY_YOBBU_BA in noms_sans_lieu
            and nom_fichier_lieu("Malika") in noms_sans_lieu,
            noms_sans_lieu,
        )
        verifie(
            "lieu manquant journalisé",
            "[voix] segment manquant" in flux.getvalue()
            and nom_fichier_lieu("Gadaye") in flux.getvalue(),
            flux.getvalue(),
        )

    return echecs, total


def _phrases_ajouts_notebook() -> dict[str, str]:
    """Les ajouts (232 de la série Adia + 4 réponses de conversation) : fichier
    -> phrase, lues du PLAN embarqué dans le notebook.

    Colab n'a pas accès au dépôt ; la liste est copiée dans le notebook même,
    généré par scripts/preparer_notebook_ajouts.py. C'est là qu'elle reste
    exacte.
    """
    import json

    notebook = json.loads(
        (RACINE / "notebooks" / "voix_ajouts_colab.ipynb").read_text(encoding="utf-8")
    )
    source = next(
        "".join(cellule["source"])
        for cellule in notebook["cells"]
        if cellule["cell_type"] == "code"
        and "".join(cellule["source"]).startswith("PLAN = ")
    )
    portee: dict = {}
    exec(source, portee)  # noqa: S102 - une cellule de ce dépôt, pas une entrée
    return {p["fichier"]: p["phrase"] for p in portee["PHRASES"]}


def test_prononciations() -> tuple[int, int]:
    """Le plan porte le texte exact préparé pour la génération Oolel-Voices.

    La voix passe à la voix native d'Oolel (8_1_c.wav du Space
    Oolel-Voices-Demo) : la liste complète des 873 audios régénérables
    (data/audit/voix_complete.csv, texte final après lexique) doit couvrir
    exactement ce que l'app peut jouer aujourd'hui (hors les 4 réponses de
    conversation pas encore générées), et les trois notebooks de génération
    (test de prononciation, complet, ajouts de conversation) doivent suivre
    les mêmes réglages que les séries précédentes.
    """
    import csv
    import json

    plan = json.loads(
        (RACINE / "scripts" / "phrases_voix.json").read_text(encoding="utf-8")
    )
    prononciations = json.loads(
        (RACINE / "scripts" / "prononciations_wolof.json").read_text(
            encoding="utf-8"
        )
    )["lieux"]

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | prononciations {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    lieux = {
        entree["fichier"]: entree
        for entree in plan["phrases"]
        if entree["type"] == "lieu"
    }
    fichiers_plan = set(lieux)
    fichiers_prononciations = set(prononciations)
    verifie(
        "mêmes fichiers lieu des deux côtés",
        fichiers_plan == fichiers_prononciations,
        {
            "absents_du_plan": sorted(fichiers_prononciations - fichiers_plan),
            "absents_des_prononciations": sorted(
                fichiers_plan - fichiers_prononciations
            ),
        },
    )

    differentes = [
        fichier
        for fichier in fichiers_plan & fichiers_prononciations
        if lieux[fichier]["phrase"] != prononciations[fichier]
    ]
    verifie(
        "chaque lieu reprend exactement la prononciation",
        not differentes,
        [
            (fichier, lieux[fichier]["phrase"], prononciations[fichier])
            for fichier in differentes
        ],
    )
    verifie(
        "aucun chiffre dans une phrase du plan",
        all(not re.search(r"\d", entree["phrase"]) for entree in plan["phrases"]),
        [
            entree["fichier"]
            for entree in plan["phrases"]
            if re.search(r"\d", entree["phrase"])
        ],
    )
    verifie(
        "aucune phrase du plan au-delà de 200 caractères",
        all(len(entree["phrase"]) <= 200 for entree in plan["phrases"]),
        [
            (entree["fichier"], len(entree["phrase"]))
            for entree in plan["phrases"]
            if len(entree["phrase"]) > 200
        ],
    )
    liste_a_regenerer = [
        ligne.strip()
        for ligne in (RACINE / "scripts" / "a_regenerer.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if ligne.strip()
    ]
    marquees = {
        entree["fichier"]
        for entree in plan["phrases"]
        if entree.get("a_regenerer") is True
    }
    marquees_lieux = [
        entree for entree in plan["phrases"]
        if entree["fichier"] in marquees and entree["type"] == "lieu"
    ]
    marquees_lignes = [
        entree for entree in plan["phrases"]
        if entree["fichier"] in marquees and entree["type"] == "ligne"
    ]
    verifie(
        "les 637 entrées sont à régénérer, exactement la liste fournie",
        len(liste_a_regenerer) == 637
        and marquees == set(liste_a_regenerer)
        and len(marquees_lieux) == 519
        and len(marquees_lignes) == 112,
        {
            "liste": len(liste_a_regenerer),
            "marquees": len(marquees),
            "lieux": len(marquees_lieux),
            "lignes": len(marquees_lignes),
            "ecart": sorted(marquees.symmetric_difference(set(liste_a_regenerer))),
        },
    )
    verifie(
        "les 6 services sont régénérés",
        all(
            entree.get("a_regenerer") is True
            for entree in plan["phrases"]
            if entree["type"] == "service"
        )
        and sum(1 for entree in plan["phrases"] if entree["type"] == "service") == 6,
        [
            entree["fichier"]
            for entree in plan["phrases"]
            if entree["type"] == "service" and entree.get("a_regenerer") is not True
        ],
    )

    entrees = {entree["fichier"]: entree for entree in plan["phrases"]}
    lignes = [entree for entree in plan["phrases"] if entree["type"] == "ligne"]
    lignes_tata = [
        entree for entree in lignes if "bus bu Tataa" in entree["phrase"]
    ]
    verifie(
        "aucune ligne ne dit encore « bus bu Tata, »",
        all("bus bu Tata," not in entree["phrase"] for entree in lignes),
        [
            entree["fichier"]
            for entree in lignes
            if "bus bu Tata," in entree["phrase"]
        ],
    )
    verifie(
        "aucune ligne ne dit encore « TAF TAF »",
        all("TAF TAF" not in entree["phrase"] for entree in lignes),
        [
            entree["fichier"]
            for entree in lignes
            if "TAF TAF" in entree["phrase"]
        ],
    )
    verifie(
        "les 72 lignes Tata disent Tataa",
        len(lignes_tata) == 72
        and all("bus bu Tataa" in entree["phrase"] for entree in lignes_tata),
        [entree["fichier"] for entree in lignes_tata],
    )

    nga = entrees.get("nga_wacc.wav")
    verifie(
        "nga_wacc vaut nga wàcc et est régénéré",
        nga is not None
        and nga["phrase"] == "nga wàcc"
        and nga.get("a_regenerer") is True,
        nga,
    )
    moo = entrees.get("moo_lay_yobbu_ba.wav")
    verifie(
        "moo_lay_yobbu_ba garde sa phrase et est régénéré",
        moo is not None
        and moo["phrase"] == "moo lay yóbbu ba"
        and moo.get("a_regenerer") is True,
        moo,
    )
    taf = entrees.get("dakar_dem_dikk_taf_taf.wav")
    verifie(
        "TAF TAF devient Taf Taf et est régénéré",
        taf is not None
        and taf["phrase"] == "Jëlal bus bu Dem Dikk, Taf Taf."
        and taf.get("a_regenerer") is True,
        taf,
    )
    bene = [
        entrees.get("lieu_bene_baraque.wav"),
        entrees.get("lieu_yeumbeul_bene_baraque.wav"),
    ]
    verifie(
        "Bene Baraque et Yeumbeul Bene Baraque gardent leur phrase",
        all(
            entree is not None
            and entree["phrase"] in ("Bene Baraque", "Yeumbeul Bene Baraque")
            and entree.get("a_regenerer") is True
            for entree in bene
        ),
        bene,
    )

    # --- La régénération complète (voix native Oolel, 8_1_c.wav) ------------ #

    complete = list(
        csv.DictReader(
            (RACINE / "data" / "audit" / "voix_complete.csv").open(encoding="utf-8")
        )
    )
    fichiers_complete = [r["fichier_wav"] for r in complete]
    verifie(
        "voix_complete.csv : 873 audios, 637 du plan + 236 ajouts, sans doublon",
        len(complete) == 873
        and len(set(fichiers_complete)) == 873
        and sum(1 for r in complete if r["origine"] == "tts_cache") == 637
        and sum(1 for r in complete if r["origine"] == "tts_cache_ajouts") == 236,
        (len(complete), len(set(fichiers_complete))),
    )
    import os as _os

    def _voix_d_aujourdhui(fichier: str) -> bool:
        return _os.path.isfile(RACINE / "data" / "tts_cache" / fichier) or _os.path.isfile(
            RACINE / "data" / "tts_cache_ajouts" / fichier
        )

    # Les 4 réponses de conversation validées après la série Adia : leur texte
    # est dans la liste, mais elles partent du petit notebook Brev
    # (voix_ajouts_conversation_brev.ipynb), pas encore tourné — donc pas encore
    # jouables. Dès qu'elles sont installées, cette liste redevient vide.
    EN_ATTENTE_CONVERSATION = {
        "conversation_ci_lo_nekk.wav",
        "conversation_liggeey.wav",
        "conversation_dekk.wav",
        "conversation_wolof.wav",
    }
    manquants_d_aujourdhui = [
        f for f in fichiers_complete if not _voix_d_aujourdhui(f)
    ]
    verifie(
        "voix_complete.csv : chaque audio est jouable aujourd'hui",
        set(manquants_d_aujourdhui) == EN_ATTENTE_CONVERSATION,
        manquants_d_aujourdhui[:5],
    )

    # Couverture de la voix native : chaque nom que l'app peut jouer — les
    # 873 de la liste complète + les phrases fixes du module de voix
    # (aucune_ligne, walla, …) — doit exister dans data/tts_cache_oolel/.
    # Les rares manquants, s'il y en a un jour, se listent ICI, nom par nom :
    # jamais devinés, jamais générés à la volée. Aujourd'hui : uniquement les
    # 4 réponses de conversation en attente du zip de Brev.
    import tts.speak as speak

    fixe_a_jouer = sorted(
        getattr(speak, nom)
        for nom in dir(speak)
        if re.fullmatch(r"[A-Z][A-Z_0-9]*", nom)
        and isinstance(getattr(speak, nom), str)
        and str(getattr(speak, nom)).endswith(".wav")
    )
    installes_oolel = {f.name for f in (RACINE / "data" / "tts_cache_oolel").glob("*.wav")}
    sans_voix = sorted(set(fichiers_complete).union(fixe_a_jouer) - installes_oolel)
    verifie(
        "voix native : tts_cache_oolel couvre la liste complète et les phrases fixes",
        set(sans_voix) == EN_ATTENTE_CONVERSATION,
        sans_voix[:10],
    )
    # Texte final = phrase du plan / des ajouts, avec le lexique de l'écoute
    # appliqué : le CSV porte exactement ce que la voix doit lire.
    par_fichier = {r["fichier_wav"]: r for r in complete}
    from tts.lexique_prononciation import LEXIQUE, appliquer

    ecarts = []
    sources_textes = {e["fichier"]: e["phrase"] for e in plan["phrases"]}
    for fichier, phrase in _phrases_ajouts_notebook().items():
        sources_textes.setdefault(fichier, phrase)
    for fichier, phrase in sources_textes.items():
        attendu = appliquer(phrase)
        if par_fichier.get(fichier, {}).get("texte_a_prononcer") != attendu:
            ecarts.append(
                (fichier, par_fichier.get(fichier, {}).get("texte_a_prononcer"), attendu)
            )
    verifie(
        "voix_complete.csv : le texte final suit phrases + lexique",
        not ecarts,
        ecarts[:3],
    )
    lexiques = [
        fichier
        for fichier, phrase in sources_textes.items()
        if appliquer(phrase) != phrase
    ]
    verifie(
        "lexique : le CSV porte le texte retouché, la phrase affichée reste la sienne",
        all(
            par_fichier[f]["texte_a_prononcer"] != sources_textes[f]
            for f in lexiques
        ),
        lexiques[:5],
    )
    terrain_acapes = par_fichier.get("lieu_terrain_acapes.wav", {})
    verifie(
        "lexique : écran « Terrain Acapes » se dit « Terrain Akaapes » dans le CSV",
        terrain_acapes.get("texte_a_prononcer") == "Terrain Akaapes"
        and sources_textes.get("lieu_terrain_acapes.wav") == "Terrain Acapes",
        terrain_acapes,
    )
    place_sarraut = par_fichier.get("lieu_place_de_l_independance_avenue_sarraut.wav", {})
    verifie(
        "lexique : « Avenue Sarraut » sans « Albert » n'est pas touché",
        place_sarraut.get("texte_a_prononcer")
        == "Place de l'Indépendance Avenue Sarraut",
        place_sarraut,
    )

    # Notebook complet : liste exacte du CSV, mêmes réglages, voix du Space.
    complet = json.loads(
        (RACINE / "notebooks" / "voix_oolel_complete.ipynb").read_text(encoding="utf-8")
    )
    sources_complet = [
        "".join(c["source"]) if isinstance(c["source"], list) else str(c["source"])
        for c in complet["cells"]
        if c["cell_type"] == "code"
    ]
    plan_complet_src = next(s for s in sources_complet if s.startswith("PLAN = "))
    portee_complet: dict = {}
    exec(plan_complet_src, portee_complet)
    verifie(
        "notebook complet : exactement les 873 audios de voix_complete.csv",
        [(p["fichier"], p["phrase"]) for p in portee_complet["PHRASES"]]
        == [(r["fichier_wav"], r["texte_a_prononcer"]) for r in complete]
        and portee_complet["GRAINE"] == 1234,
        len(portee_complet.get("PHRASES", [])),
    )
    gen_637 = "".join(
        json.loads((RACINE / "notebooks" / "voix_oolel_colab.ipynb").read_text(encoding="utf-8"))["cells"][7]["source"]
    )
    gen_complet = next(s for s in sources_complet if s.startswith("# Générer"))
    verifie(
        "notebook complet : génération identique aux 637 (3 essais, reprise)",
        gen_complet == gen_637,
    )
    tout_complet = "\n".join(sources_complet)
    verifie(
        "notebook complet : jeton dans les secrets Colab, jamais écrit",
        'userdata.get("HF_TOKEN")' in tout_complet
        and not re.search(r"hf_[A-Za-z0-9]{20,}", tout_complet),
    )
    drive_complet = next(s for s in sources_complet if s.startswith("# Google Drive"))
    verifie(
        "notebook complet : la voix se télécharge du Space, jamais l'audio Adia importé",
        "hf_hub_download" in drive_complet
        and "repo_type='space'" in drive_complet
        and "8_1_c.wav" in drive_complet
        and "aucune_ligne" not in drive_complet
        and "Adia_TTS" not in tout_complet,
        (drive_complet[:160]),
    )
    verifie(
        "notebook complet : écrit dans Drive guindima_oolel_complete/tts_cache_oolel",
        "/content/drive/MyDrive/guindima_oolel_complete" in tout_complet
        and "tts_cache_oolel" in tout_complet,
    )

    # Notebook du test de prononciation : 12 variantes à écouter, mêmes réglages.
    test_nb = json.loads(
        (RACINE / "notebooks" / "voix_test_prononciation_colab.ipynb").read_text(encoding="utf-8")
    )
    sources_test = [
        "".join(c["source"]) if isinstance(c["source"], list) else str(c["source"])
        for c in test_nb["cells"]
        if c["cell_type"] == "code"
    ]
    plan_test_src = next(s for s in sources_test if s.startswith("PLAN = "))
    portee_test: dict = {}
    exec(plan_test_src, portee_test)
    variantes = [
        ("Baal ma, biis yi rekk laa xam.", "test_biis.wav"),
        ("Baal ma, bis yi rekk laa xam.", "test_bis.wav"),
        ("Jëlal biis bu Dem Dikk, Taaf Taaf Wakaam.", "test_biis_taaf_taaf_wakaam.wav"),
        ("Jëlal bis bu Dem Dikk, Taf Taf Wakaam.", "test_bis_taf_taf_wakaam.wav"),
        ("Jëlal biis bu Dem Dikk, Tafe Tafe Wakaam.", "test_biis_tafe_tafe_wakaam.wav"),
        ("Akapes", "test_akapes.wav"),
        ("Akaapes", "test_akaapes.wav"),
        ("Albeer Saróo", "test_albeer_saroo.wav"),
        ("Alber Saroo", "test_alber_saroo.wav"),
        ("Aseknaa", "test_aseknaa.wav"),
        ("Asekna", "test_asekna.wav"),
        ("Maalekum salaam ! Fan nga bëgga dem ?", "test_maalekum.wav"),
    ]
    verifie(
        "notebook de test : les 12 variantes, une par fichier, graine 1234",
        [(p["phrase"], p["fichier"]) for p in portee_test["PHRASES"]] == variantes
        and portee_test["GRAINE"] == 1234,
        len(portee_test.get("PHRASES", [])),
    )
    tout_test = "\n".join(sources_test)
    verifie(
        "notebook de test : génération partagée avec les 637, voix du Space, Drive dédié",
        gen_637 in sources_test
        and "8_1_c.wav" in tout_test
        and "guindima_test_prononciation" in tout_test
        and "aucune_ligne" not in tout_test
        and "Adia" not in tout_test,
    )
    verifie(
        "notebook de test : jeton dans les secrets Colab, jamais écrit",
        'userdata.get("HF_TOKEN")' in tout_test
        and not re.search(r"hf_[A-Za-z0-9]{20,}", tout_test),
    )
    for numero, source in enumerate(sources_test + sources_complet, 1):
        lignes = [
            ligne for ligne in source.splitlines() if not ligne.lstrip().startswith("!")
        ]
        try:
            compile("\n".join(lignes), f"cellule {numero}", "exec")
        except SyntaxError as exc:
            verifie("notebooks voix native : cellules valides", False, exc)

    # --- Variante Brev : Jupyter simple, sans Google Drive ------------------ #

    def _sources_code(nom_notebook: str) -> list[str]:
        nb = json.loads(
            (RACINE / "notebooks" / nom_notebook).read_text(encoding="utf-8")
        )
        return [
            "".join(c["source"]) if isinstance(c["source"], list) else str(c["source"])
            for c in nb["cells"]
            if c["cell_type"] == "code"
        ]

    nb_test_brev = json.loads(
        (RACINE / "notebooks" / "voix_test_prononciation_brev.ipynb").read_text(encoding="utf-8")
    )
    nb_complet_brev = json.loads(
        (RACINE / "notebooks" / "voix_oolel_complete_brev.ipynb").read_text(encoding="utf-8")
    )
    nb_conv_brev = json.loads(
        (RACINE / "notebooks" / "voix_ajouts_conversation_brev.ipynb").read_text(encoding="utf-8")
    )
    sources_test_brev = _sources_code("voix_test_prononciation_brev.ipynb")
    sources_complet_brev = _sources_code("voix_oolel_complete_brev.ipynb")
    sources_conv_brev = _sources_code("voix_ajouts_conversation_brev.ipynb")
    tout_test_brev = "\n".join(sources_test_brev)
    tout_complet_brev = "\n".join(sources_complet_brev)
    tout_conv_brev = "\n".join(sources_conv_brev)
    tout_brev = tout_test_brev + tout_complet_brev + tout_conv_brev

    verifie(
        "Brev (test + complet + conversation) : plus de Google Drive, secrets, saisie clavier ou redémarrage forcé",
        not any(
            reste in tout_brev
            for reste in (
                "google.colab",
                "drive.mount",
                "userdata",
                "os.kill",
                "files.download",
                "getpass",
            )
        ),
        [
            reste
            for reste in (
                "google.colab",
                "drive.mount",
                "userdata",
                "os.kill",
                "files.download",
                "getpass",
            )
            if reste in tout_brev
        ],
    )
    verifie(
        "Brev (test + complet + conversation) : jeton HF lu dans la variable d'environnement, jamais affiché ni écrit",
        'os.environ.get("HF_TOKEN"' in tout_brev
        and "WHISPER_PRINCIPAL = WHISPER_SECOURS" in tout_brev
        and not re.search(r"hf_[A-Za-z0-9]{20,}", tout_brev)
        and not re.search(r"print\([^)]*HF_TOKEN", tout_brev),
    )
    verifie(
        "Brev (test + complet + conversation) : tout dans ./sortie_voix, zip à côté du notebook",
        "./sortie_voix" in tout_test_brev
        and "./sortie_voix" in tout_complet_brev
        and "./sortie_voix" in tout_conv_brev
        and "shutil.make_archive('./sortie_voix/voix_test', 'zip', SORTIE)" in tout_test_brev
        and "shutil.make_archive('./sortie_voix/tts_cache_oolel', 'zip', SORTIE)"
        in tout_complet_brev
        and "shutil.make_archive('./sortie_voix/ajouts_conversation', 'zip', SORTIE)"
        in tout_conv_brev,
    )
    # Brev : le Jupyter démarre nu (pas de pip, pas de torch, pas de numpy). La
    # première cellule installe pip via ensurepip (sans -q : il refuse les
    # options) puis le pip du noyau ; la note impose le redémarrage (sinon
    # « Numpy is not available » dès que torch est chargé).
    cells_pip = [
        "".join(c["source"])
        for nb in (nb_test_brev, nb_complet_brev, nb_conv_brev)
        for c in nb["cells"]
        if c["cell_type"] == "code" and "-m ensurepip" in "".join(c["source"])
    ]
    verifie(
        "Brev : pip via ensurepip + pip du noyau, pile torch/numpy d'abord, note de redémarrage",
        len(cells_pip) == 3
        and all(
            c.startswith("# Brev : le Jupyter de base démarre sans pip")
            and "import sys" in c
            and "!{sys.executable} -m ensurepip --upgrade" in c
            and "-q" not in c
            and "!{sys.executable} -m pip install torch torchaudio torchcodec huggingface_hub numpy omegaconf einops scipy safetensors resemble-perth pyloudnorm"
            in c
            and "'librosa>=0.10.2'" in c
            and "transformers==4.46.3" in c
            and "diffusers==0.29.0" in c
            for c in cells_pip
        )
        and any(
            "Kernel -> Restart Kernel, puis Run All" in "".join(c["source"])
            and "Numpy is not available" in "".join(c["source"])
            for nb in (nb_test_brev, nb_complet_brev)
            for c in nb["cells"]
            if c["cell_type"] == "markdown"
        ),
    )
    verifie(
        "Brev (test + complet + conversation) : Whisper-small public secours du préprocesseur du dépôt privé",
        'WhisperProcessor.from_pretrained(\n                    "openai/whisper-small", token=jeton\n                )' in tout_brev
        and tout_brev.count("Sans preprocessor_config.json dans le dépôt") == 3,
    )

    plan_test_brev = next(s for s in sources_test_brev if s.startswith("PLAN = "))
    portee_test_brev: dict = {}
    exec(plan_test_brev, portee_test_brev)
    verifie(
        "Brev test : les 12 variantes, graine 1234, génération partagée avec les 637",
        [(p["phrase"], p["fichier"]) for p in portee_test_brev["PHRASES"]] == variantes
        and portee_test_brev["GRAINE"] == 1234
        and gen_637 in sources_test_brev,
        len(portee_test_brev.get("PHRASES", [])),
    )
    plan_complet_brev = next(s for s in sources_complet_brev if s.startswith("PLAN = "))
    portee_complet_brev: dict = {}
    exec(plan_complet_brev, portee_complet_brev)
    verifie(
        "Brev complet : les 873 audios du CSV, graine 1234, génération identique aux 637",
        [(p["fichier"], p["phrase"]) for p in portee_complet_brev["PHRASES"]]
        == [(r["fichier_wav"], r["texte_a_prononcer"]) for r in complete]
        and portee_complet_brev["GRAINE"] == 1234
        and gen_637 in sources_complet_brev,
        len(portee_complet_brev.get("PHRASES", [])),
    )
    plan_conv_brev = next(s for s in sources_conv_brev if s.startswith("PLAN = "))
    portee_conv_brev: dict = {}
    exec(plan_conv_brev, portee_conv_brev)
    # Les 4 réponses de conversation reprennent le texte du CSV (lexique
    # appliqué) ; les 3 essais « Tata » sont des phrases d'écoute, absentes de
    # la liste complète : l'app ne les joue jamais, l'installateur les ignore.
    nouvelles_conversation = (
        "conversation_ci_lo_nekk.wav",
        "conversation_liggeey.wav",
        "conversation_dekk.wav",
        "conversation_wolof.wav",
    )
    attendu_conv = [
        (r["fichier_wav"], r["texte_a_prononcer"])
        for r in complete
        if r["fichier_wav"] in nouvelles_conversation
    ]
    essais_tata = [
        ("Jëlal Tataa ñett.", "test_tata_tataa.wav"),
        ("Jëlal Tatà ñett.", "test_tata_tata_accent.wav"),
        ("Jëlal Tata ñett.", "test_tata_tata.wav"),
    ]
    verifie(
        "Brev conversation : 4 réponses du CSV + 3 essais Tata à écouter, graine 1234",
        [(p["phrase"], p["fichier"]) for p in portee_conv_brev["PHRASES"]]
        == [(phrase, fichier) for fichier, phrase in attendu_conv]
        + [(phrase, fichier) for phrase, fichier in essais_tata]
        and portee_conv_brev["GRAINE"] == 1234
        and gen_637 in sources_conv_brev
        and not {f for _, f in essais_tata} & set(fichiers_complete),
        len(portee_conv_brev.get("PHRASES", [])),
    )
    verifie(
        "Brev conversation : voix du Space, jamais la voix Adia",
        "8_1_c.wav" in tout_conv_brev
        and "soynade-research/Oolel-Voices-Demo" in tout_conv_brev
        and "Adia" not in tout_conv_brev,
    )
    verifie(
        "Brev (test + complet) : voix du Space, jamais la voix Adia",
        "8_1_c.wav" in tout_brev
        and "soynade-research/Oolel-Voices-Demo" in tout_brev
        and "Adia" not in tout_brev,
    )

    # Même plan, mêmes outils, même génération : seules les 4 cellules qui
    # dépendent de Colab ont été réécrites, le reste doit être octet pour octet.
    def _cellules_colab_gardes(sources: list[str]) -> list[str]:
        reecrites = (
            "!pip -q install",
            "from google.colab import drive",
            "from google.colab import userdata",
            "files.download(",
        )
        return [s for s in sources if not any(m in s for m in reecrites)]

    def _cellules_brev_gardes(sources: list[str]) -> list[str]:
        reecrites = (
            "-m ensurepip",
            "Tout atterrit ici",
            'os.environ.get("HF_TOKEN"',
            "shutil.make_archive(",
        )
        return [s for s in sources if not any(m in s for m in reecrites)]

    def _ecart_cellules(colab: list[str], brev: list[str]) -> list:
        return [
            (i, colab[i][:80], brev[i][:80])
            for i in range(min(len(colab), len(brev)))
            if colab[i] != brev[i]
        ] + ([(len(colab), len(brev))] if len(colab) != len(brev) else [])

    colab_restes = (_cellules_colab_gardes(sources_test), _cellules_colab_gardes(sources_complet))
    brev_restes = (_cellules_brev_gardes(sources_test_brev), _cellules_brev_gardes(sources_complet_brev))
    ecart_reste = (
        []
        if colab_restes[0] == brev_restes[0] and colab_restes[1] == brev_restes[1]
        else _ecart_cellules(colab_restes[0], brev_restes[0])
        + _ecart_cellules(colab_restes[1], brev_restes[1])
    )
    verifie(
        "Brev : hors des 4 cellules réécrites, notebooks identiques au Colab",
        not ecart_reste,
        ecart_reste or "",
    )
    # Les magies (%, !) ne se compilent pas : on les retire, comme pour les
    # versions Colab, puis on vérifie le reste cellule par cellule.
    for numero, source in enumerate(sources_test_brev + sources_complet_brev + sources_conv_brev, 1):
        lignes = [
            ligne
            for ligne in source.splitlines()
            if not ligne.lstrip().startswith(("!", "%"))
        ]
        try:
            compile("\n".join(lignes), f"cellule Brev {numero}", "exec")
        except SyntaxError as exc:
            verifie("notebooks Brev : cellules valides", False, exc)

    lire_moi = (RACINE / "notebooks" / "BREV_LIRE_MOI.md").read_text(encoding="utf-8")
    verifie(
        "BREV_LIRE_MOI.md : les trois notebooks, jeton en variable d'environnement, exécution sans interface, installer --zip/--conversation, machine à éteindre",
        "voix_oolel_complete_brev.ipynb" in lire_moi
        and "voix_test_prononciation_brev.ipynb" in lire_moi
        and "voix_ajouts_conversation_brev.ipynb" in lire_moi
        and "getpass" not in lire_moi
        and "variable d'environnement" in lire_moi
        and "--ExecutePreprocessor.timeout=-1" in lire_moi
        and "--zip" in lire_moi
        and "--conversation" in lire_moi
        and "Éteins" in lire_moi,
    )
    installer_src = (RACINE / "scripts" / "installer_voix_oolel.py").read_text(encoding="utf-8")
    verifie(
        "installer : option --zip (dossier du notebook Brev), --conversation (4 réponses seules), mêmes attentes voix_complete.csv",
        "--zip" in installer_src
        and "--conversation" in installer_src
        and "def installer(" in installer_src
        and "def installer_conversation(" in installer_src
        and "fichiers_attendus()" in installer_src
        and "voix_oolel_complete_brev.ipynb" in installer_src
        and "voix_ajouts_conversation_brev.ipynb" in installer_src,
    )

    # Installation réelle, sans réseau ni gros fichier : une mini-archive avec
    # deux noms réels de voix_complete.csv, deux WAV de silence, un cache
    # temporaire. Le script doit les recopier… et refuser une archive incomplète.
    import contextlib
    import importlib.util
    import io
    import tempfile
    import wave as _wave
    import zipfile as _zipfile

    specification = importlib.util.spec_from_file_location(
        "installer_voix_oolel", RACINE / "scripts" / "installer_voix_oolel.py"
    )
    installeur = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(installeur)

    with tempfile.TemporaryDirectory(prefix="installer_voix_") as dossier_temp:
        tmp_installer = Path(dossier_temp)
        deux = fichiers_complete[:2]
        sons = tmp_installer / "tts_cache_oolel"
        sons.mkdir()
        for nom in deux:
            with _wave.open(str(sons / nom), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 160)
        archive_mini = tmp_installer / "mini.zip"
        with _zipfile.ZipFile(archive_mini, "w") as boite:
            for nom in deux:
                boite.write(sons / nom, arcname=f"tts_cache_oolel/{nom}")
        cache_test = tmp_installer / "cache_test"

        verifie(
            "installer : mini-archive réelle installée (2 noms de voix_complete.csv)",
            installeur.installer(archive_mini, deux, cache=cache_test) == 0
            and all((cache_test / nom).is_file() for nom in deux),
        )
        refle = io.StringIO()
        with contextlib.redirect_stderr(refle):
            refus = installeur.installer(
                archive_mini, installeur.fichiers_attendus(), cache=cache_test
            )
        verifie(
            "installer : archive incomplète refusée (les 873 attendus, 2 fournis)",
            refus == 1
            and "manquant(s)" in refle.getvalue()
            and not (cache_test / fichiers_complete[5]).is_file(),
            (refus, refle.getvalue()[:120]),
        )

        # Le petit zip « ajouts_conversation » : les 4 réponses de
        # conversation, plus deux essais « Tata » que l'installateur doit
        # ignorer (phrases d'écoute, jamais jouées par l'app). Une archive à
        # laquelle il manque une réponse est refusée.
        quatre = installeur.CONVERSATION
        sons_conv = tmp_installer / "conversation"
        sons_conv.mkdir()
        for nom in quatre + ("test_tata_tataa.wav", "test_tata_tata.wav"):
            with _wave.open(str(sons_conv / nom), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 160)
        archive_conv = tmp_installer / "ajouts_conversation.zip"
        with _zipfile.ZipFile(archive_conv, "w") as boite:
            for nom in quatre + ("test_tata_tataa.wav", "test_tata_tata.wav"):
                boite.write(sons_conv / nom, arcname=f"audios_conversation/{nom}")
        cache_conv = tmp_installer / "cache_conv"
        refle_conv = io.StringIO()
        with contextlib.redirect_stdout(refle_conv):
            pose = installeur.installer_conversation(archive_conv, cache=cache_conv)
        verifie(
            "installer --conversation : les 4 réponses posées, essais Tata ignorés",
            pose == 0
            and all((cache_conv / nom).is_file() for nom in quatre)
            and not (cache_conv / "test_tata_tataa.wav").is_file()
            and "ignoré(s)" in refle_conv.getvalue()
            and "test_tata_tataa.wav" in refle_conv.getvalue(),
            (pose, refle_conv.getvalue()[:160]),
        )
        archive_conv_incomplete = tmp_installer / "conversation_incomplete.zip"
        with _zipfile.ZipFile(archive_conv_incomplete, "w") as boite:
            for nom in ("test_tata_tataa.wav", "test_tata_tata.wav"):
                boite.write(sons_conv / nom, arcname=f"audios_conversation/{nom}")
        refle_manque = io.StringIO()
        with contextlib.redirect_stderr(refle_manque):
            refus_conv = installeur.installer_conversation(
                archive_conv_incomplete, cache=cache_conv
            )
        verifie(
            "installer --conversation : une réponse manquante est refusée (4 attendues)",
            refus_conv == 1 and "manquant(s)" in refle_manque.getvalue(),
            (refus_conv, refle_manque.getvalue()[:120]),
        )

    return echecs, total


def test_notebooks_brev() -> tuple[int, int]:
    """Les notebooks Brev et Colab se rejouent, mot pour mot, depuis les scripts.

    On ne fait pas confiance au fichier écrit à la main : on régénère chaque
    notebook dans un dossier temporaire (preparer --brev, preparer défaut,
    brev.py --dossier) et on compare octet pour octet avec la version du dépôt.
    """
    import os
    import subprocess
    import tempfile

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | notebooks Brev {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    environnement = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with tempfile.TemporaryDirectory(prefix="brev_regen_") as dossier_temp:
        tmp = Path(dossier_temp)
        tutoriels = (
            (
                "preparer --brev",
                [
                    sys.executable,
                    "scripts/preparer_notebook_oolel.py",
                    "--brev",
                    "--sortie",
                    str(tmp / "complet_brev.ipynb"),
                ],
                tmp / "complet_brev.ipynb",
                RACINE / "notebooks" / "voix_oolel_complete_brev.ipynb",
            ),
            (
                "preparer Colab",
                [
                    sys.executable,
                    "scripts/preparer_notebook_oolel.py",
                    "--sortie",
                    str(tmp / "complet_colab.ipynb"),
                ],
                tmp / "complet_colab.ipynb",
                RACINE / "notebooks" / "voix_oolel_complete.ipynb",
            ),
        )
        for nom, commande, genere, attente in tutoriels:
            lance = subprocess.run(
                commande,
                cwd=RACINE,
                capture_output=True,
                encoding="utf-8",
                env=environnement,
            )
            ok = (
                lance.returncode == 0
                and genere.exists()
                and genere.read_text(encoding="utf-8") == attente.read_text(encoding="utf-8")
            )
            verifie(f"régénération {nom} identique au dépôt", ok, (lance.returncode, lance.stdout, lance.stderr[:400]))

        lance = subprocess.run(
            [sys.executable, "scripts/brev.py", "--dossier", str(tmp / "regen")],
            cwd=RACINE,
            capture_output=True,
            encoding="utf-8",
            env=environnement,
        )
        regeneres = tmp / "regen"
        ok = lance.returncode == 0 and all(
            (regeneres / nom).read_text(encoding="utf-8")
            == (RACINE / "notebooks" / nom).read_text(encoding="utf-8")
            for nom in (
                "voix_test_prononciation_brev.ipynb",
                "voix_oolel_complete_brev.ipynb",
                "voix_ajouts_conversation_brev.ipynb",
            )
        )
        verifie("régénération brev.py --dossier identique au dépôt", ok, (lance.returncode, lance.stderr[:400]))

    return echecs, total


def test_verification_voix() -> tuple[int, int]:
    """Teste le best-of-3 (similarité, durée, choix) sans charger un modèle."""
    import json

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | vérification voix {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    notebook = json.loads(
        (RACINE / "notebooks" / "voix_oolel_colab.ipynb").read_text(encoding="utf-8")
    )
    source = None
    for cellule in notebook["cells"]:
        texte = "".join(cellule["source"])
        if "# HELPERS_VERIFICATION_VOIX" in texte:
            source = texte
            break
    verifie("cellule helpers présente dans le notebook", source is not None)
    if source is None:
        return echecs, total

    # On exécute uniquement la cellule pure : aucun import de torch/parler_tts.
    espace: dict[str, object] = {}
    exec(compile(source, "<helpers notebook>", "exec"), espace)
    normaliser = espace["normaliser_texte"]
    distance = espace["distance_levenshtein"]
    score = espace["similarite"]
    bornes = espace["bornes_duree"]
    controler = espace["controler_duree"]
    douteux_score = espace["est_douteux"]
    choisir = espace["choisir_meilleur_candidat"]

    verifie(
        "normalisation accents, ponctuation et majuscules",
        normaliser("Jëlal bus bu Dem Dikk, Tàf Tàf.") == "jelal bus bu dem dikk taf taf",
        normaliser("Jëlal bus bu Dem Dikk, Tàf Tàf."),
    )
    verifie(
        "normalisation de ñ et ŋ",
        normaliser("Ñaari Ŋa") == "naari na",
        normaliser("Ñaari Ŋa"),
    )
    verifie("Levenshtein identique", distance("abc", "abc") == 0)
    verifie("Levenshtein substitution", distance("abc", "abd") == 1)
    verifie("similarité identique après normalisation", score("Tàf Tàf", "taf taf") == 1.0)
    verifie(
        "similarité partielle entre 0 et 1",
        0.0 < score("Benn baraak", "benn baraq") < 1.0,
        score("Benn baraak", "benn baraq"),
    )

    mini, maxi = bornes("Benn baraak")
    verifie("bornes de durée cohérentes", 0.0 < mini < maxi, (mini, maxi))
    ok_court, raison_court = controler(0.2, "Benn baraak")
    verifie(
        "durée trop courte détectée",
        not ok_court and "court" in raison_court,
        (ok_court, raison_court),
    )
    ok_long, raison_long = controler(maxi + 2.0, "Benn baraak")
    verifie(
        "son après la fin attendue détecté",
        not ok_long and "fin" in raison_long,
        (ok_long, raison_long),
    )
    ok_normal, _ = controler((mini + maxi) / 2, "Benn baraak")
    verifie("durée normale acceptée", ok_normal)
    verifie(
        "douteux si la similarité est faible",
        douteux_score(0.4, True) is True and douteux_score(0.9, True) is False,
    )
    verifie(
        "douteux si la durée est anormale",
        douteux_score(0.9, False) is True,
    )

    candidats = [
        {"score": 0.80, "duree_ok": True},
        {"score": 0.90, "duree_ok": False},
        {"score": 0.70, "duree_ok": True},
    ]
    verifie(
        "un candidat à durée anormale ne passe pas devant un bon",
        choisir(candidats) == 0,
        choisir(candidats),
    )
    candidats_valides = [
        {"score": 0.40, "duree_ok": True},
        {"score": 0.60, "duree_ok": True},
        {"score": 0.50, "duree_ok": True},
    ]
    verifie(
        "le meilleur score gagne quand les durées sont bonnes",
        choisir(candidats_valides) == 1,
        choisir(candidats_valides),
    )

    plan = json.loads(
        (RACINE / "scripts" / "phrases_voix.json").read_text(encoding="utf-8")
    )
    liste_a_regenerer = [
        ligne.strip()
        for ligne in (RACINE / "scripts" / "a_regenerer.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if ligne.strip()
    ]
    marquees = {
        entree["fichier"]
        for entree in plan["phrases"]
        if entree.get("a_regenerer") is True
    }
    verifie(
        "le plan marque exactement les 637 fichiers de a_regenerer.txt",
        len(liste_a_regenerer) == 637 and marquees == set(liste_a_regenerer),
        {
            "liste": len(liste_a_regenerer),
            "marquees": len(marquees),
            "ecart": sorted(marquees.symmetric_difference(set(liste_a_regenerer))),
        },
    )

    import contextlib
    import io

    cellule_plan = next(
        "".join(cellule["source"])
        for cellule in notebook["cells"]
        if "# HELPERS_VERIFICATION_VOIX" not in "".join(cellule["source"])
        and "PLAN = {" in "".join(cellule["source"])
    )
    espace_plan: dict[str, object] = {}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(cellule_plan, "<plan notebook>", "exec"), espace_plan)
    verifie(
        "le plan du notebook Oolel est celui du dépôt",
        espace_plan["PLAN"] == plan,
        {
            "modele_notebook": espace_plan["PLAN"].get("modele")
            if isinstance(espace_plan["PLAN"], dict)
            else None,
            "modele_plan": plan.get("modele"),
        },
    )

    page_ecoute = (RACINE / "scripts" / "ecoute_voix.html").read_text(encoding="utf-8")
    verifie(
        "la page d'écoute filtre douteux depuis rapport_voix.csv",
        'value="douteux"' in page_ecoute
        and "rapport_voix.csv" in page_ecoute
        and "function parseCsv" in page_ecoute,
    )

    return echecs, total


def _lignes_dans(carte: str) -> set[str]:
    """Numéros de ligne affichés dans la carte HTML renvoyée par l'app."""
    texte = re.sub(r"<[^>]+>", " ", carte)
    numeros = set(re.findall(r"(?:DAKAR DEM DIKK|TATA AFTU|Dakar Dem Dikk|Tata AFTU)\s+(\w+)", texte))
    lignes = {f"Ligne {n}" for n in numeros}
    if "Pas de bus direct" in texte:
        premier = re.search(r"1er bus · (?:Tata AFTU|Dakar Dem Dikk)\s+(\w+)", texte)
        if premier:
            lignes.add(f"corr:Ligne {premier.group(1)}")
    return lignes


URL_APP = "https://tijaani-guindima-ai.hf.space"


def _appel(client, phrase: str) -> list:
    """Appelle l'API Gradio de l'app, comme le fait le navigateur.

    httpx est déjà installé (dépendance de huggingface_hub) : pas besoin de
    gradio_client. Le premier champ est le micro, toujours vide pour un test
    texte ; le 3e est le bouton Compagnie, vide pour « Tous ».
    """
    import json

    reponse = client.post(
        f"{URL_APP}/gradio_api/call/repondre_et_vider_micro",
        json={"data": [None, phrase or "", ""]},
    )
    reponse.raise_for_status()
    flux = client.get(
        f"{URL_APP}/gradio_api/call/repondre_et_vider_micro/{reponse.json()['event_id']}"
    ).text
    trouve = re.search(r"event: (complete|error)\ndata: (.*)", flux)
    if not trouve:
        raise RuntimeError(f"réponse inattendue : {flux[:200]}")
    if trouve.group(1) == "error":
        raise RuntimeError(f"erreur de l'app : {trouve.group(2)}")
    return json.loads(trouve.group(2))


def _charger_module(chemin: Path, nom: str):
    """Charge un fichier .py sans passer par le paquet `app` de src/."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


class _FauxMessage:
    def __init__(self, contenu: str):
        self.content = contenu


class _FauxChoix:
    def __init__(self, contenu: str):
        self.message = _FauxMessage(contenu)


class _FauxReponse:
    def __init__(self, contenu: str):
        self.choices = [_FauxChoix(contenu)]


class _FauxCompletions:
    def __init__(self, contenu: str):
        self.contenu = contenu
        self.appels: list[dict] = []

    def create(self, **kwargs):
        self.appels.append(kwargs)
        return _FauxReponse(self.contenu)


class _FauxChat:
    def __init__(self, contenu: str):
        self.completions = _FauxCompletions(contenu)


class _FauxClient:
    """Client OpenAI minimal : capture le prompt et renvoie un JSON fixé."""

    def __init__(self, contenu: str):
        self.chat = _FauxChat(contenu)


def test_securite() -> tuple[int, int]:
    """Vérifie les garde-fous : logs, audio, prompt, HTML, révisions, déploiement."""
    import contextlib
    import io
    import os
    import shutil
    import tempfile
    import wave

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_securite")
    from app.cartes import titre_autre_possibilite
    from intent.extract_intent import (
        CONSIGNE_TEXTE,
        DEBUT_TEXTE,
        FIN_TEXTE,
        TEXTE_MAX,
        extract_intent,
    )

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool) -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | sécurité {nom}")

    # 1. Les logs ne doivent jamais contenir la phrase ni les lieux.
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        app._journal("Kiriku", 1.25, 2, "extraction_llm")
    journal = tampon.getvalue()
    verifie(
        "logs sans texte utilisateur",
        "phrase" not in journal
        and "départ" not in journal
        and "arrivée" not in journal
        and "ASR=Kiriku" in journal
        and "lignes=2" in journal
        and "erreur=extraction_llm" in journal,
    )

    # 2. Audio : refus avant transcription, message FR + wolof.
    dossier = Path(tempfile.mkdtemp(prefix="test_securite_"))
    try:
        gros = dossier / "trop_gros.wav"
        with open(gros, "wb") as fichier:
            fichier.write(b"0" * (10 * 1024 * 1024 + 1))
        sortie = app.trouver_le_bus(str(gros), "", "")
        verifie(
            "audio > 10 Mo refusé",
            "10 Mo" in sortie[2] and "Fi bi" in sortie[2],
        )

        long = dossier / "trop_long.wav"
        with wave.open(str(long), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(app.SAMPLE_RATE)
            wav.writeframes(b"\0\0" * (31 * app.SAMPLE_RATE))
        sortie = app.trouver_le_bus(str(long), "", "")
        verifie(
            "audio > 30 s refusé",
            "30 secondes" in sortie[2] and "segond" in sortie[2],
        )

        vieux = app.DOSSIER_VOIX / "reponse_test_securite.wav"
        vieux.write_bytes(b"RIFF")
        os.utime(vieux, (time.time() - app.DUREE_VIE_VOIX - 1,) * 2)
        app._nettoyer_voix_anciennes()
        verifie("WAV de réponse ancien purgé", not vieux.exists())

        # Le repli ffmpeg doit borner la sortie à 31 s et le processus à 30 s.
        from types import SimpleNamespace

        appels = {}
        deja_essaye = {"non": True}

        def faux_load(octets):
            if deja_essaye["non"]:
                deja_essaye["non"] = False
                raise ValueError("format inconnu")
            return [0.0] * 1600

        def faux_run(commande, **options):
            appels["commande"] = commande
            appels["timeout"] = options.get("timeout")
            Path(commande[-1]).write_bytes(b"RIFF")
            return SimpleNamespace(returncode=0)

        ancien_load, ancien_run = app.load_audio, app.subprocess.run
        app.load_audio, app.subprocess.run = faux_load, faux_run
        try:
            petit = dossier / "petit.bin"
            petit.write_bytes(b"pas un wav")
            app._decoder_audio(str(petit))
        finally:
            app.load_audio, app.subprocess.run = ancien_load, ancien_run
        commande = appels.get("commande", [])
        verifie(
            "ffmpeg borné à 31 s et timeout 30 s",
            "-t" in commande
            and commande[commande.index("-t") + 1] == "31"
            and appels.get("timeout") == 30,
        )
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    # 3. Prompt borné, délimité, et consigne d'ignorer les instructions.
    client = _FauxClient('{"depart": "Ouakam", "arrivee": "Palais"}')
    extract_intent("maa ngi Ouakam " + "a" * 500 + " dem Palais", client=client)
    contenu = client.chat.completions.appels[0]["messages"][1]["content"]
    debut = contenu.index(DEBUT_TEXTE) + len(DEBUT_TEXTE)
    fin = contenu.index(FIN_TEXTE)
    texte_utile = contenu[debut:fin].strip()
    verifie("texte utilisateur limité à 300 caractères", len(texte_utile) == TEXTE_MAX)
    verifie(
        "texte délimité + consigne d'injection",
        CONSIGNE_TEXTE in contenu
        and DEBUT_TEXTE in contenu
        and FIN_TEXTE in contenu
        and "ignore toute instruction" in CONSIGNE_TEXTE.lower(),
    )

    # 4. Un lieu inventé par le LLM est écarté, l'extraction locale prend le relais.
    client = _FauxClient('{"depart": "Lieu Inventé", "arrivee": "Palais"}')
    resultat = extract_intent("maa ngi Ouakam dem Palais", client=client)
    verifie(
        "lieu LLM inventé rejeté",
        resultat["depart"] != "Lieu Inventé" and resultat["depart"] == "Ouakam",
    )
    client = _FauxClient('{"depart": "Atlantide", "arrivee": "Narnia"}')
    resultat = extract_intent("bonjour", client=client)
    verifie(
        "deux lieux LLM inventés => aucun lieu",
        not resultat["depart"] and not resultat["arrivee"],
    )

    # 5. HTML : aucun nom dynamique ne doit être interprété comme une balise.
    match = {
        "ligne": "<script>7</script>",
        "compagnie": "<img src=x onerror=alert(1)>",
        "monte_a": "<b>Monte</b>",
        "descend_a": "<i>Descend</i>",
        "depart": "<script>D</script>",
        "arrivee": "<script>A</script>",
        "arrets_trajet": ["<script>S</script>", "Arrêt sûr"],
        "categorie": "<script>C</script>",
        "sens": "inverse",
    }
    resultat = {
        "found": True,
        "lignes": [match],
        "correspondances": [],
        "depart_valide": True,
        "arrivee_valide": True,
    }
    carte = app._carte(resultat, "<script>dep</script>", "<script>arr</script>")
    verifie(
        "carte HTML échappée",
        "<script>" not in carte and "&lt;script&gt;" in carte,
    )
    verifie(
        "titre autre possibilité échappé",
        "<script>" not in titre_autre_possibilite("<script>2</script>"),
    )
    mention = app._mention(
        {"erreur": "<script>erreur</script>"}, "<script>asr</script>"
    )
    verifie("mention échappée", "<script>" not in mention)

    resultat_vide = {
        "found": False,
        "lignes": [],
        "correspondances": [],
        "depart_valide": False,
        "arrivee_valide": False,
    }
    carte = app._carte(resultat_vide, "<script>dep</script>", "<script>arr</script>")
    verifie(
        "lieu hors réseau échappé",
        "<script>" not in carte and "&lt;script&gt;" in carte,
    )

    # 6. Révisions et dépendances corrigées.
    transcribe = _charger_module(RACINE / "src" / "asr" / "transcribe.py", "transcribe_securite")
    finetune = _charger_module(RACINE / "scripts" / "finetune_whisper.py", "finetune_securite")
    evaluer = _charger_module(RACINE / "scripts" / "evaluer_modele.py", "evaluer_securite")
    revisions = {
        transcribe.REVISION_WHISPER,
        transcribe.REVISION_WHISPER_SECOURS,
        transcribe.REVISION_ASR_GPU,
        finetune.REVISIONS_CONNUES[finetune.MODEL_DEFAUT],
        finetune.REVISIONS_CONNUES[finetune.MODELE_ESSAI],
        evaluer.REVISIONS_CONNUES["M9and2M/whisper-small-wolof"],
    }
    verifie(
        "révisions épinglées (SHA de 40 caractères)",
        all(revision and len(revision) == 40 for revision in revisions),
    )
    requirements = (RACINE / "requirements.txt").read_text(encoding="utf-8")
    requirements_train = (RACINE / "requirements-train.txt").read_text(encoding="utf-8")
    readme = (RACINE / "README.md").read_text(encoding="utf-8")
    # Le README du Space porte sa configuration : Gradio y est fixé par
    # sdk_version, pas par requirements.txt (une ligne gradio== cassait le build).
    paquets = [
        ligne.split("#", 1)[0].strip()
        for ligne in requirements.splitlines()
        if ligne.split("#", 1)[0].strip()
    ]
    entete_readme = readme.split("---", 2)[1] if readme.startswith("---") else ""
    verifie(
        "dépendances épinglées, Gradio via sdk_version",
        not any(re.match(r"(?i)^gradio(?:\s|[<>=!~]|$)", paquet) for paquet in paquets)
        and re.search(r"(?m)^sdk_version\s*:", entete_readme) is not None
        and "pillow==12.3.0" in requirements
        and "pillow==13.0.0" not in requirements
        and "python-dotenv==1.2.2" in requirements_train,
    )

    # 7. Déploiement : pas de copie du token, .claude exclu, dry-run sans
    # réseau, dossiers du projet obligatoires, relecture anti-secret.
    upload = (RACINE / "upload_space.py").read_text(encoding="utf-8")
    ignore = (RACINE / ".gitignore").read_text(encoding="utf-8")
    verifie(
        "token non copié et .claude exclu",
        "add_space_secret" not in upload
        and "get_token" not in upload
        and ".claude/*" in upload
        and ".claude/" in ignore,
    )
    verifie(
        "dry-run fidèle, dossiers obligatoires, double filet anti-secret",
        "--dry-run" in upload
        and "filter_repo_objects" in upload
        and "verifier_secrets" in upload
        and ".ipynb_checkpoints" in upload
        and all(
            dossier in upload
            for dossier in ("data/corrections", "data/sources", "data/tts_cache_oolel")
        ),
    )

    return echecs, total


def test_interface_micro() -> tuple[int, int]:
    """Le micro est évident, sans choix de périphérique, et sans démos audio."""
    import json
    import os

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_interface")

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | interface {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    css = app.CSS_GUINDIMA
    verifie(
        "bouton d'enregistrement vert, large et lisible",
        all(
            morceau in css
            for morceau in (
                "#micro_guindima .record-button",
                "#00853F",
                "width: 100%",
                "min-height: 64px",
                "font-size: 20px",
                "border-radius: 14px",
                "#FFFFFF",
            )
        ),
        css[:400],
    )
    verifie(
        "bouton Arrêter rouge et pulsation",
        "#micro_guindima .record-button,\n#micro_guindima .stop-button" in css
        and "#D62828" in css
        and "@keyframes guindima-pulse" in css
        and "animation: guindima-pulse" in css,
    )
    verifie(
        "sélecteur de périphérique masqué dans le micro",
        "#micro_guindima .mic-select" in css and "display: none !important" in css,
    )
    verifie(
        "consigne bordée en vert à gauche et à droite",
        "border-left: 5px solid #00853F" in css
        and "border-right: 5px solid #00853F" in css,
    )
    verifie(
        "bouton Arrête à 25 %, centré, avec largeur minimale",
        "#micro_guindima .stop-button" in css
        and "width: 25%" in css
        and "min-width: 120px" in css
        and "margin-top: 14px !important" in css
        and "margin: 0 auto !important" in css,
    )
    verifie(
        "espace entre les boutons et consigne forcée en mode sombre",
        "margin-top: 14px !important" in css
        and all(
            selecteur in css
            for selecteur in (
                "#consigne_micro p",
                "#consigne_micro strong",
                "#consigne_micro span",
                ".dark #consigne_micro",
                ".dark #consigne_micro p",
                ".dark #consigne_micro strong",
                ".dark #consigne_micro span",
            )
        )
        and all(
            css.count(f"{variable}: #064E2B !important;") >= 2
            for variable in (
                "--body-text-color",
                "--block-label-text-color",
                "--link-text-color",
            )
        )
        and ".dark #consigne_micro {" in css
        and "#consigne_micro *" in css
        and ".dark #consigne_micro *" in css
        and "color: #064E2B !important" in css
        and "background: #E8F5EE !important" in css,
    )
    verifie(
        "croix d'effacement du micro masquée",
        'button[aria-label="Effacer"]' in css
        and 'button[aria-label="Clear"]' in css
        and "display: none !important" in css,
    )
    verifie(
        "chaque option de trajet fréquent est cliquable sur toute la ligne",
        "#trajets_frequents .item" in css
        and "min-height: 44px" in css
        and "width: 100%" in css,
    )
    verifie(
        "libellés du micro en français",
        app.I18N_GUINDIMA is not None
        and app.I18N_GUINDIMA.translations["fr"]["audio.record"] == "Appuie et parle"
        and app.I18N_GUINDIMA.translations["fr"]["audio.stop"] == "Arrête",
    )

    interface = app._construire()
    config = interface.get_config_file()
    composants = config["components"]
    texte_config = json.dumps(config, ensure_ascii=False, default=str)
    source_app = (RACINE / "app.py").read_text(encoding="utf-8")
    verifie(
        "plus de démos audio ni de gr.Examples",
        "demo_audio" not in texte_config
        and "rejoue un enregistrement" not in texte_config
        and "rejoue un enregistrement" not in source_app
        and "DEMO_AUDIO" not in source_app
        and "gr.Examples" not in source_app,
    )

    micros = [
        composant
        for composant in composants
        if composant.get("type") == "audio"
        and composant.get("props", {}).get("elem_id") == app.MICRO_ELEM_ID
    ]
    verifie(
        "consigne simple au-dessus du micro",
        "Appuie sur le bouton vert, dis ton trajet, puis appuie sur Arrête"
        in source_app
        and "css=CSS_GUINDIMA" in source_app
        and "i18n=I18N_GUINDIMA" in source_app,
    )
    verifie(
        "composant micro ciblé par elem_id",
        len(micros) == 1
        and micros[0]["props"].get("sources") == ["microphone", "upload"]
        and micros[0]["props"].get("show_label") is False,
        micros,
    )
    micro_id = micros[0]["id"] if micros else None
    evenements_micro = [
        dependance
        for dependance in config["dependencies"]
        if micro_id in dependance.get("inputs", [])
    ]
    verifie(
        "micro vidé par le bouton, l'arrêt et le change",
        len(evenements_micro) >= 3
        and all(micro_id in dependance.get("outputs", []) for dependance in evenements_micro),
        evenements_micro,
    )

    textboxs = [
        composant
        for composant in composants
        if composant.get("props", {}).get("label") == "Ton trajet en wolof"
    ]
    verifie(
        "zone Écrire vide avec le bon exemple",
        len(textboxs) == 1
        and textboxs[0]["props"].get("value") == ""
        and textboxs[0]["props"].get("placeholder")
        == "Ex. : Maa ngi Parcelles Assainies, bëgg naa dem UCAD",
        textboxs,
    )

    dropdowns = [
        composant
        for composant in composants
        if composant.get("props", {}).get("elem_id") == "trajets_frequents"
    ]
    props = dropdowns[0]["props"] if len(dropdowns) == 1 else {}
    choix = props.get("choices") or []
    libelles = [choix_item[0] for choix_item in choix if isinstance(choix_item, (list, tuple))]
    verifie(
        "liste des trajets fréquents, avec recherche",
        len(dropdowns) == 1
        and props.get("filterable") is True
        and props.get("allow_custom_value") is False
        and props.get("label") == "🚌 Trajets fréquents à Dakar"
        and props.get("info") == "Tape le nom d'un quartier, par ex. Malika"
        and props.get("value") is None
        and len(choix) == len(app.TRAJETS_FREQUENTS)
        and all(" → " in libelle for libelle in libelles),
        props,
    )
    verifie(
        "plus de faux choix dans la liste",
        not any("Cherche" in libelle or "choisis" in libelle.lower() for libelle in libelles),
        libelles[:3],
    )
    dropdown_id = dropdowns[0]["id"] if len(dropdowns) == 1 else None
    verifie(
        "plus de champ Chercher un trajet fréquent",
        not any(
            composant.get("props", {}).get("label") == "Chercher un trajet fréquent"
            for composant in composants
        )
        and "recherche_trajets" not in texte_config
        and not hasattr(app, "filtrer_trajets_frequents"),
        [
            composant.get("props", {}).get("label")
            for composant in composants
            if composant.get("type") == "textbox"
        ],
    )
    verifie(
        "le choix « mal » contient Malika",
        any("mal" in libelle.lower() for libelle in libelles),
        libelles,
    )
    evenements_frequents = [
        dependance
        for dependance in config["dependencies"]
        if dropdown_id in dependance.get("inputs", [])
    ]
    verifie(
        "trajet fréquent : vidage du micro et de la liste câblés",
        len(evenements_frequents) == 1
        and micro_id in evenements_frequents[0].get("outputs", [])
        and dropdown_id in evenements_frequents[0].get("outputs", []),
        evenements_frequents,
    )

    states = [
        composant
        for composant in composants
        if composant.get("type") == "state"
    ]
    state_ids = {composant["id"] for composant in states}
    compagnies = [
        composant
        for composant in composants
        if composant.get("props", {}).get("label") == "Compagnie"
    ]
    compagnie_id = compagnies[0]["id"] if len(compagnies) == 1 else None
    evenements_compagnie = [
        dependance
        for dependance in config["dependencies"]
        if any(
            cible[0] == compagnie_id and cible[1] == "change"
            for cible in dependance.get("targets", [])
        )
    ]
    verifie(
        "changement de compagnie relié à l'état de la dernière demande",
        len(evenements_compagnie) == 1
        and compagnie_id in evenements_compagnie[0].get("inputs", [])
        and micro_id in evenements_compagnie[0].get("outputs", [])
        and len(evenements_compagnie[0].get("outputs", [])) == 7
        and bool(state_ids & set(evenements_compagnie[0].get("inputs", [])))
        and bool(state_ids & set(evenements_compagnie[0].get("outputs", []))),
        evenements_compagnie,
    )

    api_boutons = [
        composant
        for composant in composants
        if composant.get("props", {}).get("elem_id") == "api_repondre"
    ]
    api_id = api_boutons[0]["id"] if len(api_boutons) == 1 else None
    evenements_api = [
        dependance
        for dependance in config["dependencies"]
        if any(cible[0] == api_id for cible in dependance.get("targets", []))
    ]
    verifie(
        "point d'entrée API repondre_et_vider_micro conservé",
        len(api_boutons) == 1
        and api_boutons[0]["props"].get("visible") is False
        and len(evenements_api) == 1
        and evenements_api[0].get("api_name") == "repondre_et_vider_micro"
        and micro_id in evenements_api[0].get("outputs", [])
        and len(evenements_api[0].get("outputs", [])) == 6,
        (api_boutons, evenements_api),
    )

    readme = (RACINE / "README.md").read_text(encoding="utf-8")
    verifie(
        "README sans démos audio",
        "demo_audio" not in readme and "rejoue un enregistrement" not in readme,
    )
    verifie(
        "README credits: native Oolel voice, ASR licenses to verify, data sources, corrections",
        "Credits and licenses" in readme
        and "Oolel-Voices-Demo" in readme
        and "8_1_c" in readme
        and "AGPL-3.0" in readme
        and "TTS model" in readme
        and "runs inside the app" in readme
        and "aftu-senegal.org" in readme
        and "ODbL 1.0" in readme
        and "data/corrections" in readme
        and "see model card (TODO verify)" in readme,
    )
    verifie(
        "README : GUINDIMA_MOTEUR documenté (v2 par défaut, v1 exprès, pas de repli silencieux)",
        "GUINDIMA_MOTEUR" in readme
        and "v2" in readme
        and "v1" in readme
        and "silently falling back" in readme,
    )
    # upload_space.py est volontairement exclu de Git (réglages locaux) : on le
    # vérifie quand il est là, sans rendre la suite impossible sur un clone nu.
    upload = RACINE / "upload_space.py"
    if upload.exists():
        contenu = upload.read_text(encoding="utf-8")
        verifie(
            "démos exclues du Space",
            "data/demo_audio/*" in contenu
            and "data/demo_audio/trajet liberte5_palais2.wav" in contenu
            and "data/demo_audio/trajet ouakam_palais.wav" in contenu,
        )
    else:
        print("IGNORÉ | upload_space.py absent (fichier local exclu de Git)")

    return echecs, total


def test_micro_vidage() -> tuple[int, int]:
    """Chaque résultat vide le micro ; un micro vide ne relance aucun calcul."""
    import os
    import shutil
    import tempfile
    import wave

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_micro")

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | micro {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    dossier = Path(tempfile.mkdtemp(prefix="test_micro_"))
    try:
        phrase = "Maa ngi Ouakam, bëgg naa dem Palais"
        sortie = app.repondre_et_vider_micro(None, phrase, "")
        verifie(
            "résultat texte : micro vidé, carte et voix gardées",
            len(sortie) == 6
            and sortie[1] == "Ouakam → Palais"
            and "Dakar Dem Dikk" in sortie[2]
            and sortie[3] is not None
            and sortie[5] is None,
            sortie,
        )

        # « Bonjour » est désormais une salutation (petite conversation) : une
        # phrase sans trajet complet, c'est une arrivée sans départ.
        sortie = app.repondre_et_vider_micro(None, "dama bëgg dem Palais", "")
        verifie(
            "aucun trajet : micro vidé, explication affichée",
            sortie[5] is None
            and sortie[1] == ""
            and "Lieu non détecté" in sortie[2]
            and sortie[3] is None,
            sortie,
        )

        sortie = app.repondre_et_vider_micro(None, "", "")
        verifie(
            "demande vide : message d'aide, micro vidé",
            sortie[5] is None
            and app.MESSAGE_DEMANDE_VIDE in sortie[2]
            and sortie[1] == "",
            sortie,
        )

        court = dossier / "court.wav"
        with wave.open(str(court), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(app.SAMPLE_RATE)
            wav.writeframes(b"\0\0" * int(app.SAMPLE_RATE * 0.1))
        sortie = app.repondre_et_vider_micro(str(court), "", "")
        verifie(
            "audio vide : micro vidé, pas d'erreur",
            sortie[5] is None
            and sortie[0] == ""
            and sortie[1] == ""
            and sortie[3] is None
            and "illisible" not in sortie[2].lower()
            and "impossible" not in sortie[2].lower(),
            sortie,
        )

        long = dossier / "long.wav"
        with wave.open(str(long), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(app.SAMPLE_RATE)
            wav.writeframes(b"\0\0" * (31 * app.SAMPLE_RATE))
        sortie = app.repondre_et_vider_micro(str(long), "", "")
        verifie(
            "audio trop long : micro vidé, erreur affichée",
            sortie[5] is None and "30 secondes" in sortie[2],
            sortie,
        )

        appels = []
        ancien_bus = app.trouver_le_bus

        def interdit(*args, **kwargs):
            appels.append((args, kwargs))
            raise AssertionError("le vidage du micro ne doit pas relancer le pipeline")

        app.trouver_le_bus = interdit
        try:
            vides = app.rechercher_une_fois(None, phrase, "")
        finally:
            app.trouver_le_bus = ancien_bus
        verifie(
            "micro None : silence, résultats conservés",
            len(vides) == 7
            and all(valeur == app.gr.skip() for valeur in vides)
            and not appels,
            vides,
        )

        sortie = app.choisir_trajet_frequent("Ouakam → Palais", "")
        verifie(
            "trajet fréquent : texte rempli, recherche lancée, liste vidée",
            len(sortie) == 9
            and sortie[0] == phrase
            and sortie[2] == "Ouakam → Palais"
            and "Dakar Dem Dikk" in sortie[3]
            and sortie[6] is None
            and sortie[7] == {"phrase": phrase, "mode": "texte"}
            and sortie[8] is None,
            sortie,
        )

        appels = []
        ancien_reponse = app.traiter_demande

        def interdit_reponse(*args, **kwargs):
            appels.append((args, kwargs))
            raise AssertionError("la liste vidée ne doit rien relancer")

        app.traiter_demande = interdit_reponse
        try:
            vides = app.choisir_trajet_frequent(None, "")
        finally:
            app.traiter_demande = ancien_reponse
        verifie(
            "liste vidée : silence, pas de boucle",
            len(vides) == 9
            and all(valeur == app.gr.skip() for valeur in vides)
            and not appels,
            vides,
        )

        phrase_compagnie = "Maa ngi Parcelles Assainies, bëgg naa dem UCAD"
        sortie = app.traiter_demande(None, phrase_compagnie, "", None, True)
        etat = sortie[6]
        verifie(
            "demande initiale : état texte enregistré",
            sortie[1] == "Parcelles Assainies → UCAD"
            and isinstance(etat, dict)
            and etat.get("phrase") == phrase_compagnie
            and etat.get("mode") == "texte",
            sortie,
        )

        appels = []
        ancien_trouver = app.trouver_le_bus

        def interdit_trouver(*args, **kwargs):
            appels.append((args, kwargs))
            raise AssertionError("un changement de compagnie ne retranscrit pas")

        app.trouver_le_bus = interdit_trouver
        try:
            cas_compagnies = [
                ("", "Dakar Dem Dikk", None, "Tous"),
                ("Dakar Dem Dikk", "Dakar Dem Dikk", "Tata AFTU", "Dem Dikk"),
                ("Tata AFTU", "Tata AFTU", "Dakar Dem Dikk", "Tata"),
                ("", "Dakar Dem Dikk", None, "Tous"),
            ]
            for compagnie, attendue, interdite, etiquette in cas_compagnies:
                resultat = app.traiter_demande(None, "IGNORE", compagnie, etat, False)
                carte = resultat[2]
                condition = (
                    attendue in carte
                    and (interdite is None or interdite not in carte)
                    and f"Compagnie : {etiquette} (choisie avec le bouton)" in carte
                    and resultat[1] == "Parcelles Assainies → UCAD"
                    and resultat[5] == app.gr.skip()
                    and resultat[6] == etat
                )
                verifie(
                    f"compagnie {etiquette} : lignes et étiquette cohérentes",
                    condition,
                    resultat,
                )

            etat_voix = {
                "phrase": phrase_compagnie + " ak Tata",
                "mode": "voix",
            }
            resultat = app.traiter_demande(
                None, "IGNORE", "Dakar Dem Dikk", etat_voix, False
            )
            carte = resultat[2]
            verifie(
                "compagnie dite à la voix : elle l'emporte sur le bouton",
                "Tata AFTU" in carte
                and "Dakar Dem Dikk" not in carte
                and "dite à la voix, prioritaire sur le bouton" in carte,
                resultat,
            )
        finally:
            app.trouver_le_bus = ancien_trouver
        verifie(
            "changement de compagnie sans retranscription",
            not appels,
            appels,
        )

        source_app = (RACINE / "app.py").read_text(encoding="utf-8")
        verifie(
            "tutoiement dans l'interface",
            "précisez" not in source_app.lower()
            and not re.search(r"\b(vous|votre|vos)\b", source_app, re.I)
            and "Astuce : précise ton lieu" in source_app,
        )
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    return echecs, total


def test_en_ligne() -> int:
    import httpx

    echecs = 0
    cas = [(p, a) for p, a in TRAJETS] + [(p, a) for p, a in TRAJETS_EN_LIGNE]
    with httpx.Client(timeout=180) as client:
        for phrase, attendues in cas:
            nom = phrase
            debut = time.perf_counter()
            try:
                sortie = _appel(client, phrase)
                transcription, trajet, carte, _voix, mention = sortie[:5]
                # Le micro doit revenir vide dans la réponse de l'app publiée.
                micro = sortie[5] if len(sortie) > 5 else None
            except Exception as exc:
                echecs += 1
                print(f"ÉCHEC | {nom} : {exc}")
                continue
            trouvees = _lignes_dans(str(carte))
            bon = _ok(trouvees, attendues, TRAJETS_EXCLUS.get(phrase or "", frozenset()))
            bon = bon and micro is None
            echecs += not bon
            print(f"{'OK ' if bon else 'ÉCHEC'} | {nom}  ({time.perf_counter() - debut:.0f} s)")
            print(f"      entendu : {transcription!r} | {trajet} | {sorted(trouvees) or 'rien'} | micro={micro!r}")
            if mention:
                print(f"      {str(mention).splitlines()[0]}")
    return echecs


if __name__ == "__main__":
    # La console Windows (cp1252) ne sait pas afficher certains caractères (⚠️, ñ).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    en_ligne = "--en-ligne" in sys.argv
    print(f"=== Test {'de l app en ligne (' + SPACE + ')' if en_ligne else 'local'} ===\n")
    if en_ligne:
        echecs = test_en_ligne()
        total = len(TRAJETS) + len(TRAJETS_EN_LIGNE)
    else:
        echecs_partage, total_partage = test_partage()
        echecs_voix, total_voix = test_voix()
        echecs_lieux, total_lieux = test_lieux()
        echecs_alias, total_alias = test_alias_lieux()
        echecs_universite, total_universite = test_universite_fac()
        echecs_equilibre, total_equilibre = test_equilibre_compagnies()
        echecs_etudiants, total_etudiants = test_trajets_etudiants()
        echecs_proches, total_proches = test_noms_proches()
        echecs_vague, total_vague = test_arret_vague()
        echecs_prononciations, total_prononciations = test_prononciations()
        echecs_brev, total_brev = test_notebooks_brev()
        echecs_verification, total_verification = test_verification_voix()
        echecs_generiques, total_generiques = test_mots_generiques()
        echecs_distance, total_distance = test_distance_courte()
        echecs_sahm, total_sahm = test_sahm_ligne_62()
        echecs_conversation, total_conversation = test_conversation()
        echecs_moteur, total_moteur = test_moteur_v2()
        echecs_frequents, total_frequents = test_trajets_frequents()
        echecs_interface, total_interface = test_interface_micro()
        echecs_micro, total_micro = test_micro_vidage()
        echecs_securite, total_securite = test_securite()
        echecs = (
            test_local()
            + echecs_partage
            + echecs_voix
            + echecs_lieux
            + echecs_alias
            + echecs_universite
            + echecs_equilibre
            + echecs_etudiants
            + echecs_proches
            + echecs_vague
            + echecs_prononciations
            + echecs_brev
            + echecs_verification
            + echecs_generiques
            + echecs_distance
            + echecs_sahm
            + echecs_conversation
            + echecs_moteur
            + echecs_frequents
            + echecs_interface
            + echecs_micro
            + echecs_securite
        )
        # +1 « tata » jamais un lieu, +1 « siis » jamais un lieu, +1 cas compagnie réelle.
        total = (
            total_partage
            + total_voix
            + total_lieux
            + total_alias
            + total_universite
            + total_equilibre
            + total_etudiants
            + total_proches
            + total_vague
            + total_prononciations
            + total_brev
            + total_verification
            + total_generiques
            + total_distance
            + total_sahm
            + total_conversation
            + total_moteur
            + total_frequents
            + total_interface
            + total_micro
            + total_securite
            + (
                len(TRAJETS)
                + len(TRAJETS_COMPAGNIE)
                + len(TRAJETS_SANS_ARRET)
                + len(TRAJETS_SANS_MONTEE_GENERIQUE)
                + len(TRAJETS_LIEUX)
                + len(TRAJETS_QUARTIER)
                + len(TRAJETS_GEO)
                + len(TRAJETS_SANS_MONTEE_FAUSSE)
                + len(TRAJETS_SANS_MONTEE_HOMONYME)
                + len(TRAJETS_DIOUGUE)
                + len(TRAJETS_VARIANTES_SURES)
                + len(TRAJETS_MARQUEUR_ETENDU)
                + len(TRAJETS_GARDES_VARIANTES)
                + len(LIEUX_INTERDITS)
                + len(TRAJETS_CORRIGES)
                + len(TRAJETS_ASR)
                + 3
            )
        )
    print(f"\n{total - echecs}/{total} réussis")
    sys.exit(1 if echecs else 0)
