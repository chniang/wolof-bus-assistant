r"""Vérifie que les trajets de référence trouvent la bonne ligne.

Trois modes :

    .\.venv\Scripts\python.exe tests\test_trajets.py                     (local, quelques secondes)
    .\.venv\Scripts\python.exe tests\test_trajets.py --rapport-officiel  (rapport des fiches officielles)
    .\.venv\Scripts\python.exe tests\test_trajets.py --en-ligne          (l'app publiée sur Hugging Face)

- local : extraction des lieux, recherche de ligne, interface Gradio et vidage
  du micro, sans modèle ni GPU ni LLM. À lancer après chaque modification.
- rapport-officiel : exécute `scripts/comparer_lignes_officielles.py` hors
  ligne et affiche les comptes par classe. Rapport seulement : ne fait jamais
  échouer la suite pour l'instant.
- en ligne : envoie les phrases à l'app publiée, exactement comme un visiteur.
  À lancer après chaque déploiement, avant de partager le lien.

Code de sortie : 0 si tout passe, 1 sinon ; le mode rapport sort toujours 0.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

SPACE = "PythonMindset/guindima-ai"

# Phrase (y compris telle que l'ASR l'écrit) -> lignes dont au moins une doit sortir.
# « corr: » = trajet avec changement attendu, dont le 1er bus est cette ligne.
TRAJETS = [
    ("maa ngi Liberté 6, bëgg naa dem Palais", {"Ligne 9"}),
    ("maa ngi liberti sis bëgg naa dem pale", {"Ligne 9"}),
    ("maa ngi liberti sënk bëgg naa dem pale dë", {"Ligne 10", "Ligne 13"}),
    ("Dama bëgg dem Palais, maa ngi Ouakam", {"Ligne 7"}),
    ("maa ngi wakaam dama bëgga dem pale", {"Ligne 7"}),
    ("Maa ngi Guédiawaye, dama bëgg dem Palais", {"Ligne 5", "Ligne 12"}),
    # Lot 3 : la DDD 217 est « à confirmer » ; la DDD 218 (même parcours Dépôt
    # Thiaroye -> Ouakam, itinéraire confirmé) passe devant elle.
    ("Maa ngi Thiaroye, bëgg naa dem Ouakam", {"Ligne 217", "Ligne 218"}),
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
    # Lot 2c : plus de repli silencieux sur v1. Un lieu inconnu donne la réponse
    # de v2 (aucun trajet, lieu non valide), jugée comme v1 jugeait le lieu.
    inconnu = moteur.find_line("Zzzqwx", "Colobane")
    verifie(
        "lieu inconnu de GuindiMa : aucun trajet, lieu non valide, comme v1 le jugeait",
        not inconnu["found"]
        and not inconnu["lignes"]
        and not inconnu["correspondances"]
        and inconnu["depart_valide"] is False
        and inconnu["depart_valide"] == repli.find_line("Zzzqwx", "Colobane")["depart_valide"],
        inconnu,
    )
    appels_v1 = []
    ancien_find = repli.find_line
    repli.find_line = lambda *a, **k: appels_v1.append(a) or ancien_find(*a, **k)
    try:
        for dep, arr in (("Zzzqwx", "Colobane"), ("Pikine", "AIBD"), ("Rufisque", "AIBD"), ("Ouakam", "Médina")):
            moteur.find_line(dep, arr)
    finally:
        repli.find_line = ancien_find
    verifie("jamais d'appel au moteur v1 (find_line) depuis MoteurV2", not appels_v1, appels_v1)

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
        # « bus » à l'écran ; la voix dit « biis » par le lexique (même audio).
        "liggeey": "Sama liggéey mooy won nit ñi bus bi ñuy jël ci Ndakaaru.",
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
    « Hann Bel Air » n'a pas d'arrêt à son nom : un usager natif le place à
    côté de Hann Maristes, près de Colobane, donc même arrêt « Maristes »,
    jamais les « Rocade Fann Bel-Air » de Fann.
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

    for forme in (
        "hane belair", "hann bel air", "anne bel air", "hann belair", "hane bel air",
        "Hann Bel-Air",
    ):
        bel_air = extract_local(f"Maa ngi {forme}, bëgg naa dem Colobane")
        verifie(
            f"« {forme} » -> Maristes (à côté de Hann Maristes)",
            bel_air.get("depart") == "Maristes" and bel_air.get("arrivee") == "Colobane",
            bel_air,
        )
        verifie(f"alias matcher : « {forme} » vaut « Maristes »", score(forme, "Maristes") == 1.0)
    verifie(
        "alias matcher : « Hann Bel Air » ne vaut jamais « Rocade Fann Bel Air »",
        score("Hann Bel Air", "Rocade Fann Bel Air") == 0.0,
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


def test_unite_15() -> tuple[int, int]:
    """« Unité 15 » des Parcelles est reconnu, mais seul, et au chiffre près.

    L'arrêt existe (Tata 80, position « bonne ») ; les noms « Unité … » restaient
    hors de LIEUX. On ne remet que celui-là, nom exact : « Unité 1 » et
    « Unité 5 » ne doivent jamais tomber dessus par ressemblance.
    """
    from intent.extract_intent import extract_local

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | unité 15 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    for phrase in ("Maa ngi Unité 15, bëgg naa dem Liberté 5", "maa ngi unite 15 bëgg naa dem Liberté 5"):
        lieux = extract_local(phrase)
        verifie(
            f"« {phrase} » -> départ Unité 15",
            lieux.get("depart") == "Unité 15" and lieux.get("arrivee") == "Liberté 5",
            lieux,
        )
    for numero in ("1", "5", "10", "16"):
        lieux = extract_local(f"Maa ngi Unité {numero}, bëgg naa dem Médina")
        verifie(
            f"« Unité {numero} » ne devient jamais Unité 15",
            lieux.get("depart") != "Unité 15" and lieux.get("arrivee") == "Médina",
            lieux,
        )
    lieux = extract_local("Maa ngi Parcelles Unité 15, bëgg naa dem Colobane")
    verifie(
        "deux lieux avant « dem » : l'arrivée reste Colobane",
        lieux.get("arrivee") == "Colobane",
        lieux,
    )
    resultat = _matcher_hors_ligne().find_line("Unité 15", "Liberté 5")
    verifie(
        "Unité 15 -> Liberté 5 : un trajet, la Tata 80 part de l'arrêt Unité 15",
        any(
            c["etape_1"]["ligne"] == "Ligne 80" and c["etape_1"]["monte_a"] == "Unité 15"
            for c in resultat.get("correspondances") or []
        )
        or any(l["monte_a"] == "Unité 15" for l in resultat.get("lignes") or []),
        _detail(resultat),
    )
    return echecs, total


def test_vague_voix_partage() -> tuple[int, int]:
    """Arrêt lointain (> 600 m) : ni la voix ni WhatsApp ne le nomment.

    WhatsApp écrit le lieu dit et « cherche l'arrêt de la ligne N le plus
    proche ». La voix dit le lieu nommé par l'usager (« moo lay yóbbu ba
    Rufisque ») avec les WAV déjà là ; sans WAV pour ce lieu, elle se tait sur
    ce morceau, sans rien synthétiser.
    """
    import tempfile
    import wave as _wave

    from app.partage import texte_partage
    import tts.speak as speak

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | vague voix/partage {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    ligne = {
        "ligne": "Ligne 62", "compagnie": "Tata AFTU",
        "monte_a": "UCAD", "descend_a": "Fass Rufisque",
        "monte_a_vague": False, "descend_a_vague": True,
    }
    texte = texte_partage("UCAD", "Rufisque", {"lignes": [ligne]})
    verifie(
        "WhatsApp direct : lieu dit + conseil, jamais l'arrêt lointain",
        "descends à Rufisque (cherche l'arrêt de la ligne 62 le plus proche)" in texte
        and "Fass Rufisque" not in texte
        and "monte à UCAD" in texte,
        texte,
    )
    corr = {
        "etape_1": {
            "ligne": "Ligne 40", "compagnie": "Tata AFTU", "monte_a": "Keur Ngoor",
            "descend_a": "Colobane", "monte_a_vague": True,
        },
        "etape_2": {
            "ligne": "Ligne 62", "compagnie": "Tata AFTU", "monte_a": "Colobane",
            "descend_a": "Fass Rufisque", "descend_a_vague": True,
        },
    }
    texte = texte_partage("Maristes", "Rufisque", {"correspondances": [corr]})
    verifie(
        "WhatsApp changement : bouts vagues remplacés, le changement reste nommé",
        "monte à Maristes (cherche l'arrêt de la ligne 40 le plus proche)" in texte
        and "descends à Rufisque (cherche l'arrêt de la ligne 62 le plus proche)" in texte
        and "Keur Ngoor" not in texte
        and "Fass Rufisque" not in texte
        and "Colobane" in texte,
        texte,
    )
    ligne_sure = {**ligne, "descend_a_vague": False}
    verifie(
        "WhatsApp : arrêt proche toujours nommé",
        "descends à Fass Rufisque." in texte_partage("UCAD", "Rufisque", {"lignes": [ligne_sure]}),
    )

    verifie(
        "voix : descente vague -> lieu dit",
        speak.descente_dite({"descend_a": "Fass Rufisque", "descend_a_vague": True,
                             "lieu_arrivee_dit": "Rufisque"}) == "Rufisque",
    )
    verifie(
        "voix : descente proche -> arrêt",
        speak.descente_dite({"descend_a": "Fass Rufisque", "lieu_arrivee_dit": "Rufisque"})
        == "Fass Rufisque",
    )

    # Un petit cache factice : le bus, les connecteurs, mais aucun WAV de lieu.
    with tempfile.TemporaryDirectory() as dossier_tmp:
        dossier = Path(dossier_tmp)
        etape_1 = {**corr["etape_1"]}
        etape_2 = {**corr["etape_2"], "lieu_arrivee_dit": "Rufisque"}
        for nom in (
            speak.nom_cache_match(etape_1), speak.nom_cache_match(etape_2),
            speak.NGA_WACC, speak.LIAISON_CORRESPONDANCE, speak.MOO_LAY_YOBBU_BA,
        ):
            with _wave.open(str(dossier / nom), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 160)
        trajet_2 = {"etapes": [etape_1, etape_2], "changements": ["Colobane"]}
        plan = speak.plan_trajet_2(trajet_2, dossier)
        noms = [chemin.name for chemin, _ in plan]
        verifie(
            "voix 2 changements : lieu dit sans WAV -> « moo lay yóbbu ba » tu, jamais l'arrêt lointain",
            speak.MOO_LAY_YOBBU_BA not in noms
            and speak.nom_fichier_lieu("Fass Rufisque") not in noms,
            noms,
        )
        plan_c = speak.plan_correspondance({"etape_1": etape_1, "etape_2": etape_2}, dossier)
        noms_c = [chemin.name for chemin, _ in plan_c]
        verifie(
            "voix changement : jamais l'arrêt lointain",
            speak.nom_fichier_lieu("Fass Rufisque") not in noms_c,
            noms_c,
        )
        lieu_dit = speak.chemin_lieu(dossier, "Rufisque")
        with _wave.open(str(dossier / lieu_dit.name), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 160)
        noms = [chemin.name for chemin, _ in speak.plan_trajet_2(trajet_2, dossier)]
        verifie(
            "voix : WAV du lieu dit présent -> « moo lay yóbbu ba Rufisque »",
            noms[-2:] == [speak.MOO_LAY_YOBBU_BA, lieu_dit.name],
            noms,
        )

    # Le vrai moteur porte le lieu dit sur la descente.
    resultat = _matcher_hors_ligne().find_line("UCAD", "Rufisque")
    etapes_fin = [l for l in resultat.get("lignes") or []] + [
        c["etape_2"] for c in resultat.get("correspondances") or []
    ]
    verifie(
        "moteur : chaque descente porte le lieu dit",
        bool(etapes_fin) and all(e.get("lieu_arrivee_dit") == "Rufisque" for e in etapes_fin),
        _detail(resultat),
    )
    return echecs, total


def test_vie_privee() -> tuple[int, int]:
    """L'audio de l'usager est effacé dès qu'il est décodé ; la note est affichée.

    Seuls les fichiers du dossier temporaire de Gradio sont effacés : un audio
    pris ailleurs (data/demo_audio/, data/collecte/) n'est jamais touché.
    """
    import os
    import shutil
    import tempfile
    import wave as _wave

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_vie_privee")

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | vie privée {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    def petit_wav(chemin: Path) -> None:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with _wave.open(str(chemin), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 800)  # 0,05 s : trop court, rien à chercher

    dossier_gradio = Path(tempfile.gettempdir()) / "gradio" / "test_guindima_vie_privee"
    recu = dossier_gradio / "micro.wav"
    petit_wav(recu)
    try:
        app.trouver_le_bus(str(recu), "", "")
        verifie("audio reçu par Gradio : effacé après décodage", not recu.exists())
    finally:
        shutil.rmtree(dossier_gradio, ignore_errors=True)

    ailleurs = Path(tempfile.mkdtemp(prefix="guindima_hors_gradio_")) / "garde.wav"
    petit_wav(ailleurs)
    try:
        app.trouver_le_bus(str(ailleurs), "", "")
        verifie("audio hors du dossier Gradio : jamais effacé", ailleurs.exists())
        verifie("effacement refusé hors Gradio", app._effacer_audio_recu(str(ailleurs)) is False)
    finally:
        shutil.rmtree(ailleurs.parent, ignore_errors=True)
    verifie("rien à effacer sans audio", app._effacer_audio_recu(None) is False)

    source = (RACINE / "app.py").read_text(encoding="utf-8")
    verifie(
        "note sous la saisie, mot pour mot",
        app.NOTE_VIE_PRIVEE
        == "Ta voix n'est pas enregistrée. Pour comprendre ton trajet, le texte peut "
        "être envoyé à un service d'IA (NVIDIA) et les noms de lieux à OpenStreetMap."
        and "NOTE_VIE_PRIVEE}" in source,
    )
    verifie("Gradio vide son cache (delete_cache)", "delete_cache=(600, 600)" in source)
    return echecs, total


def test_correspondances_coherentes() -> tuple[int, int]:
    """Un changement de bus que l'usager peut vraiment faire.

    Retour du terrain, Maristes -> Rufisque : descendre à Bountou Pikine puis
    monter à « Péage » (position devinée), changer à Marché Colobane Rufisque
    (déjà Rufisque) pour un 3e bus parti de ZAC Mbao (en arrière), un tronçon
    RN1 -> Marché Colobane Rufisque en 7 min. Règles vérifiées sur 6 trajets :
    - le bus suivant part du même arrêt, ou d'un arrêt à 400 m au plus, et une
      marche n'existe qu'entre deux positions mesurées ;
    - jamais un changement dans le lieu d'arrivée (ni dans le lieu de départ) ;
    - jamais de recul de plus de 1 km vers le départ ;
    - un tronçon n'est jamais plus court que la ligne droite à la vitesse du bus.
    """
    from routing import adapter
    from routing.network import (
        MAX_TRANSFER_WALK_M,
        SPEED_BY_COMPANY_M_PER_MIN,
        WALK_SPEED_M_PER_MIN,
        haversine_m,
    )

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | changements {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    reseau = adapter._NETWORK
    verifie("marche entre deux bus : 400 m au plus", MAX_TRANSFER_WALK_M <= 400)

    def ligne_de(etape: dict):
        return reseau.lines.get((etape["compagnie"], etape["ligne"]))

    def position(etape: dict, arret: str, sure: bool):
        ligne = ligne_de(etape)
        if ligne is None or arret not in ligne.stops:
            return None
        index = ligne.stops.index(arret)
        if sure and not reseau.position_sure(ligne, index):
            return None
        return reseau.position_on_line(ligne, index)

    def etapes_de(trajet: dict) -> list[dict]:
        return trajet.get("etapes") or [trajet["etape_1"], trajet["etape_2"]]

    matcher = _matcher_hors_ligne()
    cas = (
        ("Maristes", "Rufisque"),
        ("Médina", "Malika"),
        ("Fann", "Yeumbeul"),
        ("Point E", "Yeumbeul"),
        ("Mermoz", "Malika"),
        ("Almadies", "Rufisque"),
    )
    for dep, arr in cas:
        resultat = matcher.find_line(dep, arr)
        trajets = (resultat.get("correspondances") or []) + (resultat.get("trajets_2") or [])
        verifie(f"{dep} -> {arr} : au moins un trajet avec changement", bool(trajets), _detail(resultat))
        lieu_arr = adapter._resoudre(matcher._repli, arr)
        lieu_dep = adapter._resoudre(matcher._repli, dep)
        for trajet in trajets:
            etapes = etapes_de(trajet)
            marches = trajet.get("marches") or [0] * (len(etapes) - 1)
            resume = " | ".join(
                f"{e['ligne']} {e['monte_a_reseau']} -> {e['descend_a_reseau']} ({e.get('minutes')} min)"
                for e in etapes
            )
            for n in range(1, len(etapes)):
                avant, apres = etapes[n - 1], etapes[n]
                marche = marches[n - 1] if n - 1 < len(marches) else 0
                meme = avant["descend_a_reseau"] == apres["monte_a_reseau"]
                if not meme and marche:
                    a = position(avant, avant["descend_a_reseau"], sure=True)
                    b = position(apres, apres["monte_a_reseau"], sure=True)
                    ok = (
                        a is not None
                        and b is not None
                        and haversine_m(a, b) <= MAX_TRANSFER_WALK_M + 1
                        and marche <= MAX_TRANSFER_WALK_M / WALK_SPEED_M_PER_MIN + 1
                    )
                else:
                    ok = marche <= MAX_TRANSFER_WALK_M / WALK_SPEED_M_PER_MIN + 1
                verifie(f"{dep} -> {arr} : changement {n} faisable à pied", ok, (resume, marches))
                verifie(
                    f"{dep} -> {arr} : changement {n} hors du lieu d'arrivée",
                    avant["descend_a_reseau"] not in lieu_arr["nom_exact"]
                    and avant["descend_a_reseau"] not in lieu_arr["par_son_nom"],
                    resume,
                )
                verifie(
                    f"{dep} -> {arr} : bus {n + 1} ne repart pas du lieu de départ",
                    apres["monte_a_reseau"] not in lieu_dep["nom_exact"]
                    and apres["monte_a_reseau"] not in lieu_dep["par_son_nom"],
                    resume,
                )
            cible = lieu_arr["point_sur"]
            if cible is not None:
                precedent = lieu_dep["point_sur"]
                for etape in etapes[1:]:
                    ici = position(etape, etape["monte_a_reseau"], sure=False)
                    if ici is None:
                        continue
                    if precedent is not None:
                        verifie(
                            f"{dep} -> {arr} : jamais en arrière ({etape['monte_a_reseau']})",
                            haversine_m(ici, cible) <= haversine_m(precedent, cible) + adapter.RECUL_MAX_M,
                            resume,
                        )
                    precedent = ici
            for etape in etapes:
                a = position(etape, etape["monte_a_reseau"], sure=True)
                b = position(etape, etape["descend_a_reseau"], sure=True)
                if a is None or b is None or etape.get("minutes") is None:
                    continue
                vitesse = SPEED_BY_COMPANY_M_PER_MIN.get(etape["compagnie"], max(SPEED_BY_COMPANY_M_PER_MIN.values()))
                verifie(
                    f"{dep} -> {arr} : {etape['ligne']} pas plus court que la ligne droite",
                    etape["minutes"] + 1 >= haversine_m(a, b) / vitesse,
                    (resume, int(haversine_m(a, b))),
                )

    # Le cas exact du terrain.
    resultat = matcher.find_line("Maristes", "Rufisque")
    trajets = (resultat.get("correspondances") or []) + (resultat.get("trajets_2") or [])
    montees = [e["monte_a_reseau"] for t in trajets for e in etapes_de(t)[1:]]
    descentes = [e["descend_a_reseau"] for t in trajets for e in etapes_de(t)[:-1]]
    verifie("Maristes -> Rufisque : jamais « Péage » après Bountou Pikine",
            not any(m.lower() == "péage" for m in montees), montees)
    verifie("Maristes -> Rufisque : jamais ZAC Mbao ni 3e bus après Marché Colobane Rufisque",
            "ZAC Mbao" not in montees and "Marché Colobane Rufisque" not in descentes, (montees, descentes))
    verifie("Maristes -> Rufisque : jamais le détour par Liberté 6",
            not any("Liberté 6" in m for m in montees), montees)

    # Les positions devinées ne portent jamais une marche.
    l57 = reseau.lines[("Tata AFTU", "Ligne 57")]
    l213 = reseau.lines[("Dakar Dem Dikk", "Ligne 213")]
    verifie("Tata 57 : Marché Colobane Rufisque a une position devinée",
            not reseau.position_sure(l57, l57.stops.index("Marché Colobane Rufisque")))
    verifie("Dem Dikk 213 : « péage » a une position devinée",
            not reseau.position_sure(l213, l213.stops.index("péage")))
    return echecs, total


def test_titres_markdown() -> tuple[int, int]:
    """Les titres de section ne s'affichent jamais avec leurs « ### ».

    Collé à la carte précédente (« </div>### … »), le Markdown restait dans le
    bloc HTML : l'usager voyait « ### Pas de bus direct … ».
    """
    import os as _os

    _os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_titres")
    from app.cartes import titre_section

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | titres {nom}")
        if not condition and detail:
            print(f"      {str(detail)[:300]!r}")

    matcher = _matcher_hors_ligne()
    for dep, arr, titre in (
        ("Maristes", "Rufisque", "Pas de bus direct"),
        ("Fann", "Yeumbeul", "Avec deux changements"),
    ):
        carte = app._carte(matcher.find_line(dep, arr), dep, arr)
        verifie(f"{dep} -> {arr} : titre « {titre} » présent, sans « ### »",
                titre in carte and "###" not in carte, carte)
    verifie("titre_section : HTML, texte échappé",
            titre_section("a < b").startswith("<div") and "a &lt; b" in titre_section("a < b"))
    return echecs, total


def test_yoff_tata_2() -> tuple[int, int]:
    """La Tata 2 ne passe pas à Yoff : jamais proposée pour Yoff.

    Trace officielle AFTU : 1,7 km de Yoff Village au plus près, 2,2 km de
    l'arrêt Yoff. Elle sortait par « Route HLM Grand Médine », pris dans la
    commune de Yoff, et parce que lieux_geo.csv pose « Yoff » sur Grand Yoff.
    Petersen reste proposé pour Sandaga (marché à 750 m).
    """
    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | yoff tata 2 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    matcher = _matcher_hors_ligne()
    for dep, arr in (("Yoff", "Petersen"), ("Petersen", "Yoff"), ("Yoff", "Médina"), ("Yoff", "Colobane")):
        resultat = matcher.find_line(dep, arr)
        lignes = {
            (t["compagnie"], t["ligne"]) for t in resultat.get("lignes") or []
        } | {
            (e["compagnie"], e["ligne"])
            for c in resultat.get("correspondances") or []
            for e in (c["etape_1"], c["etape_2"])
        }
        montees = {t["monte_a_reseau"] for t in resultat.get("lignes") or []}
        verifie(f"{dep} -> {arr} : jamais la Tata 2", ("Tata AFTU", "Ligne 2") not in lignes, _detail(resultat))
        verifie(f"{dep} -> {arr} : jamais monté à Route HLM Grand Médine ni à la Foire",
                not montees & {"Route HLM Grand Médine", "Foire", "HLM Grand Yoff"}, _detail(resultat))
    resultat = matcher.find_line("Sandaga", "Pikine")
    verifie("Sandaga -> Pikine : Petersen (Tata 55/56) toujours proposé",
            {"Ligne 55", "Ligne 56"} & {t["ligne"] for t in resultat["lignes"]}, _detail(resultat))
    return echecs, total


def test_noms_lot_1() -> tuple[int, int]:
    """Lot 1 des noms (audit du 12/11/2026, data/audit/fiabilite_rapport.md).

    - « Colobane » seul est la gare de Dakar ; les arrêts de Rufisque (Tata 57
      « Marché Colobane Rufisque », Tata 74 « Colobane Rufisque ») seulement
      pour « Colobane Rufisque ». Tata 60 (Colobane -> Rufisque) envoyait à
      Rufisque en 14 min.
    - L'aéroport Blaise Diagne (AIBD) sous tous ses noms, jamais l'ancien
      aéroport de Yoff (LSS) ni l'avenue ou le lycée Blaise Diagne.
    - Chiffres romains : « Liberté VI » = « Liberté 6 » (Sicap, HLM, Grand Yoff).
    - Noms à parenthèses : chaque partie désigne le lieu.
    - Arrêts AFTU nommés d'après une rue, reliés à leur lieu seulement quand
      c'est sûr (data/corrections/lieux_arrets_aftu.csv).
    """
    import csv

    from intent.extract_intent import extract_local
    from matching.lieux import LIENS_AFTU, NOTE_ARRET_RELIE, jetons, nom_exact, parties, score

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | noms lot 1 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    def lignes(resultat: dict) -> set[tuple[str, str]]:
        return {(t["compagnie"], t["ligne"]) for t in resultat.get("lignes") or []} | {
            (e["compagnie"], e["ligne"])
            for c in resultat.get("correspondances") or []
            for e in (c["etape_1"], c["etape_2"])
        }

    def arrets(resultat: dict) -> set[str]:
        etapes = list(resultat.get("lignes") or []) + [
            e for c in resultat.get("correspondances") or [] for e in (c["etape_1"], c["etape_2"])
        ]
        return {
            nom
            for e in etapes
            for nom in (e["monte_a"], e["descend_a"], e.get("monte_a_reseau", ""), e.get("descend_a_reseau", ""))
            if nom
        }

    tata = {"Tata AFTU"}
    matcher = _matcher_hors_ligne()

    # ---------------------------------------------------------------- Colobane
    for arret in ("Marché Colobane Rufisque", "Colobane Rufisque", "MARCHE COLOBANE RUFISQUE"):
        verifie(f"« Colobane » ne vaut jamais « {arret} »", score("Colobane", arret) == 0.0, score("Colobane", arret))
        verifie(f"« Colobane Rufisque » trouve « {arret} »", score("Colobane Rufisque", arret) >= 0.8,
                score("Colobane Rufisque", arret))
    verifie("« Colobane Rufisque » ne vaut pas la gare de Colobane (Dakar)",
            score("Colobane Rufisque", "Gare de Colobane") == 0.0)
    verifie("« Rufisque » garde ses arrêts de Colobane Gouye Mouride",
            score("Rufisque", "Marché Colobane Rufisque") >= 0.6)
    lieux = extract_local("maa ngi Colobane Rufisque bëgg naa dem Thiaroye")
    verifie("phrase « maa ngi Colobane Rufisque » -> Colobane Rufisque", lieux.get("depart") == "Colobane Rufisque", lieux)
    rufisque_colobane = {"Marché Colobane Rufisque", "Colobane Rufisque"}
    for dep, arr in (("Colobane", "Rufisque"), ("Thiaroye", "Colobane"), ("Pikine", "Colobane")):
        for filtre in (None, tata):
            resultat = matcher.find_line(dep, arr, filtre)
            verifie(f"{dep} -> {arr} ({'Tata' if filtre else 'Tous'}) : jamais un arrêt Colobane de Rufisque",
                    not arrets(resultat) & rufisque_colobane, _detail(resultat))
    resultat = matcher.find_line("Colobane", "Rufisque", tata)
    verifie("Colobane -> Rufisque (Tata) : la Tata 60 de la fiche AFTU est proposée",
            ("Tata AFTU", "Ligne 60") in lignes(resultat), _detail(resultat))
    resultat = matcher.find_line("Colobane Rufisque", "Thiaroye")
    verifie("Colobane Rufisque -> Thiaroye : monte à Rufisque (Tata 57)",
            ("Tata AFTU", "Ligne 57") in lignes(resultat) and bool(arrets(resultat) & rufisque_colobane),
            _detail(resultat))

    # ---------------------------------------------------------------- AIBD
    # « aéroport » seul n'est plus l'AIBD (lot 2a, test_aeroport_ambigu) : seuls
    # les noms précis y mènent.
    for nom in ("aéroport Blaise Diagne", "Aéroport AIBD", "Blaise Diagne", "AIBD",
                "aéroport de Diass", "Diass", "Aéroport international Blaise Diagne"):
        verifie(f"« {nom} » -> AIBD", score(nom, "AIBD") == 1.0, score(nom, "AIBD"))
        for arret in ("Aéroport", "Aéroport LSS", "Aéroport L S Senghor", "Avenue Blaise Diagne",
                      "Av Blaise Diagne", "Lycée Blaise Diagne", "Blaise Diagne"):
            verifie(f"« {nom} » ne vaut jamais « {arret} »", score(nom, arret) == 0.0, score(nom, arret))
    # Côté arrêt, rien ne change : « Blaise Diagne » (Dem Dikk 11, avenue de la
    # Médina) et « Aéroport » (Tata 35, Yoff) gardent leur nom.
    verifie("l'arrêt « Blaise Diagne » reste l'avenue", jetons("Blaise Diagne") == ["blaise", "diagne"])
    verifie("l'arrêt « Aéroport » reste l'aéroport de Yoff", score("Aéroport LSS", "Aéroport") == 1.0)
    verifie("« Avenue Blaise Diagne » reste l'avenue",
            score("Avenue Blaise Diagne", "Avenue Blaise Diagne") == 1.0 and score("Avenue Blaise Diagne", "AIBD") == 0.0)
    for forme_dite in ("aéroport Blaise Diagne", "Diass", "aéroport de Diass",
                       "Blaise Diagne", "AIBD", "l'aéroport international Blaise Diagne"):
        lieux = extract_local(f"maa ngi Ouakam bëgg naa dem {forme_dite}")
        verifie(f"phrase « dem {forme_dite} » -> AIBD",
                lieux.get("depart") == "Ouakam" and lieux.get("arrivee") == "AIBD", lieux)
    for forme_dite in ("aéroport LSS", "aéroport Léopold Sédar Senghor", "aéroport de Yoff"):
        lieux = extract_local(f"maa ngi Pikine bëgg naa dem {forme_dite}")
        verifie(f"phrase « dem {forme_dite} » -> l'ancien aéroport, jamais l'AIBD",
                lieux.get("arrivee") == "Aéroport LSS", lieux)
    lieux = extract_local("maa ngi Pikine bëgg naa dem Avenue Blaise Diagne")
    verifie("phrase « Avenue Blaise Diagne » reste l'avenue", lieux.get("arrivee") == "Avenue Blaise Diagne", lieux)
    for dep in ("Ouakam", "Yoff", "Liberté 6", "Grand Yoff"):
        resultat = matcher.find_line(dep, "aéroport Blaise Diagne")
        verifie(f"{dep} -> aéroport Blaise Diagne : TAF TAF jusqu'à l'AIBD",
                ("Dakar Dem Dikk", "TAF TAF") in lignes(resultat) and "AIBD" in arrets(resultat), _detail(resultat))
        verifie(f"{dep} -> aéroport Blaise Diagne : aucune Tata (aucune ne dessert l'AIBD)",
                not any(c == "Tata AFTU" for c, _ in lignes(resultat)), _detail(resultat))
        verifie(f"{dep} -> aéroport Blaise Diagne : jamais à pied", not resultat.get("a_pied"), resultat.get("a_pied"))
    resultat = matcher.find_line("Pikine", "Aéroport LSS")
    verifie("Pikine -> Aéroport LSS : toujours l'aéroport de Yoff, jamais l'AIBD",
            resultat["found"] and "AIBD" not in arrets(resultat), _detail(resultat))

    # ---------------------------------------------------------------- chiffres romains
    for romain, arabe in (("Liberté VI", "Liberté 6"), ("Liberté V", "Liberté 5"), ("Sicap Liberté VI", "Liberté 6"),
                          ("HLM V", "HLM 5"), ("Grand Yoff II", "Grand Yoff 2"), ("Sicap IV", "Sicap 4")):
        verifie(f"« {romain} » = « {arabe} »", jetons(romain) == jetons(arabe), (jetons(romain), jetons(arabe)))
    verifie("« Liberté 6 » trouve « Giratoire de Liberté VI » (Tata 1)",
            score("Liberté 6", "Giratoire de Liberté VI") == 1.0)
    for phrase, attendu in (("maa ngi Lat Dior bëgg naa dem Liberté VI", "Liberté 6"),
                            ("maa ngi Liberté V bëgg naa dem Palais", "Liberté 5"),
                            ("maa ngi Sicap Liberté VI bëgg naa dem Médina", "Liberté 6")):
        lieux = extract_local(phrase)
        verifie(f"phrase « {phrase} » -> {attendu}", attendu in (lieux.get("depart"), lieux.get("arrivee")), lieux)

    # ---------------------------------------------------------------- parenthèses
    verifie("parties de « Liberté 5 (Dieuppeul) »",
            parties("Liberté 5 (Dieuppeul)") == ("Liberté 5 (Dieuppeul)", "Liberté 5", "Dieuppeul"))
    for nom, arret in (("Liberté 5 (Dieuppeul)", "Liberté 5"), ("Liberté 5 (Dieuppeul)", "Dieuppeul"),
                       ("Liberté 5 (Dieuppeul)", "Terminus Liberté 5 (Dieuppeul)"),
                       ("Médina (Gueule Tapée)", "Médina"), ("Médina (Gueule Tapée)", "Gueule Tapée")):
        verifie(f"« {nom} » trouve « {arret} »", score(nom, arret) == 1.0, score(nom, arret))
    # La virgule ne sépare pas : « HLM » seul est un autre quartier que HLM Grand Yoff.
    verifie("« Grand Yoff (HLM, stade LSS) » ne vaut pas l'arrêt « HLM »",
            score("Grand Yoff (HLM, stade LSS)", "HLM") == 0.0)
    verifie("« Grand Yoff (HLM, stade LSS) » vaut Grand Yoff", score("Grand Yoff (HLM, stade LSS)", "Grand Yoff") == 1.0)
    resultat = matcher.find_line("Liberté 5 (Dieuppeul)", "UCAD")
    verifie("Liberté 5 (Dieuppeul) -> UCAD : monte à Liberté 5 / Dieuppeul, plus à Stade Demba Diop",
            bool(resultat["lignes"]) and all("Demba Diop" not in t["monte_a"] for t in resultat["lignes"]),
            _detail(resultat))
    resultat = matcher.find_line("Médina (Gueule Tapée)", "Parcelles (HLM Grand Médine)", tata)
    verifie("Médina (Gueule Tapée) -> Parcelles (HLM Grand Médine) (Tata) : la Tata 1 de la fiche AFTU",
            ("Tata AFTU", "Ligne 1") in lignes(resultat), _detail(resultat))

    # ---------------------------------------------------------------- arrêts AFTU reliés
    with open(RACINE / "data" / "reference" / "arrets_toutes_lignes_aftu.csv", encoding="utf-8-sig", newline="") as f:
        noms_aftu = {nom_exact(r["arret"]) for r in csv.DictReader(f)}
    with open(RACINE / "data" / "corrections" / "lieux_arrets_aftu.csv", encoding="utf-8-sig", newline="") as f:
        liens = list(csv.DictReader(f))
    verifie(f"{len(liens)} liens AFTU, chacun avec une source", bool(liens) and all(r["source"].strip() for r in liens))
    for r in liens:
        verifie(f"lien « {r['arret_aftu']} » : nom exact d'une fiche AFTU", nom_exact(r["arret_aftu"]) in noms_aftu)
        verifie(f"lien « {r['arret_aftu']} » -> {r['lieu']} chargé",
                r["lieu"] in LIENS_AFTU.get(nom_exact(r["arret_aftu"]), ()))
    for lieu, arret in (("UCAD", "Avenue Cheikh Anta Diop"), ("UCAD", "Avenue Cheikh Antadiop"),
                        ("Parcelles Assainies", "Route Principale des Parcelles Assainies"),
                        ("Parcelles Assainies", "Route du Marché des Parcelles Assainies"),
                        ("HLM Grand Médine", "Rte Corniche de HLM Gd Médine"),
                        ("Gueule Tapée", "Boulevard de la Gueule Tapée")):
        verifie(f"« {lieu} » trouve l'arrêt relié « {arret} », après un nom exact",
                score(lieu, arret) == NOTE_ARRET_RELIE, score(lieu, arret))
    # « AV CHEIKH ANTA DIOP » : Tata 42 côté Ouakam, Tata 47 incertaine. Pas relié.
    verifie("« UCAD » ne vaut jamais « Av Cheikh Anta Diop » (Tata 42, Ouakam)",
            score("UCAD", "Av Cheikh Anta Diop") == 0.0)
    resultat = matcher.find_line("Yoff", "UCAD", tata)
    verifie("Yoff -> UCAD (Tata) : Tata 4 directe, par Avenue Cheikh Anta Diop",
            ("Tata AFTU", "Ligne 4") in {(t["compagnie"], t["ligne"]) for t in resultat["lignes"]}, _detail(resultat))
    resultat = matcher.find_line("Parcelles Assainies", "Petersen", tata)
    verifie("Parcelles Assainies -> Petersen (Tata) : Tata 2 de la fiche AFTU",
            ("Tata AFTU", "Ligne 2") in lignes(resultat), _detail(resultat))
    for dep in ("Parcelles Assainies", "Guédiawaye", "Aéroport LSS"):
        resultat = matcher.find_line(dep, "UCAD")
        verifie(f"{dep} -> UCAD : jamais la Tata 42 ni la 47 (« Av Cheikh Anta Diop », non reliée)",
                not lignes(resultat) & {("Tata AFTU", "Ligne 42"), ("Tata AFTU", "Ligne 47")}, _detail(resultat))
    resultat = matcher.find_line("Parcelles Assainies", "UCAD", tata)
    verifie("Parcelles Assainies -> UCAD (Tata) : la Tata 38 reste proposée à côté de la 25",
            ("Tata AFTU", "Ligne 38") in lignes(resultat), _detail(resultat))

    # ---------------------------------------------------------------- Guédiawaye
    resultat = matcher.find_line("Guédiawaye", "Colobane", tata)
    montees = {t["monte_a"] for t in resultat["lignes"]}
    verifie("Guédiawaye -> Colobane (Tata) : monte dans Guédiawaye, jamais au Garage Guédiawaye (Dakar)",
            bool(montees) and not any("Garage" in m for m in montees), _detail(resultat))
    verifie("« Guédiawaye » trouve « Gadaye (Guédiawaye) », terminus de la Tata 30",
            score("Guédiawaye", "Gadaye (Guédiawaye)") >= 0.6)
    verifie("« Guédiawaye » ne vaut jamais « Garage Guédiawaye »", score("Guédiawaye", "Garage Guédiawaye") == 0.0)
    return echecs, total


def test_aeroport_ambigu() -> tuple[int, int]:
    """Lot 2a : « aéroport » seul est ambigu à Dakar, on propose les deux.

    L'AIBD (Diass) et l'ancien aéroport Léopold Sédar Senghor (Yoff, arrêt
    « Aéroport » de la Tata 35) : deviner serait répondre faux une fois sur
    deux. Les noms précis vont droit au bon aéroport. La voix n'utilise que des
    segments existants (« moo lay yóbbu ba » + lieu_aibd / lieu_aeroport_lss,
    « Walla, » entre les deux).
    """
    import os

    import tts.speak as speak
    from intent.extract_intent import extract_local
    from matching.lieux import AEROPORT_LSS, AIBD, aeroport_ambigu, score

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | aéroport ambigu {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # ------------------------------------------------------------ les noms
    for forme in ("aéroport", "Aéroport", "aeroport", "earoport", "ayeropoor", "aéroport international"):
        verifie(f"« {forme} » seul est ambigu", aeroport_ambigu(forme))
        verifie(f"« {forme} » seul ne vaut plus directement l'AIBD", score(forme, "AIBD") == 0.0)
    for forme in ("aéroport Blaise Diagne", "Blaise Diagne", "AIBD", "Diass", "aéroport de Diass",
                  "aéroport Yoff", "aéroport Senghor", "Léopold Sédar Senghor", "LSS", "Aéroport LSS"):
        verifie(f"« {forme} » n'est pas ambigu", not aeroport_ambigu(forme))
    for forme in ("aéroport Yoff", "aéroport de Yoff", "aéroport Senghor", "Léopold Sédar Senghor", "LSS",
                  "aéroport LSS", "aéroport Léopold Sédar Senghor"):
        verifie(f"« {forme} » -> ancien aéroport de Yoff", score(forme, "Aéroport LSS") == 1.0
                and score(forme, "Aéroport") == 1.0, (score(forme, "Aéroport LSS"), score(forme, "Aéroport")))
        verifie(f"« {forme} » ne vaut jamais l'AIBD", score(forme, "AIBD") == 0.0)
    for forme in ("aéroport Blaise Diagne", "Blaise Diagne", "AIBD", "Diass"):
        verifie(f"« {forme} » ne vaut jamais l'ancien aéroport", score(forme, "Aéroport") == 0.0
                and score(forme, "Aéroport LSS") == 0.0)
    verifie("« Stade LSS » reste le stade", score("Stade LSS", "Aéroport LSS") == 0.0)

    for forme, attendu in (("aéroport", "Aéroport"), ("aeroport", "Aéroport"), ("earoport", "Aéroport"),
                           ("ayeropoor", "Aéroport"), ("aéroport Blaise Diagne", "AIBD"), ("Diass", "AIBD"),
                           ("aéroport Yoff", "Aéroport LSS"), ("aéroport de Yoff", "Aéroport LSS"),
                           ("aéroport Senghor", "Aéroport LSS"), ("Léopold Sédar Senghor", "Aéroport LSS"),
                           ("LSS", "Aéroport LSS"), ("Stade LSS", None), ("Avenue Blaise Diagne", "Avenue Blaise Diagne")):
        lieux = extract_local(f"maa ngi Pikine bëgg naa dem {forme}")
        if attendu is None:
            verifie(f"phrase « dem {forme} » : jamais un aéroport",
                    lieux.get("arrivee") not in ("Aéroport", "Aéroport LSS", "AIBD"), lieux)
        else:
            verifie(f"phrase « dem {forme} » -> {attendu}", lieux.get("arrivee") == attendu, lieux)

    # « aydapoor » : « aéroport » chez les locuteurs wolof plus âgés, et ses formes ASR.
    aydapoor = ("aydapoor", "ayda poor", "aydaapoor", "aydapor", "aydaporr", "aydapoore")
    for forme in aydapoor:
        verifie(f"« {forme} » seul est ambigu, comme « aéroport »", aeroport_ambigu(forme))
        lieux = extract_local(f"maa ngi Pikine bëgg naa dem {forme}")
        verifie(f"phrase « dem {forme} » -> Aéroport (ambigu)", lieux.get("arrivee") == "Aéroport", lieux)
        for suite, attendu in ((" Blaise Diagne", "AIBD"), (" AIBD", "AIBD"), (" Diass", "AIBD"),
                               (" Yoff", "Aéroport LSS"), (" Senghor", "Aéroport LSS"), (" LSS", "Aéroport LSS")):
            lieux = extract_local(f"maa ngi Pikine bëgg naa dem {forme}{suite}")
            verifie(f"phrase « dem {forme}{suite} » -> {attendu}", lieux.get("arrivee") == attendu, lieux)
            cible = "AIBD" if attendu == "AIBD" else "Aéroport LSS"
            verifie(f"« {forme}{suite} » -> {cible} (nom)", score(forme + suite, cible) == 1.0
                    and not aeroport_ambigu(forme + suite), score(forme + suite, cible))
    lieux = extract_local("maa ngi aydapoor bëgg naa dem Palais")
    verifie("phrase « maa ngi aydapoor » : départ ambigu « Aéroport »", lieux.get("depart") == "Aéroport", lieux)

    # ------------------------------------------------------------ le moteur
    matcher = _matcher_hors_ligne()
    # Pikine n'a pas de trajet v2 vers l'AIBD (demi-tour par Patte d'Oie refusé),
    # voir plus bas : seuls Ouakam, Yoff et Médina ont les deux.
    for dep in ("Ouakam", "Yoff", "Médina"):
        resultat = matcher.find_line(dep, "aéroport")
        possibles = resultat.get("lieux_possibles") or []
        verifie(f"{dep} -> aéroport : deux possibilités, AIBD puis Aéroport LSS",
                [p["lieu"] for p in possibles] == [AIBD, AEROPORT_LSS], [p["lieu"] for p in possibles])
        options = (resultat.get("lignes") or []) + (resultat.get("correspondances") or []) + (resultat.get("trajets_2") or [])
        verifie(f"{dep} -> aéroport : les deux à l'écran", len(options) + bool(resultat.get("a_pied")) == 2, _detail(resultat))
        for possible in possibles:
            option = possible["option"]
            derniere = (option.get("etapes") or [None])[-1] if possible["genre"] == "trajet_2" else (
                option.get("etape_2") if possible["genre"] == "correspondance" else option)
            if possible["genre"] == "a_pied":
                continue
            descente = derniere["descend_a"]
            bon = descente == "AIBD" if possible["lieu"] == AIBD else descente in ("Aéroport", "Aéroport LSS")
            verifie(f"{dep} -> aéroport : la possibilité {possible['lieu']} descend au bon aéroport", bon, descente)
    resultat = matcher.find_line("Ouakam", "aydapoor")
    verifie("Ouakam -> aydapoor : les deux aéroports, comme « aéroport »",
            [p["lieu"] for p in resultat.get("lieux_possibles") or []] == [AIBD, AEROPORT_LSS], _detail(resultat))
    # Lot 2c : v2 seul. Pikine -> AIBD n'a que des demi-tours (vers Patte d'Oie
    # ou Liberté 6, puis retour vers l'est) : aucune option AIBD, et on le dit.
    for forme in ("aéroport", "aydapoor"):
        resultat = matcher.find_line("Pikine", forme)
        verifie(f"Pikine -> {forme} : seul l'ancien aéroport, aucune option AIBD venue de v1",
                [p["lieu"] for p in resultat.get("lieux_possibles") or []] == [AEROPORT_LSS]
                and not any(e.get("descend_a") == "AIBD" for e in (resultat.get("lignes") or [])), _detail(resultat))
        verifie(f"Pikine -> {forme} : l'AIBD sans trajet est nommé",
                resultat.get("lieux_sans_trajet") == ["Aéroport Blaise Diagne (AIBD, Diass)"],
                resultat.get("lieux_sans_trajet"))
    resultat = matcher.find_line("Pikine", "aéroport", {"Tata AFTU"})
    verifie("Pikine -> aéroport (Tata) : seul l'ancien aéroport, aucune Tata ne va à l'AIBD",
            [p["lieu"] for p in resultat.get("lieux_possibles") or []] == [AEROPORT_LSS], _detail(resultat))
    resultat = matcher.find_line("aéroport", "Palais")
    verifie("aéroport -> Palais : deux possibilités au départ",
            [p["lieu"] for p in resultat.get("lieux_possibles") or []] == [AIBD, AEROPORT_LSS], _detail(resultat))
    for arrivee in ("aéroport Blaise Diagne", "aéroport Yoff", "AIBD", "Aéroport LSS"):
        resultat = matcher.find_line("Ouakam", arrivee)
        verifie(f"Ouakam -> {arrivee} : nom précis, une seule réponse directe", not resultat.get("lieux_possibles")
                and resultat["found"], _detail(resultat))

    # ------------------------------------------------------------ la voix
    entendus: list[list[str]] = []
    ancien = speak.assembler
    speak.assembler = lambda fichiers, pauses=None: entendus.append([f.name for f in fichiers]) or b"RIFF"
    try:
        resultat = matcher.find_line("Ouakam", "aéroport")
        octets = speak.voix_lieux_possibles(resultat["lieux_possibles"])
        resultat_corr = matcher.find_line("Médina", "aéroport")
        speak.voix_lieux_possibles(resultat_corr["lieux_possibles"])
        resultat_pikine = matcher.find_line("Pikine", "aéroport")
        speak.voix_lieux_possibles(resultat_pikine["lieux_possibles"])
    finally:
        speak.assembler = ancien
    pikine = entendus[2] if len(entendus) > 2 else []
    verifie("voix Pikine -> aéroport : un seul aéroport, nommé (LSS), sans « Walla, » ni AIBD",
            "lieu_aeroport_lss.wav" in pikine and "walla_autre.wav" not in pikine and "lieu_aibd.wav" not in pikine,
            pikine)
    for nom, fichiers in (("Ouakam -> aéroport", entendus[0] if entendus else []),
                          ("Médina -> aéroport", entendus[1] if len(entendus) > 1 else [])):
        verifie(f"voix {nom} : « Walla, » entre les deux possibilités", fichiers.count("walla_autre.wav") == 1, fichiers)
        verifie(f"voix {nom} : dit l'AIBD puis l'aéroport LSS",
                "lieu_aibd.wav" in fichiers and "lieu_aeroport_lss.wav" in fichiers
                and fichiers.index("lieu_aibd.wav") < fichiers.index("walla_autre.wav") < fichiers.index("lieu_aeroport_lss.wav"),
                fichiers)
        verifie(f"voix {nom} : jamais l'arrêt ambigu « Aéroport »", "lieu_aeroport.wav" not in fichiers, fichiers)
        dossier = speak.CACHE_DIR
        verifie(f"voix {nom} : seulement des segments existants",
                all(speak.chemin_audio(dossier, f).is_file() for f in fichiers), fichiers)
    verifie("voix : assemblée", octets == b"RIFF")
    regenerer = RACINE / "data" / "audit" / "voix_a_regenerer.csv"
    verifie("phrase manquante (départ « aéroport ») listée dans voix_a_regenerer.csv, pas créée",
            regenerer.is_file() and "voix_lieux_possibles" in regenerer.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ l'écran
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_aeroport")
    repli = getattr(app.MATCHER, "_repli", app.MATCHER)
    repli.geo.point = repli.geo.point_connu
    resultat = app.MATCHER.find_line("Ouakam", "Aéroport")
    carte = app._carte(resultat, "Ouakam", "Aéroport")
    verifie("écran : les deux aéroports titrés",
            "Aéroport Blaise Diagne (AIBD, Diass)" in carte and "Ancien aéroport Léopold Sédar Senghor (Yoff)" in carte,
            carte[:300])
    verifie("écran : pas de « tout près à pied » vers un seul des deux", "C'est tout près" not in carte)
    resultat = app.MATCHER.find_line("Pikine", "Aéroport")
    carte = app._carte(resultat, "Pikine", "Aéroport")
    verifie("écran Pikine -> aéroport : « aucun trajet en bus » vers l'AIBD, dit franchement",
            "Aéroport Blaise Diagne (AIBD, Diass) : aucun trajet en bus trouvé" in carte
            and "Ancien aéroport Léopold Sédar Senghor (Yoff)" in carte, carte[:400])
    return echecs, total


def test_duree_et_v1() -> tuple[int, int]:
    """Lot 2c : pas de durée inventée, pas de repli silencieux sur v1.

    Ouakam -> AIBD par le TAF TAF affichait ~175 min : 27 km sans aucune
    position mesurée (Autoroute à Péage, Diamniadio, AIBD estimés ; « VDN »
    placé à Guédiawaye). La durée devient « inconnue » au lieu d'un chiffre
    inventé ; les durées ordinaires restent affichées.
    """
    import os

    from routing import adapter

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | durée et v1 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    matcher = _matcher_hors_ligne()
    for dep in ("Ouakam", "Yoff", "Grand Yoff", "Liberté 6"):
        resultat = matcher.find_line(dep, "AIBD")
        taf = [t for t in resultat["lignes"] if t["ligne"] == "TAF TAF"]
        verifie(f"{dep} -> AIBD : TAF TAF proposé par v2", bool(taf), _detail(resultat))
        verifie(f"{dep} -> AIBD : durée inconnue, pas de chiffre inventé",
                bool(taf) and all(t["minutes"] is None and t["duree_inconnue"] for t in taf),
                [(t["minutes"], t.get("duree_inconnue")) for t in taf])
    resultat = matcher.find_line("Médina", "AIBD")
    verifie("Médina -> AIBD (trois bus, dernier le TAF TAF) : durée totale inconnue",
            all(t["minutes"] is None for t in resultat.get("trajets_2") or []) and bool(resultat.get("trajets_2")),
            _detail(resultat))
    # Les durées qui reposent sur des positions gardent leur chiffre.
    # La 217 n'a plus que ses terminus (liste officielle = copie de la 218) :
    # Ouakam -> Aéroport LSS passe par la 218, qui a ses positions.
    for dep, arr, ligne in (("Ouakam", "Aéroport LSS", "Ligne 218"), ("Yoff", "UCAD", "Ligne 8"),
                            ("Colobane", "Rufisque", "Ligne 15"), ("Parcelles Assainies", "Petersen", "Ligne 25")):
        resultat = matcher.find_line(dep, arr)
        t = next((t for t in resultat["lignes"] if t["ligne"] == ligne), None)
        verifie(f"{dep} -> {arr} : {ligne} garde sa durée", t is not None and isinstance(t["minutes"], int)
                and not t.get("duree_inconnue"), t and (t["minutes"], t.get("duree_inconnue")))
    verifie("seuil : 15 km sans position mesurée", adapter.DISTANCE_DEVINEE_MAX_M == 15_000.0)

    # Jamais de repli v1 : le moteur v2 ne rappelle jamais StopsMatcher.find_line.
    repli = getattr(matcher, "_repli", matcher)
    appels = []
    ancien = repli.find_line
    repli.find_line = lambda *a, **k: appels.append(a) or ancien(*a, **k)
    try:
        for dep, arr in (("Pikine", "aéroport"), ("Pikine", "AIBD"), ("Rufisque", "AIBD"), ("Zzzqwx", "Colobane")):
            for filtre in (None, {"Tata AFTU"}):
                matcher.find_line(dep, arr, filtre)
    finally:
        repli.find_line = ancien
    verifie("aucun appel à v1, même sans trajet v2", not appels, appels)

    # À l'écran : « durée inconnue » au lieu de « ~175 min ».
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_duree")
    repli_app = getattr(app.MATCHER, "_repli", app.MATCHER)
    repli_app.geo.point = repli_app.geo.point_connu
    resultat = app.MATCHER.find_line("Ouakam", "AIBD")
    carte = app._carte(resultat, "Ouakam", "AIBD")
    verifie("écran Ouakam -> AIBD : « durée inconnue », plus de ~175 min",
            "durée inconnue" in carte and "175 min" not in carte, carte[:300])
    return echecs, total


def test_parcelles_grand_yoff() -> tuple[int, int]:
    """Lot 2a : Parcelles Assainies -> Grand Yoff n'est plus la Tata 2 en 3 min.

    Cause (lot 1) : les liens « Route Principale / Route du Marché des Parcelles
    Assainies » (data/corrections/lieux_arrets_aftu.csv) ont fait de la Tata 2
    une ligne de départ des Parcelles ; à l'arrivée, « Route HLM Grand Médine »
    était prise pour Grand Yoff par son quartier géocodé (« Hlm Grand Yoff »,
    arrets_geo.csv). Un arrêt relié à son lieu est désormais ce lieu, jamais
    un autre quartier par la géographie.
    """
    import importlib.util

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | parcelles grand yoff {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    matcher = _matcher_hors_ligne()
    for filtre in (None, {"Tata AFTU"}):
        resultat = matcher.find_line("Parcelles Assainies", "Grand Yoff", filtre)
        descentes = {t["descend_a"] for t in resultat["lignes"]}
        verifie(f"Parcelles -> Grand Yoff ({'Tata' if filtre else 'Tous'}) : jamais descendre à Route HLM Grand Médine",
                "Route HLM Grand Médine" not in descentes, _detail(resultat))
        verifie(f"Parcelles -> Grand Yoff ({'Tata' if filtre else 'Tous'}) : plus la Tata 2",
                "Ligne 2" not in {t["ligne"] for t in resultat["lignes"] if t["compagnie"] == "Tata AFTU"}, _detail(resultat))
        verifie(f"Parcelles -> Grand Yoff ({'Tata' if filtre else 'Tous'}) : des bus restent proposés",
                bool(resultat["lignes"]), _detail(resultat))
    geo = getattr(matcher, "_repli", matcher).geo
    verifie("« Route HLM Grand Médine » n'est pas Grand Yoff par son quartier",
            "Route HLM Grand Médine" not in geo.scores_lieu("Grand Yoff", proximite=False))
    # Le lien du lot 1 sert toujours : Parcelles -> Petersen garde la Tata 2,
    # et HLM Grand Médine reste trouvé par son nom.
    resultat = matcher.find_line("Parcelles Assainies", "Petersen", {"Tata AFTU"})
    verifie("Parcelles -> Petersen (Tata) : la Tata 2 reste proposée",
            "Ligne 2" in {t["ligne"] for t in resultat["lignes"]}, _detail(resultat))
    resultat = matcher.find_line("Parcelles Assainies", "HLM Grand Médine", {"Tata AFTU"})
    verifie("Parcelles -> HLM Grand Médine (Tata) : la Tata 2 y descend",
            "Ligne 2" in {t["ligne"] for t in resultat["lignes"]}, _detail(resultat))

    spec = importlib.util.spec_from_file_location("audit_fiabilite", RACINE / "scripts" / "audit_fiabilite.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    rangees = [r for r in audit.audit_trajets(_matcher_hors_ligne())
               if r["depart"] == "Parcelles Assainies" and r["arrivee"] == "Grand Yoff"]
    verifie("audit : Parcelles -> Grand Yoff n'est plus LIGNE_FAUSSE",
            bool(rangees) and all("LIGNE_FAUSSE" not in (r["statut_tous"], r["statut_filtre"]) for r in rangees),
            [(r["statut_tous"], r["statut_filtre"]) for r in rangees])
    return echecs, total


def test_terminus_tata_officiels() -> tuple[int, int]:
    """Lot 2b : terminus des 15 lignes Tata TERMINUS_DIFFERENT, d'après les fiches AFTU.

    data/lignes_dakar.csv reste intact : data/corrections/terminus_tata_officiels.csv
    (URL et date de chaque fiche) s'applique en mémoire, partout où les lignes
    sont lues (StopsMatcher, moteur v2, comparer_lignes_officielles.py). La
    voix ne lit jamais les terminus : aucun audio n'est touché.
    """
    import csv
    import importlib.util
    import re as re_

    import tts.speak as speak
    from matching.stops_matcher import StopsMatcher
    from matching.terminus import corrections_terminus
    from routing.data import load_data

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | terminus tata {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    lignes_attendues = {f"Ligne {n}" for n in (1, 26, 45, 50, 52, 56, 58, 63, 64, 65, 69, 70, 72, 74, 81)}
    with open(RACINE / "data" / "corrections" / "terminus_tata_officiels.csv", encoding="utf-8-sig", newline="") as f:
        rangees = list(csv.DictReader(f))
    verifie("15 lignes corrigées, exactement celles de l'audit",
            {r["ligne"] for r in rangees} == lignes_attendues and len(rangees) == 15, sorted(r["ligne"] for r in rangees))
    corrections = corrections_terminus()
    verifie("les 15 corrections sont chargées", set(k[1] for k in corrections) == lignes_attendues)

    with open(RACINE / "data" / "reference" / "arrets_toutes_lignes_aftu.csv", encoding="utf-8-sig", newline="") as f:
        officiels: dict[str, list[dict]] = {}
        for r in csv.DictReader(f):
            officiels.setdefault(r["ligne"], []).append(r)
    with open(RACINE / "data" / "itineraires_dakar.csv", encoding="utf-8", newline="") as f:
        itineraires: dict[str, list[tuple[int, str]]] = {}
        for r in csv.DictReader(f):
            if r["compagnie"] == "Tata AFTU":
                itineraires.setdefault(r["ligne"], []).append((int(r["ordre"]), r["arret"]))

    spec = importlib.util.spec_from_file_location("comparer_officiel", RACINE / "scripts" / "comparer_lignes_officielles.py")
    comparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparer)

    for r in rangees:
        numero = r["ligne"].split()[-1]
        fiche = officiels.get(numero) or []
        verifie(f"{r['ligne']} : source = fiche AFTU de la ligne, avec sa date",
                r["source"] == f"https://aftu-senegal.org/map/dakar-urbain-ligne-{numero}/"
                and bool(fiche) and r["date_fiche"].strip() and r["date_fiche"] in fiche[0]["date"], (r["source"], r["date_fiche"]))
        for cle in ("terminus_a", "terminus_b"):
            nom = r[cle]
            # Ni faute (« TERMINNUS »), ni majuscules de fiche ; « Terminus » seulement
            # devant un numéro seul (« Terminus 63 », nom de l'arrêt sur la fiche 45).
            lisible = (nom == nom.strip() and not nom.isupper() and "  " not in nom
                       and not re_.search(r"\b(?:terminnus|termnus|termibus)\b", nom, re_.I)
                       and (not re_.match(r"terminus\b", nom, re_.I) or re_.fullmatch(r"Terminus \d+", nom)))
            verifie(f"{r['ligne']} : « {nom} » est un nom lisible", lisible)
        # Les deux terminus sont ceux de la fiche, dans un sens ou dans l'autre.
        ok, _, _ = comparer.comparer_terminus((r["terminus_a"], r["terminus_b"]), [x["arret"] for x in fiche])
        verifie(f"{r['ligne']} : terminus = premier et dernier points de la fiche AFTU", ok == "oui",
                (r["terminus_a"], r["terminus_b"], fiche[0]["arret"] if fiche else "", fiche[-1]["arret"] if fiche else ""))
        # terminus_a reste le premier arrêt de NOTRE itinéraire : le sens affiché ne change pas.
        arrets = [a for _, a in sorted(itineraires.get(r["ligne"], []))]
        verifie(f"{r['ligne']} : terminus_a dans le sens de notre itinéraire",
                bool(arrets) and comparer.type_correspondance(r["terminus_a"], arrets[0]) is not None
                and comparer.type_correspondance(r["terminus_b"], arrets[-1]) is not None,
                (r["terminus_a"], r["terminus_b"], arrets[:1], arrets[-1:]))

    # Le CSV d'origine n'est pas modifié ; les lecteurs voient la correction.
    with open(RACINE / "data" / "lignes_dakar.csv", encoding="utf-8", newline="") as f:
        brut = {(r["compagnie"], r["ligne"]): r for r in csv.DictReader(f)}
    verifie("lignes_dakar.csv intact (Tata 74 finit toujours à Tivaouane Peulh dans le fichier)",
            brut[("Tata AFTU", "Ligne 74")]["terminus_b"] == "Tivaouane Peulh")
    matcher = StopsMatcher()
    verifie("StopsMatcher : Tata 74 -> Cité Cocehas",
            matcher.lignes[("Tata AFTU", "Ligne 74")]["terminus_b"] == "Cité Cocehas")
    data = load_data()
    ligne_74 = data.lignes[(data.lignes["compagnie"] == "Tata AFTU") & (data.lignes["ligne"] == "Ligne 74")].iloc[0]
    verifie("moteur v2 : Tata 74 -> Cité Cocehas", ligne_74["terminus_b"] == "Cité Cocehas", ligne_74["terminus_b"])
    autres = [k for k in brut if k[0] == "Tata AFTU" and k[1] not in lignes_attendues]
    verifie("les autres lignes Tata gardent leurs terminus",
            all(matcher.lignes[k]["terminus_a"] == brut[k]["terminus_a"]
                and matcher.lignes[k]["terminus_b"] == brut[k]["terminus_b"] for k in autres))
    troncon = matcher._troncon(("Tata AFTU", "Ligne 74"), 0, 3)
    verifie("affichage : « Ligne : Bargny (Gare ferroviaire) → Cité Cocehas »",
            (troncon["depart"], troncon["arrivee"]) == ("Bargny (Gare ferroviaire)", "Cité Cocehas"),
            (troncon["depart"], troncon["arrivee"]))

    rangees_comparees, _ = comparer.construire_rangees()
    differentes = [r["ligne"] for r in rangees_comparees
                   if r.get("type_ligne") == "notre_ligne" and r["classe"] == "TERMINUS_DIFFERENT"]
    verifie("comparer_lignes_officielles : plus aucune ligne TERMINUS_DIFFERENT", not differentes, differentes)

    # La voix : jamais les terminus. Une ligne aux terminus inventés ne change
    # aucun fichier lu, et chaque nouveau terminus a déjà son WAV de lieu.
    entendus: list[list[str]] = []
    ancien = speak.assembler
    speak.assembler = lambda fichiers, pauses=None: entendus.append([f.name for f in fichiers]) or b"RIFF"
    try:
        for depart, arrivee in (("Tivaouane Peulh", "Bargny"), ("ZZZ_A", "ZZZ_B")):
            match = {"compagnie": "Tata AFTU", "ligne": "Ligne 74", "depart": depart, "arrivee": arrivee,
                     "monte_a": "Bargny (Gare ferroviaire)", "descend_a": "Keur Massar"}
            speak.voix_depuis_cache([match])
            speak.voix_correspondances_depuis_cache([{"etape_1": match, "etape_2": match, "changement": "Keur Massar"}])
    finally:
        speak.assembler = ancien
    verifie("voix : les terminus ne changent aucun segment lu (0 phrase concernée)",
            len(entendus) == 4 and entendus[0] == entendus[2] and entendus[1] == entendus[3], entendus)
    for r in rangees:
        for cle in ("terminus_a", "terminus_b"):
            verifie(f"voix : « {r[cle]} » a déjà son WAV de lieu", speak.chemin_lieu(speak.CACHE_DIR, r[cle]).is_file(),
                    speak.nom_fichier_lieu(r[cle]))
    return echecs, total


def test_terrain_en_ligne() -> tuple[int, int]:
    """Retours du test en ligne : titres lisibles, lieu précis, options trop lentes, « bus »."""
    import csv

    from app.cartes import TITRE_FOND, TITRE_TEXTE, titre_autre_possibilite, titre_section
    from intent.conversation import INTENTIONS
    from intent.extract_intent import extract_local
    from tts.lexique_prononciation import appliquer

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | terrain {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # 1. Titres : vert foncé sur fond bleu nuit (thème sombre) était illisible.
    # Le titre porte son propre fond clair : contraste WCAG >= 7 dans les deux thèmes.
    def luminance(hexa: str) -> float:
        canaux = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canaux]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    claire, foncee = sorted((luminance(TITRE_FOND), luminance(TITRE_TEXTE)), reverse=True)
    contraste = (claire + 0.05) / (foncee + 0.05)
    verifie("titres : contraste texte/fond >= 7", contraste >= 7, round(contraste, 2))
    for html in (titre_section("Pas de bus direct : un changement suffit"), titre_autre_possibilite(2)):
        verifie("titre avec son propre fond clair", f"background:{TITRE_FOND}" in html, html)

    # 2. Le lieu précis l'emporte sur le quartier qui le contient.
    for phrase, depart, arrivee in (
        ("Maa ngi Parcelles Unité 15, bëgg naa dem Colobane", "Unité 15", "Colobane"),
        ("Parcelles Unité 15 laa nekk, dem Colobane", "Unité 15", "Colobane"),
        ("Maa ngi Colobane, bëgg naa dem Parcelles Unité 15", "Colobane", "Unité 15"),
        # Unité 26 n'est dans aucun CSV : on garde Parcelles (vrai, mais large),
        # jamais une autre unité devinée par ressemblance.
        ("Maa ngi Parcelles Unité 26, bëgg naa dem Colobane", "Parcelles", "Colobane"),
        ("Maa ngi HLM Grand Yoff, bëgg naa dem Colobane", "HLM Grand Yoff", "Colobane"),
        ("Maa ngi Liberté 6 Extension, bëgg naa dem Colobane", "Liberté 6 Extension", "Colobane"),
        # Deux lieux séparés par « dem » ne fusionnent jamais.
        ("Maa ngi Parcelles, bëgg naa dem Colobane", "Parcelles", "Colobane"),
    ):
        r = extract_local(phrase)
        verifie(f"{phrase!r} -> {depart} / {arrivee}",
                (r["depart"], r["arrivee"]) == (depart, arrivee), r)
    matcher = _matcher_hors_ligne()
    r = matcher.find_line("Unité 15", "Colobane")
    montees = [t["monte_a_reseau"] for t in r.get("lignes") or []] + [
        c["etape_1"]["monte_a_reseau"] for c in r.get("correspondances") or []
    ]
    verifie("Unité 15 -> Colobane : un arrêt de montée", bool(montees) and all(montees), _detail(r))
    r = matcher.find_line("Liberté 6 Extension", "Colobane")
    verifie("Liberté 6 Extension -> Colobane : un trajet", bool(r.get("lignes") or r.get("correspondances")), _detail(r))

    # 3. Une option 1,8 fois plus longue ET 30 min de plus que la meilleure disparaît.
    def options(resultat: dict) -> list[tuple[str, str, int]]:
        sortie = [(t["compagnie"], t["ligne"], t["minutes"]) for t in resultat.get("lignes") or []]
        sortie += [("corr", c["etape_1"]["ligne"] + "+" + c["etape_2"]["ligne"], c["minutes"])
                   for c in resultat.get("correspondances") or []]
        sortie += [("2 chg", "", t["minutes"]) for t in resultat.get("trajets_2") or []]
        return sortie

    tous = options(matcher.find_line("Yoff", "Sandaga"))
    verifie("Yoff -> Sandaga (Tous) : plus de Tata 3", ("Tata AFTU", "Ligne 3") not in {o[:2] for o in tous}, tous)
    verifie("Yoff -> Sandaga (Tous) : DDD 8 et Tata 4 restent",
            {("Dakar Dem Dikk", "Ligne 8"), ("Tata AFTU", "Ligne 4")} <= {o[:2] for o in tous}, tous)
    for dep, arr, filtre in (
        ("Yoff", "Sandaga", None), ("Yoff", "Sandaga", {"Tata AFTU"}),
        ("Maristes", "Rufisque", None), ("Almadies", "Malika", None),
        ("Parcelles Assainies", "Petersen", None), ("Université", "Rufisque", {"Dakar Dem Dikk"}),
    ):
        opts = options(matcher.find_line(dep, arr, filtre) if filtre else matcher.find_line(dep, arr))
        # « durée inconnue » (None) : rien à comparer. Lot 3 : la Tata 5, dont la
        # trace est étirée par des arrêts mal placés, n'a plus de durée inventée.
        opts = [o for o in opts if o[2] is not None]
        if not opts:
            continue
        meilleure = min(o[2] for o in opts)
        lentes = [o for o in opts if o[2] > 1.8 * meilleure and o[2] - meilleure > 30]
        verifie(f"{dep} -> {arr} {sorted(filtre or [])} : aucune option trop lente", not lentes, opts)
    # Sous filtre, la seule option de la compagnie reste, même lente.
    from routing.adapter import _sans_les_trop_lents
    seule = [{"compagnie": "Tata AFTU", "ligne": "Ligne 3", "minutes": 88}]
    verifie("option seule : jamais retirée", _sans_les_trop_lents(seule, [], [])[0] == seule)
    deux = [{"minutes": 40}, {"minutes": 88}, {"minutes": 69}]
    verifie("88 min retirée (> 1,8 x 40 et +48), 69 min gardée (+29)",
            [t["minutes"] for t in _sans_les_trop_lents(deux, [], [])[0]] == [40, 69])

    # 4. À l'écran toujours « bus » ; la voix dit « biis » par le lexique, l'audio ne change pas.
    sources = [RACINE / "app.py", *sorted((RACINE / "src" / "app").glob("*.py")),
               RACINE / "src" / "intent" / "conversation.py", RACINE / "src" / "tts" / "speak.py"]
    restes = [f"{s.name}:{n}" for s in sources
              for n, ligne in enumerate(s.read_text(encoding="utf-8").splitlines(), 1)
              if re.search(r"\bbiis\b", ligne, re.IGNORECASE) and not ligne.lstrip().startswith("#")]
    verifie("aucun « biis » affiché (app, cartes, conversation, voix)", not restes, restes)
    with (RACINE / "data" / "audit" / "voix_complete.csv").open(encoding="utf-8-sig", newline="") as f:
        phrases = {r["fichier_wav"]: r["texte_a_prononcer"] for r in csv.DictReader(f)}
    for intention in INTENTIONS:
        verifie(f"conversation {intention.nom} : « bus » à l'écran, pas « biis »",
                not re.search(r"\bbiis\b", intention.reponse, re.IGNORECASE), intention.reponse)
        if intention.fichier in phrases:
            verifie(f"conversation {intention.nom} : la voix garde son audio",
                    appliquer(intention.reponse) == phrases[intention.fichier],
                    (appliquer(intention.reponse), phrases[intention.fichier]))
    return echecs, total


# Plancher du score de vérité terrain (lot 1 des noms, 12/11/2026).
PLANCHER_VERITE = {"statut_tous": 43, "statut_filtre": 50}


def test_verite_terrain() -> tuple[int, int]:
    """Les trajets de data/reference/ passent dans le moteur, avec un score plancher.

    Le 12/11/2026 : 36/67 OK sous « Tous » et 42/67 sous le filtre de la
    compagnie, 4 trajets sans réponse (AIBD). Après le lot 1 des noms (Colobane,
    aéroport, chiffres romains, parenthèses, arrêts AFTU reliés) : 43 et 50,
    aucun trajet sans réponse. Le plancher empêche de revenir en arrière ; les
    corrections de positions (lot suivant) le relèveront.
    """
    import importlib.util

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | vérité terrain {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    spec = importlib.util.spec_from_file_location("audit_fiabilite", RACINE / "scripts" / "audit_fiabilite.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    rangees = audit.audit_trajets(_matcher_hors_ligne())
    statuts = {"OK", "AUTRE_LIGNE", "LIGNE_FAUSSE", "ABSENT"}
    verifie(f"{len(rangees)} trajets de référence, chacun avec un statut",
            len(rangees) >= 60 and all(r["statut_tous"] in statuts and r["statut_filtre"] in statuts for r in rangees))
    for colonne, nom in (("statut_tous", "Tous"), ("statut_filtre", "filtre compagnie")):
        compte = audit.score(rangees, colonne)
        print(f"      SCORE {nom} : {compte['OK']}/{len(rangees)} OK, {compte['AUTRE_LIGNE']} autre ligne, "
              f"{compte['LIGNE_FAUSSE']} ligne fausse, {compte['ABSENT']} absent")
        verifie(f"score {nom} : au moins {PLANCHER_VERITE[colonne]} OK", compte["OK"] >= PLANCHER_VERITE[colonne], compte)
        verifie(f"score {nom} : aucun trajet sans réponse (aéroport AIBD compris)", compte["ABSENT"] == 0, compte)
    return echecs, total


def test_compte_hugging_face() -> tuple[int, int]:
    """Le compte Hugging Face s'appelle maintenant PythonMindset (ex-TIJAANI).

    Les anciennes adresses redirigent « pour l'instant » seulement : le lien
    WhatsApp, le Whisper fine-tuné et les tests en ligne doivent viser le
    nouveau nom. « --collecteur TIJAANI » (preparer_collecte.py) reste : c'est
    le nom d'un collecteur de voix, pas une adresse Hugging Face.
    """
    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | compte hf {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    partage = (RACINE / "src" / "app" / "partage.py").read_text(encoding="utf-8")
    transcribe = (RACINE / "src" / "asr" / "transcribe.py").read_text(encoding="utf-8")
    verifie("lien WhatsApp vers le Space PythonMindset",
            'LIEN_APP = "https://huggingface.co/spaces/PythonMindset/guindima-ai"' in partage)
    verifie("Whisper fine-tuné sous PythonMindset",
            'MODEL_WHISPER = "PythonMindset/whisper-small-wolof-dakar-essai3"' in transcribe)
    verifie("tests en ligne vers PythonMindset/guindima-ai", SPACE == "PythonMindset/guindima-ai")
    # Plus aucune adresse Hugging Face à l'ancien nom dans le code, les
    # notebooks et la doc (identifiants « ancien-nom/… » et lien de profil).
    # os.walk pour ne pas descendre dans .venv (des milliers de fichiers).
    import os

    # Motifs recollés ici, sinon ce test se trouverait lui-même.
    ancien = "TIJ" + "AANI"
    motifs = (ancien + "/", "huggingface.co/" + ancien)
    restes = []
    for dossier, sous, fichiers in os.walk(RACINE):
        sous[:] = [d for d in sous if d not in {".venv", ".git", "data", "models", "__pycache__"}]
        for nom in fichiers:
            if not nom.endswith((".py", ".ipynb", ".md")) and nom != "LICENSE":
                continue
            chemin = Path(dossier) / nom
            texte = chemin.read_text(encoding="utf-8", errors="ignore")
            if any(motif in texte for motif in motifs):
                restes.append(str(chemin.relative_to(RACINE)))
    verifie("aucune adresse Hugging Face à l'ancien nom TIJAANI", not restes, restes[:5])
    return echecs, total


def test_gare_gaar() -> tuple[int, int]:
    """« Gare » se dit « Gaar » : la voix disait « heure de Rufisque ».

    Le lexique change le texte parlé (mot entier), jamais l'écran. La liste
    des audios à refaire est data/audit/voix_gare.csv ; le notebook générique
    voix_regen_liste_brev et installer_voix_oolel.py --liste la reposent.
    """
    import contextlib
    import csv as _csv
    import io as _io
    import json as _json
    import os
    import shutil
    import tempfile
    import wave as _wave
    import zipfile as _zipfile

    from tts.lexique_prononciation import appliquer

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | gare {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    verifie("lexique : « Gare de Rufisque » -> « Gaar de Rufisque »", appliquer("Gare de Rufisque") == "Gaar de Rufisque")
    verifie("lexique : « Garage » intact", appliquer("Garage Guédiawaye") == "Garage Guédiawaye")
    verifie("lexique : « gare routière » -> « Gaar routière »", appliquer("gare routière") == "Gaar routière")

    complete = list(_csv.DictReader(open(RACINE / "data/audit/voix_complete.csv", encoding="utf-8", newline="")))
    avec_gare = [r for r in complete if re.search(r"(?<!\w)gare(?!\w)", r["texte_a_prononcer"], re.I)]
    avec_gaar = {r["fichier_wav"]: r["texte_a_prononcer"] for r in complete if "Gaar" in r["texte_a_prononcer"]}
    verifie("voix_complete.csv : plus aucun « Gare » parlé", not avec_gare, [r["fichier_wav"] for r in avec_gare][:5])
    liste_gare = list(_csv.DictReader(open(RACINE / "data/audit/voix_gare.csv", encoding="utf-8", newline="")))
    verifie(
        "voix_gare.csv : exactement les audios « Gaar », même phrase",
        len(liste_gare) == len(avec_gaar) == 11
        and {r["fichier"]: r["phrase"] for r in liste_gare} == avec_gaar,
        (len(liste_gare), len(avec_gaar)),
    )

    # Le notebook générique : pas de saisie cachée, voix 8_1_c, 3 essais, reprise.
    nb = _json.loads((RACINE / "notebooks/voix_regen_liste_brev.ipynb").read_text(encoding="utf-8"))
    codes = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    tout = "\n".join(codes)
    verifie(
        "notebook liste : sans getpass, 8_1_c, meilleur de 3, reprise, regen.zip",
        "getpass" not in tout
        and "8_1_c.wav" in tout
        and "GRAINES = [GRAINE, GRAINE + 1, GRAINE + 2]" in tout
        and "choisir_meilleur_candidat" in tout
        and "faits = {l['fichier']" in tout
        and "regen.zip" in tout,
    )
    # Les cellules plan et zip s'exécutent pour de vrai, dans un dossier jetable.
    plan = next(c for c in codes if "PLAN = " in c)
    fin = next(c for c in codes if "regen.zip" in c and "make_archive" not in c and "ZipFile" in c)
    tmp = Path(tempfile.mkdtemp(prefix="guindima_regen_"))
    try:
        sortie = tmp / "audios_regen"
        sortie.mkdir()
        (tmp / "liste.csv").write_text("fichier,phrase\na.wav,Gaar de Dakar\nb.wav,Gaar Ter\n", encoding="utf-8")
        for nom in ("a.wav", "b.wav", "vieux.wav"):
            (sortie / nom).write_bytes(b"RIFF")
        rapport = tmp / "rapport.csv"
        rapport.write_text("fichier,phrase\na.wav,Gare de Dakar\nb.wav,Gaar Ter\n", encoding="utf-8")
        espace = {"os": os, "BASE": str(tmp), "SORTIE": str(sortie), "RAPPORT": str(rapport)}
        os.environ["LISTE_REGEN"] = str(tmp / "liste.csv")
        with contextlib.redirect_stdout(_io.StringIO()):
            exec(compile(plan, "<plan liste>", "exec"), espace)
        verifie(
            "notebook liste : la phrase changée est refaite, l'autre gardée",
            not (sortie / "a.wav").exists() and (sortie / "b.wav").exists()
            and [p["fichier"] for p in espace["PHRASES"]] == ["a.wav", "b.wav"],
        )
        (sortie / "a.wav").write_bytes(b"RIFF")
        with contextlib.redirect_stdout(_io.StringIO()):
            exec(compile(fin, "<fin liste>", "exec"), espace)
        with _zipfile.ZipFile(tmp / "regen.zip") as boite:
            contenu = sorted(boite.namelist())
        verifie("notebook liste : zip = la liste + le rapport, rien d'autre",
                contenu == ["a.wav", "b.wav", "rapport_regen.csv"], contenu)
    finally:
        os.environ.pop("LISTE_REGEN", None)
        shutil.rmtree(tmp, ignore_errors=True)

    # installer_voix_oolel.py --liste : exactement ces fichiers, tout ou rien.
    import importlib.util

    spec = importlib.util.spec_from_file_location("installer_voix_oolel_liste", RACINE / "scripts/installer_voix_oolel.py")
    installeur = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installeur)
    tmp = Path(tempfile.mkdtemp(prefix="guindima_liste_"))
    try:
        for nom in ("lieu_gare_ter.wav", "lieu_gare_de_dakar.wav", "autre.wav"):
            with _wave.open(str(tmp / nom), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 160)
        archive = tmp / "regen.zip"
        with _zipfile.ZipFile(archive, "w") as boite:
            for nom in ("lieu_gare_ter.wav", "lieu_gare_de_dakar.wav", "autre.wav"):
                boite.write(tmp / nom, arcname=nom)
        liste = tmp / "liste.csv"
        liste.write_text("fichier,phrase\nlieu_gare_ter.wav,Gaar Ter\nlieu_gare_de_dakar.wav,Gaar de Dakar\n", encoding="utf-8")
        cache = tmp / "cache"
        connus = ["lieu_gare_ter.wav", "lieu_gare_de_dakar.wav", "lieu_gare_de_rufisque.wav"]
        with contextlib.redirect_stdout(_io.StringIO()):
            pose = installeur.installer_liste(archive, installeur.lire_liste(liste), cache=cache, connus=connus)
        verifie("installer --liste : exactement les fichiers de la liste",
                pose == 0 and sorted(p.name for p in cache.iterdir()) == ["lieu_gare_de_dakar.wav", "lieu_gare_ter.wav"])
        with contextlib.redirect_stderr(_io.StringIO()):
            manque = installeur.installer_liste(archive, ["lieu_gare_de_rufisque.wav"], cache=tmp / "vide", connus=connus)
            inconnu = installeur.installer_liste(archive, ["autre.wav"], cache=tmp / "vide", connus=connus)
            chemin = installeur.installer_liste(archive, ["../lieu_gare_ter.wav"], cache=tmp / "vide", connus=connus)
        verifie("installer --liste : manquant, inconnu ou chemin refusés, rien posé",
                manque == inconnu == chemin == 1 and not (tmp / "vide").exists())
        verifie("installer --liste : la vraie voix_gare.csv est lisible (11 noms)",
                len(installeur.lire_liste(RACINE / "data/audit/voix_gare.csv")) == 11)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
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
        "lexique de l'écoute : les 6 choix du locuteur natif",
        LEXIQUE
        == {
            "bus": "biis",
            "TAF TAF": "Taf Taf",
            "Acapes": "Akaapes",
            "Albert Sarraut": "Alber Saroo",
            "ASECNA": "Aseknaa",
            # « Gare de Rufisque » s'entendait « heure de Rufisque ».
            "Gare": "Gaar",
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
    # Avec le plancher « jamais plus court que la ligne droite » (network.py),
    # la 16A n'est plus dans les deux meilleures : 221 + 220, puis 221 + Tata 37.
    attendu_corr_plancher = (
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Dem Dikk, numero ñaari "
        "téeméer ak ñaar fukk, moo lay yóbbu ba Malika. Walla, "
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Tata, numero fanweer ak "
        "juróom ñaar, moo lay yóbbu ba Malika."
    )
    # Lot 3 : la DDD 220 (itinéraire à confirmer) passe après les lignes
    # confirmées. 221 + 16A (changement à Arrêt Dial Mbaye) puis 221 + Tata 37.
    attendu_corr_lot3 = (
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Arrêt Dial Mbaye. Ci ginnaaw, jëlal biis bu Dem Dikk, numero fukk ak "
        "juróom benn A, moo lay yóbbu ba Malika. Walla, "
        "Jëlal biis bu Dem Dikk, numero ñaari téeméer ak ñaar fukk ak benn, "
        "nga wàcc Gàddaay. Ci ginnaaw, jëlal biis bu Tata, numero fanweer ak "
        "juróom ñaar, moo lay yóbbu ba Malika."
    )
    verifie(
        "voix 2 changements",
        phrase_corr in {attendu_corr, attendu_corr_officiel, attendu_corr_plancher, attendu_corr_lot3},
        phrase_corr,
    )
    verifie(
        "voix 2 changements : jamais la DDD 220 (à confirmer) en premier",
        "numero ñaari téeméer ak ñaar fukk, moo" not in phrase_corr.split("Walla")[0],
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
        entree for entree in lignes if "bus bu Tattaa" in entree["phrase"]
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
        # « Tattaa » : l'écriture choisie par un locuteur natif à l'écoute
        # (« Tataa » se lisait trop court).
        "les 72 lignes Tata disent Tattaa",
        len(lignes_tata) == 72
        and all("bus bu Tattaa" in entree["phrase"] for entree in lignes_tata),
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

    # Jouable aujourd'hui : dans l'un des trois dossiers que lit l'app
    # (tts_cache_oolel d'abord, puis les ajouts Adia et le plan des 637).
    def _voix_d_aujourdhui(fichier: str) -> bool:
        return any(
            _os.path.isfile(RACINE / "data" / dossier / fichier)
            for dossier in ("tts_cache_oolel", "tts_cache_ajouts", "tts_cache")
        )

    # Les 4 réponses de conversation du petit notebook Brev sont installées
    # (installer_voix_oolel.py --conversation) : plus rien n'est en attente.
    EN_ATTENTE_CONVERSATION: set[str] = set()
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
    # jamais devinés, jamais générés à la volée. Aujourd'hui : aucun.
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
    # « Yoff » : la voix dit « off ». Deux graphies parlées à écouter à la
    # prochaine session Brev (« Yoof », choix du locuteur natif, et « Yooff »),
    # sans toucher au lexique tant que l'écoute n'a pas tranché.
    essais_yoff = [
        ("Bëgg naa dem Yoof.", "test_yoff_yoof.wav"),
        ("Bëgg naa dem Yooff.", "test_yoff_yooff.wav"),
    ]
    verifie(
        "Brev conversation : 4 réponses du CSV + 3 essais Tata + 2 essais Yoff, graine 1234",
        [(p["phrase"], p["fichier"]) for p in portee_conv_brev["PHRASES"]]
        == [(phrase, fichier) for fichier, phrase in attendu_conv]
        + [(phrase, fichier) for phrase, fichier in essais_tata]
        + [(phrase, fichier) for phrase, fichier in essais_yoff]
        and portee_conv_brev["GRAINE"] == 1234
        and gen_637 in sources_conv_brev
        and not {f for _, f in essais_tata + essais_yoff} & set(fichiers_complete),
        len(portee_conv_brev.get("PHRASES", [])),
    )
    from tts.lexique_prononciation import appliquer as appliquer_lexique

    verifie(
        "Yoff : lexique inchangé tant que l'écoute n'a pas tranché",
        "Yoof" not in appliquer_lexique("Bëgg naa dem Yoff")
        and "Yooff" not in appliquer_lexique("Bëgg naa dem Yoff"),
        appliquer_lexique("Bëgg naa dem Yoff"),
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

        # Le zip « tata_tattaa » : les lignes Tata seules sont remplacées, le
        # CSV de rapport est ignoré, et rien n'est posé s'il en manque une.
        tata = ("tata_aftu_1.wav", "tata_aftu_2.wav")
        for nom in tata:
            with _wave.open(str(sons_conv / nom), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 160)
        archive_tata = tmp_installer / "tata_tattaa.zip"
        with _zipfile.ZipFile(archive_tata, "w") as boite:
            for nom in tata + ("conversation_dekk.wav",):
                boite.write(sons_conv / nom, arcname=nom)
            boite.writestr("rapport_tata_final.csv", "fichier,score\n")
        cache_tata = tmp_installer / "cache_tata"
        with contextlib.redirect_stdout(io.StringIO()):
            pose_tata = installeur.installer_tata(archive_tata, list(tata), cache=cache_tata)
        verifie(
            "installer --tata : seules les lignes Tata posées, CSV et autres WAV ignorés",
            pose_tata == 0
            and sorted(p.name for p in cache_tata.iterdir()) == sorted(tata),
            (pose_tata, sorted(p.name for p in cache_tata.iterdir())),
        )
        with contextlib.redirect_stderr(io.StringIO()):
            refus_tata = installeur.installer_tata(
                archive_tata, ["tata_aftu_1.wav", "tata_aftu_3.wav"], cache=tmp_installer / "vide"
            )
            refus_autre = installeur.installer_tata(
                archive_tata, ["conversation_dekk.wav"], cache=tmp_installer / "vide"
            )
        verifie(
            "installer --tata : ligne manquante ou nom non Tata refusés, rien posé",
            refus_tata == 1 and refus_autre == 1 and not (tmp_installer / "vide").exists(),
        )
        verifie(
            "installer --tata : la liste réelle compte les 72 lignes Tata",
            len(installeur.fichiers_tata()) == 72,
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
            # En-tête WebM : le seul contrôle préalable est la signature du format.
            petit.write_bytes(b"\x1aE\xdf\xa3 pas decodable par soundfile")
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
        "README crédits : voix native Oolel, licences ASR, sources de données, corrections",
        "Crédits et licences" in readme
        and "Oolel-Voices-Demo" in readme
        and "8_1_c" in readme
        and "AGPL-3.0" in readme
        and "aucun modèle TTS ne tourne dans l'app" in readme
        and len(re.findall(r"voir la\s+fiche du modèle", readme)) == 3
        and "aftu-senegal.org" in readme
        and "demdikk.sn" in readme
        and "ODbL 1.0" in readme
        and "data/corrections" in readme,
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
            # Lot F5 : l'arrivée comprise s'affiche, le départ manquant aussi.
            and sortie[1] == "? → Palais"
            and "Lieu non détecté" in sortie[2]
            # Arrivée sans départ : la voix redemande (phrase capacités, 20/11).
            and "d'où pars-tu" in sortie[2]
            and sortie[3] is not None,
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


class _ClientQuiLeve:
    """Faux client OpenAI dont chaque appel lève l'exception fournie."""

    def __init__(self, fabrique):
        self.appels = 0
        fabrique_ = fabrique
        client = self

        class _Completions:
            def create(self, **kwargs):
                client.appels += 1
                raise fabrique_()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def test_lot_3() -> tuple[int, int]:
    """Lot 3 : LLM NVIDIA (modèle retiré, journal), Malika -> UCAD, DDD douteuses, Tata 60.

    Aucun appel réseau : le LLM est remplacé par des faux clients, le moteur
    n'utilise que les positions des CSV.
    """
    import contextlib
    import csv
    import io
    import os

    import httpx
    import openai

    import intent.extract_intent as ei
    from matching.compagnie import LIGNES_A_CONFIRMER, MENTION_A_CONFIRMER
    from routing.adapter import _confirmees_dabord
    from tts.lexique_prononciation import appliquer

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 3 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # ------------------------------------------------------------ LLM
    # 1. Le modèle retiré (410 Gone le 2026-11-05) n'est plus le défaut, et
    #    LLM_MODEL le remplace sans toucher au code.
    ancien = os.environ.pop("LLM_MODEL", None)
    try:
        verifie("modèle par défaut : plus le Llama 3.2 11B retiré",
                ei._modeles_configures() == (ei.MODELE_PAR_DEFAUT,)
                and "llama-3.2-11b" not in ei.MODELE_PAR_DEFAUT,
                ei._modeles_configures())
        # Le nemotron 51b répondait 404 en production (13/11/2026), comme les
        # autres anciens modèles encore listés au catalogue : le défaut est
        # celui qui a répondu 200 avec un JSON pur lors de la sonde.
        verifie("modèle par défaut : vérifié en direct, plus le nemotron 51b (404)",
                ei.MODELE_PAR_DEFAUT == "nvidia/nemotron-3.5-lightning-30b-a3b",
                ei.MODELE_PAR_DEFAUT)
        os.environ["LLM_MODEL"] = "  meta/llama-test-instruct "
        verifie("LLM_MODEL remplace le modèle", ei._modeles_configures() == ("meta/llama-test-instruct",))
    finally:
        os.environ.pop("LLM_MODEL", None)
        if ancien is not None:
            os.environ["LLM_MODEL"] = ancien

    requete = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    fausse_cle = "nvapi-CLE-DE-TEST-NE-DOIT-JAMAIS-SORTIR"
    phrase = "maa ngi Ouakam dama bëgg dem Palais"

    def journal_de(fabrique) -> tuple[str, dict, _ClientQuiLeve]:
        client = _ClientQuiLeve(fabrique)
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon):
            resultat = ei.extract_intent(phrase, client=client)
        return tampon.getvalue(), resultat, client

    def erreur_http(classe, statut: int):
        return lambda: classe(
            f"Error code: {statut} - clé {fausse_cle} ; phrase {phrase}",
            response=httpx.Response(statut, request=requete),
            body={"detail": f"{fausse_cle} {phrase}"},
        )

    # 2. 410 Gone : statut, modèle et type dans le journal ; ni clé ni phrase.
    journal, resultat, client = journal_de(erreur_http(openai.APIStatusError, 410))
    verifie("410 : statut HTTP et modèle dans le journal",
            "statut=410" in journal and f"modèle={ei.MODELES[0]}" in journal and "type=" in journal,
            journal)
    verifie("410 : ni la clé ni la phrase dans le journal",
            fausse_cle not in journal and "nvapi-" not in journal and "Ouakam" not in journal
            and "Palais" not in journal, journal)
    verifie("410 : un seul appel, puis repli local qui trouve le trajet",
            client.appels == 1 and resultat["depart"] == "Ouakam"
            and resultat["arrivee"].startswith("Palais") and resultat["source"] == "local",
            (client.appels, resultat))
    verifie("410 : plus de « RuntimeError » nu dans le journal", "RuntimeError" not in journal, journal)

    # 3. 401 (clé refusée) et 429 (quota) : leur statut apparaît tel quel.
    journal, _, _ = journal_de(erreur_http(openai.AuthenticationError, 401))
    verifie("401 : statut et type AuthenticationError",
            "statut=401" in journal and "type=AuthenticationError" in journal
            and fausse_cle not in journal, journal)
    journal, _, _ = journal_de(erreur_http(openai.RateLimitError, 429))
    verifie("429 : statut et type RateLimitError",
            "statut=429" in journal and "type=RateLimitError" in journal, journal)

    # 4. Timeout : « type=timeout », pas de statut inventé.
    journal, _, client = journal_de(lambda: openai.APITimeoutError(request=requete))
    verifie("timeout : type=timeout, statut=-, un seul appel",
            "type=timeout" in journal and "statut=-" in journal and client.appels == 1, journal)

    # 5. 400 : les trois syntaxes JSON sont essayées, puis statut 400 au journal.
    journal, _, client = journal_de(erreur_http(openai.BadRequestError, 400))
    verifie("400 : trois variantes essayées puis statut=400",
            client.appels == 3 and "statut=400" in journal and "type=BadRequestError" in journal,
            (client.appels, journal))

    # 6. Pas de clé : le repli local le dit sans rien d'autre.
    ancienne_cle = os.environ.pop("NVIDIA_API_KEY", None)
    try:
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon):
            resultat = ei.extract_intent(phrase)
        verifie("clé absente : type=cle_absente, repli local",
                "type=cle_absente" in tampon.getvalue() and resultat["source"] == "local",
                tampon.getvalue())
    finally:
        if ancienne_cle is not None:
            os.environ["NVIDIA_API_KEY"] = ancienne_cle

    # 7. Le LLM qui répond reste utilisé : le correctif ne casse pas le cas nominal.
    resultat = ei.extract_intent(phrase, client=_FauxClient('{"depart": "Ouakam", "arrivee": "Palais"}'))
    verifie("LLM qui répond : source llm", resultat["source"] == "llm", resultat)

    # ------------------------------------------------------------ moteur
    matcher = _matcher_hors_ligne()

    # 8. Malika -> UCAD : plus la DDD 220 (descente à « SIPRES », à Rufisque,
    #    confondue avec la cité Sipres d'Amitié) ; la Tata 37 (fiche AFTU : Malika
    #    Terminus ... Terminus UCAD (Claudel)) est proposée en direct.
    resultat = matcher.find_line("Malika", "UCAD")
    toutes = [ligne["ligne"] for ligne in resultat["lignes"]] + [
        etape["ligne"]
        for corr in resultat["correspondances"]
        for etape in (corr["etape_1"], corr["etape_2"])
    ]
    verifie("Malika -> UCAD : jamais la DDD 220", "Ligne 220" not in toutes, _detail(resultat))
    premiere = (resultat["lignes"] or [{}])[0]
    verifie("Malika -> UCAD : Tata 37 directe, descente UCAD (Claudel)",
            premiere.get("compagnie") == "Tata AFTU" and premiere.get("ligne") == "Ligne 37"
            and premiere.get("descend_a") == "UCAD (Claudel)", _detail(resultat))
    descentes = {ligne["descend_a"] for ligne in resultat["lignes"]}
    verifie("Malika -> UCAD : aucune descente à Sipres", not any("sipres" in d.lower() for d in descentes),
            descentes)
    # La trace de la 37 fait 26 km sur ce trajet ; des arrêts « sûrs » mal placés
    # l'étiraient à 45 km, soit « ~188 min ». Pas de chiffre inventé à l'écran.
    verifie("Malika -> UCAD : Tata 37 sans durée inventée",
            premiere.get("minutes") is None and premiere.get("duree_inconnue") is True,
            (premiere.get("minutes"), premiere.get("duree_inconnue")))

    # 9. Colobane -> Rufisque sous « Tous » : DDD 15 et Tata 60 (Terminus
    #    Colobane -> Dioutyba (Rufisque) -> Bargny).
    resultat = matcher.find_line("Colobane", "Rufisque")
    lignes = {(ligne["compagnie"], ligne["ligne"]) for ligne in resultat["lignes"]}
    verifie("Colobane -> Rufisque : DDD 15 et Tata 60",
            {("Dakar Dem Dikk", "Ligne 15"), ("Tata AFTU", "Ligne 60")} <= lignes, _detail(resultat))
    tata_60 = next((l for l in resultat["lignes"] if l["ligne"] == "Ligne 60"), {})
    verifie("Colobane -> Rufisque : Tata 60 descend à Dioutyba (Rufisque)",
            tata_60.get("descend_a") == "Dioutyba (Rufisque)", tata_60)
    resultat, exacte = matcher.find_line_compagnie("Colobane", "Rufisque", "Tata AFTU")
    verifie("Colobane -> Rufisque filtre Tata : Tata 60 sans bandeau",
            exacte and any(l["ligne"] == "Ligne 60" for l in resultat["lignes"]), _detail(resultat))

    # 9 bis. Malika -> Colobane : la Tata 75 de la référence (Terminus Malika
    #    (Cité Sonatel) -> Terminus Gare routière de Colobane). Les deux noms
    #    entre parenthèses / « Gare routière de » ne valaient que 0,67 et 0,75.
    resultat = matcher.find_line("Malika", "Colobane")
    verifie("Malika -> Colobane (Tous) : Tata 75 proposée",
            ("Tata AFTU", "Ligne 75") in {(l["compagnie"], l["ligne"]) for l in resultat["lignes"]},
            _detail(resultat))
    resultat, exacte = matcher.find_line_compagnie("Malika", "Colobane", "Tata AFTU")
    verifie("Malika -> Colobane (Tata) : Tata 75 en tête, montée au terminus Cité Sonatel",
            exacte and resultat["lignes"] and resultat["lignes"][0]["ligne"] == "Ligne 75"
            and resultat["lignes"][0]["monte_a"] == "Malika (Cité Sonatel)", _detail(resultat))
    from matching.lieux import LIENS_AFTU
    verifie("liens Terminus : la forme sans « Terminus » est chargée",
            "Malika" in LIENS_AFTU.get("malika cite sonatel", ())
            and "Colobane" in LIENS_AFTU.get("gare routiere de colobane", ())
            and "Université Cheikh Anta Diop" in LIENS_AFTU.get("ucad claudel", ()))

    # 10. DDD douteuses : jamais avant une ligne confirmée du même trajet.
    verifie("lignes à confirmer : DDD 6, 208, 217, 220, 233",
            LIGNES_A_CONFIRMER == {("Dakar Dem Dikk", f"Ligne {n}") for n in ("6", "208", "217", "220", "233")})

    # Lot B-217 : la liste officielle de la 217 est celle de la 218, point pour
    # point (data/audit/rapport_lignes_divergentes.md) ; celle de la 233 est
    # celle de la 232. Elles sont écartées par data/corrections/lignes_officiel_exclues.csv.
    from matching.itineraires_app import (
        lignes_officiel_exclues, rangees_ddd_officielles, rangees_itineraires, sans_terminus,
    )
    verifie("listes officielles écartées : 217 et 233",
            lignes_officiel_exclues() == {"Ligne 217", "Ligne 233"}, sorted(lignes_officiel_exclues()))
    verifie("aucune rangée officielle 217 ni 233 chargée",
            not any(r["ligne"] in {"Ligne 217", "Ligne 233"} for r in rangees_ddd_officielles()))
    nos_217 = [r["arret"] for r in sorted(
        (r for r in rangees_itineraires() if r["compagnie"] == "Dakar Dem Dikk" and r["ligne"] == "Ligne 217"),
        key=lambda r: float(r["ordre"]))]
    verifie("217 servie avec nos terminus seuls : Thiaroye -> Ouakam", nos_217 == ["Thiaroye", "Ouakam"], nos_217)
    verifie("218 garde sa liste officielle",
            sum(r["ligne"] == "Ligne 218" for r in rangees_ddd_officielles()) == 15)

    def lignes_du_resultat(resultat: dict) -> list[str]:
        noms = [t["ligne"] for t in resultat["lignes"]]
        for trajet in resultat.get("correspondances") or []:
            noms += [trajet["etape_1"]["ligne"], trajet["etape_2"]["ligne"]]
        for trajet in resultat.get("trajets_2") or []:
            noms += [etape["ligne"] for etape in trajet.get("etapes") or []]
        return noms

    # Trajets que seule la copie de la 218 faisait passer par la 217.
    for depart, arrivee in (("Ouakam", "Aéroport LSS"), ("Bountou Pikine", "Ngor"),
                            ("Dépôt Thiaroye", "Aéroport LSS")):
        resultat = matcher.find_line(depart, arrivee)
        noms = lignes_du_resultat(resultat)
        verifie(f"{depart} -> {arrivee} : la 218, plus jamais la 217 avec ses arrêts",
                "Ligne 218" in noms and "Ligne 217" not in noms, _detail(resultat))
    resultat = matcher.find_line("Thiaroye", "Ouakam")
    t217 = next((t for t in resultat["lignes"] if t["ligne"] == "Ligne 217"), None)
    verifie("Thiaroye -> Ouakam : la 217 entre ses terminus, sans les arrêts de la 218",
            t217 is not None and t217["monte_a"] == "Thiaroye" and t217["descend_a"] == "Ouakam"
            and not any(nom in str(t217.get("arrets_trajet")) for nom in ("Sipses", "Bountou Pikine", "VDN")),
            t217 and (t217["monte_a"], t217["descend_a"], t217.get("arrets_trajet")))

    # Les lignes douteuses portent toutes la marque « à confirmer ».
    douteuses = {}
    for depart, arrivee, ligne in (
        ("Parcelles Assainies", "Colobane", "Ligne 6"), ("Bambilor", "Rufisque", "Ligne 208"),
        ("Thiaroye", "Ouakam", "Ligne 217"), ("Malika", "Guédiawaye", "Ligne 220"),
        ("Baux Maraîchers", "Palais", "Ligne 233"),
    ):
        resultat = matcher.find_line(depart, arrivee)
        douteuses[ligne] = next((t for t in resultat["lignes"] if t["ligne"] == ligne), None)
        verifie(f"{depart} -> {arrivee} : DDD {ligne[6:]} proposée et marquée « à confirmer »",
                douteuses[ligne] is not None and douteuses[ligne]["a_confirmer"] is True, _detail(resultat))

    # 501 : la liste officielle finit à Leclerc, le catalogue dit « Gare de Dakar
    # → Palais 2 ». data/corrections/terminus_ddd_officiels.csv ajoute la gare au
    # bout de la 501, et d'elle seule.
    def arrets_app(ligne: str) -> list[str]:
        return [r["arret"] for r in sorted(
            (r for r in rangees_itineraires() if r["compagnie"] == "Dakar Dem Dikk" and r["ligne"] == ligne),
            key=lambda r: float(r["ordre"]))]

    verifie("501 : Gare de Dakar ajoutée après Leclerc",
            arrets_app("Ligne 501")[-2:] == ["Leclerc", "Gare de Dakar"], arrets_app("Ligne 501"))
    resultat = matcher.find_line("Gare de Dakar", "Palais")
    t501 = next((t for t in resultat["lignes"] if t["ligne"] == "Ligne 501"), None)
    verifie("Gare de Dakar -> Palais : la 501 est proposée, de la gare à Palais 2",
            t501 is not None and t501["monte_a"] == "Gare de Dakar" and t501["descend_a"] == "Palais 2",
            _detail(resultat))
    verifie("Gare de Dakar -> Palais : la 13 reste proposée", "Ligne 13" in lignes_du_resultat(resultat))

    # Les lignes 1, 2, 4 et 121 finissent aussi à Leclerc : rien ne change pour elles.
    import csv as _csv
    with open(RACINE / "data" / "corrections" / "corrections_geo_ddd_proposees.csv", encoding="utf-8", newline="") as f:
        brutes_ddd = list(_csv.DictReader(f))
    for numero in ("1", "2", "4", "121"):
        attendu = [sans_terminus(r["arret"]) for r in sorted(
            (r for r in brutes_ddd if r["ligne"] == numero), key=lambda r: float(r["ordre"]))]
        verifie(f"DDD {numero} : liste officielle inchangée, toujours terminée à Leclerc",
                arrets_app(f"Ligne {numero}") == attendu and attendu[-1] == "Leclerc"
                and "Gare de Dakar" not in attendu[-1:], arrets_app(f"Ligne {numero}")[-3:])
    from matching.lieux import score as score_lieu
    verifie("Leclerc n'est pas relié à Gare de Dakar", score_lieu("Gare de Dakar", "Leclerc") == 0.0)
    for depart, arrivee, ligne, montee in (("Parcelles Assainies", "Leclerc", "Ligne 1", "Parcelles Assainies"),
                                           ("Gare de Dakar", "Leclerc", "Ligne 2", "Gare de Dakar"),
                                           ("Grand Yoff", "Leclerc", "Ligne 121", "Mairie Grand Yoff")):
        resultat = matcher.find_line(depart, arrivee)
        trajet = next((t for t in resultat["lignes"] if t["ligne"] == ligne), None)
        verifie(f"{depart} -> {arrivee} : {ligne} inchangée (montée {montee}, descente Leclerc)",
                trajet is not None and trajet["monte_a"] == montee and trajet["descend_a"] == "Leclerc",
                _detail(resultat))
    synthetique = [
        {"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 220"},
        {"compagnie": "Tata AFTU", "ligne": "Ligne 37"},
        {"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 6"},
        {"compagnie": "Dakar Dem Dikk", "ligne": "Ligne 16A"},
    ]
    ordre = [t["ligne"] for t in _confirmees_dabord(synthetique, lambda t: [t])]
    verifie("tri : confirmées d'abord, ordre gardé", ordre == ["Ligne 37", "Ligne 16A", "Ligne 220", "Ligne 6"], ordre)
    for depart, arrivee, douteuse in (
        ("Parcelles Assainies", "Colobane", "Ligne 6"),
        ("Malika", "Guédiawaye", "Ligne 220"),
    ):
        resultat = matcher.find_line(depart, arrivee)
        rangs = [ligne["ligne"] for ligne in resultat["lignes"]]
        marques = [ligne.get("a_confirmer") for ligne in resultat["lignes"]]
        verifie(f"{depart} -> {arrivee} : DDD {douteuse[6:]} après les lignes confirmées",
                douteuse in rangs and marques == sorted(marques) and not marques[0]
                and resultat["lignes"][rangs.index(douteuse)]["a_confirmer"] is True,
                list(zip(rangs, marques)))

    # 11. La carte le dit pour la ligne douteuse, et seulement pour elle.
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_lot_3")
    resultat = matcher.find_line("Parcelles Assainies", "Colobane")
    cartes = {ligne["ligne"]: app._une_carte(ligne) for ligne in resultat["lignes"]}
    verifie("carte DDD 6 : « itinéraire à confirmer »",
            MENTION_A_CONFIRMER in cartes.get("Ligne 6", ""), list(cartes))
    verifie("carte d'une ligne confirmée : pas de mention",
            all(MENTION_A_CONFIRMER not in carte for ligne, carte in cartes.items() if ligne != "Ligne 6"))
    carte = app._carte(resultat, "Parcelles Assainies", "Colobane")
    verifie("réponse complète : la mention apparaît", MENTION_A_CONFIRMER in carte)
    for ligne, trajet in douteuses.items():
        verifie(f"carte DDD {ligne[6:]} : « itinéraire à confirmer »",
                trajet is not None and MENTION_A_CONFIRMER in app._une_carte(trajet))

    # ------------------------------------------------------------ voix
    # 12. Phrase validée par le locuteur natif, en attente de génération.
    with open(RACINE / "data" / "audit" / "voix_a_regenerer.csv", encoding="utf-8", newline="") as f:
        rangees = list(csv.DictReader(f))
    texte = "Baal ma waaye amoul bus bouy diogué fii dem aéroport Blaise Diagne"
    rangee = next((r for r in rangees if r["texte_a_prononcer"] == texte), None)
    verifie("voix_a_regenerer : phrase AIBD validée listée",
            rangee is not None and rangee["fichier_wav"] == "aibd_aucun_bus.wav", rangees[-1])
    verifie("lexique : « bus » devient « biis »",
            appliquer(texte) == "Baal ma waaye amoul biis bouy diogué fii dem aéroport Blaise Diagne",
            appliquer(texte))
    verifie("aibd_aucun_bus.wav pas créé (aucune synthèse en direct)",
            not any((RACINE / "data" / d / "aibd_aucun_bus.wav").exists()
                    for d in ("tts_cache", "tts_cache_oolel", "tts_cache_ajouts")))

    return echecs, total


