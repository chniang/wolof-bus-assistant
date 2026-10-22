r"""Vérifie que les trajets de référence trouvent la bonne ligne.

Deux modes :

    .\.venv\Scripts\python.exe tests\test_trajets.py            (local, quelques secondes)
    .\.venv\Scripts\python.exe tests\test_trajets.py --en-ligne (l'app publiée sur Hugging Face)

- local : extraction des lieux + recherche de ligne, sans micro ni GPU ni LLM.
  À lancer après chaque modification du code ou des données.
- en ligne : envoie les phrases ET les deux audios de démo à l'app publiée,
  exactement comme un visiteur. À lancer après chaque déploiement, avant de
  partager le lien.

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
    # Ligne 78 : Liberté 5 -> Golf (Guédiawaye), DIRECT. « Département de
    # Guédiawaye » compte pour Guédiawaye quand l'utilisateur dit « Guédiawaye »
    # (jamais « Dakar »), et une ligne directe passe avant une correspondance.
    ("Maa ngi Liberté 5, dama bëgg dem Guédiawaye", {"Ligne 78"}),
    ("Maa ngi Pikine, bëgg naa dem Guédiawaye", {"Ligne 37", "Ligne 41", "Ligne 46"}),
]

# Trajets qui doivent rester DIRECTS, sans correspondance proposée :
# phrase -> ligne directe attendue.
TRAJETS_DIRECTS = {
    "Maa ngi Liberté 5, dama bëgg dem Guédiawaye": "Ligne 78",
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
    ("Maa ngi Liberté 6, dama bëgg dem Médina ak Tata", {"Ligne 1"}, frozenset()),
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
    ("maa ngi liberation siis dama bëgg a dem madiina ak tata", "Tata AFTU", {"Ligne 1"}, {"Dakar Dem Dikk"}),
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

# Phrases texte envoyées en plus à l'app publiée (--en-ligne) : elles traversent
# la vraie extraction (NVIDIA) et la carte affichée, pas seulement l'extraction locale.
TRAJETS_EN_LIGNE = [
    ("Maa ngi Liberté 6, dama bëgg dem Médina ak Tata", {"Ligne 1"}),
    ("Maa ngi Sandaga, dama bëgg dem Pikine", {"Ligne 27", "Ligne 41", "Ligne 50", "Ligne 55", "Ligne 56"}),
]

AUDIOS = [
    ("data/demo_audio/trajet ouakam_palais.wav", {"Ligne 7"}),
    ("data/demo_audio/trajet liberte5_palais2.wav", {"Ligne 10", "Ligne 13"}),
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


def test_local() -> int:
    from intent.extract_intent import extract_local
    from matching.compagnie import message_autre_compagnie
    from matching.stops_matcher import StopsMatcher

    matcher = StopsMatcher()
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
            bon = bon and directe in {l["ligne"] for l in resultat["lignes"]} and not resultat["correspondances"]
        echecs += not bon
        print(f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n      {lieux.get('depart')} -> {lieux.get('arrivee')}")
        print(f"      {_detail(resultat) if (resultat['lignes'] or resultat['correspondances']) else 'rien'}")
    for phrase, compagnie, attendues, interdites in TRAJETS_COMPAGNIE:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = {l["ligne"] for l in resultat["lignes"] if l["compagnie"] == compagnie}
        exclues = {l["ligne"] for l in resultat["lignes"] if l["compagnie"] in interdites}
        bon = lieux.get("compagnie") == compagnie and _ok(trouvees, attendues, exclues)
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
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = {l["ligne"] for l in resultat["lignes"]}
        trouvees |= {"corr:" + c["etape_1"]["ligne"] for c in resultat["correspondances"]}
        bon = _ok(trouvees, attendues, exclues)
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


def test_partage() -> tuple[int, int]:
    """Le message WhatsApp : trajet direct, avec changement, aucun trajet, encodage.

    Le texte est vérifié mot pour mot : c'est lui que le contact lira, et une
    flèche ou un accent mal encodé casserait le lien wa.me.
    """
    from app.partage import LIEN_APP, bouton_partage, lien_partage, texte_partage
    from matching.stops_matcher import StopsMatcher

    matcher = StopsMatcher()
    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: str = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | partage {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    direct = matcher.find_line("Ouakam", "Palais")
    texte = texte_partage("Ouakam", "Palais", direct)
    attendu = (
        "🚌 GuindiMa : Ouakam → Palais\n"
        "Ligne 7 (Dakar Dem Dikk) : monte à Ouakam, descends à Palais 2.\n"
        f"{LIEN_APP}"
    )
    verifie("trajet direct", texte == attendu, texte)

    corr = matcher.find_line("Ngor", "Colobane")
    attendu_corr = (
        "🚌 GuindiMa : Ngor → Colobane\n"
        "1. Ligne 35 (Tata AFTU) : monte à Ngor, descends à Patte d'Oie.\n"
        "2. Ligne 48 (Tata AFTU) : monte à Patte d'Oie, descends à Colobane.\n"
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
        phrase_correspondances,
        phrase_reponse,
        voix_correspondances_depuis_cache,
        voix_depuis_cache,
    )

    matcher = StopsMatcher()
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

    une = [{"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 7"}]
    verifie(
        "1 ligne directe",
        phrase_reponse(une)
        == "Jëlal bus bu Dem Dikk, numero juróom ñaar.",
        phrase_reponse(une),
    )

    deux = [
        {"compagnie": "Tata AFTU", "ligne": "Ligne 7"},
        {"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 8"},
    ]
    verifie(
        "2 lignes directes",
        phrase_reponse(deux)
        == "Jëlal bus bu Tata, numero juróom ñaar. walla "
        "Jëlal bus bu Dem Dikk, numero juróom ñett.",
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
        phrase_reponse(taf_taf) == "Jëlal bus bu Dem Dikk, TAF TAF.",
        phrase_reponse(taf_taf),
    )
    ouakam_parcelles = matcher.find_line("Ouakam", "Parcelles")["lignes"]
    annoncees = [match["ligne"] for match in lignes_annoncees(ouakam_parcelles)]
    verifie(
        "TAF TAF annoncé quand il est affiché",
        "TAF TAF" in annoncees,
        annoncees,
    )

    suffixe = [{"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 15A"}]
    verifie(
        "suffixe de ligne (15A) dit et fichier distinct",
        phrase_reponse(suffixe)
        == "Jëlal bus bu Dem Dikk, numero fukk ak juróom A."
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
        "Almadies -> Malika : 2 changements affichés",
        len(corr) == 2,
        [(c["etape_1"]["ligne"], c["etape_2"]["ligne"]) for c in corr],
    )
    phrase_corr = phrase_correspondances(corr)
    attendu_corr = (
        "Jëlal bus bu Dem Dikk, numero 221. Ci ginnaaw, "
        "jëlal bus bu Tata, numero fanweer ak juróom ñaar. Walla, "
        "Jëlal bus bu Dem Dikk, numero 221. Ci ginnaaw, "
        "jëlal bus bu Tata, numero juróom ñaar fukk ak juróom ñeent."
    )
    verifie("voix 2 changements", phrase_corr == attendu_corr, phrase_corr)
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


def _appel(client, phrase: str, audio: Path | None) -> list:
    """Appelle l'API Gradio de l'app, comme le fait le navigateur.

    httpx est déjà installé (dépendance de huggingface_hub) : pas besoin de
    gradio_client.
    """
    import json

    fichier = None
    if audio:
        with open(audio, "rb") as f:
            envoi = client.post(f"{URL_APP}/gradio_api/upload", files={"files": (audio.name, f, "audio/wav")})
        envoi.raise_for_status()
        fichier = {"path": envoi.json()[0], "meta": {"_type": "gradio.FileData"}}
    # 3e entrée = bouton Compagnie : vide pour « Tous ». Sans elle, l'app Gradio
    # reçoit moins d'entrées que de paramètres et l'appel échoue.
    reponse = client.post(
        f"{URL_APP}/gradio_api/call/trouver_le_bus",
        json={"data": [fichier, phrase or "", ""]},
    )
    reponse.raise_for_status()
    flux = client.get(f"{URL_APP}/gradio_api/call/trouver_le_bus/{reponse.json()['event_id']}").text
    trouve = re.search(r"event: (complete|error)\ndata: (.*)", flux)
    if not trouve:
        raise RuntimeError(f"réponse inattendue : {flux[:200]}")
    if trouve.group(1) == "error":
        raise RuntimeError(f"erreur de l'app : {trouve.group(2)}")
    return json.loads(trouve.group(2))


def test_en_ligne() -> int:
    import httpx

    echecs = 0
    cas = (
        [(p, None, a) for p, a in TRAJETS]
        + [(None, RACINE / f, a) for f, a in AUDIOS]
        + [(p, None, a) for p, a in TRAJETS_EN_LIGNE]
    )
    with httpx.Client(timeout=180) as client:
        for phrase, audio, attendues in cas:
            nom = phrase or f"[audio] {audio.name}"
            debut = time.perf_counter()
            try:
                transcription, trajet, carte, _voix, mention = _appel(client, phrase, audio)
            except Exception as exc:
                echecs += 1
                print(f"ÉCHEC | {nom} : {exc}")
                continue
            trouvees = _lignes_dans(str(carte))
            bon = _ok(trouvees, attendues, TRAJETS_EXCLUS.get(phrase or "", frozenset()))
            echecs += not bon
            print(f"{'OK ' if bon else 'ÉCHEC'} | {nom}  ({time.perf_counter() - debut:.0f} s)")
            print(f"      entendu : {transcription!r} | {trajet} | {sorted(trouvees) or 'rien'}")
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
        total = len(TRAJETS) + len(AUDIOS) + len(TRAJETS_EN_LIGNE)
    else:
        echecs_partage, total_partage = test_partage()
        echecs_voix, total_voix = test_voix()
        echecs = test_local() + echecs_partage + echecs_voix
        # +1 « tata » jamais un lieu, +1 « siis » jamais un lieu, +1 cas compagnie réelle.
        total = total_partage + total_voix + (
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
    print(f"\n{total - echecs}/{total} réussis")
    sys.exit(1 if echecs else 0)
