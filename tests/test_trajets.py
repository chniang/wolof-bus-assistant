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
    ("Maa ngi Liberté 5, dama bëgg dem Guédiawaye", {"corr:Ligne 77", "corr:Ligne 78"}),
]

AUDIOS = [
    ("data/demo_audio/trajet ouakam_palais.wav", {"Ligne 7"}),
    ("data/demo_audio/trajet liberte5_palais2.wav", {"Ligne 10", "Ligne 13"}),
]


def _ok(trouvees: set[str], attendues: set[str]) -> bool:
    return bool(trouvees & attendues)


def test_local() -> int:
    from intent.extract_intent import extract_local
    from matching.stops_matcher import StopsMatcher

    matcher = StopsMatcher()
    echecs = 0
    for phrase, attendues in TRAJETS:
        lieux = extract_local(phrase)
        resultat = matcher.find_line(lieux.get("depart") or "", lieux.get("arrivee") or "")
        trouvees = {l["ligne"] for l in resultat["lignes"]}
        trouvees |= {"corr:" + c["etape_1"]["ligne"] for c in resultat["correspondances"]}
        bon = _ok(trouvees, attendues)
        echecs += not bon
        print(f"{'OK ' if bon else 'ÉCHEC'} | {phrase}\n      {lieux.get('depart')} -> {lieux.get('arrivee')} | {sorted(trouvees) or 'rien'}")
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
    reponse = client.post(
        f"{URL_APP}/gradio_api/call/trouver_le_bus", json={"data": [fichier, phrase or ""]}
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
    cas = [(p, None, a) for p, a in TRAJETS] + [(None, RACINE / f, a) for f, a in AUDIOS]
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
            bon = _ok(trouvees, attendues)
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
    echecs = test_en_ligne() if en_ligne else test_local()
    total = len(TRAJETS) + (len(AUDIOS) if en_ligne else 0)
    print(f"\n{total - echecs}/{total} réussis")
    sys.exit(1 if echecs else 0)