def test_lot_4() -> tuple[int, int]:
    """Lot 4 : journal du LLM qui répond, ordre départ / arrivée, AIBD, journal ZeroGPU.

    Aucun appel réseau : faux clients LLM, extraction locale, exceptions fabriquées.
    """
    import contextlib
    import io
    import os

    import intent.extract_intent as ei

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 4 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # ------------------------------------------------------------ 1. LLM ok
    # Le journal de production ne montrait que les échecs : un succès doit
    # laisser « [LLM] ok modèle=... durée=...s », sans phrase ni clé.
    phrase = "maa ngi Ouakam dama bëgg dem Palais"
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        resultat = ei.extract_intent(
            phrase, client=_FauxClient('{"depart": "Ouakam", "arrivee": "Palais"}')
        )
    journal = tampon.getvalue()
    lignes_ok = [l for l in journal.splitlines() if l.startswith("[LLM] ok ")]
    verifie("LLM ok : une ligne « [LLM] ok modèle=... durée=...s »",
            len(lignes_ok) == 1
            and re.fullmatch(r"\[LLM\] ok modèle=\S+ durée=\d+\.\ds", lignes_ok[0]) is not None,
            journal)
    verifie("LLM ok : le modèle configuré est nommé", f"modèle={ei.MODELES[0]}" in journal, journal)
    verifie("LLM ok : ni la phrase ni la clé dans le journal",
            "Ouakam" not in journal and "Palais" not in journal and "nvapi-" not in journal
            and os.getenv("NVIDIA_API_KEY", "jamais-vide-ici") not in journal, journal)
    verifie("LLM ok : la réponse reste celle du LLM", resultat["source"] == "llm", resultat)

    # Un échec ne doit jamais écrire « ok ».
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        ei.extract_intent(phrase, client=_ClientQuiLeve(lambda: TimeoutError("lent")))
    verifie("LLM en échec : pas de ligne « ok »", "[LLM] ok" not in tampon.getvalue(), tampon.getvalue())

    # ------------------------------------------------------------ 2. ordre
    # Vu en ligne : « Bëgg naa dem aydapoor Blaise Diagne, fi ma nekk mooy Yoff »
    # donnait départ = aéroport (ambigu), arrivée = Yoff : à l'envers, et
    # « Blaise Diagne » oublié. Ce qui suit « dem / jëm » est l'arrivée ; ce
    # qui suit « fi ma nekk (mooy) », « maa ngi (nekk / ci) », « dama nekk »
    # est le départ, quel que soit l'ordre de la phrase.
    variantes_aibd = (
        "Bëgg naa dem aydapoor Blaise Diagne, fi ma nekk mooy Yoff",
        "Bëgg naa dem aydapoor, Blaise Diagne, fi ma nekk mooy Yoff",
        "Fi ma nekk mooy Yoff, bëgg naa dem aéroport Blaise Diagne",
        "Salam aleykum, bëgg naa dem AIBD, maa ngi Yoff",
        "Asalaa maalekum, maa ngi Yoff, bëgg naa dem aydapoor Blaise Diagne",
        "Maa ngi nekk Yoff te bëgg naa jëm aéroport Diass",
        "Dama nekk Yoff, dama bëgg dem aydapoor Blaise Diagne",
        "Bëgg naa jëm ayda poor Blaise Diagne te maa ngi ci Yoff",
        "bëgg naa dem aidapoor blez diagne fi ma nekk mooy yoff",
        "Bëgg naa dem aéroport international Blaise Diagne, fii ma nekk Yoff",
        "aéroport Blaise Diagne laa bëgg dem, maa ngi Yoff",
        "Bëgg naa dem AIBD, aéroport, fi ma nekk mooy Yoff",
    )
    for texte in variantes_aibd:
        r = ei.extract_local(texte)
        verifie(f"« {texte} » : Yoff -> AIBD",
                (r["depart"], r["arrivee"]) == ("Yoff", "AIBD"), (r["depart"], r["arrivee"]))

    autres_ordres = (
        ("Dama bëgg dem Palais, dama nekk Ouakam", "Ouakam", "Palais"),
        ("Bëgg naa dem Colobane te fi ma nekk mooy Pikine", "Pikine", "Colobane"),
        ("Asalaa maalekum, fi ma nekk Grand Yoff, bëgg naa dem UCAD", "Grand-Yoff", "UCAD"),
        ("maa ngi ci Liberté 6, bëgg naa dem Sandaga", "Liberté 6", "Sandaga"),
        ("Bëgg naa jëm Sandaga, fi ma nekk mooy Ouakam", "Ouakam", "Sandaga"),
    )
    for texte, depart, arrivee in autres_ordres:
        r = ei.extract_local(texte)
        verifie(f"« {texte} » : {depart} -> {arrivee}",
                (r["depart"], r["arrivee"]) == (depart, arrivee), (r["depart"], r["arrivee"]))

    # « Aéroport » seul reste ambigu, et l'Avenue / le Lycée Blaise Diagne
    # (Médina) ne deviennent jamais l'AIBD.
    r = ei.extract_local("Maa ngi Yoff, bëgg naa dem aydapoor")
    verifie("« aydapoor » seul : aéroport ambigu, jamais AIBD d'office",
            r["arrivee"] == "Aéroport", r)
    verifie("« Avenue Blaise Diagne » n'est pas l'AIBD",
            "aibd" not in ei._normaliser_phrase("maa ngi avenue Blaise Diagne").split())
    verifie("« Lycée Blaise Diagne » n'est pas l'AIBD",
            "aibd" not in ei._normaliser_phrase("dem lycée Blaise Diagne").split())
    verifie("« Ouakam laa nekk » reste un départ",
            ei.extract_local("Ouakam laa nekk, bëgg naa dem Palais")["depart"] == "Ouakam")

    # ------------------------------------------------------------ 3. ZeroGPU
    # En ligne : « [ASR] ZeroGPU en échec (RuntimeError) » sans rien d'autre.
    # Le journal doit dire le message, la cause et l'endroit, en une ligne courte.
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_lot_4")

    def leve_gpu():
        try:
            raise ValueError("CUDA driver initialization failed")
        except ValueError as cause:
            raise RuntimeError() from cause

    try:
        leve_gpu()
    except RuntimeError as exc:
        resume = app._resume_erreur_gpu(exc)
    verifie("ZeroGPU : type, cause et message dans le journal",
            resume.startswith("RuntimeError") and "cause ValueError" in resume
            and "CUDA driver initialization failed" in resume, resume)
    verifie("ZeroGPU : lieu de l'erreur, nom de fichier sans chemin",
            "test_trajets.py:" in resume and "\\" not in resume and "/" not in resume, resume)
    verifie("ZeroGPU : ligne courte, une seule ligne", len(resume) <= 220 and "\n" not in resume, resume)
    try:
        raise RuntimeError("ZeroGPU worker error\nTraceback ...\n" + "x" * 500)
    except RuntimeError as exc:
        resume = app._resume_erreur_gpu(exc)
    verifie("ZeroGPU : seule la première ligne du message", "Traceback" not in resume
            and len(resume) <= 220, resume)

    # Le décorateur ne réserve le GPU que pour le calcul : aucun chargement de
    # modèle dans transcrire_wolof (règle ZeroGPU), durée explicite.
    source_app = (RACINE / "app.py").read_text(encoding="utf-8")
    corps = source_app.split("def transcrire_wolof", 1)[1].split("\ndef ", 1)[0]
    # Depuis le 20/11 : durée fixe de 20 s (test de la panne No CUDA GPUs) ;
    # _duree_gpu reste dans le code, testée ci-dessous, mais n'est plus branchée.
    verifie("ZeroGPU : durée fixe de 20 s sur transcrire_wolof",
            "# « No CUDA GPUs are available » après 1 ou 2 appels (20/11).\n"
            "@spaces.GPU(duration=20)\ndef transcrire_wolof" in source_app
            and "duration=_duree_gpu" not in source_app)
    import contextlib
    import io

    import numpy as np

    # Une phrase courte réserve 15 à 20 s ; un vocal de collecte (20 s) 25 s ;
    # jamais plus de 30 s, même au-delà de la durée maximale acceptée.
    durees = {s: app._duree_gpu(np.zeros(int(s * 16_000), dtype=np.float32))
              for s in (0.5, 4, 10, 20, 30, 60)}
    verifie("ZeroGPU : durée réservée selon l'audio",
            durees == {0.5: 16, 4: 17, 10: 20, 20: 25, 30: 30, 60: 30}, durees)
    verifie("ZeroGPU : audio inattendu, durée maximale", app._duree_gpu(None) == 30)

    # Quota ZeroGPU dépassé : le décorateur lève avant même d'appeler la
    # fonction (spaces lève une gr.Error). L'app doit passer au whisper CPU et
    # répondre au trajet, sans montrer l'erreur.
    class ErreurQuota(Exception):
        pass

    def quota_depasse(_audio):
        raise ErreurQuota("You have exceeded your GPU quota (20s requested vs. 3s left).")

    originaux = (app.transcrire_wolof, app._transcrire_cpu, app._decoder_audio,
                 app._effacer_audio_recu)
    appels_gpu = []
    journal = io.StringIO()
    try:
        app.transcrire_wolof = lambda a: (appels_gpu.append(1), quota_depasse(a))[1]
        app._transcrire_cpu = lambda a: "Maa ngi Sandaga, dama bëgg dem Pikine"
        app._decoder_audio = lambda chemin: np.zeros(16_000 * 3, dtype=np.float32)
        app._effacer_audio_recu = lambda chemin: False
        with contextlib.redirect_stdout(journal):
            sortie = app.trouver_le_bus("x.webm", "", "")
    finally:
        (app.transcrire_wolof, app._transcrire_cpu, app._decoder_audio,
         app._effacer_audio_recu) = originaux
    visible = " ".join(str(x) for x in sortie)
    verifie("quota dépassé : la phrase vient du whisper CPU",
            sortie[0] == "Maa ngi Sandaga, dama bëgg dem Pikine", sortie[0])
    verifie("quota dépassé : un trajet est proposé",
            "Pikine" in visible and app.CARTE_TRANSCRIPTION_IMPOSSIBLE not in visible, sortie[2][:200])
    verifie("quota dépassé : aucune erreur technique à l'écran",
            not any(m in visible for m in ("quota", "ErreurQuota", "GPU", "requested")), visible[:300])
    verifie("quota dépassé : le journal le dit, secours CPU",
            "ZeroGPU en échec (ErreurQuota" in journal.getvalue()
            and "secours CPU" in journal.getvalue(), journal.getvalue()[:300])
    verifie("quota dépassé : le GPU est demandé au premier essai", len(appels_gpu) >= 1, appels_gpu)
    verifie("ZeroGPU : aucun chargement de modèle ni appel CUDA dans la fonction décorée",
            not any(m in corps for m in ("pipeline(", "load_model", "_charger_kiriku", ".to(", ".cuda")))

    return echecs, total


