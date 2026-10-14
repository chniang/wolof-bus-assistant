r"""Analyse des transcriptions Whisper de la collecte : formes entendues, score
avant fine-tuning, variantes proposées et simulation.

Utilisation :
    .\.venv\Scripts\python.exe scripts\analyser_whisper.py
    .\.venv\Scripts\python.exe scripts\analyser_whisper.py --locuteur locuteur_10

100 % lecture seule : aucun audio touché, aucune règle de l'app modifiée. Le
script compare data/collecte/asr_whisper.csv à la colonne transcription_propre
de data/collecte/metadata.csv.

« --locuteur X » restreint TOUTES les étapes aux vocaux de ce seul locuteur :
pour une évaluation honnête, mesurer le score (étape 2) sur un locuteur jamais
vu séparément du reste de la collecte, avant et après l'ajout de variantes.

1) Pour chaque lieu annoncé dans la phrase propre (départ et arrivée), on
   aligne les deux phrases mot à mot (difflib) pour retrouver la forme que
   Whisper a réellement écrite. On agrège : lieu -> formes entendues (nombre).
   Même chose pour la formule « ban bus » et le marqueur de départ
   (« diougué » -> juge, njuge, jóge…).

2) Score AVANT : combien des 144 vocaux donnent le bon départ ET la bonne
   arrivée (via extract_local), et combien trouvent un trajet (StopsMatcher).

3) Proposition de variantes (NON appliquées) : acceptées / refusées, avec la
   raison (mot de la phrase, ou trop proche d'un autre lieu).

4) Simulation : ce que vaudrait le score de (2) si les variantes acceptées
   étaient ajoutées.

5) Variantes SÛRES (NON appliquées) : sous-ensemble des acceptées de (3),
   restreint à celles entendues au moins deux fois chez au moins deux
   locuteurs différents, et, pour un lieu, confirmées comme son lieu le plus
   proche parmi tous les lieux connus (pas seulement « pas trop proche d'un
   autre »). Pour le marqueur de départ (ce que Whisper écrit pour « diougué »/
   « diogué », jamais présent tel quel dans la transcription propre) : liste
   blanche jóge/joge, juge, njuge, njugee — jamais « dem », qui annonce
   l'arrivée, même entendu plusieurs fois.
"""

from __future__ import annotations

import csv
import difflib
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from intent.extract_intent import (  # noqa: E402
    LIEUX,
    LIEUX_SUPPLEMENTAIRES,
    MOTS_CHIFFRES,
    MOTS_DE_LA_PHRASE,
    MOTS_TROP_VAGUES,
    extract_local,
)
from matching.lieux import forme  # noqa: E402
from matching.stops_matcher import StopsMatcher  # noqa: E402

META = RACINE / "data" / "collecte" / "metadata.csv"
ASR = RACINE / "data" / "collecte" / "asr_whisper.csv"

TOUS_LIEUX = list(LIEUX) + list(LIEUX_SUPPLEMENTAIRES)

# Mots à ne jamais proposer comme variante de lieu : la phrase elle-même, les
# mots trop vagues, les chiffres dits, et la famille « ban bus ».
MOTS_INTERDITS = (
    set(MOTS_DE_LA_PHRASE)
    | set(MOTS_TROP_VAGUES)
    | set(MOTS_CHIFFRES)
    | {
        "ban", "bann", "bane", "benn", "bën", "ben", "bus", "biss", "bis",
        "biis", "buus", "mbus", "mbis", "mbismay", "bius", "mbismoo", "bël",
        "mban", "bëng", "bënn", "ba", "la", "wu", "ku", "bu", "buur", "per",
        "pour", "puur", "pur", "poor", "por", "kur", "tur", "bor", "bar",
    }
)

# Marqueur de DÉPART (« partir de X ») : liste BLANCHE des formes que WHISPER
# peut entendre pour « diougué »/« diogué » (la transcription_propre, elle,
# écrit toujours « diougué »/« diogué » littéralement — jamais ces formes :
# vérifié sur toute la collecte). Seules ces 4 formes sont assez stables pour
# devenir une variante ; le reste du bruit ASR (« jge », « jile », « monge »,
# « nduwaa »…) n'a pas de forme fixe et n'est jamais accepté. « dem » annonce
# l'ARRIVÉE (voir CLAUDE.md) : même entendu plusieurs fois pour ce marqueur,
# il ne doit JAMAIS être pris pour un départ, d'où l'assertion ci-dessous.
MARQUEURS_DEPART_PROPRES = {"joge", "juge", "njuge", "njugee"}
assert "dem" not in MARQUEURS_DEPART_PROPRES, "'dem' annonce l'arrivée, jamais le départ"

