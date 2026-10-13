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
    # « Liberté 5 » comme « Guédiawaye » sont des lieux : la montée doit être un
    # arrêt « Liberté 5 » et non l'arrêt simplement proche « Liberté 6 ».
    ("Maa ngi Liberté 5, dama bëgg dem Guédiawaye", {"corr:Ligne 77", "corr:Ligne 78"}),
    ("Maa ngi Pikine, bëgg naa dem Guédiawaye", {"Ligne 37", "Ligne 41", "Ligne 46"}),
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


def test_local() -> int:
    from intent.extract_intent import extract_local
    from matching.compagnie import message_autre_compagnie
    from matching.stops_matcher import StopsMatcher

    matcher = StopsMatcher()
    echecs = 0
    for phrase, attendues in TRAJETS:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = {l["ligne"] for l in resultat["lignes"]}
        trouvees |= {"corr:" + c["etape_1"]["ligne"] for c in resultat["correspondances"]}
        bon = _ok(trouvees, attendues, TRAJETS_EXCLUS.get(phrase, frozenset()))
        echecs += not bon
        print(f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n      {lieux.get('depart')} -> {lieux.get('arrivee')} | {sorted(trouvees) or 'rien'}")
    for phrase, compagnie, attendues, interdites in TRAJETS_COMPAGNIE:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = {l["ligne"] for l in resultat["lignes"] if l["compagnie"] == compagnie}
        exclues = {l["ligne"] for l in resultat["lignes"] if l["compagnie"] in interdites}
        bon = lieux.get("compagnie") == compagnie and _ok(trouvees, attendues, exclues)
        echecs += not bon
        print(
            f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n"
            f"      compagnie={lieux.get('compagnie')!r} | {lieux.get('depart')} -> {lieux.get('arrivee')} | {sorted(trouvees) or 'rien'}"
        )
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
            f"      {lieux.get('depart')} -> {lieux.get('arrivee')} | {sorted(trouvees) or 'rien'}"
        )
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
            f"      {lieux.get('depart')} -> {lieux.get('arrivee')} | {sorted(trouvees) or 'rien'}"
        )
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
        echecs = test_local()
        # +1 « tata » jamais un lieu, +1 « siis » jamais un lieu, +1 cas compagnie réelle.
        total = (
            len(TRAJETS)
            + len(TRAJETS_COMPAGNIE)
            + len(TRAJETS_LIEUX)
            + len(TRAJETS_QUARTIER)
            + len(TRAJETS_GEO)
            + len(TRAJETS_SANS_MONTEE_FAUSSE)
            + len(TRAJETS_SANS_MONTEE_HOMONYME)
            + 3
        )
    print(f"\n{total - echecs}/{total} réussis")
    sys.exit(1 if echecs else 0)