def test_lot_5() -> tuple[int, int]:
    """Lot 5 : salutation + trajet, le trajet gagne ; la politesse seule reste politesse.

    Vu en production : « Salaam aleekum, man damay dem Petersen te maa ngi
    Ouakam, ban bus laa wara jël ? » a reçu trois fois « Maalekum salaam »
    (erreur=conversation_salutation), Kiriku comme seconde chance CPU. Aucun
    appel réseau : faux clients LLM, fausses transcriptions.
    """
    import contextlib
    import io
    import os

    from asr.transcribe import transcrir_avec_seconde_chance
    from intent.conversation import detecter, signal_trajet

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 5 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_lot_5")
    client_origine = app._client_llm

    def pipeline(phrase: str, client) -> tuple[str, bool, str]:
        app._client_llm = lambda: client
        tampon = io.StringIO()
        try:
            with contextlib.redirect_stdout(tampon):
                quint, trouve = app._pipeline(phrase, "Kiriku-Wolof-ASR (GPU)", 1.0)
        finally:
            app._client_llm = client_origine
        return quint[2], trouve, tampon.getvalue()

    # 1. Salutation, remerciement ou « ça va » + trajet lisible : l'extraction
    #    locale trouve les deux lieux, le trajet sort, le LLM n'est pas appelé.
    lisibles = (
        ("Salaam aleekum, man damay dem Petersen te maa ngi Ouakam, ban bus laa wara jël ?",
         "Ouakam", "Petersen"),
        ("Salaam aleekum, maa ngi Ouakam, bëgg naa dem Petersen", "Ouakam", "Petersen"),
        ("Maa ngi Ouakam, bëgg naa dem Petersen. Salaam aleekum", "Ouakam", "Petersen"),
        ("Salam, bëgg naa dem Palais, fi ma nekk mooy Ouakam", "Ouakam", "Palais"),
        ("Asalaa maalekum, dama nekk Pikine te bëgg naa jëm UCAD", "Pikine", "UCAD"),
        ("Jërëjëf, maa ngi Ouakam, bëgg naa dem Palais", "Ouakam", "Palais"),
        ("Bëgg naa dem Colobane, maa ngi Pikine. Jërëjëf", "Pikine", "Colobane"),
        ("Naka nga def ? Dama bëgg dem UCAD, fi ma nekk mooy Pikine", "Pikine", "UCAD"),
        ("Nanga def, maa ngi ci Liberté 6, bëgg naa dem Sandaga", "Liberté 6", "Sandaga"),
        ("Salamalekum, damay dem Sandaga te maa ngi Ouakam", "Ouakam", "Sandaga"),
        ("Hello, maa ngi Yoff, bëgg naa dem aéroport Blaise Diagne", "Yoff", "AIBD"),
    )
    for texte, depart, arrivee in lisibles:
        local = app.extract_local(texte)
        client = _ClientQuiLeve(lambda: TimeoutError("ne doit pas être appelé"))
        carte, trouve, journal = pipeline(texte, client)
        verifie(f"« {texte} » : le trajet {depart} -> {arrivee} gagne",
                (local["depart"], local["arrivee"]) == (depart, arrivee)
                and "erreur=conversation_" not in journal and "Maalekum salaam" not in carte,
                ((local["depart"], local["arrivee"]), journal))

    # 2. Le cas de production : l'ASR a déformé les deux noms, l'extraction
    #    locale ne trouve rien ou presque. La salutation ne doit plus court-
    #    circuiter le LLM, qui trouve les deux lieux.
    deformees = (
        "Salaam aleekum, man damay dem Piteersen te maa ngi Wuxaam, ban bus laa wara jël ?",
        "Salam, fi ma nekk mooy Wuxaam, bëgg naa jëm Piteersen",
        "Naka nga def, dama nekk Wuxaam, damay dem Piteersen",
        "Jërëjëf, Wuxaam laa nekk, bëgg naa dem Piteersen",
    )
    for texte in deformees:
        client = _FauxClient('{"depart": "Ouakam", "arrivee": "Petersen"}')
        carte, trouve, journal = pipeline(texte, client)
        verifie(f"« {texte} » : signal de trajet, le LLM trouve Ouakam -> Petersen",
                signal_trajet(texte) and detecter(texte) is not None
                and trouve and "erreur=conversation_" not in journal
                and "[LLM] ok" in journal, (trouve, journal))

    # 3. Politesse pure : la petite conversation reste, sans appel au LLM.
    pures = (
        ("Salaam aleekum", "salutation"),
        ("Naka nga def ? Maa ngi fi rekk", "ca_va"),
        ("Jërëjëf, ba beneen yoon", "merci"),
        ("Salam, maa ngi tudd Moussa", "salutation"),
        ("Asalaa maalekum, maa ngi ci jàmm", "salutation"),
        ("Nanga def, fan nga bëgga dem ?", "ca_va"),
        ("Maa ngi dem, jërëjëf", "merci"),
    )
    for texte, nom in pures:
        client = _ClientQuiLeve(lambda: TimeoutError("ne doit pas être appelé"))
        carte, trouve, journal = pipeline(texte, client)
        verifie(f"« {texte} » : reste « {nom} », sans LLM",
                not signal_trajet(texte) and f"erreur=conversation_{nom}" in journal
                and client.appels == 0 and trouve, (signal_trajet(texte), journal, client.appels))

    # 4. Salutation + forme de trajet, mais aucun lieu même pour le LLM : la
    #    salutation répond (« Fan nga bëgga dem ? » redemande le trajet), sans
    #    trajet inventé ; False laisse sa chance à la seconde transcription.
    texte = "Salaam aleekum, damay dem Xyzzq"
    carte, trouve, journal = pipeline(texte, _FauxClient('{"depart": "", "arrivee": ""}'))
    verifie("salutation + trajet sans lieu : réponse de salutation, pas de trajet",
            "erreur=conversation_salutation" in journal and not trouve, (trouve, journal))

    # 5. Seconde chance : la salutation ne doit plus l'empêcher quand la phrase
    #    a la forme d'une demande de trajet.
    garbled = deformees[0]
    propre = lisibles[0][0]
    verifie("seconde chance : salutation + trajet déformé ne suffit pas",
            app._phrase_donne_un_trajet(garbled) is False)
    verifie("seconde chance : salutation seule suffit (rien à re-transcrire)",
            app._phrase_donne_un_trajet("Salaam aleekum") is True)
    verifie("seconde chance : salutation + trajet lisible suffit",
            app._phrase_donne_un_trajet(propre) is True)
    phrase, libelle, _, retente = transcrir_avec_seconde_chance(
        None,
        lambda son: (garbled, "Kiriku-Wolof-ASR (GPU)", 1.0),
        lambda son, premier: (propre, "Whisper fine-tuné Dakar (CPU)", 2.0),
        app._phrase_donne_un_trajet,
    )
    verifie("seconde chance : le 2e essai (CPU) qui lit les lieux est retenu",
            phrase == propre and retente and libelle.endswith("(2e essai)"), (phrase, libelle))

    # 6. Aucune nouvelle phrase parlée : la réponse de trajet ne gagne pas de
    #    préfixe de salutation (aucun audio existant ne le permet seul).
    carte, trouve, journal = pipeline(propre, _ClientQuiLeve(lambda: TimeoutError("non")))
    verifie("trajet après salutation : pas de « Maalekum salaam » ajouté",
            "Maalekum" not in carte, carte[:200])

    return echecs, total