# Seuils de prudence pour une variante « sûre » : entendue au moins deux fois,
# chez au moins deux locuteurs différents (sinon un seul vocal bruité suffirait
# à fabriquer une règle). Au-delà, on vérifie aussi que le lieu visé est bien
# celui dont la forme entendue est le plus proche parmi tous les lieux connus.
OCCURRENCES_MIN_SUR = 2
LOCUTEURS_MIN_SUR = 2


def norm(texte: str) -> list[str]:
    """Minuscules, sans accents, découpé en mots (comme lieux.py but tokenisé)."""
    texte = unicodedata.normalize("NFD", str(texte).lower().replace("œ", "oe"))
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texte).split()


def sim(a: str, b: str) -> float:
    """Similarité 0-1 entre deux formes (caractères, sans accents ni espaces doublés)."""
    return difflib.SequenceMatcher(None, " ".join(norm(a)), " ".join(norm(b))).ratio()


def _aligner(ptoks: list[str], wtoks: list[str]):
    return difflib.SequenceMatcher(None, ptoks, wtoks, autojunk=False).get_opcodes()


def _span_propre(ptoks: list[str], cible: str, maxn: int = 5) -> tuple[float, int, int]:
    """Meilleur n-gramme de la phrase propre pour un nom de lieu cible."""
    cible_n = " ".join(norm(cible))
    best = (0.0, 0, 0)
    for n in range(1, maxn + 1):
        for i in range(len(ptoks) - n + 1):
            s = difflib.SequenceMatcher(None, " ".join(ptoks[i:i + n]), cible_n).ratio()
            if s > best[0]:
                best = (s, i, i + n)
    return best


def _map_span(opcodes, i1: int, i2: int) -> tuple[int, int] | None:
    """Portion des mots Whisper alignée sur la portion [i1:i2] de la phrase propre."""
    blocs = [(b1, b2) for _tag, a1, a2, b1, b2 in opcodes if a2 > i1 and a1 < i2]
    if not blocs:
        return None
    return min(b[0] for b in blocs), max(b[1] for b in blocs)


def _meilleur_ngram(wtoks: list[str], cible: str, maxn: int = 3) -> str | None:
    """n-gramme de la phrase Whisper le plus proche d'une cible (recherche globale)."""
    cible_n = " ".join(norm(cible))
    meilleur = (0.0, None)
    for n in range(1, maxn + 1):
        for k in range(len(wtoks) - n + 1):
            s = difflib.SequenceMatcher(None, " ".join(wtoks[k:k + n]), cible_n).ratio()
            if s > meilleur[0]:
                meilleur = (s, (k, k + n))
    return " ".join(wtoks[meilleur[1][0]:meilleur[1][1]]) if meilleur[1] else None


def _forme_entendue(ptoks: list[str], wtoks: list[str], opcodes, cible: str) -> str | None:
    """Forme écrite par Whisper pour ce lieu : la sous-suite alignée la plus proche.

    On s'aide de l'alignement avec la phrase propre (claims des mots-structure
    répétés comme « dem ») pour ne pas confondre départ et arrivée, puis, dans la
    fenêtre obtenue, on garde le n-gramme le plus proche de la cible.
    """
    score, i1, i2 = _span_propre(ptoks, cible)
    if score < 0.6:
        return None
    bornes = _map_span(opcodes, i1, i2)
    if not bornes:
        return ""
    j1, j2 = bornes
    cible_n = " ".join(norm(cible))
    meilleur = (0.0, None)
    for n in range(1, min(5, j2 - j1) + 1):
        for k in range(j1, j2 - n + 1):
            s = difflib.SequenceMatcher(None, " ".join(wtoks[k:k + n]), cible_n).ratio()
            if s > meilleur[0] or (meilleur[1] and abs(s - meilleur[0]) < 1e-9
                                   and n > meilleur[1][1] - meilleur[1][0]):
                meilleur = (s, (k, k + n))
    if not meilleur[1]:
        return ""
    return " ".join(wtoks[meilleur[1][0]:meilleur[1][1]])


def _est_mot_de_phrase(mots: list[str]) -> bool:
    return bool(mots) and all(m in MOTS_INTERDITS for m in mots)


