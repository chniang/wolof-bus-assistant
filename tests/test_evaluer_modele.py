r"""Teste la logique de scripts/evaluer_modele.py qui ne demande pas de modèle :
le filtrage du jeu de test et la métrique « trajet bien compris » (extract_local
+ StopsMatcher, comme scripts/analyser_whisper.py). Aucun modèle Whisper n'est
chargé ici : trop long et sans rapport avec cette logique.

    .\.venv\Scripts\python.exe tests\test_evaluer_modele.py

Code de sortie : 0 si tout passe.
"""

from __future__ import annotations

import csv
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "scripts" / "evaluer_modele.py"
sys.path.insert(0, str(RACINE / "src"))

from matching.stops_matcher import StopsMatcher  # noqa: E402


def _charger_module():
    spec = importlib.util.spec_from_file_location("evaluer_modele", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trajet_compris_ok(module) -> list[tuple[str, bool]]:
    matcher = StopsMatcher()
    return [
        ("T: trajet direct bien compris",
         module.trajet_compris(matcher, "maa ngi Guédiawaye dama bëgg dem Colobane") is True),
        ("T: phrase sans lieu => aucun trajet", module.trajet_compris(matcher, "Gawal ndayam") is False),
        ("T: texte vide => aucun trajet", module.trajet_compris(matcher, "") is False),
    ]


def _charger_jeu_test_ok(module, travail: Path) -> list[tuple[str, bool]]:
    """charger_jeu_test : ne garde que les vocaux « ok » des locuteurs demandés
    (une LISTE, pour supporter plusieurs locuteurs de test en même temps)."""
    dossier = travail / "collecte"
    dossier.mkdir(parents=True, exist_ok=True)
    lignes = [
        {"file_name": "locuteur_10/a.wav", "transcription": "x", "transcription_propre":
         "maa ngi Guédiawaye dama bëgg dem Colobane", "locuteur": "locuteur_10", "duree_s": "3.00", "statut": "ok"},
        {"file_name": "locuteur_10/b.wav", "transcription": "x", "transcription_propre":
         "Gawal ndayam", "locuteur": "locuteur_10", "duree_s": "3.00", "statut": "sans_lieu"},
        {"file_name": "locuteur_11/d.wav", "transcription": "x", "transcription_propre":
         "maa ngi Thiaroye dama bëgg dem Mbao", "locuteur": "locuteur_11", "duree_s": "3.00", "statut": "ok"},
        {"file_name": "locuteur_01/c.wav", "transcription": "x", "transcription_propre":
         "maa ngi Yoff dama bëgg dem Ouakam", "locuteur": "locuteur_01", "duree_s": "3.00", "statut": "ok"},
    ]
    for ligne in lignes:
        chemin = dossier / ligne["file_name"]
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(b"")
    meta = dossier / "metadata.csv"
    champs = ["file_name", "transcription", "transcription_propre", "locuteur", "duree_s", "statut"]
    with open(meta, "w", encoding="utf-8", newline="") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=champs)
        redacteur.writeheader()
        redacteur.writerows(lignes)

    jeu_10_11 = module.charger_jeu_test(meta, ["locuteur_10", "locuteur_11"])
    jeu_01 = module.charger_jeu_test(meta, ["locuteur_01"])
    jeu_vide = module.charger_jeu_test(meta, ["locuteur_99"])

    return [
        ("J: plusieurs locuteurs de test combinés, statut ok seulement",
         len(jeu_10_11) == 2
         and {e["chemin_audio"].name for e in jeu_10_11} == {"a.wav", "d.wav"}),
        ("J: autre locuteur isolé", len(jeu_01) == 1 and jeu_01[0]["chemin_audio"].name == "c.wav"),
        ("J: locuteur absent => jeu vide", jeu_vide == []),
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    module = _charger_module()
    travail = Path(tempfile.mkdtemp(prefix="test_evaluer_modele_"))
    try:
        verifications: list[tuple[str, bool]] = []
        verifications += _trajet_compris_ok(module)
        verifications += _charger_jeu_test_ok(module, travail)

        echecs = 0
        for titre, bon in verifications:
            echecs += not bon
            print(f"{'OK ' if bon else 'ÉCHEC'} | {titre}")
        print(f"\n{len(verifications) - echecs}/{len(verifications)} réussis")
        return 1 if echecs else 0
    finally:
        shutil.rmtree(travail, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