def test_lot_6() -> tuple[int, int]:
    """Lot 6 : « wakaay », garde « même lieu », formes ASR de « Blaise Diagne ».

    Phrases test du locuteur natif, transcrites en production. Aucun réseau.
    """
    import contextlib
    import io
    import os

    import intent.extract_intent as ei

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 6 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # 1. Transcriptions exactes de production, puis 8 variantes.
    attendus = (
        # Kiriku : « wakaay » n'était pas Ouakam -> départ = arrivée = Petersen.
        ("salaamaalekum damay dem petersen te maa ngi wakaay bon bus laay jële", "Ouakam", "Petersen"),
        # Whisper CPU : « arappor beles gang » restait l'aéroport ambigu.
        ("Yoff, arappor beles gang", "Yoff", "AIBD"),
        # Variantes.
        ("salaam aleekum damay dem petersen te maa ngi wakay", "Ouakam", "Petersen"),
        ("maa ngi waakaay damay dem petersen", "Ouakam", "Petersen"),
        ("damay dem Petersen, maa ngi wakhaay", "Ouakam", "Petersen"),
        ("Yoff arapor bles diagne", "Yoff", "AIBD"),
        ("maa ngi Yoff, bëgg naa dem araport belez diagne", "Yoff", "AIBD"),
        ("Yoff, arappor belesgang", "Yoff", "AIBD"),
        ("maa ngi Yoff dem aéroport blez jaañ", "Yoff", "AIBD"),
        ("Fi ma nekk mooy Yoff, damay dem arappor beles gaan", "Yoff", "AIBD"),
    )
    for texte, depart, arrivee in attendus:
        r = ei.extract_local(texte)
        verifie(f"« {texte} » : {depart} -> {arrivee}",
                (r["depart"], r["arrivee"]) == (depart, arrivee), (r["depart"], r["arrivee"]))

    # « wakaay » ne touche aucun autre lieu ; « Wakhinane » reste Wakhinane.
    verifie("« wakhinane » n'est pas réécrit en Ouakam",
            "ouakam" not in ei._normaliser_phrase("maa ngi wakhinane"))
    # Le rapprochement phonétique ne vaut qu'après un mot « aéroport ».
    for texte in ("dem avenue beles gang", "dem lycée beles gang", "maa ngi beles gang",
                  "dem aéroport bel air", "dem aéroport bi", "dem arappor ba leen"):
        verifie(f"« {texte} » : jamais l'AIBD par ressemblance",
                "aibd" not in ei._normaliser_phrase(texte).split(), ei._normaliser_phrase(texte))
    verifie("Avenue Blaise Diagne reste la Médina, pas l'AIBD",
            "aibd" not in ei._normaliser_phrase("dem avenue blaise diagne").split())
    verifie("seuil phonétique : « beles gang » au-dessus, « ba leen » en dessous",
            ei.SequenceMatcher(None, ei._phonetique("belesgang"), ei._BLAISE_PHONETIQUE).ratio()
            >= ei.SEUIL_BLAISE
            > ei.SequenceMatcher(None, ei._phonetique("baleen"), ei._BLAISE_PHONETIQUE).ratio())

    # 2. Garde « même lieu » dans l'app.
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_lot_6")
    client_origine = app._client_llm

    def pipeline(phrase: str, client) -> tuple[str, bool, str, object]:
        app._client_llm = lambda: client
        tampon = io.StringIO()
        try:
            with contextlib.redirect_stdout(tampon):
                quint, trouve = app._pipeline(phrase, "Kiriku-Wolof-ASR (GPU)", 1.0)
        finally:
            app._client_llm = client_origine
        return quint[2], trouve, tampon.getvalue(), quint[3]

    verifie("même lieu : même nom", app._meme_lieu("Petersen", "petersen"))
    verifie("même lieu : marche de 0 m (Palais -> Palais 2)",
            app._meme_lieu("Palais", "Palais 2", app.MATCHER.find_line("Palais", "Palais 2")))
    verifie("même lieu : Sandaga -> Petersen n'en est pas un",
            not app._meme_lieu("Sandaga", "Petersen", app.MATCHER.find_line("Sandaga", "Petersen")))

    # La phrase de production passe maintenant par le local : Ouakam -> Petersen.
    carte, trouve, journal, _ = pipeline(attendus[0][0], _ClientQuiLeve(lambda: TimeoutError("non")))
    verifie("production Kiriku : trajet Ouakam -> Petersen, sans « À pied » ni redemande",
            trouve and "conversation_" not in journal and "À pied environ 0" not in carte,
            (trouve, journal))

    # Le LLM recopie le seul lieu entendu (Petersen, après « dem ») des deux
    # côtés : depuis le 20/11, c'est une arrivée sans départ. On demande le
    # départ (phrase capacités à l'oral), jamais « même lieu », aucun bus.
    carte, trouve, journal, voix = pipeline(
        "salaamaalekum damay dem petersen te maa ngi xyzzq",
        _FauxClient('{"depart": "Petersen", "arrivee": "Petersen"}'),
    )
    verifie("LLM Petersen -> Petersen, un seul lieu dit : départ demandé, aucun bus",
            "erreur=lieu_manquant" in journal and "conversation_meme_lieu" not in journal
            and not trouve and "d'où pars-tu" in carte and "Ligne" not in carte
            and "À pied" not in carte, (trouve, journal, carte[:200]))
    verifie("redemande : voix déjà enregistrée (conversation_capacites.wav), rien de nouveau",
            app.DEMANDE_MEME_LIEU.fichier == "conversation_capacites.wav"
            and any((RACINE / "data" / d / "conversation_capacites.wav").is_file()
                    for d in ("tts_cache_oolel", "tts_cache_ajouts", "tts_cache")))

    # Le local trouve le même lieu des deux côtés : le LLM relit la phrase.
    client = _FauxClient('{"depart": "Ouakam", "arrivee": "Petersen"}')
    carte, trouve, journal, _ = pipeline("maa ngi Petersen, bëgg naa dem Petersen", client)
    verifie("local Petersen -> Petersen : le LLM relit la phrase entière",
            "[LLM] ok" in journal and trouve and "conversation_meme_lieu" not in journal, journal)
    carte, trouve, journal, _ = pipeline(
        "maa ngi Petersen, bëgg naa dem Petersen",
        _FauxClient('{"depart": "Petersen", "arrivee": "Petersen"}'),
    )
    verifie("local et LLM tous deux Petersen -> Petersen : redemande",
            "erreur=conversation_meme_lieu" in journal and not trouve, journal)

    # Seconde chance : un même lieu ne compte pas comme un trajet trouvé.
    verifie("seconde chance : « maa ngi Petersen dem Petersen » relance l'autre ASR",
            app._phrase_donne_un_trajet("maa ngi Petersen, bëgg naa dem Petersen") is False)
    verifie("seconde chance : la phrase Kiriku corrigée suffit",
            app._phrase_donne_un_trajet(attendus[0][0]) is True)

    return echecs, total