def _deja_reconnu(entendu: str, canon: str) -> bool:
    """Vrai si l'extraction actuelle range déjà cette forme au bon lieu."""
    resultat = extract_local(entendu)
    cible = forme(canon)
    return cible in {forme(resultat.get("depart") or ""), forme(resultat.get("arrivee") or "")}


def _plus_proche_autre(entendu: str, canon: str) -> tuple[str, float]:
    """Lieu (différent de canon) le plus proche de la forme, et la similarité."""
    cible = forme(canon)
    meilleur = ("", 0.0)
    for lieu in TOUS_LIEUX:
        if forme(lieu) == cible:
            continue
        s = sim(entendu, lieu)
        if s > meilleur[1]:
            meilleur = (lieu, s)
    return meilleur


def _canon_est_le_plus_proche(entendu: str, canon: str) -> bool:
    """Vrai si, parmi TOUS les lieux connus (canon compris), canon est bien
    celui dont la forme entendue est la plus proche.

    Plus strict que le seuil de 0.8 utilisé contre un autre lieu : ce n'est
    pas parce qu'aucun autre lieu n'est « trop » proche que canon est pour
    autant le meilleur candidat. On compare le score de canon au meilleur
    score tous lieux confondus (une petite marge flottante évite qu'une
    égalité exacte échoue par arrondi).
    """
    score_canon = sim(entendu, canon)
    meilleur_score = max((sim(entendu, lieu) for lieu in TOUS_LIEUX), default=0.0)
    return score_canon >= meilleur_score - 1e-9


def _charger():
    with open(META, encoding="utf-8", newline="") as fichier:
        meta = {r["file_name"]: r for r in csv.DictReader(fichier)}
    with open(ASR, encoding="utf-8", newline="") as fichier:
        asr = {r["file_name"]: r["transcription_whisper"] for r in csv.DictReader(fichier)}
    ok = [r for r in meta.values() if r["statut"] == "ok"]
    return ok, asr


def _correct(got: dict, ref: dict) -> bool:
    if not (ref.get("depart") and ref.get("arrivee")):
        return False
    return (
        forme(got.get("depart") or "") == forme(ref["depart"])
        and forme(got.get("arrivee") or "") == forme(ref["arrivee"])
    )


