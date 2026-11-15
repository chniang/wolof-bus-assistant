"""Petite conversation en wolof : salutations, remerciements, présentation.

Elle ne sert que si la phrase ne contient aucun lieu : une demande de trajet
l'emporte toujours (« salam, dama bëgga dem Médina » est un trajet).  Les phrases
de réponse sont celles validées par l'équipe (locuteur natif) ; leur audio est
pré-généré comme le reste de la voix, jamais synthétisé en direct.

La reconnaissance suit la même normalisation tolérante que les noms de lieux :
Kiriku écrit le wolof avec une orthographe française (« dieuredieuf »), sans
accents, parfois en collant les mots (« nangadef »).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

try:  # import à plat (app.py) ou en paquet
    from intent.extract_intent import MOTS_DE_LA_PHRASE, _normaliser_phrase, _sans_compagnie
except ImportError:  # pragma: no cover
    from .extract_intent import MOTS_DE_LA_PHRASE, _normaliser_phrase, _sans_compagnie

# Une forme proche d'une variante connue (faute de l'ASR) compte à partir de ce
# score, sur des variantes d'au moins LONGUEUR_FLOUE lettres.  Plus court, la
# forme doit être exacte : « bye » ne doit pas venir de « bay ».
SEUIL_FLOU = 0.85
LONGUEUR_FLOUE = 6


@dataclass(frozen=True)
class Intention:
    nom: str
    reponse: str
    fichier: str
    variantes: tuple[str, ...]


# Dans l'ordre de priorité : la plus précise d'abord.  « lan nga mëna def » (ce que
# tu sais faire) contient presque « nanga def » (ça va) ; « kan moo la defar »
# (qui t'a créé) commence comme « kan nga » (qui es-tu).  « lan ngay def » (ton
# travail ?) et « lan nga di def » (qu'est-ce que tu fais ?) se ressemblent trop
# pour laisser le hasard trancher : « lan ngay def » est consommé par « liggeey »,
# placé avant « role ».
INTENTIONS: tuple[Intention, ...] = (
    Intention(
        "createur",
        "Cheikh Niang moo ma defar.",
        "conversation_createur.wav",
        (
            "kan moo la defar", "kan mo la defar", "kan moo la sos", "kan mo la sos",
            "qui t a cree", "qui t a fait", "qui t as cree", "qui t as fait",
        ),
    ),
    Intention(
        "capacites",
        "Wax ma fan nga nekk ak fan nga bëgga dem, ma won la bus bi nga wara jël.",
        "conversation_capacites.wav",
        (
            "lan nga mena def", "lan nga men a def", "lan nga mana def",
            "qu est ce que tu peux faire", "que peux tu faire",
        ),
    ),
    Intention(
        "ci_lo_nekk",
        "Maa ngi ci jàmm, alxamdulilaay. Yaw nag ?",
        "conversation_ci_lo_nekk.wav",
        (
            # « silo nekk » et « ci lo nekk » : même question (comment ça va ?),
            # écrite selon l'oreille de l'ASR.
            "silo nekk", "silo neh", "si lo nekk", "ci lo nekk", "silo nex",
        ),
    ),
    Intention(
        "liggeey",
        # À l'écran on écrit toujours « bus » (comme les autres réponses) ;
        # le lexique fait dire « biis » à la voix, l'audio ne change pas.
        "Sama liggéey mooy won nit ñi bus bi ñuy jël ci Ndakaaru.",
        "conversation_liggeey.wav",
        (
            "lan mooy sa liggeey", "lan mooy sa ligeey", "lane mooy sa ligeey",
            "lan ngay def",
        ),
    ),
    Intention(
        "role",
        "Maa ngi tudd GuindiMa. Damay won nit ñi bus bi ñuy jël ci Ndakaaru.",
        "conversation_role.wav",
        (
            "kan nga", "kan nga doon", "lan nga di def",
            "naka nga tudd", "noo tudd", "yaay kan", "yaay kane",
            "yaw la kan", "yaw la kane",
            "qui es tu", "tu es qui", "tu fais quoi", "c est quoi ton role",
            "quel est ton role",
        ),
    ),
    Intention(
        "dekk",
        "Ci Ndakaaru laa dëkk, ci biir sa telefon.",
        "conversation_dekk.wav",
        ("fan nga dekk",),
    ),
    Intention(
        "wolof",
        "Waaw, dégg naa wolof. Wax ma fan nga bëgga dem.",
        "conversation_wolof.wav",
        (
            "ndax danga degg wolof", "ndax degg nga wolof", "degg nga wolof",
            "ndakh danga degg wolof",
        ),
    ),
    Intention(
        "ca_va",
        "Maa ngi fi rekk, jërëjëf. Yaw nag ? Fan nga bëgga dem ?",
        "conversation_ca_va.wav",
        (
            "nanga def", "na nga def", "naka nga def", "naka waa", "naka wa",
            "jamm nga am", "mbaa jamm nga am",
            "ca va", "comment tu vas", "comment vas tu", "comment ca va",
        ),
    ),
    Intention(
        "merci",
        "Ñoo ko bokk ! Soo ma soxlaa, maa ngi lay déglu.",
        "conversation_merci.wav",
        (
            "jerejef", "jerejeuf", "dieuredieuf", "diere dieuf", "jere jef",
            "jaajef", "jaajeuf", "diadieuf", "diaadieuf", "merci",
        ),
    ),
    Intention(
        "au_revoir",
        "Ba beneen yoon !",
        "conversation_au_revoir.wav",
        (
            "ba beneen", "ba beneen yoon", "ba benen yoon", "ba suba",
            # « je m'en vais » : l'usager raccroche en annonçant son départ.
            "mangi dem", "maa ngi dem",
            "au revoir", "bye",
        ),
    ),
    Intention(
        "salutation",
        "Maalekum salaam ! Fan nga bëgga dem ?",
        "conversation_salutation.wav",
        (
            "salam", "salamaleykoum", "salamalekum", "salamaleikoum",
            "salamalaikoum", "salamalekoum", "salaam aleekum", "salam alaykum",
            "assalamou aleykoum", "assalamou alaykoum", "assalamu alaykum",
            "asalaa maalekum", "asalamaalekum", "assalam alaykoum",
            "bonjour", "salut", "hello",
        ),
    ),
)

# Rien compris : ni lieu, ni petite conversation.
HORS_SUJET = Intention(
    "hors_sujet",
    "Baal ma, bus yi rekk laa xam. Wax ma fan nga nekk ak fan nga bëgga dem.",
    "conversation_hors_sujet.wav",
    (),
)

TOUTES = INTENTIONS + (HORS_SUJET,)


def _forme(texte: str) -> str:
    return _normaliser_phrase(texte or "")


def _colle(texte: str) -> str:
    return texte.replace(" ", "")


def _reconnue(phrase: str, variante: str) -> bool:
    """La variante est-elle dans la phrase, exacte, collée ou à une faute près ?"""
    cible = _forme(variante)
    if not cible:
        return False
    if re.search(rf"(?<![a-z0-9]){re.escape(cible)}(?![a-z0-9])", phrase):
        return True
    if len(_colle(cible)) < LONGUEUR_FLOUE:
        return False
    # Mots collés par l'ASR (« nangadef »), ou une lettre de travers
    # (« dieuredieuf ») : on compare des fenêtres de mots, sans les espaces.
    mots = phrase.split()
    taille = len(cible.split())
    for largeur in {max(1, taille - 1), taille, taille + 1}:
        for debut in range(0, max(1, len(mots) - largeur + 1)):
            morceau = _colle(" ".join(mots[debut : debut + largeur]))
            if SequenceMatcher(None, morceau, _colle(cible)).ratio() >= SEUIL_FLOU:
                return True
    return False


# Mots qui suivent « maa ngi » ou « dem » dans une phrase de politesse, jamais
# un lieu : « maa ngi fi rekk » (ça va), « maa ngi ci jàmm », « maa ngi tudd
# Moussa », « maa ngi dem, ba beneen yoon » (au revoir). Les mots des formules
# de conversation ci-dessus s'y ajoutent (« maa ngi dem, jërëjëf »).
_NON_LIEUX = {
    "fi", "fii", "fee", "fale", "rekk", "jamm", "tudd", "lay", "def", "dem", "yoon",
    "beneen", "benen", "suba", "sant", "nuyu", "yaw", "nag", "alxamdulilaay",
    "alhamdoulilah", "alhamdulillah", "waaw", "deedeet", "xam", "deglu",
}
_NON_LIEUX |= {
    mot
    for intention in INTENTIONS
    for texte in intention.variantes
    for mot in _normaliser_phrase(texte).split()
}
# « dem ci Petersen » : « ci » se saute pour trouver le lieu.
_SAUTES = {"ci"}
_MARQUEURS_ICI = re.compile(
    r"(?:^| )(?:maa ngi|ma ngi|mangi|maangi|mangui|man gui|fi ma nekk|fii ma nekk|dama nekk)"
    r"(?: nekk)?(?: mooy| moy| mooye)?(?= |$)"
)


def _peut_etre_un_lieu(mot: str) -> bool:
    return (
        len(mot) >= 3
        and mot not in MOTS_DE_LA_PHRASE
        and mot not in _NON_LIEUX
    )


def _premier_mot_utile(mots: list[str], debut: int) -> str:
    for mot in mots[debut:]:
        if mot not in _SAUTES:
            return mot
    return ""


def signal_trajet(phrase: str) -> bool:
    """La phrase demande-t-elle un trajet, même si aucun lieu n'est reconnu ?

    Vu en production : « Salaam aleekum, man damay dem Petersen te maa ngi
    Ouakam, ban bus laa wara jël ? » a reçu trois fois la salutation. L'ASR
    avait déformé les noms de lieux, l'extraction locale n'en trouvait aucun,
    et la salutation passait avant le LLM. Un mot qui peut être un lieu après
    « dem / jëm », ou après « maa ngi », « fi ma nekk (mooy) », « dama nekk »,
    suffit : le trajet passe alors avant la petite conversation (le LLM a sa
    chance, la seconde chance ASR aussi). « maa ngi fi rekk », « maa ngi dem »
    (au revoir) ou « fan nga bëgga dem ? » n'en sont pas.
    """
    mots = _sans_compagnie(phrase or "").split()
    for i, mot in enumerate(mots):
        if mot == "dem" and _peut_etre_un_lieu(_premier_mot_utile(mots, i + 1)):
            return True
        # « Ouakam laa nekk » : le lieu avant « laa nekk ».
        if mot in {"laa", "la"} and i > 0 and mots[i + 1 : i + 2] == ["nekk"]:
            if _peut_etre_un_lieu(mots[i - 1]):
                return True
    texte = " ".join(mots)
    for trouve in _MARQUEURS_ICI.finditer(texte):
        if _peut_etre_un_lieu(_premier_mot_utile(texte[trouve.end():].split(), 0)):
            return True
    return False


def detecter(phrase: str) -> Intention | None:
    """L'intention de petite conversation de la phrase, ou None.

    À n'appeler que si la phrase ne contient aucun lieu : l'appelant le vérifie.
    """
    forme = _forme(phrase)
    if not forme:
        return None
    for intention in INTENTIONS:
        if any(_reconnue(forme, variante) for variante in intention.variantes):
            return intention
    return None


__all__ = ["HORS_SUJET", "INTENTIONS", "Intention", "TOUTES", "detecter", "signal_trajet"]