def test_lot_7() -> tuple[int, int]:
    """Lot 7 : les 27 lignes Dem Dikk « A_COMPLETER » mesurées comme l'app les sert.

    Constat : l'app (src/routing/data.py) sert déjà ces lignes depuis les listes
    officielles de data/corrections/corrections_geo_ddd_proposees.csv ; seule la
    comparaison lisait encore data/itineraires_dakar.csv brut (2 à 8 arrêts).
    Aucun arrêt n'est ajouté (il ferait doublon), aucun CSV de données modifié.
    """
    import csv
    import importlib.util

    from routing.data import SOURCES_SURES, load_data

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 7 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    spec = importlib.util.spec_from_file_location(
        "comparer_lot_7", RACINE / "scripts" / "comparer_lignes_officielles.py"
    )
    comparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparer)
    rangees, _ = comparer.construire_rangees()
    classes = {
        r["ligne"]: r for r in rangees
        if r["type_ligne"] == "notre_ligne" and r["operateur"] == "Dakar Dem Dikk"
    }

    # 1. Les 24 lignes complètes dans l'app sont CONFORME, tous points retrouvés
    #    (TAF TAF : 16/17, « Itinéraire 213 » de la fiche n'est pas un arrêt).
    conformes = (
        "1", "2", "4", "5", "7", "8", "9", "10", "11", "12", "13", "16A", "16B", "18",
        "20", "121", "213", "218", "219", "221", "227", "232", "234",
    )
    for numero in conformes:
        r = classes[f"Ligne {numero}"]
        verifie(f"Ligne {numero} : CONFORME, {r['points_officiels_trouves']}/{r['points_officiels']}",
                r["classe"] == "CONFORME" and r["points_officiels_trouves"] == r["points_officiels"],
                (r["classe"], r["points_officiels_trouves"], r["points_officiels"]))
    taf = classes["TAF TAF"]
    verifie("TAF TAF : CONFORME (16/17, « Itinéraire 213 » n'est pas un arrêt)",
            taf["classe"] == "CONFORME" and taf["points_officiels_non_trouves"] == "Itinéraire 213",
            (taf["classe"], taf["points_officiels_non_trouves"]))

    # 2. Restent signalées, jamais maquillées : 15A / 15B (la fiche ne distingue
    #    pas les deux, l'app sert la « Ligne 15 » officielle à côté) et 228 (4/4
    #    points, mais l'ordre strict bute sur deux arrêts « Rufisque »).
    verifie("15A et 15B restent A_COMPLETER",
            classes["Ligne 15A"]["classe"] == classes["Ligne 15B"]["classe"] == "A_COMPLETER")
    verifie("228 : 4/4 points, ordre strict à 0,75 -> DIVERGENTE signalée",
            classes["Ligne 228"]["classe"] == "DIVERGENTE"
            and classes["Ligne 228"]["points_officiels_trouves"] == classes["Ligne 228"]["points_officiels"],
            classes["Ligne 228"]["classe"])

    # 3. Lignes douteuses et divergentes : mesure brute conservée, hors lot.
    hors_lot = {"6": "DIVERGENTE", "217": "DIVERGENTE", "233": "DIVERGENTE", "23": "DIVERGENTE",
                "208": "DIVERGENTE", "501": "DIVERGENTE", "220": "DOUTEUSE"}
    for numero, attendue in hors_lot.items():
        verifie(f"Ligne {numero} : hors lot, mesure brute ({attendue})",
                ("Dakar Dem Dikk", f"Ligne {numero}") in comparer.MESURE_BRUTE_CONSERVEE
                and classes[f"Ligne {numero}"]["classe"] == attendue,
                classes[f"Ligne {numero}"]["classe"])

    # 4. La vue de la comparaison est celle de l'app : même liste, même ordre.
    data = load_data()
    vus = comparer.itineraires_vus_par_app(comparer.lire_csv(RACINE / "data" / "itineraires_dakar.csv"))
    for numero in ("1", "18", "234"):
        app_liste = list(
            data.itineraires[(data.itineraires["compagnie"] == "Dakar Dem Dikk")
                             & (data.itineraires["ligne"] == f"Ligne {numero}")]
            .sort_values("ordre")["arret"]
        )
        cmp_liste = [r["arret"] for r in sorted(
            (r for r in vus if r["compagnie"] == "Dakar Dem Dikk" and r["ligne"] == f"Ligne {numero}"),
            key=lambda r: int(r["ordre"]))]
        verifie(f"Ligne {numero} : la comparaison voit les {len(app_liste)} arrêts de l'app",
                len(cmp_liste) == len(app_liste) > 2, (len(cmp_liste), len(app_liste)))

    # 5. Positions : une estimation n'est jamais un arrêt sûr. Toute position
    #    interpolée ou géocodée sur ces lignes reste hors SOURCES_SURES.
    with open(RACINE / "data" / "corrections" / "corrections_geo_ddd_proposees.csv",
              encoding="utf-8-sig", newline="") as f:
        officiel = [r for r in csv.DictReader(f) if r["ligne"] in conformes or r["ligne"] == "TAF TAF"]
    estimees = {"interpolation", "interpolation_sur_trace_osm", "nominatim", "inconnu", "repere_connu"}
    verifie("positions estimées jamais classées sûres",
            not (estimees & SOURCES_SURES)
            and all(r["source"] in SOURCES_SURES | estimees for r in officiel),
            sorted({r["source"] for r in officiel} - SOURCES_SURES - estimees))
    cle = ("Dakar Dem Dikk", "Ligne 1")
    ordres_estimes = [int(r["ordre"]) for r in officiel if r["ligne"] == "1" and r["source"] not in SOURCES_SURES]
    verifie("Ligne 1 : Sapeur Pompiers (interpolé) n'est pas une position sûre dans l'app",
            ordres_estimes and not any(data.positions_sures[cle][o] for o in ordres_estimes),
            ordres_estimes)

    # 6. La 15 officielle est bien servie par l'app, sous « Ligne 15 ».
    quinze = data.itineraires[(data.itineraires["compagnie"] == "Dakar Dem Dikk")
                              & (data.itineraires["ligne"] == "Ligne 15")]
    verifie("Ligne 15 officielle servie (18 arrêts)", len(quinze) == 18, len(quinze))

    return echecs, total


def test_lot_8() -> tuple[int, int]:
    """Lot 8 : l'extraction et geo.py voient les arrêts Dem Dikk que l'app sert.

    « Sapeur Pompiers », « Difoncé »… sont servis par l'app (listes officielles)
    mais n'étaient pas reconnus quand l'usager les disait. Sans faux lieux :
    notes, fautes, noms qui écraseraient un lieu plus large restent écartés, et
    ces arrêts ne sont jamais géocodés (position non sûre). Aucun réseau : le
    géocodage est remplacé par un enregistreur qui ne lit que le cache.
    """
    import contextlib
    import csv
    import io
    import os

    import intent.extract_intent as ei
    import routing.data as rdata
    from matching import geo
    from matching import itineraires_app as ia

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 8 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # 1. Noms officiels désormais reconnus dans une vraie phrase (au moins 15).
    reconnus = (
        "Sapeur Pompiers", "Difoncé", "Embarcadère", "Arsenal", "Assemblée Nationale",
        "Institut Pasteur", "Hôpital Le Dantec", "Grand théâtre", "Monument de la Renaissance",
        "Place ONU", "Sicap Karack", "Sorano", "Obelisque", "Douta Seck", "Cité Isra",
        "Mosquée Seydou Nourrou Tall", "Lycée Delafosse", "Albert Sarraut", "Djoutiba",
        "Leclerc", "Acapes", "Bel Air", "Lycée Blaise Diagne", "Stade Léopold Sédar Senghor",
        "Corniche Ouest",
    )
    for nom in reconnus:
        r = ei.extract_local(f"maa ngi {nom}, bëgg naa dem Sandaga")
        verifie(f"« maa ngi {nom} » : départ reconnu",
                ei.cle_lieu(r["depart"]) == ei.cle_lieu(nom) and r["arrivee"] == "Sandaga",
                (r["depart"], r["arrivee"]))
    verifie("au moins 15 noms officiels ajoutés", len(ei.LIEUX_DDD_OFFICIELS) >= 15, len(ei.LIEUX_DDD_OFFICIELS))
    verifie("le LLM les connaît aussi : prompt et contrôle de sortie",
            "- Sapeur Pompiers" in ei.SYSTEM_PROMPT and ei._lieu_connu("Sapeur Pompiers"))

    # 2. Écartés, avec une raison : jamais un lieu.
    for nom in ("Itinéraire 213", "2 voies", "National 1", "Terminus", "Croisement", "vers Camp Leclerc",
                "BOP", "DAF", "TER", "Ex Rue 10", "Ville de Rufisque", "Blaise Diagne", "Arsanel"):
        verifie(f"« {nom} » écarté ({ia.raison_ecart(nom)})", ia.raison_ecart(nom) is not None)
    for nom in ("Rond Point Sahm", "Marché Fass", "Mairie Grand Yoff", "Police de Parcelles Assainies",
                "Hôpital Fann", "Police Bel Air", "Terrain Acapes"):
        verifie(f"« {nom} » écarté : contient un lieu plus large",
                nom in ei.LIEUX_DDD_ECARTES and "plus large" in ei.LIEUX_DDD_ECARTES[nom],
                ei.LIEUX_DDD_ECARTES.get(nom))
    verifie("aucun nom écarté n'est dans LIEUX",
            not {ei.cle_lieu(n) for n in ei.LIEUX_DDD_ECARTES} & {ei.cle_lieu(n) for n in ei.LIEUX_DDD_OFFICIELS})

    # 3. Le lieu plus large reste prioritaire, et les mots wolof restent des mots.
    plus_larges = (
        ("maa ngi Ville de Rufisque, bëgg naa dem Petersen", "depart", "Rufisque"),
        ("maa ngi Marché Fass, bëgg naa dem Petersen", "depart", "Fass"),
        ("maa ngi Mairie Grand Yoff, bëgg naa dem Petersen", "depart", "Grand-Yoff"),
        ("maa ngi Hôpital Fann, bëgg naa dem Petersen", "depart", "Fann"),
        ("maa ngi Yoff, bëgg naa dem aéroport Blaise Diagne", "arrivee", "AIBD"),
    )
    for phrase, champ, attendu in plus_larges:
        r = ei.extract_local(phrase)
        verifie(f"« {phrase} » : {champ} = {attendu}", ei.cle_lieu(r[champ]) == ei.cle_lieu(attendu), r[champ])
    # « daf » (wolof) et le sigle « BOP » ne deviennent pas des lieux. « sama
    # bopp » est couvert par le lot 9.
    r = ei.extract_local("daf ma neex")
    verifie("« daf » : aucun lieu", not r["depart"] and not r["arrivee"], r)
    verifie("sigles BOP / DAF / TER jamais ajoutés",
            not {"bop", "daf", "ter"} & {ei.cle_lieu(n) for n in ei.LIEUX_DDD_OFFICIELS})

    # 4. Les 10 phrases habituelles ne changent pas (relevé hors ligne avant le lot).
    habituelles = (
        ("Maa ngi Ouakam, bëgg naa dem Palais", "Ouakam", "Palais"),
        ("maa ngi Parcelles Assainies, bëgg naa dem UCAD", "Parcelles Assainies", "UCAD"),
        ("Maa ngi Yoff, bëgg naa dem aéroport Blaise Diagne", "Yoff", "AIBD"),
        ("Maa ngi Pikine, bëgg naa dem Colobane", "Pikine", "Colobane"),
        ("maa ngi Liberté 6, bëgg naa dem Sandaga", "Liberté 6", "Sandaga"),
        ("Maa ngi Guédiawaye, bëgg naa dem Petersen", "Guédiawaye", "Petersen"),
        ("Maa ngi Grand Yoff, bëgg naa dem Médina", "Grand-Yoff", "Médina"),
        ("maa ngi Keur Massar, bëgg naa dem Rufisque", "Keur Massar", "Rufisque"),
        ("Maa ngi Malika, bëgg naa dem UCAD", "Malika", "UCAD"),
        ("Salaam aleekum, damay dem Petersen te maa ngi Ouakam", "Ouakam", "Petersen"),
    )
    for phrase, depart, arrivee in habituelles:
        r = ei.extract_local(phrase)
        verifie(f"inchangée : « {phrase} »", (r["depart"], r["arrivee"]) == (depart, arrivee),
                (r["depart"], r["arrivee"]))

    # 5. Positions : jamais géocodés, jamais « sûrs ».
    demandes: list[str] = []
    geocode_origine, sauver_origine = geo._Nominatim.geocode, geo._Nominatim._sauver

    def enregistre(self, requete):
        demandes.append(requete)
        return tuple(self.cache[requete]) if self.cache.get(requete) else None

    geo._Nominatim.geocode, geo._Nominatim._sauver = enregistre, (lambda self: None)
    try:
        lieux_geo = geo.LieuxGeo()
        points = {nom: lieux_geo.point(nom) for nom in ei.LIEUX_DDD_OFFICIELS}
        os.environ["GUINDIMA_SANS_MODELES"] = "1"
        app = _charger_module(RACINE / "app.py", "app_guindima_lot_8")
        with contextlib.redirect_stdout(io.StringIO()):
            resultat = app.MATCHER.find_line("Sapeur Pompiers", "Sandaga")
            corniche = app.MATCHER.find_line("Corniche Ouest", "Sandaga")
    finally:
        geo._Nominatim.geocode, geo._Nominatim._sauver = geocode_origine, sauver_origine
    verifie("aucun nom ajouté n'est géocodé (ni point, ni requête)",
            not any(points.values()) and not demandes, (demandes[:5], [n for n, p in points.items() if p][:5]))
    verifie("aucun nom ajouté n'a une position sûre",
            not any(lieux_geo.position_sure(nom) for nom in ei.LIEUX_DDD_OFFICIELS))
    premiere = (resultat["lignes"] or [{}])[0]
    verifie("Sapeur Pompiers -> Sandaga : Dem Dikk 1, montée à Sapeur Pompiers",
            premiere.get("ligne") == "Ligne 1" and premiere.get("monte_a") == "Sapeur Pompiers",
            (premiere.get("ligne"), premiere.get("monte_a")))
    verifie("Corniche Ouest n'est jamais rattachée à Sandaga par un point estimé",
            ei.cle_lieu(corniche.get("depart_matched") or "") != "sandaga", corniche.get("depart_matched"))
    with open(RACINE / "data" / "corrections" / "corrections_geo_ddd_proposees.csv",
              encoding="utf-8-sig", newline="") as f:
        sapeur = next(r for r in csv.DictReader(f) if r["ligne"] == "1" and r["arret"] == "Sapeur Pompiers")
    data = rdata.load_data()
    verifie("Sapeur Pompiers (interpolé) n'est pas une position sûre pour le moteur",
            sapeur["source"] not in rdata.SOURCES_SURES
            and data.positions_sures[("Dakar Dem Dikk", "Ligne 1")][int(sapeur["ordre"])] is False)

    # 6. Une seule règle : routing/data.py, l'extraction et geo.py partagent le module.
    verifie("routing/data.py utilise les fonctions de itineraires_app",
            rdata._nom_ligne_ddd is ia.nom_ligne_ddd and rdata._sans_terminus is ia.sans_terminus)
    vus = ia.rangees_itineraires()
    for numero in ("1", "18"):
        app_liste = list(data.itineraires[(data.itineraires["compagnie"] == "Dakar Dem Dikk")
                                          & (data.itineraires["ligne"] == f"Ligne {numero}")]
                         .sort_values("ordre")["arret"])
        nos = [r["arret"] for r in sorted((r for r in vus if r["ligne"] == f"Ligne {numero}"
                                           and r["compagnie"] == "Dakar Dem Dikk"), key=lambda r: int(r["ordre"]))]
        # Le moteur renomme quelques arrêts au chargement (« Ucad » -> « UCAD ») :
        # on compare les formes normalisées.
        verifie(f"Ligne {numero} : mêmes arrêts que le moteur ({len(app_liste)})",
                [ia.cle_lieu(a) for a in nos] == [ia.cle_lieu(a) for a in app_liste],
                [(a, b) for a, b in zip(nos, app_liste) if ia.cle_lieu(a) != ia.cle_lieu(b)][:3])
    # geo.py : le contrôle de voisinage ne lit que les lignes Tata, résultat inchangé.
    with open(RACINE / "data" / "itineraires_dakar.csv", encoding="utf-8", newline="") as f:
        tata_brut = [r for r in csv.DictReader(f) if r["compagnie"] == "Tata AFTU"]
    tata_app = [r for r in vus if r["compagnie"] == "Tata AFTU"]
    verifie("geo.py : mêmes lignes Tata qu'avec le CSV brut",
            sorted((r["ligne"], int(r["ordre"]), r["arret"]) for r in tata_brut)
            == sorted((r["ligne"], int(r["ordre"]), r["arret"]) for r in tata_app))

    return echecs, total