def _trajet(matcher: StopsMatcher, got: dict) -> bool:
    r = matcher.find_line(got.get("depart") or "", got.get("arrivee") or "")
    return bool(r["found"] or r["correspondances"])


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    analyseur.add_argument(
        "--locuteur",
        default=None,
        help=(
            "ne garder que les vocaux de ce locuteur (ex. locuteur_10) : pour mesurer "
            "le score Whisper sur un locuteur jamais vu séparément du reste de la collecte."
        ),
    )
    args = analyseur.parse_args(argv[1:])

    ok, asr = _charger()
    if args.locuteur:
        avant_filtre = len(ok)
        ok = [r for r in ok if r.get("locuteur") == args.locuteur]
        if not ok:
            print(f"Aucun vocal « ok » pour le locuteur {args.locuteur!r} (sur {avant_filtre} au total).")
            return 1
        print(f"=== Filtré sur {args.locuteur} : {len(ok)}/{avant_filtre} vocaux « ok » ===\n")
    matcher = StopsMatcher()

    # ------------------------------------------------------------------ #
    # Étape 1 : formes entendues
    # ------------------------------------------------------------------ #
    lieux_formes: dict[str, Counter] = defaultdict(Counter)
    lieux_locuteurs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    ban_bus_formes: Counter = Counter()
    marqueur_formes: Counter = Counter()
    marqueur_locuteurs: dict[str, set[str]] = defaultdict(set)

    preparé = []
    for ligne in ok:
        propre = ligne["transcription_propre"]
        whisper = asr.get(ligne["file_name"], "")
        locuteur = ligne.get("locuteur", "")
        ptoks, wtoks = norm(propre), norm(whisper)
        opcodes = _aligner(ptoks, wtoks)
        ref = extract_local(propre)
        for canon in {ref.get("depart"), ref.get("arrivee")}:
            if canon:
                entendu = _forme_entendue(ptoks, wtoks, opcodes, canon)
                lieux_formes[canon][entendu] += 1
                lieux_locuteurs[canon][entendu].add(locuteur)
        if "bus" in ptoks:
            ban_bus_formes[_meilleur_ngram(wtoks, "ban bus")] += 1
        if any(t in {"diogue", "diougue"} for t in ptoks):
            # La transcription propre écrit toujours « diougué/diogué » (les
            # collecteurs n'écrivent jamais « jóge »/« juge » tels quels) :
            # c'est Whisper qui, lui, entend souvent « joge », « juge »,
            # « njuge »… C'est pour CES formes entendues que la liste blanche
            # MARQUEURS_DEPART_PROPRES tranche à l'étape 5, pas pour chercher
            # ces mots dans la phrase propre (ils n'y apparaissent jamais).
            entendu = _meilleur_ngram(wtoks, "diougue")
            marqueur_formes[entendu] += 1
            marqueur_locuteurs[entendu].add(locuteur)
        preparé.append((ligne, propre, whisper, ref))

    print("=" * 72)
    print("1. FORMES ENTENDUES PAR LIEU (forme Whisper -> nombre)")
    print("=" * 72)
    for canon in sorted(lieux_formes, key=lambda c: forme(c)):
        formes = ", ".join(f"{h!r} ({n})" for h, n in lieux_formes[canon].most_common())
        print(f"  {canon} : {formes}")

    print("\n  Formule « ban bus » (Whisper) :",
          ", ".join(f"{h!r} ({n})" for h, n in ban_bus_formes.most_common()))
    print("  Marqueur de départ « diougué » (Whisper) :",
          ", ".join(f"{h!r} ({n})" for h, n in marqueur_formes.most_common()))

    # ------------------------------------------------------------------ #
    # Étape 2 : score AVANT
    # ------------------------------------------------------------------ #
    avant_correct = avant_trajet = ref_trajet = 0
    for ligne, propre, whisper, ref in preparé:
        got = extract_local(whisper)
        avant_correct += _correct(got, ref)
        avant_trajet += _trajet(matcher, got)
        ref_trajet += _trajet(matcher, ref)

    total = len(preparé)
    print("\n" + "=" * 72)
    print(f"2. SCORE AVANT (extract_local + StopsMatcher, sur les {total} vocaux « ok »"
          f"{' de ' + args.locuteur if args.locuteur else ''})")
    print("=" * 72)
    print(f"  Bon départ ET bonne arrivée : {avant_correct}/{total}")
    print(f"  Trouve un trajet             : {avant_trajet}/{total}")
    print(f"  (référence : les phrases propres trouvent un trajet : {ref_trajet}/{total})")

    # ------------------------------------------------------------------ #
    # Étape 3 : variantes proposées (SANS les appliquer)
    # ------------------------------------------------------------------ #
    acceptees: dict[tuple[str, str], str] = {}   # (type, entendu) -> cible
    refusees: list[tuple[str, str, str]] = []     # (type, entendu, raison)
    deja: list[tuple[str, str]] = []              # (type, entendu)

    formes_marqueur = {f for f in marqueur_formes if f}

    def classer(type_: str, entendu: str, canon: str) -> None:
        if entendu is None or not entendu.strip():
            return
        if forme(entendu) == forme(canon):
            return
        if _est_mot_de_phrase(norm(entendu)):
            refusees.append((type_, entendu, "mot de la phrase"))
            return
        if _deja_reconnu(entendu, canon):
            deja.append((type_, entendu))
            return
        autre, s = _plus_proche_autre(entendu, canon)
        if s >= 0.8:
            refusees.append((type_, entendu, f"proche de « {autre} » ({s:.2f})"))
            return
        acceptees[(type_, entendu)] = canon

    for canon, compteur in lieux_formes.items():
        for entendu in compteur:
            if entendu in formes_marqueur:
                continue  # déjà proposé comme forme du marqueur « diougué »
            classer("lieu", entendu, canon)
    for entendu in marqueur_formes:
        classer("marqueur", entendu, "diougue")

    print("\n" + "=" * 72)
    print("3. VARIANTES PROPOSÉES (aucune n'est appliquée)")
    print("=" * 72)
    print("  ACCEPTÉES :")
    for (type_, entendu), canon in sorted(acceptees.items()):
        print(f"    [{type_}] {entendu!r} -> {canon}")
    print("  REFUSÉES :")
    for type_, entendu, raison in sorted(refusees):
        print(f"    [{type_}] {entendu!r} : {raison}")
    print("  DÉJÀ RECONNUES (rien à ajouter) :")
    print("    " + ", ".join(f"{e!r}" for _t, e in sorted(set(deja))) if deja else "    (aucune)")

    # ------------------------------------------------------------------ #
    # Étape 5 : variantes SÛRES — sous-ensemble des ACCEPTÉES ci-dessus (donc
    # déjà débarrassées des mots de la phrase, des formes déjà reconnues et de
    # celles trop proches d'un AUTRE lieu), filtré en plus sur :
    #   - au moins OCCURRENCES_MIN_SUR occurrences,
    #   - entendues chez au moins LOCUTEURS_MIN_SUR locuteurs différents
    #     (sinon un seul vocal bruité suffirait à fabriquer une règle),
    #   - pour un lieu : le lieu visé est confirmé comme LE plus proche parmi
    #     tous les lieux connus (pas seulement « pas trop proche d'un autre »),
    #   - pour le marqueur de départ : SEULEMENT jóge/joge, juge, njuge, njugee
    #     (MARQUEURS_DEPART_PROPRES). La transcription propre écrit toujours
    #     « diougué »/« diogué » ; ce sont les formes que WHISPER invente pour
    #     ce même marqueur (voir marqueur_formes) qu'on restreint ici à cette
    #     liste blanche — jamais « dem » (6 occurrences dans la collecte !),
    #     qui annonce l'ARRIVÉE et corromprait toute phrase si on le réécrivait
    #     en marqueur de départ, et jamais le bruit ASR (« jge », « jile »,
    #     « monge », « nduwaa », « ndem »…) qui n'a aucune forme stable.
    # ------------------------------------------------------------------ #
    surs: list[tuple[str, str, str, int, int]] = []  # (type, entendu, canon, occurrences, locuteurs)
    for (type_, entendu), canon in acceptees.items():
        if type_ == "lieu":
            occurrences = lieux_formes[canon][entendu]
            locuteurs = lieux_locuteurs[canon][entendu]
        else:  # "marqueur"
            if forme(entendu) not in MARQUEURS_DEPART_PROPRES:
                continue
            assert forme(entendu) != forme("dem")  # garde-fou : jamais un marqueur de départ
            occurrences = marqueur_formes[entendu]
            locuteurs = marqueur_locuteurs[entendu]
        if occurrences < OCCURRENCES_MIN_SUR or len(locuteurs) < LOCUTEURS_MIN_SUR:
            continue
        if type_ == "lieu" and not _canon_est_le_plus_proche(entendu, canon):
            continue
        surs.append((type_, entendu, canon, occurrences, len(locuteurs)))

    print("\n" + "=" * 72)
    print(
        f"5. VARIANTES SÛRES (>= {OCCURRENCES_MIN_SUR} fois, >= {LOCUTEURS_MIN_SUR} locuteurs "
        "différents, lieu confirmé comme le plus proche)"
    )
    print("=" * 72)
    if surs:
        for type_, entendu, canon, occurrences, nloc in sorted(surs, key=lambda s: (s[0], s[1])):
            print(f"    [{type_}] {entendu!r} -> {canon}  ({occurrences} fois, {nloc} locuteurs)")
    else:
        print("    (aucune)")

    # ------------------------------------------------------------------ #
    # Étape 4 : simulation avec les variantes acceptées
    # ------------------------------------------------------------------ #
    reglages: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for (type_, entendu), canon in acceptees.items():
        cible = "diougue" if type_ == "marqueur" else canon
        reglages.append((tuple(norm(entendu)), tuple(norm(cible))))
    reglages.sort(key=lambda r: -len(r[0]))

    def appliquer(toks: list[str]) -> list[str]:
        sortie, i = [], 0
        while i < len(toks):
            for var, rep in reglages:
                if tuple(toks[i:i + len(var)]) == var:
                    sortie.extend(rep)
                    i += len(var)
                    break
            else:
                sortie.append(toks[i])
                i += 1
        return sortie

    apres_correct = apres_trajet = 0
    for _ligne, _propre, whisper, ref in preparé:
        got = extract_local(" ".join(appliquer(norm(whisper))))
        apres_correct += _correct(got, ref)
        apres_trajet += _trajet(matcher, got)

    print("\n" + "=" * 72)
    print("4. SCORE SIMULÉ APRÈS AJOUT DES VARIANTES ACCEPTÉES")
    print("=" * 72)
    print(f"  Bon départ ET bonne arrivée : {apres_correct}/{total}"
          f"   (avant : {avant_correct}/{total})")
    print(f"  Trouve un trajet             : {apres_trajet}/{total}"
          f"   (avant : {avant_trajet}/{total})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
