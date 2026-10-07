"""Noms de lieux du réseau : normalisation, affichage et comparaison.

Les itinéraires officiels AFTU sont publiés en majuscules, sans accents et avec
leurs variantes (« GIRATOIRE LIBERTE VI », « TERMINUS GARE PETERSEN »,
« KHARYALLA »). L'utilisateur, lui, dit « Liberté 6 », « Petersen », « Khar Yalla ».
Ce module ramène les deux à une même forme de travail pour les comparer.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

# Mots qui ne désignent pas le lieu lui-même : « Terminus Gare de Colobane »
# et « Colobane » doivent être reconnus comme le même endroit.
MOTS_GENERIQUES = {
    "terminus", "terminnus", "termnus", "termibus", "gare", "arret", "station",
    "croisement", "carrefour", "rond", "point", "giratoire",
    "de", "des", "du", "la", "le", "les", "l", "d", "et", "x", "a", "au", "aux",
}

ABREVIATIONS = {
    "gd": "grand", "rte": "route", "av": "avenue", "bld": "boulevard", "bd": "boulevard",
    "rd": "rond", "pt": "point", "st": "saint", "ste": "sainte",
}

CHIFFRES_ROMAINS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}
# Le chiffre romain n'est converti qu'après ces mots : « V » seul ne veut rien dire.
AVANT_NUMERO = {"liberte", "hamo", "unite", "unites", "jaxaay", "gorom", "palais"}

# Surnoms et formes courantes qui ne se déduisent pas de l'orthographe. Les deux
# côtés de la comparaison passent par cette table.
ALIAS = {
    "leclerc": "place leclerc",
    "ucad": "universite cheikh anta diop",
    "universite": "universite cheikh anta diop",
    "stade lss": "stade leopold sedar senghor",
    "stade l s s": "stade leopold sedar senghor",
    "aeroport lss": "aeroport",
    "aeroport l s senghor": "aeroport",
    "aeroport leopold sedar senghor": "aeroport",
    "kharyalla": "khar yalla",
    "sacree coeur": "sacre coeur",
    "pattesd oie": "patte d oie",
    "lat dior": "lat dior",
}

# Premiers mots d'une voie : « Route de Rufisque » n'est pas Rufisque.
VOIES = {
    "rue", "rues", "avenue", "boulevard", "route", "autoroute", "rocade", "allees",
    "echangeur", "branche", "voie", "voies", "canal", "piste", "ancienne", "prolongement",
    "retour", "sortie", "peage", "virage", "passage",
}


def sans_accents(texte: str) -> str:
    texte = unicodedata.normalize("NFD", str(texte).lower().replace("œ", "oe"))
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def _calcul_jetons(texte: str) -> list[str]:
    brut = re.sub(r"[^a-z0-9]+", " ", sans_accents(texte)).split()
    sortie: list[str] = []
    for mot in brut:
        mot = ABREVIATIONS.get(mot, mot)
        if mot in CHIFFRES_ROMAINS and sortie and sortie[-1] in AVANT_NUMERO:
            mot = CHIFFRES_ROMAINS[mot]
        sortie.append(mot)
    return [m for m in sortie if m not in MOTS_GENERIQUES]


@lru_cache(maxsize=16384)
def _jetons(texte: str) -> tuple[str, ...]:
    return tuple(_calcul_jetons(texte))


def jetons(texte: str) -> list[str]:
    """Mots significatifs d'un nom de lieu, dans l'ordre (alias résolus)."""
    base = _jetons(str(texte))
    alias = ALIAS.get(" ".join(base))
    return list(_jetons(alias)) if alias else list(base)


def forme(texte: str) -> str:
    """Forme de travail d'un lieu : jetons significatifs joints par des espaces."""
    return " ".join(jetons(texte))