def test_lot_9() -> tuple[int, int]:
    """Lot 9 : « Demba Diop » reconnu, « sama bopp » n'est pas un lieu, aucun e-mail.

    Aucun réseau : le moteur lit les CSV, le LLM et la session HTTP sont simulés.
    """
    import contextlib
    import io
    import json
    import tempfile

    import intent.extract_intent as ei
    from intent.conversation import signal_trajet
    from matching import geo

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 9 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    def lieux(phrase: str) -> tuple[str, str]:
        r = ei.extract_local(phrase)
        return r["depart"] or "", r["arrivee"] or ""

    # 1. Les noms en « Dem… » ne sont plus coupés par la règle « dem » collé.
    for phrase, attendu in (
        # « Stade Demba DIOP » : orthographe de l'arrêt dans le réseau.
        ("Maa ngi Stade Demba Diop, bëgg naa dem Sandaga", ("Stade Demba DIOP", "Sandaga")),
        ("Maa ngi Stade Dembadiop, bëgg naa dem Sandaga", ("Stade Dembadiop", "Sandaga")),
        ("Maa ngi Sandaga, bëgg naa dem Stade Demba Diop", ("Sandaga", "Stade Demba DIOP")),
        ("Maa ngi Sandaga, bëgg naa dem Stade Dembadiop", ("Sandaga", "Stade Dembadiop")),
        ("maa ngi stade demba-diop, bëgg naa dem sandaga", ("Stade Demba DIOP", "Sandaga")),
    ):
        verifie(f"« {phrase} »", lieux(phrase) == attendu, lieux(phrase))
    formes = {c for c, _ in ei._CIBLES + ei._CIBLES_COMPLETES + ei._CIBLES_ETENDUES}
    for cible in sorted(formes):
        if any(m.startswith("dem") and len(m) > 3 for m in cible.split()):
            verifie(f"nom protégé intact : « {cible} »", ei._normaliser_phrase(cible) == cible,
                    ei._normaliser_phrase(cible))
    moteur = _matcher_hors_ligne()
    with contextlib.redirect_stdout(io.StringIO()):
        trajet = moteur.find_line("Stade Demba Diop", "Sandaga")
    verifie("Stade Demba Diop -> Sandaga : le moteur répond",
            bool(trajet.get("lignes") or trajet.get("correspondances") or trajet.get("trajets_2")),
            trajet.get("depart_matched"))
    # La règle continue de servir pour tout le reste.
    verifie("« dempale » reste « dem » + Palais", lieux("dempale") == ("", "Palais"), lieux("dempale"))
    verifie("« demba Colobane » reste « dem ba Colobane »",
            ei._normaliser_phrase("demba Colobane") == "dem ba colobane" and lieux("demba Colobane") == ("", "Colobane"),
            ei._normaliser_phrase("demba Colobane"))
    verifie("« demdikk » reste la compagnie, jamais un lieu",
            ei.extract_local("demdikk")["compagnie"] == "Dakar Dem Dikk" and lieux("demdikk") == ("", ""),
            ei.extract_local("demdikk"))

    # 2. « bopp » (soi-même, tête) n'est pas le quartier Bopp.
    for phrase in (
        "sama bopp", "Sama bopp day metti", "dama bëgg dem sama bopp", "maa ngi ci sama bopp",
        "sa bopp", "seen bopp", "suñu bopp", "sunu bopp", "sama-bopp", "sama bop",
        "bopp bi day metti", "boppam", "dama metti bopp", "damay dem ak sa bopp",
    ):
        verifie(f"« {phrase} » : aucun lieu", lieux(phrase) == ("", ""), lieux(phrase))
    verifie("« damay dem sama bopp » n'est pas une demande de trajet", not signal_trajet("damay dem sama bopp"))
    for phrase, attendu in (
        ("maa ngi Bopp, bëgg naa dem Sandaga", ("Bopp", "Sandaga")),
        ("Bopp laa nekk, bëgg naa dem Sandaga", ("Bopp", "Sandaga")),
        ("bëgg naa dem Bopp", ("", "Bopp")),
        ("maa ngi Ouakam, bëgg naa dem ci Bopp", ("Ouakam", "Bopp")),
        ("maa ngi Ouakam, bëgg naa dem Sandaga ak sama bopp", ("Ouakam", "Sandaga")),
    ):
        verifie(f"« {phrase} »", lieux(phrase) == attendu, lieux(phrase))

    # Le LLM ne peut pas ramener le faux lieu : « Bopp » existe dans le réseau.
    appel_origine = ei._call_llm
    ei._call_llm = lambda client, texte: (json.dumps({"depart": "Bopp", "arrivee": ""}), "simulé")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            faux = ei.extract_intent("sama bopp", client=object())
            vrai = ei.extract_intent("maa ngi Bopp, bëgg naa dem Sandaga", client=object())
    finally:
        ei._call_llm = appel_origine
    verifie("LLM : « Bopp » refusé pour « sama bopp »", not faux["depart"] and not faux["arrivee"], faux)
    verifie("LLM : « Bopp » gardé quand il est nommé", vrai["depart"] == "Bopp" and vrai["arrivee"] == "Sandaga", vrai)

    # 3. Aucune adresse e-mail dans le code, ni dans l'en-tête envoyé.
    attendu = "GuindiMa-AI/1.0 (+https://github.com/chniang/wolof-bus-assistant)"
    verifie("geo.py : User-Agent du projet", geo.USER_AGENT == attendu, geo.USER_AGENT)
    verifie("geolocaliser_arrets.py : même User-Agent",
            f'USER_AGENT = "{attendu}"' in (RACINE / "data" / "sources" / "geolocaliser_arrets.py").read_text(encoding="utf-8"))

    class Reponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> list:
            return []

    class Session:
        entetes: dict = {}

        def get(self, url, params=None, headers=None, timeout=None):
            Session.entetes = headers or {}
            return Reponse()

    with tempfile.TemporaryDirectory() as dossier:
        nominatim = geo._Nominatim(Path(dossier) / "cache.json")
        nominatim.session = Session()
        nominatim.geocode("lieu de test")
    verifie("l'en-tête envoyé à Nominatim est celui du projet",
            Session.entetes.get("User-Agent") == attendu, Session.entetes)

    motif = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
    extensions = {".py", ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ".cfg", ".ini", ".html", ".css", ".js", ".csv"}
    fichiers = [p for p in (RACINE / "src").rglob("*")
                if p.is_file() and p.suffix.lower() in extensions and "__pycache__" not in p.parts]
    # Seuls les noms de fichiers sont affichés : jamais l'adresse trouvée.
    avec_adresse = [p.relative_to(RACINE).as_posix() for p in fichiers
                    if motif.search(p.read_text(encoding="utf-8", errors="replace"))]
    verifie(f"aucune adresse e-mail dans src/ ({len(fichiers)} fichiers)", bool(fichiers) and not avec_adresse, avec_adresse)

    return echecs, total


def test_rapport_lignes_officielles() -> int:
    """Mode rapport : compare les lignes aux fiches officielles, hors ligne.

    Le script est en lecture seule et sans réseau. On affiche son tableau et un
    résumé par classe ; aucun écart n'est compté comme un échec pour l'instant.
    """

    script = RACINE / "scripts" / "comparer_lignes_officielles.py"
    if not script.exists():
        print(f"Rapport indisponible : {script} absent.")
        return 0

    environnement = os.environ.copy()
    environnement["PYTHONIOENCODING"] = "utf-8"
    try:
        resultat = subprocess.run(
            [sys.executable, str(script)],
            cwd=RACINE,
            env=environnement,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Rapport non bloquant : {exc}")
        return 0

    print("=== Rapport lignes officielles (lecture seule, sans réseau) ===\n")
    sortie = resultat.stdout or ""
    print(sortie, end="" if sortie.endswith("\n") else "\n")

    classes = (
        "CONFORME",
        "A_COMPLETER",
        "TERMINUS_DIFFERENT",
        "DIVERGENTE",
        "DOUTEUSE",
        "SANS_SOURCE",
    )
    comptes: dict[str, tuple[str, str, str]] = {}
    for ligne in sortie.splitlines():
        morceaux = [morceau.strip() for morceau in ligne.split("|")]
        if len(morceaux) == 4 and morceaux[0] in classes:
            comptes[morceaux[0]] = (morceaux[1], morceaux[2], morceaux[3])
    if comptes:
        print("\nComptes par classe :")
        for classe in classes:
            if classe in comptes:
                dem_dikk, tata, total = comptes[classe]
                print(
                    f"  {classe}: Dem Dikk={dem_dikk}, "
                    f"Tata AFTU={tata}, total={total}"
                )

    if resultat.returncode != 0:
        print(f"Rapport non bloquant : le script a renvoyé {resultat.returncode}.")
        erreurs = resultat.stderr or ""
        if erreurs:
            print(erreurs, end="" if erreurs.endswith("\n") else "\n")
    print("\nRapport seulement : aucun échec compté.")
    return 0


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


def test_lot_10() -> tuple[int, int]:
    """Lot 10 : collecte des voix de l'onglet Parler et avis, éteinte par défaut.

    Aucun réseau : le collecteur, l'API Hugging Face, l'ASR et le géocodage sont simulés.
    """
    import contextlib
    import io
    import json
    import threading
    import types
    import wave

    import gradio as gr
    import numpy as np

    from app import collecte

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 10 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    class FauxCollecteur:
        def __init__(self, accepte: bool = True):
            self.lots: list[dict] = []
            self.accepte = accepte

        def soumettre(self, fichiers: dict) -> bool:
            self.lots.append(fichiers)
            return self.accepte

        def chemins(self) -> list[str]:
            return [chemin for lot in self.lots for chemin in lot]

    class CollecteurEnPanne:
        def soumettre(self, fichiers: dict) -> bool:
            raise RuntimeError("panne GM-AAAAAA")

    variables = ("COLLECTE_ACTIVE", "HF_TOKEN_COLLECTE", "CONTACT_WHATSAPP", "HF_TOKEN")
    avant = {nom: os.environ.get(nom) for nom in variables}
    collecteur_avant = collecte.COLLECTEUR
    for nom in variables:
        os.environ.pop(nom, None)
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    PHRASE = "maa ngi Liberté 6, bëgg naa dem Palais"
    SON = np.full(16_000, 0.25, dtype=np.float32)
    AUDIO = "faux_micro.webm"
    NUMERO_FICTIF = "+000 11 222 33 44"
    INTERDITS = {"nom", "name", "telephone", "phone", "ip", "user_agent", "heure", "time", "timestamp"}

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            app = _charger_module(RACINE / "app.py", "app_guindima_lot_10")
        repli = getattr(app.MATCHER, "_repli", app.MATCHER)
        repli.geo.point = repli.geo.point_connu
        effaces: list[str] = []
        app._decoder_audio = lambda chemin: SON
        app._effacer_audio_recu = lambda chemin: effaces.append(chemin) or True
        app.transcrir_avec_seconde_chance = lambda son, *_: (PHRASE, "Modèle test", 0.1, False)
        app._voix_wolof = lambda *a, **k: None
        app._client_llm = lambda: None

        def silencieux(fonction, *args, **kwargs):
            with contextlib.redirect_stdout(io.StringIO()):
                return fonction(*args, **kwargs)

        def libelles(config: dict) -> list:
            return [c.get("props", {}).get("label") or c.get("props", {}).get("value")
                    for c in config["components"]]

        # 1. Éteinte : ni composant, ni stockage, audio effacé comme avant.
        verifie("éteinte par défaut", collecte.collecte_active() is False)
        os.environ["COLLECTE_ACTIVE"] = "0"
        verifie("« 0 » n'allume pas la collecte", collecte.collecte_active() is False)
        del os.environ["COLLECTE_ACTIVE"]
        faux = collecte.COLLECTEUR = FauxCollecteur()
        config = silencieux(app._construire).get_config_file()
        vus = libelles(config)
        verifie("éteinte : ni case ni avis dans l'interface",
                not any(c.get("type") == "checkbox" for c in config["components"])
                and "Temps réel du trajet (min)" not in vus
                and "La ligne est juste" not in json.dumps(config, ensure_ascii=False, default=str))
        verifie("éteinte : la note de confidentialité ne change pas",
                app.NOTE_VIE_PRIVEE in json.dumps(config, ensure_ascii=False, default=str))
        sortie = silencieux(app.traiter_demande, AUDIO, "", "", None, True)
        verifie("éteinte : aucun stockage, audio effacé, 7 sorties",
                not faux.lots and effaces == [AUDIO] and len(sortie) == 7 and sortie[0] == PHRASE,
                (faux.lots, effaces, len(sortie)))
        verifie("éteinte : le pipeline ne garde aucune trace", app._TRACE.get() is None)

        # 2. Allumée : aucune case, les avis sont présents, la note prévient.
        os.environ["COLLECTE_ACTIVE"] = "1"
        os.environ["HF_TOKEN_COLLECTE"] = "jeton-de-test"
        config = silencieux(app._construire).get_config_file()
        texte_config = json.dumps(config, ensure_ascii=False, default=str)
        verifie("aucune case de consentement",
                not any(c.get("type") == "checkbox" for c in config["components"])
                and "J'accepte" not in texte_config and "consentement_voix" not in texte_config)
        vus = libelles(config)
        verifie("boutons d'avis et temps réel",
                all(x in vus for x in ("Oui", "Non", "Je ne sais pas", "Temps réel du trajet (min)")), vus)
        verifie("note : nouveau début, suite conservée, même emplacement",
                app.NOTE_VIE_PRIVEE_COLLECTE == (
                    "🎙️ Voix gardée pour améliorer le wolof, sans ton nom ni ton numéro "
                    "(sinon : Écrire). Si tu donnes ton avis, il est gardé "
                    "avec les lieux compris et les lignes proposées. Pour comprendre "
                    "ton trajet, le texte peut être envoyé à un service d'IA (NVIDIA) et les noms "
                    "de lieux à OpenStreetMap.")
                and app.NOTE_VIE_PRIVEE_COLLECTE in texte_config
                and "note_vie_privee" in texte_config, app.NOTE_VIE_PRIVEE_COLLECTE)

        # 3. Onglet Écrire : jamais de voix ; l'avis part sans audio ni phrase.
        faux = collecte.COLLECTEUR = FauxCollecteur()
        sortie = silencieux(app.traiter_demande_collecte, None, PHRASE, "", None, True, None)
        suivi = sortie[7]
        verifie("Écrire : rien n'est envoyé, aucun code affiché",
                not faux.lots and sortie[9] == "" and suivi["voix"] is False and len(sortie) == 11,
                (faux.lots, sortie[9]))
        verifie("Écrire : le panneau d'avis apparaît", sortie[8].get("visible") is True, sortie[8])
        verifie("le suivi ne contient jamais l'audio", "son" not in suivi)
        suivi, message = silencieux(app.donner_avis, "oui", 25, suivi)
        chemins = faux.chemins()
        fiche = json.loads(faux.lots[0][chemins[0]]) if chemins else {}
        verifie("avis après Écrire : un seul fichier, sans audio",
                chemins == [f"donnees/{suivi['code']}/avis.json"], chemins)
        verifie("avis après Écrire : ni transcription ni modèle",
                "transcription" not in fiche and "modele_asr" not in fiche and fiche["avec_voix"] is False, fiche)
        verifie("avis : réponse, temps et lignes gardés",
                fiche["reponse"] == "oui" and fiche["minutes_reelles"] == 25 and fiche["lignes_proposees"], fiche)
        verifie("avis : le code et « ton avis » sont affichés",
                suivi["code"] in message and "supprimer ton avis" in message, message)
        _, message = silencieux(app.donner_temps, 400, suivi)
        verifie("temps invraisemblable : refusé sans envoi",
                message == collecte.MESSAGE_MINUTES and len(faux.lots) == 1, message)

        # 4. Onglet Parler : chaque voix traitée part, sans donnée personnelle.
        faux = collecte.COLLECTEUR = FauxCollecteur()
        app._DERNIERE_RECHERCHE = None
        sortie = silencieux(app.rechercher_une_fois_collecte, AUDIO, "", "", None, None)
        suivi = sortie[7]
        code = suivi["code"]
        lot = faux.lots[0] if faux.lots else {}
        verifie("Parler : audio et fiche sous le dossier du code, sans case",
                set(lot) == {f"donnees/{code}/audio.wav", f"donnees/{code}/demande.json"}, set(lot))
        with wave.open(io.BytesIO(lot[f"donnees/{code}/audio.wav"])) as lu:
            verifie("audio : WAV 16 kHz mono 16 bits, durée conservée",
                    (lu.getframerate(), lu.getnchannels(), lu.getsampwidth(), lu.getnframes())
                    == (16_000, 1, 2, 16_000))
        fiche = json.loads(lot[f"donnees/{code}/demande.json"])
        verifie("fiche : exactement les champs prévus",
                set(fiche) == {"code", "date", "consentement_voix", "transcription", "modele_asr",
                               "depart", "arrivee", "lignes_proposees"}, sorted(fiche))
        verifie("fiche : transcription, modèle, lieux et lignes",
                fiche["transcription"] == PHRASE and fiche["modele_asr"] == "Modèle test"
                and fiche["depart"] and fiche["arrivee"] and fiche["lignes_proposees"], fiche)
        verifie("fiche : le jour seulement", re.fullmatch(r"\d{4}-\d{2}-\d{2}", fiche["date"]), fiche["date"])
        verifie("fiche : aucun champ personnel", not INTERDITS & {c.lower() for c in fiche}, sorted(fiche))
        verifie("fiche : l'accord vient de l'usage de Parler",
                fiche["consentement_voix"] == "usage_onglet_parler", fiche["consentement_voix"])
        verifie("Parler : le fichier reçu de Gradio est quand même effacé", effaces[-1] == AUDIO)
        verifie("Parler : le code et la phrase de suppression avec la réponse",
                code in sortie[9] and sortie[0] == PHRASE
                and "Pour faire supprimer ton enregistrement, envoie ce code à la personne "
                "qui t'a partagé l'application." in sortie[9], sortie[9])
        _, message = silencieux(app.donner_avis, "non", None, suivi)
        avis = faux.lots[-1] if len(faux.lots) == 2 else {}
        fiche_avis = json.loads(avis.get(f"donnees/{code}/avis.json", b"{}"))
        verifie("avis après Parler : même code, rattaché à la voix",
                set(avis) == {f"donnees/{code}/avis.json"} and fiche_avis.get("avec_voix") is True
                and fiche_avis.get("code") == code and code in message, (set(avis), fiche_avis))
        _, message = silencieux(app.donner_temps, 35, suivi)
        fiche_temps = json.loads(faux.lots[-1].get(f"donnees/{code}/avis.json", b"{}"))
        verifie("temps après Parler : même code",
                fiche_temps.get("minutes_reelles") == 35 and len(faux.lots) == 3, fiche_temps)
        del faux.lots[1:]
        verifie("format du code", collecte.MOTIF_CODE.fullmatch(code), code)
        verifie("codes différents d'une demande à l'autre",
                len({collecte.nouveau_code() for _ in range(200)}) == 200)

        # Changer de compagnie : même code, lignes à jour, aucune nouvelle voix.
        etat = sortie[6]
        rejeu = silencieux(app.traiter_demande_collecte, None, "", "Tata AFTU", etat, False, suivi)
        verifie("compagnie : même code, aucun envoi",
                rejeu[7]["code"] == code and len(faux.lots) == 1, rejeu[7])

        # Un même geste émet deux événements : une seule contribution.
        faux = collecte.COLLECTEUR = FauxCollecteur()
        app._DERNIERE_RECHERCHE = None
        silencieux(app.rechercher_une_fois_collecte, AUDIO, "", "", None, None)
        double = silencieux(app.rechercher_une_fois_collecte, AUDIO, "", "", None, None)
        verifie("doublon d'événement : une seule voix, écran inchangé",
                len(faux.lots) == 1 and double[7] == gr.skip(), double[7])

        # Un trajet fréquent (onglet Écrire) n'a pas d'audio non plus.
        faux = collecte.COLLECTEUR = FauxCollecteur()
        silencieux(app.choisir_trajet_frequent_collecte, next(iter(app.CHOIX_TRAJETS_FREQUENTS)), "", None)
        verifie("trajet fréquent : rien n'est envoyé", not faux.lots, faux.chemins())

        # 5. La phrase de suppression, avec et sans numéro configuré.
        os.environ.pop("CONTACT_WHATSAPP", None)
        attendu = ("Pour faire supprimer ton enregistrement, envoie ce code à la personne "
                   "qui t'a partagé l'application.")
        verifie("sans CONTACT_WHATSAPP : renvoi vers la personne qui a partagé",
                collecte.phrase_suppression() == attendu, collecte.phrase_suppression())
        message = collecte.message_code("GM-ABCDEF")
        verifie("sans CONTACT_WHATSAPP : ni WhatsApp ni chiffre affiché",
                attendu in message and "WhatsApp" not in message and not re.search(r"\d", message), message)
        os.environ["CONTACT_WHATSAPP"] = "   "
        verifie("CONTACT_WHATSAPP blanc : traité comme vide", collecte.phrase_suppression() == attendu)
        os.environ["CONTACT_WHATSAPP"] = NUMERO_FICTIF
        verifie("avec CONTACT_WHATSAPP : phrase WhatsApp et numéro",
                collecte.phrase_suppression() == "Pour faire supprimer ton enregistrement, envoie ce "
                f"code par WhatsApp au {NUMERO_FICTIF}.", collecte.phrase_suppression())
        del os.environ["CONTACT_WHATSAPP"]

        # 6. Une panne ne touche jamais la réponse ni le journal.
        collecte.COLLECTEUR = CollecteurEnPanne()
        journal = io.StringIO()
        with contextlib.redirect_stdout(journal):
            sortie = app.traiter_demande_collecte(AUDIO, "", "", None, True, None)
        verifie("panne de collecte : la réponse part quand même",
                sortie[0] == PHRASE and "Ligne :" in sortie[2], sortie[:2])
        verifie("panne de collecte : panneau masqué", sortie[7] is None and sortie[8].get("visible") is False)
        verifie("panne de collecte : journal sans donnée", "GM-" not in journal.getvalue()
                and PHRASE not in journal.getvalue(), journal.getvalue())

        faux = collecte.COLLECTEUR = FauxCollecteur(accepte=False)
        sortie = silencieux(app.traiter_demande_collecte, AUDIO, "", "", None, True, None)
        verifie("contribution refusée : aucun code promis", sortie[9] == "" and sortie[7]["voix"] is False)

        envois: list[dict] = []
        pannes = [ValueError("donnees/GM-AAAAAA/audio.wav"), ValueError("encore GM-AAAAAA")]

        def televerse(lot: dict) -> None:
            if pannes:
                raise pannes.pop(0)
            envois.append(lot)

        collecteur = collecte.Collecteur(televerser=televerse, intervalle=3600)
        journal = io.StringIO()
        with contextlib.redirect_stdout(journal):
            collecteur.soumettre({"donnees/GM-AAAAAA/audio.wav": b"1"})
            premier = collecteur.vider()
            second = collecteur.vider()
            troisieme = collecteur.vider()
        collecteur.arreter()
        verifie("envoi en échec : retenté une fois puis abandonné",
                (premier, second, troisieme) == (0, 0, 0) and not envois, (premier, second, troisieme, envois))
        verifie("envoi en échec : journal court, sans code",
                "GM-" not in journal.getvalue() and "ValueError" in journal.getvalue(), journal.getvalue())

        collecteur = collecte.Collecteur(televerser=envois.append, intervalle=3600)
        collecteur.soumettre({"donnees/GM-AAAAAA/avis.json": b"ancien", "donnees/GM-AAAAAA/audio.wav": b"x"})
        collecteur.soumettre({"donnees/GM-AAAAAA/avis.json": b"nouveau"})
        parti = collecteur.vider()
        collecteur.arreter()
        verifie("un lot par envoi, dernier avis conservé",
                parti == 2 and len(envois) == 1 and envois[0]["donnees/GM-AAAAAA/avis.json"] == b"nouveau", envois)

        # L'envoi tourne à côté : un téléversement bloqué ne retient pas soumettre().
        entre, libere = threading.Event(), threading.Event()

        def bloque(lot: dict) -> None:
            entre.set()
            libere.wait(5)

        collecteur = collecte.Collecteur(televerser=bloque, intervalle=0.01)
        collecteur.soumettre({"a": b"1"})
        arrive = entre.wait(5)
        debut = time.perf_counter()
        accepte = collecteur.soumettre({"b": b"2"})
        duree = time.perf_counter() - debut
        libere.set()
        collecteur.arreter()
        verifie("envoi bloqué : la demande suivante n'attend pas", arrive and accepte and duree < 0.5, duree)

        collecteur = collecte.Collecteur(televerser=envois.append, capacite=1, intervalle=3600)
        with contextlib.redirect_stdout(io.StringIO()):
            collecteur.soumettre({"a": b"1"})
            plein = collecteur.soumettre({"b": b"2"})
        collecteur.arreter()
        verifie("file pleine : refus immédiat", plein is False)

        # Sans jeton dédié, HF_TOKEN ne sert jamais de remplaçant.
        del os.environ["HF_TOKEN_COLLECTE"]
        os.environ["HF_TOKEN"] = "autre-jeton"
        appels: list = []
        collecteur = collecte.Collecteur(televerser=appels.append, intervalle=3600)
        journal = io.StringIO()
        with contextlib.redirect_stdout(journal):
            accepte = collecteur.soumettre({"a": b"1"})
            collecteur.soumettre({"b": b"2"})
            collecteur.vider()
        verifie("jeton absent : rien n'est envoyé, même avec HF_TOKEN", accepte is False and not appels)
        verifie("jeton absent : signalé une seule fois", journal.getvalue().count("[collecte]") == 1, journal.getvalue())
        del os.environ["HF_TOKEN"]
        os.environ["HF_TOKEN_COLLECTE"] = "jeton-de-test"

        # 7. Le dépôt doit être privé, et l'historique ne cite aucun code.
        class FausseApi:
            def __init__(self, prive=True):
                self.prive, self.commits = prive, []

            def repo_info(self, depot, repo_type=None):
                return types.SimpleNamespace(private=self.prive)

            def create_commit(self, **kwargs):
                self.commits.append(kwargs)

        api = FausseApi(prive=False)
        try:
            collecte.televerser_hf({"donnees/GM-AAAAAA/audio.wav": b"1"}, api=api)
            refuse = False
        except PermissionError:
            refuse = True
        verifie("dépôt public : aucune voix ne part", refuse and not api.commits)
        api = FausseApi()
        collecte.televerser_hf({"donnees/GM-AAAAAA/audio.wav": b"1"}, api=api)
        commit = api.commits[0] if api.commits else {}
        verifie("dépôt privé : commit dans le bon dataset, sans code",
                commit.get("repo_id") == "PythonMindset/guindima-voix-testeurs"
                and commit.get("repo_type") == "dataset"
                and [o.path_in_repo for o in commit.get("operations", [])] == ["donnees/GM-AAAAAA/audio.wav"]
                and "GM-" not in commit.get("commit_message", "GM-"), commit)

        # 8. Le script de suppression simule par défaut et ne vise que son code.
        script = _charger_module(RACINE / "scripts" / "supprimer_enregistrement.py", "supprimer_lot_10")

        class ApiDepot:
            def __init__(self):
                self.actions: list = []

            def list_repo_tree(self, depot, recursive=False, repo_type=None):
                def fichier(chemin, sha=None):
                    lfs = types.SimpleNamespace(sha256=sha) if sha else None
                    return types.SimpleNamespace(path=chemin, lfs=lfs)

                return [types.SimpleNamespace(path="donnees"),
                        fichier("donnees/GM-AAAAAA/audio.wav", "sha-a"),
                        fichier("donnees/GM-AAAAAA/avis.json"),
                        fichier("donnees/GM-BBBBBB/audio.wav", "sha-b"),
                        fichier("README.md")]

            def list_lfs_files(self, depot, repo_type=None):
                return [types.SimpleNamespace(filename="donnees/GM-AAAAAA/audio.wav", file_oid="sha-a"),
                        types.SimpleNamespace(filename="donnees/GM-BBBBBB/audio.wav", file_oid="sha-b")]

            def delete_folder(self, chemin, depot, repo_type=None, commit_message=None):
                self.actions.append(("dossier", chemin))

            def permanently_delete_lfs_files(self, depot, fichiers, rewrite_history=True, repo_type=None):
                self.actions.append(("lfs", [f.filename for f in fichiers], rewrite_history))

            def super_squash_history(self, depot, repo_type=None, commit_message=None):
                self.actions.append(("historique",))

        verifie("script : codes malformés refusés",
                not any(script.code_valide(c) for c in ("../..", "GM-*", "GM-AAAAA", "", "GM-AAAAAA/x")))
        verifie("script : code normalisé", script.code_valide(" gm-aaaaaa ") == "GM-AAAAAA")
        api = ApiDepot()
        nombre = silencieux(script.supprimer, api, "GM-AAAAAA")
        verifie("script : simulation par défaut", nombre == 2 and not api.actions, api.actions)
        silencieux(script.supprimer, api, "GM-AAAAAA", executer=True)
        verifie("script : dossier, audio LFS et historique, ce code seulement",
                api.actions == [("dossier", "donnees/GM-AAAAAA"),
                                ("lfs", ["donnees/GM-AAAAAA/audio.wav"], True), ("historique",)], api.actions)

        # 9. Aucun numéro ni e-mail dans le code livré.
        motifs = (
            re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}"),
            re.compile(r"(?<![\d.])(?:\+|00)221[ .-]?\d"),
            re.compile(r"(?<![\d.])7[05678][ .-]?\d{3}[ .-]?\d{2}[ .-]?\d{2}(?![\d])"),
        )
        trouves = []
        for fichier in [*sorted((RACINE / "src").rglob("*.py")), RACINE / "app.py",
                        RACINE / "scripts" / "supprimer_enregistrement.py"]:
            texte = fichier.read_text(encoding="utf-8")
            trouves += [fichier.name for motif in motifs if motif.search(texte)]
        verifie("aucun numéro de téléphone ni e-mail dans src/ et app.py", not trouves, trouves)
    finally:
        collecte.COLLECTEUR = collecteur_avant
        for nom, valeur in avant.items():
            if valeur is None:
                os.environ.pop(nom, None)
            else:
                os.environ[nom] = valeur
    return echecs, total


