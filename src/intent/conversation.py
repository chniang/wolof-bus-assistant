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
    from intent.extract_intent import _normaliser_phrase
except ImportError:  # pragma: no cover
    from .extract_intent import _normaliser_phrase

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
# (qui t'a créé) commence comme « kan nga » (qui es-tu).
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
        "role",
        "Maa ngi tudd GuindiMa. Damay won nit ñi bus bi ñuy jël ci Ndakaaru.",
        "conversation_role.wav",
        (
            "kan nga", "kan nga doon", "lan ngay def", "lan nga di def",
            "qui es tu", "tu es qui", "tu fais quoi", "c est quoi ton role",
            "quel est ton role",
        ),
    ),
    Intention(
        "ca_va",
        "Maa ngi fi rekk, jërëjëf. Yaw nag ? Fan nga bëgga dem ?",
        "conversation_ca_va.wav",
        (
            "nanga def", "na nga def", "naka nga def", "naka waa", "naka wa",
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
        ("ba beneen", "ba beneen yoon", "ba benen yoon", "au revoir", "bye"),
    ),
    Intention(
        "salutation",
        "Maalekum salaam ! Fan nga bëgga dem ?",
        "conversation_salutation.wav",
        (
            "salam", "salamaleykoum", "salamalekum", "salamaleikoum",
            "salamalaikoum", "salamalekoum", "assalamou aleykoum",
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


__all__ = ["HORS_SUJET", "INTENTIONS", "Intention", "TOUTES", "detecter"]