def _proches(a: str, b: str) -> bool:
    """Deux mots presque identiques (« guediawaye » / « guediewaye », « thiandom »)."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.85


@lru_cache(maxsize=131072)
def _score_brut(q: tuple[str, ...], s: tuple[str, ...]) -> float:
    if q == s:
        return 1.0
    if all(mot in s for mot in q):
        return 0.5 + 0.5 * len(q) / len(s)
    if all(any(_proches(mot, m) for m in s) for mot in q):
        return 0.45 + 0.45 * len(q) / len(s)
    # Mots collés par l'ASR ou l'opérateur : « kharyalla », « taliboubess ».
    colle_q, colle_s = "".join(q), "".join(s)
    if len(colle_q) >= 5 and colle_q in colle_s:
        return 0.45 + 0.45 * len(colle_q) / len(colle_s)
    return 0.0


def score(requete: str, arret: str) -> float:
    """Ressemblance entre un lieu demandé et un arrêt, entre 0 et 1.

    1.0 : même lieu. Entre 0 et 1 : tous les mots demandés sont dans l'arrêt
    (« Liberté 6 » dans « Giratoire Liberté VI »), d'autant mieux noté que
    l'arrêt a peu de mots en plus. 0 : rien de commun.
    """
    q = jetons(requete)
    s = jetons(arret)
    if not q or not s:
        return 0.0
    brut = _score_brut(tuple(q), tuple(s))
    # Une rue ou une route qui porte le nom d'un quartier (« Route de Rufisque »)
    # n'est pas ce quartier : on la note moins bien qu'un vrai arrêt.
    if s[0] in VOIES and q[0] not in VOIES:
        return 0.7 * brut
    return brut


# --------------------------------------------------------------------------- #
# Affichage
# --------------------------------------------------------------------------- #

ACCENTS = {
    "liberte": "Liberté", "guediawaye": "Guédiawaye", "guediewaye": "Guédiawaye",
    "camberene": "Cambérène", "medina": "Médina", "medine": "Médine",
    "diamaguene": "Diamaguène", "thiawlene": "Thiawlène", "derkle": "Derklé",
    "ndiareme": "Ndiarème", "aeroport": "Aéroport", "ecole": "École", "eglise": "Église",
    "cite": "Cité", "marche": "Marché", "prefecture": "Préfecture", "lycee": "Lycée",
    "hopital": "Hôpital", "universite": "Université", "senegal": "Sénégal",
    "leopold": "Léopold", "sedar": "Sédar", "emergence": "Émergence", "college": "Collège",
    "sebikhotane": "Sébikotane", "sebikotane": "Sébikotane", "mbedou": "Mbédou",
    "allees": "Allées", "peage": "Péage", "securite": "Sécurité", "entree": "Entrée",
    "maraichers": "Maraîchers", "cimetiere": "Cimetière", "etage": "Étage",
    "penitence": "Pénitence", "sacree": "Sacré", "sacre": "Sacré", "coeur": "Cœur",
    "hotel": "Hôtel", "routiere": "routière", "mole": "Môle", "prolongee": "Prolongée",
    "tapee": "Tapée", "unites": "Unités", "unite": "Unité", "general": "Général",
    "degagement": "Dégagement", "tilene": "Tilène", "cinema": "Cinéma",
    "aere": "Aéré", "hygiene": "Hygiène", "obelisque": "Obélisque", "siege": "Siège",
}
MAJUSCULES = {
    "hlm", "ucad", "lss", "sips", "sde", "mtoa", "apix", "scoa", "seras", "capa", "rts",
    "cto", "vdn", "zac", "pai", "bceao", "sicap", "sedima", "sonadis", "sococim", "capec",
    "sagef", "socabeg", "cocehas", "asecna", "sotrac", "safco", "sahm", "sham", "jvc",
    "aibd", "ii", "iii", "iv", "vi", "ue", "p11", "scat",
}
MINUSCULES = {"de", "des", "du", "la", "le", "les", "et", "aux", "au", "à"}


def joli(nom: str) -> str:
    """« TERMINUS GARE DE COLOBANE » -> « Gare de Colobane » (sans le mot terminus)."""
    texte = re.sub(r"^\s*(terminus|terminnus|termnus|arret)\s+", "", nom.strip(), flags=re.I)
    texte = texte.replace("’", "'").strip(" .-–")
    mots = []
    for i, mot in enumerate(texte.split()):
        bas = mot.lower()
        prefixe = "(" if bas.startswith("(") else ""
        suffixe = ")" if bas.endswith(")") else ""
        corps = bas.strip("()")
        cle = sans_accents(corps).strip("'.,")
        if corps.startswith(("d'", "l'")):
            reste = corps[2:]
            mots.append(prefixe + corps[:2] + ACCENTS.get(sans_accents(reste), reste.capitalize()) + suffixe)
        elif cle in MAJUSCULES:
            mots.append(mot.upper())
        elif i > 0 and cle in MINUSCULES:
            mots.append(bas)
        elif cle in ACCENTS:
            mots.append(prefixe + ACCENTS[cle] + suffixe)
        else:
            mots.append(prefixe + "-".join(p[:1].upper() + p[1:] for p in corps.split("-")) + suffixe)
    return " ".join(mots)


# --------------------------------------------------------------------------- #
# Liste des lieux à reconnaître dans une phrase
# --------------------------------------------------------------------------- #

PREFIXES_RETIRABLES = re.compile(
    r"^(croisement|carrefour|rond-point( de)?|giratoire( de)?|station|gare( routière)?( de| des)?"
    r"|poste de police|police( des| de)?|2 voies( de)?|deux voies|entrée|terminus)\s+",
    re.I,
)

# Morceaux d'itinéraire qui ne sont pas des lieux qu'on demande.
BRUIT = {
    "par bassin retention", "face autoroute", "marche", "eglise", "auto route", "r802",
    "ue 02", "par station titan", "dakar", "port", "corniche", "g dakar",
    "derriere hopital dalal diam", "pharmicie abdourahmane", "toure",
}


def lieux_reconnaissables(arrets: list[str]) -> list[str]:
    """Noms de lieux à proposer au LLM et à l'extraction locale.

    Part des arrêts du réseau, écarte les rues et routes (« Rue 34 »,
    « Route des Niayes »), sépare les précisions entre parenthèses
    (« Gadaye (Guédiawaye) » donne aussi « Guédiawaye ») et ajoute la forme
    sans préfixe (« Croisement Cambérène » donne aussi « Cambérène »).
    """
    vus: dict[str, str] = {}

    def ajouter(nom: str) -> None:
        nom = nom.strip(" ()-–:")
        mots = jetons(nom)
        if not mots or mots[0] in VOIES or mots[0] in {"unite", "unites", "rues"}:
            return
        cle = " ".join(mots)
        if len(cle) < 3 or cle.replace(" ", "").isdigit() or cle in BRUIT:
            return
        # À forme égale, on garde le nom le plus court (« Petersen » plutôt que
        # « Gare Petersen ») : c'est celui que les gens disent.
        if cle not in vus or len(nom) < len(vus[cle]):
            vus[cle] = nom

    for arret in arrets:
        principal = re.sub(r"\(.*?\)", "", arret).strip()
        ajouter(principal)
        sans_prefixe = PREFIXES_RETIRABLES.sub("", principal)
        if sans_prefixe != principal:
            ajouter(sans_prefixe)
        for precision in re.findall(r"\((.*?)\)", arret):
            for morceau in precision.split("/"):
                ajouter(joli(morceau))
    return sorted(vus.values(), key=sans_accents)