def test_revue_securite() -> tuple[int, int]:
    """Revue de sécurité avant le test public : chaque correction a sa vérification.

    Aucun réseau : ffmpeg, le LLM, l'ASR et l'API Hugging Face sont simulés.
    """
    import contextlib
    import io
    import tempfile
    import types
    import wave

    from app import collecte
    from app.limites import LimiteDebit, entier_env
    from asr import transcribe

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | revue {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    verifie("plus de case de consentement, plus « anonyme »",
            not hasattr(collecte, "TEXTE_CONSENTEMENT")
            and "anonyme" not in (RACINE / "src" / "app" / "collecte.py").read_text(encoding="utf-8").lower())

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    with contextlib.redirect_stdout(io.StringIO()):
        app = _charger_module(RACINE / "app.py", "app_guindima_revue")
    repli = getattr(app.MATCHER, "_repli", app.MATCHER)
    repli.geo.point = repli.geo.point_connu
    INTERNE = r"C:\interne\modele.bin jeton-interne"

    # Les erreurs montrées à l'usager ne citent jamais l'exception.
    decoder, seconde = app._decoder_audio, app.transcrir_avec_seconde_chance
    effacer = app._effacer_audio_recu
    app._effacer_audio_recu = lambda chemin: False

    def leve(*_args):
        raise RuntimeError(INTERNE)

    journal = io.StringIO()
    try:
        app._decoder_audio = leve
        with contextlib.redirect_stdout(journal):
            illisible = app.trouver_le_bus("x.webm", "", "")
        app._decoder_audio = lambda chemin: [0.0] * 16_000
        app.transcrir_avec_seconde_chance = leve
        with contextlib.redirect_stdout(journal):
            impossible = app.trouver_le_bus("x.webm", "", "")
    finally:
        app._decoder_audio, app.transcrir_avec_seconde_chance = decoder, seconde
        app._effacer_audio_recu = effacer
    verifie("audio illisible : message générique", illisible[2] == app.CARTE_AUDIO_ILLISIBLE, illisible[2])
    verifie("transcription impossible : message générique",
            impossible[2] == app.CARTE_TRANSCRIPTION_IMPOSSIBLE, impossible[2])
    verifie("journal : le type d'erreur, pas son texte",
            "RuntimeError" in journal.getvalue() and INTERNE not in journal.getvalue(), journal.getvalue())
    mention = app._mention({"erreur": "modèle=interne statut=500", "source": "llm"})
    verifie("mention : pas de détail du LLM", "interne" not in mention and "500" not in mention, mention)

    # Signature et durée sont contrôlées avant tout décodage.
    for nom, debut in (("WAV", b"RIFF\0\0\0\0WAVEfmt "), ("WebM", b"\x1aE\xdf\xa3\x01"), ("Ogg", b"OggS\0"),
                       ("FLAC", b"fLaC\0"), ("MP3", b"ID3\x04"), ("AAC", b"\xff\xf1P@"),
                       ("M4A", b"\0\0\0\x1cftypM4A ")):
        verifie(f"format accepté : {nom}", app._signature_audio(debut))
    for nom, debut in (("playlist HLS", b"#EXTM3U\n#EXT-X-VERSION:3\n"), ("concat", b"ffconcat version 1.0\n"),
                       ("HTML", b"<html>"), ("vide", b"")):
        verifie(f"format refusé : {nom}", not app._signature_audio(debut))

    lancements: list = []
    lecture, execution = app.load_audio, app.subprocess.run

    def interdit(*args, **kwargs):
        lancements.append(args)
        raise AssertionError("décodage non autorisé")

    app.load_audio, app.subprocess.run = interdit, interdit
    try:
        with tempfile.TemporaryDirectory() as dossier:
            playlist = Path(dossier) / "piege.wav"
            playlist.write_bytes(b"#EXTM3U\n#EXTINF:1,\nfile:///etc/passwd\n")
            long_wav = Path(dossier) / "long.wav"
            with wave.open(str(long_wav), "wb") as sortie:
                sortie.setnchannels(1)
                sortie.setsampwidth(2)
                sortie.setframerate(8_000)
                sortie.writeframes(b"\0\0" * 8_000 * 40)
            messages = []
            for chemin in (playlist, long_wav):
                try:
                    app._decoder_audio(str(chemin))
                    messages.append("accepté")
                except app.AudioRefuse as exc:
                    messages.append(str(exc))
    finally:
        app.load_audio, app.subprocess.run = lecture, execution
    verifie("playlist déguisée : refusée sans lancer ffmpeg",
            messages[0] == app.MESSAGE_AUDIO_FORMAT and not lancements, (messages, lancements))
    verifie("audio trop long : refusé avant décompression",
            messages[1] == app.MESSAGE_AUDIO_TROP_LONG and not lancements, (messages, lancements))

    source = (RACINE / "app.py").read_text(encoding="utf-8")
    verifie("Gradio borne les fichiers et la file d'attente",
            "max_file_size=2 * TAILLE_MAX_AUDIO" in source and "queue(max_size=TAILLE_FILE_ATTENTE)" in source)

    # Plafond du LLM : la recherche continue en local.
    instant = [0.0]
    limite = LimiteDebit(2, 3, horloge=lambda: instant[0])
    suite = [limite.autoriser() for _ in range(3)]
    instant[0] = 61.0
    apres_minute = [limite.autoriser(), limite.autoriser()]
    instant[0] = 86_401.0
    verifie("plafond par minute puis par jour",
            suite == [True, True, False] and apres_minute == [True, False] and limite.autoriser(),
            (suite, apres_minute))
    os.environ["ESSAI_PLAFOND"] = "abc"
    verifie("réglage invalide : valeur par défaut", entier_env("ESSAI_PLAFOND", 7) == 7)
    del os.environ["ESSAI_PLAFOND"]

    appels_llm: list = []
    plafond, extraction = app.LIMITE_LLM, app.extract_intent
    app.LIMITE_LLM = LimiteDebit(1, 1, horloge=lambda: 0.0)
    app.LIMITE_LLM.autoriser()
    app.extract_intent = lambda *a, **k: appels_llm.append(a) or {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            sortie, _ = app._pipeline("phrase sans lieu connu du tout", "", 0.0)
    finally:
        app.LIMITE_LLM, app.extract_intent = plafond, extraction
    verifie("plafond atteint : pas d'appel LLM, réponse quand même",
            not appels_llm and sortie[0] == "phrase sans lieu connu du tout", appels_llm)

    # Le journal de l'ASR ne recopie pas le message de l'erreur.
    essais: list = []

    def modele(entree, generate_kwargs=None):
        essais.append(entree)
        if len(essais) == 1:
            raise ValueError("phrase-de-usager")
        return {"text": "ok"}

    journal = io.StringIO()
    with contextlib.redirect_stdout(journal):
        texte = transcribe.transcrire(modele, [0.0] * 16_000)
    verifie("ASR : second essai sans recopier l'erreur",
            texte == "ok" and "phrase-de-usager" not in journal.getvalue(), journal.getvalue())

    # L'envoi ne retombe jamais sur un autre jeton.
    avant = os.environ.pop("HF_TOKEN_COLLECTE", None)
    try:
        collecte.televerser_hf({"donnees/GM-AAAAAA/avis.json": b"{}"})
        refuse = False
    except PermissionError:
        refuse = True
    finally:
        if avant is not None:
            os.environ["HF_TOKEN_COLLECTE"] = avant
    verifie("envoi sans jeton dédié : refusé avant tout appel", refuse)

    # Suppression : un objet LFS partagé avec un autre code est conservé.
    script = _charger_module(RACINE / "scripts" / "supprimer_enregistrement.py", "supprimer_revue")

    class ApiPartagee:
        def __init__(self):
            self.purges: list = []

        def list_repo_tree(self, depot, recursive=False, repo_type=None):
            lfs = types.SimpleNamespace(sha256="meme-audio")
            return [types.SimpleNamespace(path="donnees/GM-AAAAAA/audio.wav", lfs=lfs),
                    types.SimpleNamespace(path="donnees/GM-BBBBBB/audio.wav", lfs=lfs)]

        def list_lfs_files(self, depot, repo_type=None):
            return [types.SimpleNamespace(filename="donnees/GM-AAAAAA/audio.wav", file_oid="meme-audio")]

        def delete_folder(self, *a, **k):
            pass

        def permanently_delete_lfs_files(self, depot, fichiers, **k):
            self.purges.extend(fichiers)

        def super_squash_history(self, *a, **k):
            pass

    api = ApiPartagee()
    with contextlib.redirect_stdout(io.StringIO()):
        script.supprimer(api, "GM-AAAAAA", executer=True)
    verifie("suppression : audio identique d'un autre code conservé", not api.purges, api.purges)
    return echecs, total


def test_lot_b5() -> tuple[int, int]:
    """Lot B5 : Express AIBD ajoutée (fiche officielle), Corniche Ouest de la TO1 sans faux point.

    Express AIBD : demdikk.sn/offres-de-transport donne une navette HLM Grand-Yoff
    (en face du stade Léopold Sédar Senghor) -> AIBD par l'autoroute, sans arrêt.
    Elle n'était dans aucun fichier chargé : « Grand Yoff -> AIBD » ne proposait
    que le TAF TAF. TO1 : « Corniche ouest » était géocodée au Palais de Justice
    (Cap Manuel), à ~8 km du Monument de la Renaissance.
    Aucun réseau : moteur hors ligne, points des CSV seulement.
    """
    import os

    from matching.itineraires_app import CATEGORIE_SANS_ARRET, lignes_ddd_ajoutees, rangees_ddd_officielles
    from matching.lieux import aeroport_ambigu
    from routing import adapter
    from routing.network import haversine_m

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot B5 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # 1. La fiche : deux arrêts, HLM Grand Yoff à sa position « bonne » d'arrets_geo.csv.
    express = {f["ligne"]: f for f in lignes_ddd_ajoutees()}.get("Express AIBD")
    verifie("Express AIBD lue dans lignes_ddd_ajoutees.csv", express is not None)
    if express is not None:
        arrets = [r["arret"] for r in express["rangees"]]
        verifie(
            "Express AIBD : deux arrêts, HLM Grand Yoff (stade LSS) puis AIBD",
            arrets == ["Terminus HLM Grand Yoff (Stade Léopold Sédar Senghor)", "AIBD"],
            arrets,
        )
        depart = express["rangees"][0]
        verifie(
            "HLM Grand Yoff : position « bonne » d'arrets_geo.csv, jamais devinée",
            (depart["lat"], depart["lon"], depart["source"]) == ("14.741372", "-17.455863", "arrets_geo_bonne"),
            depart,
        )
        verifie("Express AIBD : pas « à confirmer » (les deux terminus sont situés)", express["statut"] == "", express)
        verifie(
            "Express AIBD : affichée « navette express, sans arrêt »",
            express["categorie"] == CATEGORIE_SANS_ARRET and "sans arrêt" in CATEGORIE_SANS_ARRET.lower(),
            express["categorie"],
        )

    # 2. Le moteur la propose, sans durée inventée.
    if os.getenv("GUINDIMA_MOTEUR", "v2").strip().lower() != "v1":
        matcher = _matcher_hors_ligne()
        for depart, arrivee in (
            ("Grand Yoff", "AIBD"),
            ("Stade Léopold Sédar Senghor", "aéroport Blaise Diagne"),
        ):
            resultat = matcher.find_line(depart, arrivee)
            options = [l for l in resultat.get("lignes") or [] if l.get("ligne") == "Express AIBD"]
            verifie(f"{depart} -> {arrivee} : Express AIBD proposée", bool(options), _detail(resultat))
            if options:
                carte = options[0]
                verifie(
                    f"{depart} -> {arrivee} : « sans arrêt », pas de durée inventée",
                    carte.get("categorie") == CATEGORIE_SANS_ARRET
                    and carte.get("minutes") is None
                    and carte.get("duree_inconnue") is True,
                    carte,
                )
                verifie(
                    f"{depart} -> {arrivee} : descente à l'AIBD, jamais à l'ancien aéroport",
                    carte.get("descend_a_reseau") == "AIBD",
                    carte,
                )

        # « aéroport » seul : toujours la question entre les deux aéroports.
        verifie("« aéroport » seul reste ambigu", aeroport_ambigu("aéroport"))
        deux = adapter.deux_aeroports(matcher.find_line, "Stade Léopold Sédar Senghor", "aéroport")
        lieux = [p["lieu"] for p in (deux or {}).get("lieux_possibles") or []]
        verifie(
            "Stade LSS -> « aéroport » : les deux aéroports proposés",
            len(lieux) == 2 and "AIBD" in lieux,
            lieux,
        )

    # 3. TO1 : plus aucun point au Palais de Justice.
    palais_de_justice = (14.670351, -17.443821)
    corniche = [
        r for r in rangees_ddd_officielles()
        if r["ligne"] == "TAF TAF OUAKAM (TO1)" and r["arret"] == "Corniche ouest"
    ]
    verifie(
        "TO1 : « Corniche ouest » gardée, position retirée (à confirmer)",
        len(corniche) == 1 and not corniche[0]["lat"] and corniche[0]["source"] == "inconnu",
        corniche,
    )
    positions = adapter._NETWORK.line_positions.get(("Dakar Dem Dikk", "TAF TAF OUAKAM (TO1)")) or ()
    # 100 m : l'arrêt officiel suivant, « Avenue Peytavin », est à ~380 m du
    # Palais de Justice, à sa vraie place ; seul le point de la Corniche y était posé.
    loin = all(p is None or haversine_m(p, palais_de_justice) > 100 for p in positions)
    verifie(
        "TO1 ne passe plus par le Palais de Justice",
        len(positions) == 10 and positions[3] is None and loin,
        positions,
    )
    return echecs, total


def test_lot_f4() -> tuple[int, int]:
    """Lot F4 : positions devinées. Aucun réseau (moteur hors ligne, CSV seulement).

    - data/corrections/positions_corrigees.csv : position retrouvée dans le dépôt
      (arrêt OSM nommé, arrêt identique « bonne », repère de Diass pour l'AIBD),
      appliquée à chaque ligne qui porte le nom ;
    - data/corrections/positions_estimees.csv : « bonne » mais non crue (Avenue
      Cheikh Anta Diop, voie de 5 km ; Apix, agence du Plateau) ;
    - une position estimée n'affirme jamais un « arrêt conseillé » ni une durée ;
      un arrêt demandé par son nom est toujours nommé (« Maristes »).
    """
    import csv
    import os

    from matching.geo import LieuxGeo
    from matching.itineraires_app import cle_lieu
    from routing import adapter
    from routing.network import haversine_m

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot F4 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    reseau = adapter._NETWORK
    dossier = RACINE / "data" / "corrections"
    with open(dossier / "positions_corrigees.csv", newline="", encoding="utf-8") as f:
        corrigees = list(csv.DictReader(f))
    with open(dossier / "positions_estimees.csv", newline="", encoding="utf-8") as f:
        estimees = list(csv.DictReader(f))

    def places_du_nom(nom: str) -> list:
        cle = cle_lieu(nom)
        return [
            (ligne, i)
            for ligne in reseau.lines.values()
            for i, arret in enumerate(ligne.stops)
            if cle_lieu(arret) == cle
        ]

    # 1. Chaque position corrigée : sur toutes les lignes qui portent ce nom, sûre.
    for rangee in corrigees:
        point = (float(rangee["lat"]), float(rangee["lon"]))
        places = places_du_nom(rangee["arret"])
        bonnes = all(
            reseau.position_sure(ligne, i)
            and haversine_m(reseau.position_on_line(ligne, i), point) < 1
            for ligne, i in places
        )
        verifie(
            f"position corrigée « {rangee['arret']} » sur ses {len(places)} ligne(s), sûre",
            bool(places) and bonnes,
            [(l.name, reseau.position_on_line(l, i), reseau.position_sure(l, i)) for l, i in places],
        )

    # 2. AIBD : à Diass, plus jamais à Grand Yoff (arrets_geo.csv et lieux_geo.csv).
    diass, grand_yoff = (14.67, -17.0733), (14.745133, -17.468034)
    verifie(
        "AIBD : position du réseau à Diass, « bonne »",
        reseau.coords("AIBD") == diass and reseau.stop_confidence.get("AIBD") == "bonne",
        (reseau.coords("AIBD"), reseau.stop_confidence.get("AIBD")),
    )
    geo = LieuxGeo()
    point_aibd = geo.point_connu("AIBD")
    verifie(
        "AIBD : point du lieu (geo.py) à Diass, loin de Grand Yoff",
        point_aibd is not None
        and haversine_m(point_aibd, diass) < 1
        and haversine_m(point_aibd, grand_yoff) > 30_000,
        point_aibd,
    )

    # 3. Positions estimées : jamais sûres, jamais « bonne », jamais un arrêt conseillé.
    for rangee in estimees:
        places = places_du_nom(rangee["arret"])
        noms = {ligne.stops[i] for ligne, i in places}
        verifie(
            f"« {rangee['arret']} » estimée : ni sûre sur une ligne, ni « bonne »",
            bool(places)
            and not any(reseau.position_sure(ligne, i) for ligne, i in places)
            and all(reseau.stop_confidence.get(nom) != "bonne" for nom in noms),
            [(l.name, reseau.position_sure(l, i)) for l, i in places],
        )
        nom = sorted(noms)[0] if noms else rangee["arret"]
        coords = reseau.coords(nom)
        lieu = {"nom_exact": set(), "nom_demande": set(), "point_sur": coords}
        verifie(
            f"« {nom} » estimée : jamais « arrêt conseillé » (cherche l'arrêt le plus proche)",
            coords is not None and adapter._vague(lieu, nom),
            coords,
        )
    verifie(
        "geo.py : Avenue Cheikh Anta Diop n'est plus « bonne » (pas de proximité)",
        not geo.position_sure("Avenue Cheikh Anta Diop"),
    )

    # 4. Dem Dikk 327 : APIX et le croisement de Tivaouane Peulh ne sont plus au même point.
    ligne_327 = reseau.lines[("Dakar Dem Dikk", "Ligne 327")]
    i_apix = ligne_327.stops.index("Apix")
    apix = reseau.position_on_line(ligne_327, i_apix)
    croisement = reseau.position_on_line(
        ligne_327, ligne_327.stops.index("Croissement Tivaoune Peulh")
    )
    verifie(
        "327 : croisement de Tivaouane Peulh à l'arrêt OSM, APIX ailleurs et estimée",
        croisement == (14.786355, -17.294528)
        and apix != croisement
        and not reseau.position_sure(ligne_327, i_apix),
        (apix, croisement),
    )

    if os.getenv("GUINDIMA_MOTEUR", "v2").strip().lower() == "v1":
        return echecs, total
    matcher = _matcher_hors_ligne()

    def directs(depart: str, arrivee: str) -> dict:
        return {l["ligne"]: l for l in matcher.find_line(depart, arrivee).get("lignes") or []}

    # 5. Arrêt demandé par son nom : nommé, jamais « cherche l'arrêt le plus proche ».
    maristes = directs("Guédiawaye", "Maristes").get("Ligne 37")
    verifie(
        "Guédiawaye -> Maristes : Tata 37 nomme « Maristes (Par Station Titan) »",
        maristes is not None
        and maristes["descend_a_reseau"] == "Maristes (Par Station Titan)"
        and not maristes.get("descend_a_vague"),
        maristes,
    )
    # Un lien de lieu ne vaut pas un nom demandé : « UCAD » ne fait pas conseiller
    # l'Avenue Cheikh Anta Diop (voie de 5 km, position estimée).
    ucad = directs("Parcelles Assainies", "UCAD").get("Ligne 25")
    verifie(
        "Parcelles Assainies -> UCAD : Avenue Cheikh Anta Diop jamais conseillée",
        ucad is None
        or ucad["descend_a_reseau"] != "Avenue Cheikh Anta Diop"
        or ucad.get("descend_a_vague"),
        ucad,
    )
    verifie(
        "nom demandé : « Pikine Texaco » ne vaut pas « Pikine », les parenthèses et orthographes oui",
        not adapter._nom_demande("Pikine", "Pikine Texaco")
        and adapter._nom_demande("Maristes", "Maristes (Par Station Titan)")
        and adapter._nom_demande("Sapeurs Pompiers", "Dieuppeul (Sapeurs Pompiers)")
        and adapter._nom_demande("Fass Mbao", "Fassmbao"),
    )

    # 6. Durée : un arrêt deviné loin de tout voisin mesuré ne donne pas de chiffre.
    sips = directs("Malika", "Pikine").get("Ligne 16B")
    verifie(
        "Malika -> Pikine : Dem Dikk 16B jusqu'à SIPS (position devinée) sans durée",
        sips is not None and sips.get("minutes") is None and sips.get("duree_inconnue") is True,
        sips,
    )

    # 7. Trajets démo : mêmes lignes qu'avant le lot F4.
    for depart, arrivee, attendue in (
        ("Ouakam", "Petersen", "Ligne 3"),
        ("Médina", "Guédiawaye", "Ligne 12"),
        ("Guédiawaye", "Maristes", "Ligne 37"),
        ("Malika", "Pikine", "Ligne 80"),
        ("Sapeur Pompiers", "Sandaga", "Ligne 1"),
    ):
        trouvees = directs(depart, arrivee)
        verifie(
            f"démo {depart} -> {arrivee} : {attendue} toujours proposée",
            attendue in trouvees,
            sorted(trouvees),
        )
    sandaga = directs("Sapeur Pompiers", "Sandaga").get("Ligne 1") or {}
    verifie(
        "démo Sapeur Pompiers -> Sandaga : montée et descente nommées, durée donnée",
        not sandaga.get("monte_a_vague")
        and not sandaga.get("descend_a_vague")
        and sandaga.get("minutes"),
        sandaga,
    )
    return echecs, total


def test_plafonds_par_client() -> tuple[int, int]:
    """Plafonds par client (trajets, LLM, collecte), sans réseau ni modèle."""
    import contextlib
    import io
    import json
    import types

    import gradio as gr
    import numpy as np
    from gradio.helpers import special_args

    from app import collecte, limites
    from app.limites import HEURE, JOUR, MINUTE, LimiteFenetres, LimiteParClient, cle_client

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | plafonds {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    def requete(ip: str = "203.0.113.7", entete: str | None = None):
        valeur = ip if entete is None else entete
        return types.SimpleNamespace(headers={"x-forwarded-for": valeur},
                                     client=types.SimpleNamespace(host="10.0.0.1"))

    class FauxCollecteur:
        def __init__(self):
            self.lots: list[dict] = []

        def soumettre(self, fichiers: dict) -> bool:
            self.lots.append(fichiers)
            return True

    # 1. Compteurs : fenêtres, clients séparés, mémoire bornée.
    instant = [0.0]
    limite = LimiteParClient(((MINUTE, 2), (JOUR, 3)), horloge=lambda: instant[0])
    verifie("par minute : le 3e appel est refusé",
            [limite.autoriser("a") for _ in range(3)] == [True, True, False])
    verifie("un autre client garde son quota", limite.autoriser("b"))
    instant[0] = 61.0
    verifie("par jour : la minute passée ne rend que le quota du jour",
            [limite.autoriser("a"), limite.autoriser("a")] == [True, False])
    instant[0] = JOUR + 62.0
    verifie("le lendemain, le client repart de zéro", limite.autoriser("a"))
    verifie("sans client identifié, rien n'est compté", limite.autoriser(None))
    petite = LimiteParClient(((MINUTE, 1),), max_clients=3)
    for numero in range(50):
        petite.autoriser(f"client-{numero}")
    verifie("mémoire bornée face à des adresses inventées", len(petite._clients) == 3)

    # 2. Identification : empreinte salée, adresse jamais visible.
    ip_a, ip_b = "203.0.113.7", "198.51.100.9"
    os.environ.pop("IP_PROXYS_CONFIANCE", None)
    journal = io.StringIO()
    limites._FORMES_SIGNALEES.clear()
    with contextlib.redirect_stdout(journal):
        cle_a = cle_client(requete(ip_a))
        cle_b = cle_client(requete(ip_b))
    verifie("même adresse, même empreinte", cle_a == silencieux_cle(cle_client, requete(ip_a)))
    verifie("adresses différentes, empreintes différentes", cle_a != cle_b)
    verifie("l'empreinte ne contient pas l'adresse", ip_a not in cle_a and len(cle_a) == 32)
    verifie("journal : ni adresse ni empreinte",
            ip_a not in journal.getvalue() and cle_a not in journal.getvalue(), journal.getvalue())
    verifie("sans requête : aucun client", cle_client(None) is None)
    chaine = f"{ip_a}, {ip_b}"
    verifie("par défaut : première adresse de la liste",
            silencieux_cle(cle_client, requete(entete=chaine)) == cle_a)
    os.environ["IP_PROXYS_CONFIANCE"] = "1"
    verifie("IP_PROXYS_CONFIANCE=1 : adresse vue par le dernier proxy",
            silencieux_cle(cle_client, requete(entete=chaine)) == cle_b)
    del os.environ["IP_PROXYS_CONFIANCE"]
    hote = silencieux_cle(cle_client, types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="10.0.0.1")))
    verifie("adresse fantaisiste : on retombe sur la connexion",
            silencieux_cle(cle_client, requete(entete="pas-une-ip")) == hote)
    verifie("IPv6 : tout le /64 compte pour un client",
            silencieux_cle(cle_client, requete("2001:db8:1:2::1")) == silencieux_cle(cle_client, requete("2001:db8:1:2::ffff")))

    # 3. L'application.
    variables = ("COLLECTE_ACTIVE", "HF_TOKEN_COLLECTE", "CONTACT_WHATSAPP")
    avant = {nom: os.environ.get(nom) for nom in variables}
    sauve = (collecte.COLLECTEUR, collecte.LIMITE_VOIX_CLIENT, collecte.LIMITE_VOIX_JOUR, collecte.LIMITE_AVIS_CLIENT)
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    os.environ["COLLECTE_ACTIVE"] = "1"
    PHRASE = "maa ngi Liberté 6, bëgg naa dem Palais"
    INCONNUE = "phrase sans lieu connu du tout"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            app = _charger_module(RACINE / "app.py", "app_guindima_plafonds")
        repli = getattr(app.MATCHER, "_repli", app.MATCHER)
        repli.geo.point = repli.geo.point_connu
        son = [np.full(16_000, 0.1, dtype=np.float32)]
        effaces: list = []
        transcriptions: list = []

        def transcrit(valeur, *_):
            transcriptions.append(1)
            return PHRASE, "Modèle test", 0.1, False

        app._decoder_audio = lambda chemin: son[0]
        app._effacer_audio_recu = lambda chemin: effaces.append(chemin) or True
        seconde_chance_reelle = app.transcrir_avec_seconde_chance
        app.transcrir_avec_seconde_chance = transcrit
        app._voix_wolof = lambda *a, **k: None
        app._client_llm = lambda: None

        def silencieux(fonction, *args, **kwargs):
            with contextlib.redirect_stdout(io.StringIO()):
                return fonction(*args, **kwargs)

        # Gradio doit bien remettre la requête à chaque handler branché.
        marque = object()
        for fonction, entrees in (
            (app.traiter_demande, 5), (app.rechercher_une_fois, 4), (app.choisir_trajet_frequent, 2),
            (app.repondre_et_vider_micro, 3), (app.traiter_demande_collecte, 6),
            (app.rechercher_une_fois_collecte, 5), (app.choisir_trajet_frequent_collecte, 3),
            (app.avis_oui, 2), (app.avis_non, 2), (app.avis_ne_sait_pas, 2), (app.donner_temps, 2),
        ):
            valeurs, *_ = special_args(fonction, [None] * entrees, marque)
            verifie(f"Gradio transmet la requête à {fonction.__name__}",
                    len(valeurs) == entrees + 1 and valeurs[-1] is marque, len(valeurs))

        # 4. Trajets : 10 par minute, puis message poli, sans travail inutile.
        app.LIMITE_TRAJETS_CLIENT = LimiteParClient(((MINUTE, 2), (JOUR, 100)))
        client, autre = requete(ip_a), requete(ip_b)
        premiers = [silencieux(app.traiter_demande, None, PHRASE, "", None, True, client) for _ in range(2)]
        transcriptions.clear()
        effaces.clear()
        refus = silencieux(app.traiter_demande, "x.webm", "", "", {"phrase": PHRASE, "mode": "texte"}, True, client)
        verifie("sous le plafond : réponses normales", all(s[0] == PHRASE for s in premiers))
        verifie("au-delà : message poli en français", refus[2] == app.CARTE_TROP_DE_DEMANDES and "réessayer" in refus[2], refus[2])
        verifie("refus : aucune transcription lancée", not transcriptions)
        verifie("refus : l'audio reçu est effacé", effaces == ["x.webm"], effaces)
        verifie("refus : la dernière demande reste connue", refus[6] == {"phrase": PHRASE, "mode": "texte"}, refus[6])
        verifie("refus : 7 sorties, micro vidé", len(refus) == 7 and refus[5] is None)
        verifie("un autre client n'est pas touché",
                silencieux(app.traiter_demande, None, PHRASE, "", None, True, autre)[0] == PHRASE)
        verifie("appel interne sans requête : non limité",
                silencieux(app.traiter_demande, None, PHRASE, "", None, True)[0] == PHRASE)
        vide = silencieux(app.traiter_demande, None, "", "", None, True, client)
        verifie("champ vide : pas de message de plafond", vide[2] != app.CARTE_TROP_DE_DEMANDES)
        verifie("API publique : même plafond",
                silencieux(app.repondre_et_vider_micro, None, PHRASE, "", client)[2] == app.CARTE_TROP_DE_DEMANDES)
        changement = silencieux(app.traiter_demande, None, "", "Tata AFTU", {"phrase": PHRASE, "mode": "texte"}, False, client)
        verifie("changement de compagnie : compté aussi", changement[2] == app.CARTE_TROP_DE_DEMANDES)
        app.LIMITE_TRAJETS_CLIENT = LimiteParClient(((MINUTE, 50), (JOUR, 2)))
        for _ in range(2):
            silencieux(app.traiter_demande, None, PHRASE, "", None, True, client)
        verifie("plafond par jour",
                silencieux(app.traiter_demande, None, PHRASE, "", None, True, client)[2] == app.CARTE_TROP_DE_DEMANDES)
        verifie("valeurs par défaut : 10 par minute, 100 par jour",
                silencieux(lambda: _charger_module(RACINE / "app.py", "app_plafonds_defaut")).LIMITE_TRAJETS_CLIENT.fenetres
                == ((MINUTE, 10), (JOUR, 100)))

        # 5. LLM : compté par client, plafond global conservé.
        app.LIMITE_TRAJETS_CLIENT = LimiteParClient(((MINUTE, 100), (JOUR, 1000)))
        appels: list = []
        app.extract_intent = lambda phrase, client=None: appels.append(phrase) or {
            "depart": "", "arrivee": "", "compagnie": "", "erreur": None, "source": "llm"}
        app.LIMITE_LLM_CLIENT = LimiteParClient(((MINUTE, 1), (JOUR, 50)))
        app.LIMITE_LLM = limites.LimiteDebit(100, 1000)
        for _ in range(3):
            sortie = silencieux(app.traiter_demande, None, INCONNUE, "", None, True, client)
        verifie("LLM : un seul appel pour ce client", len(appels) == 1, len(appels))
        verifie("LLM refusé : la réponse part quand même", sortie[0] == INCONNUE, sortie[0])
        silencieux(app.traiter_demande, None, INCONNUE, "", None, True, autre)
        verifie("LLM : un autre client garde le sien", len(appels) == 2, len(appels))
        verifie("le client n'est plus connu après la demande", app._CLE_CLIENT.get() is None)
        appels.clear()
        app.LIMITE_LLM_CLIENT = LimiteParClient(((MINUTE, 100), (JOUR, 100)))
        app.LIMITE_LLM = limites.LimiteDebit(1, 1000)
        silencieux(app.traiter_demande, None, INCONNUE, "", None, True, client)
        silencieux(app.traiter_demande, None, INCONNUE, "", None, True, autre)
        verifie("plafond global du LLM conservé", len(appels) == 1, len(appels))

        # 6. Collecte : 15 voix par heure et par client, 200 par jour, 20 s.
        os.environ["HF_TOKEN_COLLECTE"] = "jeton-de-test"
        faux = collecte.COLLECTEUR = FauxCollecteur()
        collecte.LIMITE_VOIX_CLIENT = LimiteParClient(((HEURE, 2),))
        collecte.LIMITE_VOIX_JOUR = LimiteFenetres(((JOUR, 3),))

        def voix(req):
            return silencieux(app.traiter_demande_collecte, "x.webm", "", "", None, True, None, req)

        sorties = [voix(client) for _ in range(3)]
        verifie("voix : 2 gardées pour ce client, pas la 3e", len(faux.lots) == 2, len(faux.lots))
        verifie("voix au-delà : réponse normale", sorties[2][0] == PHRASE and "Ligne :" in sorties[2][2])
        verifie("voix au-delà : ni code ni explication",
                sorties[2][9] == "" and sorties[2][7]["voix"] is False, sorties[2][9])
        verifie("voix au-delà : le panneau d'avis reste", sorties[2][8].get("visible") is True)
        voix(autre)
        verifie("voix : un autre client passe", len(faux.lots) == 3, len(faux.lots))
        troisieme = voix(requete("192.0.2.5"))
        verifie("plafond du jour : plus rien n'est gardé",
                len(faux.lots) == 3 and troisieme[0] == PHRASE and troisieme[9] == "", len(faux.lots))
        contenu = b"".join(o for lot in faux.lots for c, o in lot.items() if c.endswith(".json")).decode("utf-8")
        cles = {silencieux_cle(cle_client, client), silencieux_cle(cle_client, autre)}
        verifie("ni adresse ni empreinte dans les fiches",
                not any(x in contenu for x in (ip_a, ip_b, *cles)), contenu[:200])
        verifie("ni adresse ni empreinte dans le suivi",
                not any(x in json.dumps(sorties[0][7]) for x in (ip_a, ip_b, *cles)), sorties[0][7])

        faux = collecte.COLLECTEUR = FauxCollecteur()
        collecte.LIMITE_VOIX_CLIENT = LimiteParClient(((HEURE, 5),))
        collecte.LIMITE_VOIX_JOUR = LimiteFenetres(((JOUR, 200),))
        son[0] = np.zeros(21 * 16_000, dtype=np.float32)
        longue = voix(client)
        verifie("voix de 21 s : réponse normale, rien de gardé",
                not faux.lots and longue[0] == PHRASE and longue[9] == "", faux.lots)
        verifie("voix trop longue : le quota n'est pas entamé", not collecte.LIMITE_VOIX_CLIENT._clients)
        son[0] = np.zeros(20 * 16_000, dtype=np.float32)
        voix(client)
        verifie("voix de 20 s : gardée", len(faux.lots) == 1, len(faux.lots))

        # Test public : 6 vocaux en moins d'une heure depuis un même wifi (PC +
        # téléphone), plus aucun code, et rien dans le journal pour le dire.
        # Désormais 15 par heure, et le refus s'écrit au journal.
        faux = collecte.COLLECTEUR = FauxCollecteur()
        collecte.LIMITE_VOIX_CLIENT = LimiteParClient(((HEURE, 15),))
        son[0] = np.full(3 * 16_000, 0.1, dtype=np.float32)
        maison = requete("198.51.100.7")
        journal = io.StringIO()
        with contextlib.redirect_stdout(journal):
            serie = [app.traiter_demande_collecte("x.webm", "", "", None, True, None, maison)
                     for _ in range(16)]
        codes = [s[9] for s in serie]
        verifie("6e voix dans l'heure : code affiché", "GM-" in codes[5], codes[5])
        verifie("voix 1 à 15 : un code chacune", all("GM-" in c for c in codes[:15]),
                [i for i, c in enumerate(codes) if "GM-" not in c])
        verifie("16e voix : réponse normale, pas de code",
                codes[15] == "" and serie[15][0] == PHRASE and serie[15][7]["voix"] is False, codes[15])
        texte_journal = journal.getvalue()
        verifie("journal : 15 voix en file, avec leur code",
                texte_journal.count("[collecte] en file GM-") == 15
                and all(s[7]["code"] in texte_journal for s in serie[:15]), texte_journal[-300:])
        verifie("journal : la limite atteinte est nommée",
                texte_journal.count("[collecte] ignorée : limite par client et par heure atteinte") == 1,
                texte_journal[-300:])
        verifie("journal : ni adresse ni phrase",
                "198.51.100.7" not in texte_journal and silencieux_cle(cle_client, maison) not in texte_journal
                and not any(PHRASE in l for l in texte_journal.splitlines() if l.startswith("[collecte]")),
                texte_journal[-300:])

        # Le chemin CPU n'empêche pas la collecte : GPU refusé, whisper répond,
        # la voix est gardée avec le nom du modèle CPU.
        faux = collecte.COLLECTEUR = FauxCollecteur()
        gpu, cpu = app.transcrire_wolof, app._transcrire_cpu

        def gpu_refuse(_audio):
            raise RuntimeError("You have exceeded your GPU quota")

        app.transcrir_avec_seconde_chance = seconde_chance_reelle
        app.transcrire_wolof, app._transcrire_cpu = gpu_refuse, lambda audio: PHRASE
        try:
            secours = voix(requete("198.51.100.8"))
        finally:
            app.transcrir_avec_seconde_chance = transcrit
            app.transcrire_wolof, app._transcrire_cpu = gpu, cpu
        fiche_cpu = json.loads(next(o for c, o in faux.lots[0].items() if c.endswith("demande.json")))
        verifie("GPU refusé : whisper CPU, code affiché, voix gardée",
                secours[0] == PHRASE and "GM-" in secours[9] and len(faux.lots) == 1
                and "Kiriku" not in fiche_cpu["modele_asr"] and fiche_cpu["modele_asr"], fiche_cpu)

        # Envoi : le nombre de dossiers (contributions), pas les codes.
        os.environ["HF_TOKEN_COLLECTE"] = "jeton-de-test"
        envoyes: list = []
        reel = collecte.Collecteur(televerser=envoyes.append, intervalle=3600)
        journal = io.StringIO()
        with contextlib.redirect_stdout(journal):
            reel.soumettre({"donnees/GM-AAAAAA/audio.wav": b"1", "donnees/GM-AAAAAA/demande.json": b"{}"})
            reel.soumettre({"donnees/GM-BBBBBB/avis.json": b"{}"})
            reel.vider()
        reel.arreter()
        verifie("journal : envoi de 2 dossier(s), sans code",
                "[collecte] envoi : 2 dossier(s)" in journal.getvalue() and "GM-" not in journal.getvalue(),
                journal.getvalue())

        collecte.LIMITE_AVIS_CLIENT = LimiteParClient(((HEURE, 1),))
        faux = collecte.COLLECTEUR = FauxCollecteur()
        suivi = {"code": "GM-AAAAAA", "depart": "A", "arrivee": "B", "lignes": ["L"],
                 "voix": False, "reponse": None, "minutes": None}
        silencieux(app.avis_oui, None, suivi, client)
        second = silencieux(app.avis_non, None, suivi, client)
        verifie("avis : plafond par client, sans message",
                len(faux.lots) == 1 and second == (gr.skip(), gr.skip()), second)

        # 7. Tous les seuils se règlent par variable d'environnement.
        reglages = {"COLLECTE_MAX_PAR_CLIENT_HEURE": "7", "COLLECTE_MAX_PAR_JOUR": "11",
                    "COLLECTE_DUREE_MAX_S": "9", "COLLECTE_AVIS_MAX_PAR_CLIENT_HEURE": "4",
                    "TRAJETS_MAX_PAR_MINUTE": "3", "TRAJETS_MAX_PAR_JOUR": "6",
                    "LLM_MAX_PAR_CLIENT_MINUTE": "2", "LLM_MAX_PAR_CLIENT_JOUR": "8"}
        os.environ.update(reglages)
        try:
            module = _charger_module(RACINE / "src" / "app" / "collecte.py", "collecte_reglee")
            regle = silencieux(lambda: _charger_module(RACINE / "app.py", "app_plafonds_regle"))
        finally:
            for nom in reglages:
                os.environ.pop(nom, None)
        verifie("collecte réglable",
                module.LIMITE_VOIX_CLIENT.fenetres == ((HEURE, 7),)
                and module.LIMITE_VOIX_JOUR.fenetres == ((JOUR, 11),)
                and module.DUREE_MAX_VOIX_S == 9 and module.LIMITE_AVIS_CLIENT.fenetres == ((HEURE, 4),))
        verifie("trajets et LLM réglables",
                regle.LIMITE_TRAJETS_CLIENT.fenetres == ((MINUTE, 3), (JOUR, 6))
                and regle.LIMITE_LLM_CLIENT.fenetres == ((MINUTE, 2), (JOUR, 8)))
        verifie("collecte : valeurs par défaut demandées",
                sauve[1].fenetres == ((HEURE, 15),) and sauve[2].fenetres == ((JOUR, 200),)
                and collecte.DUREE_MAX_VOIX_S == 20)
    finally:
        collecte.COLLECTEUR, collecte.LIMITE_VOIX_CLIENT, collecte.LIMITE_VOIX_JOUR, collecte.LIMITE_AVIS_CLIENT = sauve
        for nom, valeur in avant.items():
            if valeur is None:
                os.environ.pop(nom, None)
            else:
                os.environ[nom] = valeur
    return echecs, total


def silencieux_cle(fonction, requete):
    """Calcule une empreinte sans le message de diagnostic du journal."""
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        return fonction(requete)


def test_lot_20_11() -> tuple[int, int]:
    """Retours des testeurs du 20/11, sans réseau ni modèle.

    - spaces jamais épinglé : ZeroGPU impose sa version (0.52.1 au 20/11), un
      pin 0.51.3 faisait échouer le build ; la panne « No CUDA GPUs » se teste
      donc par une durée GPU fixe de 20 s ;
    - « maa ngi yambël / yambal / yambal yambal » = Yeumbeul ;
    - un seul lieu après « dem » : arrivée seulement, l'app demande le départ,
      même quand le LLM recopie ce lieu des deux côtés ; jamais « même lieu ».
    """
    import contextlib
    import io
    import os

    from intent.extract_intent import extract_intent, extract_local

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot 20/11 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    # 1. ZeroGPU : aucune version de spaces imposée, durée GPU fixe.
    requirements = (RACINE / "requirements.txt").read_text(encoding="utf-8-sig")
    paquets = [
        ligne.split("#", 1)[0].strip()
        for ligne in requirements.splitlines()
        if ligne.split("#", 1)[0].strip()
    ]
    verifie("spaces jamais épinglé (ZeroGPU impose sa version)",
            not any(re.match(r"(?i)^spaces\s*[<>=!~]", p) for p in paquets), paquets)
    source_app = (RACINE / "app.py").read_text(encoding="utf-8")
    verifie("durée GPU fixe de 20 s, _duree_gpu gardée mais débranchée",
            "@spaces.GPU(duration=20)\ndef transcrire_wolof" in source_app
            and "def _duree_gpu" in source_app
            and "Désactivée le 20/11 : test de la panne No CUDA GPUs" in source_app
            and "duration=_duree_gpu" not in source_app)

    # 2. Yeumbeul sous ses formes parlées, phrases réelles des testeurs.
    reelles = (
        "maa ngi yambël, dama bëgg dem Grand Yoff",
        "maa ngi yambal, dama bëgg dem Grand Yoff",
        "maa ngi yambal yambal, dama bëgg dem Grand Yoff",
    )
    for phrase in reelles:
        local = extract_local(phrase)
        verifie(f"« {phrase} » : Yeumbeul -> Grand-Yoff",
                (local["depart"], local["arrivee"]) == ("Yeumbeul", "Grand-Yoff"), local)
    for forme in ("yembeul", "yeumbeul", "yeumbël", "yembal"):
        local = extract_local(f"maa ngi {forme}, dama bëgg dem Grand Yoff")
        verifie(f"« {forme} » = Yeumbeul", local["depart"] == "Yeumbeul", local)
    from matching.lieux import ALIAS
    verifie("alias LLM yambal / yambel -> yeumbeul",
            ALIAS.get("yambal") == "yeumbeul" and ALIAS.get("yambel") == "yeumbeul")

    # 3. Un seul lieu après « dem » : départ vide, même si le LLM le recopie.
    seuls = (
        ("man dgt waay dama bëgg dem mariste", "Maristes"),
        ("dama bëgg dem Grand Yoff", "Grand-Yoff"),
    )
    for phrase, arrivee in seuls:
        local = extract_local(phrase)
        verifie(f"« {phrase} » (local) : départ vide, arrivée {arrivee}",
                (local["depart"], local["arrivee"]) == ("", arrivee), local)
        client = _FauxClient(f'{{"depart": "{arrivee}", "arrivee": "{arrivee}"}}')
        with contextlib.redirect_stdout(io.StringIO()):
            intent = extract_intent(phrase, client=client)
        verifie(f"« {phrase} » (LLM doublon) : départ vide, arrivée {arrivee}",
                (intent["depart"], intent["arrivee"]) == ("", arrivee), intent)
    # Le même lieu vraiment dit deux fois reste tel quel (l'app redemande).
    client = _FauxClient('{"depart": "Petersen", "arrivee": "Petersen"}')
    with contextlib.redirect_stdout(io.StringIO()):
        intent = extract_intent("maa ngi Petersen, bëgg naa dem Petersen", client=client)
    verifie("Petersen dit deux fois : inchangé",
            (intent["depart"], intent["arrivee"]) == ("Petersen", "Petersen"), intent)

    # 4. Dans l'app : « lieu_manquant » avec la question sur le départ, jamais
    #    « même lieu » ; Yeumbeul -> Grand-Yoff donne un trajet.
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_lot_20_11")
    client_origine = app._client_llm

    def pipeline(phrase: str, client) -> tuple[str, bool, str]:
        app._client_llm = lambda: client
        tampon = io.StringIO()
        try:
            with contextlib.redirect_stdout(tampon):
                quint, trouve = app._pipeline(phrase, "Kiriku-Wolof-ASR (GPU)", 1.0)
        finally:
            app._client_llm = client_origine
        return quint[2], trouve, tampon.getvalue(), quint[3]

    for phrase, arrivee in seuls:
        client = _FauxClient(f'{{"depart": "{arrivee}", "arrivee": "{arrivee}"}}')
        carte, trouve, journal, voix = pipeline(phrase, client)
        verifie(f"« {phrase} » (app) : départ demandé, pas « même lieu »",
                not trouve
                and "erreur=lieu_manquant" in journal
                and "erreur=conversation_meme_lieu" not in journal
                and "d'où pars-tu" in carte
                and app._echapper_markdown(arrivee) in carte
                and voix is not None,
                (carte[:300], journal, voix))
    for phrase in reelles:
        carte, trouve, journal, _ = pipeline(
            phrase, _ClientQuiLeve(lambda: TimeoutError("ne doit pas être appelé")))
        verifie(f"« {phrase} » (app) : trajet trouvé sans LLM",
                trouve and "erreur=lieu_manquant" not in journal, (carte[:300], journal))

    return echecs, total


def test_zerogpu_cuda() -> tuple[int, int]:
    """Aucun appel CUDA hors de la fonction @spaces.GPU (panne du 20/11).

    Sur ZeroGPU, le 1er appel GPU marchait et les suivants échouaient sur « No
    CUDA GPUs are available ». Le processus principal ne doit jamais toucher
    CUDA pendant une requête : seuls le chargement au démarrage (schéma
    documenté de ZeroGPU) et transcrire_wolof y ont droit. Recherche dans le
    code exécuté au runtime (app.py, src/**), sans les commentaires.
    """
    import ast
    import contextlib
    import io
    import os
    import tokenize

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | zerogpu {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    motif_cuda = re.compile(
        r"torch\.cuda\b|\.cuda\(|torch\.device\(|device_map"
        r"|device\s*=\s*(?:0|[1-9]|['\"](?:cuda|auto))|\.to\(\s*['\"]cuda"
        r"|torch\.accelerator\b|['\"]cuda(?::\d)?['\"]"
    )
    # Fonctions où CUDA est permis : le calcul GPU et le chargement au démarrage.
    autorisees = {"transcrire_wolof", "_charger_kiriku_gpu", "_precharger_kiriku"}

    def lignes_code(chemin: Path) -> dict[int, str]:
        """Lignes de code sans les commentaires (les chaînes restent : 'cuda')."""
        lignes: dict[int, list[str]] = {}
        with chemin.open(encoding="utf-8") as fichier:
            for jeton in tokenize.generate_tokens(fichier.readline):
                if jeton.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE):
                    continue
                for numero in range(jeton.start[0], jeton.end[0] + 1):
                    lignes.setdefault(numero, []).append(jeton.string)
        # Jetons recollés sans espace : « torch.cuda », « device=0 ».
        return {n: "".join(morceaux) for n, morceaux in lignes.items()}

    def plages_autorisees(chemin: Path) -> list[tuple[int, int]]:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        return [
            (noeud.lineno - len(noeud.decorator_list), noeud.end_lineno)
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef) and noeud.name in autorisees
        ]

    fichiers = [RACINE / "app.py"] + sorted((RACINE / "src").rglob("*.py"))
    hors_gpu = []
    vus_autorises = []
    for chemin in fichiers:
        plages = plages_autorisees(chemin) if chemin.name == "app.py" else []
        for numero, code in lignes_code(chemin).items():
            # Une docstring qui cite CUDA n'est pas un appel : seules les
            # lignes qui ne sont pas entièrement une chaîne comptent.
            if not motif_cuda.search(code) or re.fullmatch(r"\s*(['\"]).*", code):
                continue
            nom = f"{chemin.relative_to(RACINE).as_posix()}:{numero}"
            if any(debut <= numero <= fin for debut, fin in plages):
                vus_autorises.append(nom)
            else:
                hors_gpu.append((nom, code.strip()[:80]))
    verifie("aucun appel CUDA hors de transcrire_wolof et du chargement",
            not hors_gpu, hors_gpu)
    verifie("le scan voit bien le chargement Kiriku (device=0, is_available)",
            len(vus_autorises) >= 2, vus_autorises)

    # Le chargement CUDA n'est déclenché qu'au niveau module, jamais par une
    # requête : _precharger_kiriku est appelé une seule fois, hors fonction, et
    # _charger_kiriku_gpu seulement par lui.
    arbre = ast.parse((RACINE / "app.py").read_text(encoding="utf-8"))
    appels: dict[str, list[str]] = {"_precharger_kiriku": [], "_charger_kiriku_gpu": []}

    def parcourir(noeud: ast.AST, fonction: str) -> None:
        for enfant in ast.iter_child_nodes(noeud):
            if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parcourir(enfant, enfant.name)
                continue
            if (
                isinstance(enfant, ast.Call)
                and isinstance(enfant.func, ast.Name)
                and enfant.func.id in appels
            ):
                appels[enfant.func.id].append(fonction)
            parcourir(enfant, fonction)

    parcourir(arbre, "<module>")
    verifie("chargement GPU lancé une fois, au démarrage du module",
            appels == {"_precharger_kiriku": ["<module>"],
                       "_charger_kiriku_gpu": ["_precharger_kiriku"]}, appels)

    # _MODELE_GPU (le pipeline sur cuda) n'est lu que dans transcrire_wolof.
    lecteurs = set()

    def lecteurs_modele(noeud: ast.AST, fonction: str) -> None:
        for enfant in ast.iter_child_nodes(noeud):
            if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lecteurs_modele(enfant, enfant.name)
                continue
            if (
                isinstance(enfant, ast.Name)
                and enfant.id == "_MODELE_GPU"
                and isinstance(enfant.ctx, ast.Load)
            ):
                lecteurs.add(fonction)
            lecteurs_modele(enfant, fonction)

    lecteurs_modele(arbre, "<module>")
    verifie("Kiriku (_MODELE_GPU) utilisé seulement dans transcrire_wolof",
            lecteurs == {"transcrire_wolof"}, lecteurs)

    # transcrire_wolof ne rend que du texte Python, jamais un objet du modèle.
    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_zerogpu")
    import numpy as np

    class FauxTenseur:
        def __str__(self) -> str:
            return "maa ngi Ouakam"

    transcrire_origine = app.transcrire
    app._MODELE_GPU = object()
    try:
        audio = np.zeros(16_000, dtype=np.float32)
        app.transcrire = lambda modele, son: FauxTenseur()
        sortie_objet = app.transcrire_wolof(audio)
        app.transcrire = lambda modele, son: None
        sortie_vide = app.transcrire_wolof(audio)

        def leve(modele, son):
            raise RuntimeError("panne simulée")

        app.transcrire = leve
        with contextlib.redirect_stderr(io.StringIO()):
            sortie_erreur = app.transcrire_wolof(audio)
    finally:
        app.transcrire = transcrire_origine
        app._MODELE_GPU = None
    verifie("transcrire_wolof rend un str, jamais l'objet du modèle",
            type(sortie_objet) is str and sortie_objet == "maa ngi Ouakam", repr(sortie_objet))
    verifie("transcrire_wolof : rien du modèle -> chaîne vide", sortie_vide == "", repr(sortie_vide))
    verifie("transcrire_wolof : erreur -> str préfixé ERREUR_ASR",
            type(sortie_erreur) is str and sortie_erreur.startswith(app.ERREUR_ASR), sortie_erreur)
    source_app = (RACINE / "app.py").read_text(encoding="utf-8")
    verifie("durée GPU toujours fixe à 20 s",
            "@spaces.GPU(duration=20)\ndef transcrire_wolof" in source_app)

    return echecs, total


