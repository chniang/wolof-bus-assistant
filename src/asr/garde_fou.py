"""Garde-fou contre les transcriptions absurdes (lot G0).

Test public du 20 au 23/11/2026 : 47 transcriptions sur 52 venaient du Whisper
CPU de secours, et 14 étaient inventées (« dina dina dina… », « di sini akan
diperluuskan… », « Saya sér »). L'app répondait quand même avec un trajet :
mieux vaut dire qu'on n'a pas bien entendu.

Trois signaux, du plus sûr au moins sûr :

1. Boucle exacte : un groupe de 1 à 6 mots répété à la suite (4 fois pour un
   mot seul, 3 fois pour un groupe), ou un mot fait d'une syllabe répétée
   (« sësësësë… »). La boucle est retirée ; si ce qui reste porte encore un
   lieu ou un mot plein (« dama nég wakaaral mbindé dina dina… »), on cherche
   le trajet sur ce reste. Sinon, garde-fou.
2. Boucle approximative : au moins 8 mots dont moins de 45 % différents
   (« dama nék koo ak ame » répété avec des variantes d'écriture).
3. Langue étrangère : au moins la moitié des mots sont des marqueurs d'une
   autre langue (mots-outils indonésiens ou anglais, mots du type « di…kan »).
   On ne juge PAS sur les mots inconnus : le wolof est bien plus riche que nos
   listes, et « wakaaral » ou « mbindé » sont de vrais mots.

Jamais de garde-fou sur une salutation ou une phrase qui porte un lieu connu.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MESSAGE = "Je n'ai pas bien entendu. Redis ton trajet plus près du micro, ou utilise l'onglet Écrire."

TAILLE_GROUPE_MAX = 6
REPETITIONS_MOT_SEUL = 4
REPETITIONS_GROUPE = 3
MOTS_MIN_DIVERSITE = 8
DIVERSITE_MIN = 0.45
PART_ETRANGERE_MAX = 0.5

# Mots-outils d'autres langues vus dans les transcriptions inventées par
# Whisper (indonésien/malais, anglais). Aucun n'est un mot wolof ou français
# courant : « di » (wolof) et « on » (français) n'y sont volontairement pas.
MOTS_ETRANGERS = frozenset({
    # indonésien / malais
    "saya", "akan", "sini", "maka", "beri", "yang", "dan", "ini", "itu", "ada", "dengan",
    "untuk", "tidak", "sudah", "bisa", "kami", "kita", "mereka", "dari", "pada", "juga",
    "atau", "karena", "sangat", "lebih", "telah", "harus", "semua", "oleh", "seperti",
    "jika", "kalau", "siapa", "bagaimana", "terima", "kasih", "selamat", "pagi", "aku",
    "kamu", "anda", "dia", "sana", "situ", "sekarang", "nanti", "boleh",
    # anglais
    "the", "of", "and", "is", "are", "was", "were", "you", "your", "this", "that", "with",
    "for", "have", "has", "what", "day", "they", "it", "be", "to", "my", "we", "will",
    "would", "there", "their", "from", "about", "just", "like", "know", "thank",
})
# Morphologie indonésienne : « diperluuskan », « memberikan », « bersama-nya ».
_MOT_INDONESIEN = re.compile(r"^(?:di|me|mem|men|meng|ber|ter|per)\w{3,}(?:kan|nya|lah)$")
# Un mot fait d'une syllabe répétée : « sësësësësë », « nanananana ».
_SYLLABE_EN_BOUCLE = re.compile(r"\w{0,3}?(\w{1,3})\1{3,}\w{0,3}")
# Mots-outils wolof et français : ils ne suffisent pas à faire une demande.
MOTS_OUTILS = frozenset({
    "dama", "damaa", "damay", "nekk", "nek", "neg", "koo", "ak", "ab", "bi", "ba", "la", "ma",
    "mu", "di", "ci", "ngi", "maa", "man", "yow", "dina", "sa", "su", "fa", "bu", "waaw",
    "dem", "begg", "begga", "naa", "laa", "nga", "yi", "fi", "ame", "am", "le", "la", "les",
    "de", "du", "et", "je", "tu", "il", "un", "une", "est", "pas",
})


@dataclass(frozen=True)
class Verdict:
    declenche: bool
    texte: str
    raison: str = ""


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte.lower()) if unicodedata.category(c) != "Mn"
    )


def _mots(texte: str) -> list[str]:
    # Lettres et chiffres : « Unité 15 » garde son numéro quand on retire une boucle.
    return re.findall(r"[^\W_]+", texte.lower())


def _retirer_boucles(mots: list[str]) -> tuple[list[str], bool]:
    """Les mots hors boucles exactes, et vrai si une boucle a été retirée."""
    gardes: list[str] = []
    retire = False
    i = 0
    while i < len(mots):
        boucle = False
        for taille in range(1, TAILLE_GROUPE_MAX + 1):
            groupe = mots[i:i + taille]
            if len(groupe) < taille:
                break
            repetitions = 1
            while mots[i + repetitions * taille:i + (repetitions + 1) * taille] == groupe:
                repetitions += 1
            besoin = REPETITIONS_MOT_SEUL if taille == 1 else REPETITIONS_GROUPE
            if repetitions >= besoin:
                fin = i + repetitions * taille
                # Une dernière répétition coupée (« … the day of the day ») part aussi.
                reste = mots[fin:fin + taille]
                if reste and groupe[:len(reste)] == reste:
                    fin += len(reste)
                i, boucle, retire = fin, True, True
                break
        if boucle:
            continue
        mot = mots[i]
        if len(mot) >= 8 and _SYLLABE_EN_BOUCLE.fullmatch(mot):
            retire = True
        else:
            gardes.append(mot)
        i += 1
    return gardes, retire


def _etranger(mot: str) -> bool:
    return mot in MOTS_ETRANGERS or (len(mot) >= 7 and _MOT_INDONESIEN.match(mot) is not None)


def _porte_un_lieu(texte: str) -> bool:
    try:
        from intent.extract_intent import _chercher_lieux, _sans_compagnie
    except ImportError:  # pragma: no cover
        from ..intent.extract_intent import _chercher_lieux, _sans_compagnie
    return bool(_chercher_lieux(_sans_compagnie(texte).split()))


def _salutation(texte: str) -> bool:
    try:
        from intent.conversation import detecter
    except ImportError:  # pragma: no cover
        from ..intent.conversation import detecter
    return detecter(texte) is not None


def examiner(transcription: str | None) -> Verdict:
    """Garde-fou ou non, et le texte à utiliser (boucle retirée s'il y en avait une)."""
    texte = (transcription or "").strip()
    mots = _mots(texte)
    if not mots:
        return Verdict(True, "", "vide")

    utiles, retire = _retirer_boucles(mots)
    if retire:
        if not utiles:
            return Verdict(True, "", "boucle")
        reste = " ".join(utiles)
        pleins = [m for m in utiles if _sans_accents(m) not in MOTS_OUTILS and len(m) >= 4]
        if not (pleins or _porte_un_lieu(reste)):
            return Verdict(True, "", "boucle")
        if sum(_etranger(m) for m in utiles) / len(utiles) >= PART_ETRANGERE_MAX:
            return Verdict(True, "", "langue")
        return Verdict(False, reste, "boucle_retiree")

    if len(mots) >= MOTS_MIN_DIVERSITE and len(set(mots)) / len(mots) < DIVERSITE_MIN:
        return Verdict(True, "", "repetitions")
    # Une salutation ou un lieu connu : jamais de garde-fou sur la langue.
    if _salutation(texte) or _porte_un_lieu(texte):
        return Verdict(False, texte)
    if sum(_etranger(m) for m in mots) / len(mots) >= PART_ETRANGERE_MAX:
        return Verdict(True, "", "langue")
    return Verdict(False, texte)