def test_lot_f5() -> tuple[int, int]:
    """Lot F5 : durées en fourchettes ; « dama bëgg dem Maristes » demande le départ.

    Aucun réseau : le LLM est toujours un faux client.
    """
    import contextlib
    import io
    import os

    from intent.extract_intent import extract_intent

    echecs = 0
    total = 0

    def verifie(nom: str, condition: bool, detail: object = "") -> None:
        nonlocal echecs, total
        total += 1
        echecs += not condition
        print(f"{'OK ' if condition else 'ÉCHEC'} | lot F5 {nom}")
        if not condition and detail:
            print(f"      {detail!r}")

    os.environ["GUINDIMA_SANS_MODELES"] = "1"
    app = _charger_module(RACINE / "app.py", "app_guindima_lot_f5")

    # 1. Fourchettes : durée calculée -> durée × 1,8, arrondies à 5 min.
    attendus = {
        30: "30–55 min",    # 54 -> 55
        12: "10–20 min",    # 12 -> 10 ; 21,6 -> 20
        27.5: "30–50 min",  # 27,5 -> 30 ; 49,5 -> 50
        45: "45–80 min",    # 81 -> 80
        3: "5–10 min",      # jamais « 5–5 min »
        0: "5–10 min",      # jamais « 0 min »
    }
    obtenus = {m: app.fourchette_minutes(m) for m in attendus}
    verifie("fourchettes et arrondis à 5 min", obtenus == attendus, obtenus)

    # Sur une vraie carte : la fourchette remplace « ~N min ».
    match = dict(app.MATCHER.find_line("Ouakam", "Palais")["lignes"][0])
    carte = app._une_carte(match, depart="Ouakam", arrivee="Palais")
    verifie("carte : fourchette affichée, plus de « ~N min »",
            app.fourchette_minutes(match["minutes"]) in carte
            and re.search(r"~\d+ min", carte) is None,
            (match.get("minutes"), carte[-600:]))
    # Durée inconnue : rien d'inventé, ni chiffre ni fourchette.
    inconnue = {**match, "minutes": None, "duree_inconnue": True}
    carte = app._une_carte(inconnue, depart="Ouakam", arrivee="Palais")
    verifie("carte : durée inconnue, aucune fourchette inventée",
            "durée inconnue" in carte and re.search(r"\d+–\d+ min", carte) is None,
            carte[-600:])
    # La voix ne dit aucune durée : la phrase parlée ne change pas.
    source_app = (RACINE / "app.py").read_text(encoding="utf-8")
    corps_voix = source_app.split("def _voix_wolof", 1)[1].split("\ndef ", 1)[0]
    verifie("voix : aucune durée parlée",
            "minutes" not in corps_voix and "fourchette" not in corps_voix)

    # 2. « dama bëgg dem Maristes » : le LLM mettait Maristes en départ, le
    #    local complétait l'arrivée avec Maristes -> « même lieu ».
    for reponse_llm in (
        '{"depart": "Maristes", "arrivee": ""}',
        '{"depart": "Maristes", "arrivee": "Maristes"}',
        '{"depart": "", "arrivee": ""}',
    ):
        with contextlib.redirect_stdout(io.StringIO()):
            intent = extract_intent("dama bëgg dem Maristes", client=_FauxClient(reponse_llm))
        verifie(f"extraction, LLM {reponse_llm} : départ vide, arrivée Maristes",
                (intent["depart"], intent["arrivee"]) == ("", "Maristes"), intent)

    client_origine = app._client_llm

    def pipeline(phrase: str, client) -> tuple[tuple, bool, str]:
        app._client_llm = lambda: client
        tampon = io.StringIO()
        try:
            with contextlib.redirect_stdout(tampon):
                quint, trouve = app._pipeline(phrase, "", 0.0)
        finally:
            app._client_llm = client_origine
        return quint, trouve, tampon.getvalue()

    for phrase in ("dama bëgg dem Maristes", "dama bëgg dem Marist"):
        for reponse_llm in ('{"depart": "Maristes", "arrivee": ""}',
                            '{"depart": "Maristes", "arrivee": "Maristes"}'):
            quint, trouve, journal = pipeline(phrase, _FauxClient(reponse_llm))
            verifie(f"« {phrase} » (LLM {reponse_llm}) : départ demandé, Maristes nommé",
                    not trouve
                    and "erreur=lieu_manquant" in journal
                    and "conversation_meme_lieu" not in journal
                    and "d'où pars-tu" in quint[2]
                    and "Maristes" in quint[2]
                    and quint[1] == "? → Maristes"
                    and quint[3] is not None,
                    (quint[1], quint[2][:200], journal))
    # Pikine passait déjà : même réponse, même champ.
    quint, _, _ = pipeline("dama bëgg dem pikin", _FauxClient('{"depart": "", "arrivee": ""}'))
    verifie("« dama bëgg dem pikin » : « ? → Pikine »",
            quint[1] == "? → Pikine" and "d'où pars-tu" in quint[2], quint[1:3])
    # Un vrai trajet garde « départ → arrivée » sans point d'interrogation.
    quint, trouve, _ = pipeline("Maa ngi Ouakam, bëgg naa dem Palais",
                                _ClientQuiLeve(lambda: TimeoutError("non")))
    verifie("trajet complet : « Ouakam → Palais »",
            trouve and quint[1] == "Ouakam → Palais", quint[1])

    return echecs, total


if __name__ == "__main__":
    # La console Windows (cp1252) ne sait pas afficher certains caractères (⚠️, ñ).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--rapport-officiel" in sys.argv:
        test_rapport_lignes_officielles()
        sys.exit(0)
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
        echecs_unite, total_unite = test_unite_15()
        echecs_vp, total_vp = test_vague_voix_partage()
        echecs_prive, total_prive = test_vie_privee()
        echecs_chg, total_chg = test_correspondances_coherentes()
        echecs_titres, total_titres = test_titres_markdown()
        echecs_t2, total_t2 = test_yoff_tata_2()
        echecs_noms1, total_noms1 = test_noms_lot_1()
        echecs_aero, total_aero = test_aeroport_ambigu()
        echecs_pgy, total_pgy = test_parcelles_grand_yoff()
        echecs_term, total_term = test_terminus_tata_officiels()
        echecs_duree, total_duree = test_duree_et_v1()
        echecs_gare, total_gare = test_gare_gaar()
        echecs_hf, total_hf = test_compte_hugging_face()
        echecs_terrain, total_terrain = test_terrain_en_ligne()
        echecs_verite, total_verite = test_verite_terrain()
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
        echecs_lot3, total_lot3 = test_lot_3()
        echecs_lot4, total_lot4 = test_lot_4()
        echecs_lot5, total_lot5 = test_lot_5()
        echecs_lot6, total_lot6 = test_lot_6()
        echecs_lot7, total_lot7 = test_lot_7()
        echecs_lot8, total_lot8 = test_lot_8()
        echecs_lot9, total_lot9 = test_lot_9()
        echecs_lot10, total_lot10 = test_lot_10()
        echecs_revue, total_revue = test_revue_securite()
        echecs_plafonds, total_plafonds = test_plafonds_par_client()
        echecs_b5, total_b5 = test_lot_b5()
        echecs_f4, total_f4 = test_lot_f4()
        echecs_2011, total_2011 = test_lot_20_11()
        echecs_zerogpu, total_zerogpu = test_zerogpu_cuda()
        echecs_f5, total_f5 = test_lot_f5()
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
            + echecs_unite
            + echecs_vp
            + echecs_prive
            + echecs_chg
            + echecs_titres
            + echecs_t2
            + echecs_noms1
            + echecs_aero
            + echecs_pgy
            + echecs_term
            + echecs_duree
            + echecs_gare
            + echecs_hf
            + echecs_terrain
            + echecs_verite
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
            + echecs_lot3
            + echecs_lot4
            + echecs_lot5
            + echecs_lot6
            + echecs_lot7
            + echecs_lot8
            + echecs_lot9
            + echecs_lot10
            + echecs_revue
            + echecs_plafonds
            + echecs_b5
            + echecs_f4
            + echecs_2011
            + echecs_zerogpu
            + echecs_f5
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
            + total_unite
            + total_vp
            + total_prive
            + total_chg
            + total_titres
            + total_t2
            + total_noms1
            + total_aero
            + total_pgy
            + total_term
            + total_duree
            + total_gare
            + total_hf
            + total_terrain
            + total_verite
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
            + total_lot3
            + total_lot4
            + total_lot5
            + total_lot6
            + total_lot7
            + total_lot8
            + total_lot9
            + total_lot10
            + total_revue
            + total_plafonds
            + total_b5
            + total_f4
            + total_2011
            + total_zerogpu
            + total_f5
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
