r"""Teste le découpage des jeux et le chargement des données de
scripts/finetune_whisper.py. Ne charge aucun modèle, ne touche à aucun audio
réel : tout est fabriqué dans un dossier temporaire.

    .\.venv\Scripts\python.exe tests\test_finetune_whisper.py

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
SCRIPT = RACINE / "scripts" / "finetune_whisper.py"


def _charger_module():
    spec = importlib.util.spec_from_file_location("finetune_whisper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fabriquer_metadata(dossier: Path, lignes: list[dict]) -> Path:
    """Écrit un metadata.csv minimal ; crée un faux .wav vide pour chaque ligne
    « ok » dont le fichier n'existe pas encore (charger_metadata exige le fichier)."""
    for ligne in lignes:
        if (ligne.get("statut") or "").strip() == "ok":
            chemin = dossier / ligne["file_name"]
            chemin.parent.mkdir(parents=True, exist_ok=True)
            if not chemin.exists():
                chemin.write_bytes(b"")
    meta = dossier / "metadata.csv"
    champs = ["file_name", "transcription", "transcription_propre", "locuteur", "duree_s", "statut"]
    with open(meta, "w", encoding="utf-8", newline="") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=champs, extrasaction="ignore")
        redacteur.writeheader()
        redacteur.writerows(lignes)
    return meta


def _ligne(nom: str, locuteur: str, propre: str = "x", brute: str | None = None,
           statut: str = "ok", duree: str = "3.00") -> dict:
    return {
        "file_name": f"{locuteur}/{nom}.wav",
        "transcription": brute if brute is not None else propre,
        "transcription_propre": propre,
        "locuteur": locuteur,
        "duree_s": duree,
        "statut": statut,
    }


def _charger_metadata_ok(module, travail: Path) -> list[tuple[str, bool]]:
    """charger_metadata : utilise transcription_propre, saute statut != ok,
    saute transcription_propre vide, saute l'audio manquant."""
    dossier = travail / "metadata"
    dossier.mkdir(parents=True, exist_ok=True)
    lignes = [
        _ligne("a", "locuteur_01", propre="maa ngi Fass dama bëgg dem Mermoz", brute="magui faas..."),
        _ligne("b", "locuteur_01", propre="", brute="texte jamais nettoyé"),
        _ligne("c", "locuteur_01", propre="Gawal ndayam", statut="sans_lieu"),
    ]
    meta = _fabriquer_metadata(dossier, lignes)
    # Audio manquant pour un 4e cas : jamais écrit sur disque.
    with open(meta, "a", encoding="utf-8", newline="") as fichier:
        redacteur = csv.writer(fichier)
        redacteur.writerow(["locuteur_01/d.wav", "brute d", "texte propre d", "locuteur_01", "3.00", "ok"])

    exemples = module.charger_metadata(meta)
    textes = {e["chemin_audio"].name: e["transcription"] for e in exemples}

    return [
        ("F: ne garde que la ligne valide (ok + propre + audio présent)", len(exemples) == 1),
        ("F: texte = transcription_propre (pas la brute)",
         textes.get("a.wav") == "maa ngi Fass dama bëgg dem Mermoz"),
        ("F: transcription_propre vide => sautée", "b.wav" not in textes),
        ("F: statut != ok => sautée", "c.wav" not in textes),
        ("F: audio manquant => sautée", "d.wav" not in textes),
    ]


def _decouper_jeux_ok(module) -> list[tuple[str, bool]]:
    """decouper_jeux : PLUSIEURS locuteurs de test (LOCUTEURS_TEST / --locuteurs-test)
    entièrement en TEST, jamais en train/validation ; plafond respecté à
    l'entraînement ; validation ~10 % du reste."""
    exemples = []
    # Deux locuteurs de test (liste, pas un seul nom) : jamais touchés par le
    # découpage train/validation, même partiellement.
    for i in range(6):
        exemples.append({"locuteur": "locuteur_test_a", "transcription": f"test a {i}",
                          "chemin_audio": Path(f"locuteur_test_a/{i}.wav"), "duree_s": 3.0})
    for i in range(4):
        exemples.append({"locuteur": "locuteur_test_b", "transcription": f"test b {i}",
                          "chemin_audio": Path(f"locuteur_test_b/{i}.wav"), "duree_s": 3.0})
    # locuteur_gros : 30 vocaux, le plafond doit en couper 5 à l'entraînement.
    for i in range(30):
        exemples.append({"locuteur": "locuteur_gros", "transcription": f"gros {i}",
                          "chemin_audio": Path(f"locuteur_gros/{i}.wav"), "duree_s": 3.0})
    # locuteur_petit : 5 vocaux, sous le plafond.
    for i in range(5):
        exemples.append({"locuteur": "locuteur_petit", "transcription": f"petit {i}",
                          "chemin_audio": Path(f"locuteur_petit/{i}.wav"), "duree_s": 3.0})

    train, validation, test = module.decouper_jeux(
        exemples, graine=1337, locuteurs_test=["locuteur_test_a", "locuteur_test_b"],
        part_validation=0.10, max_train_par_locuteur=25,
    )

    loc_train = {e["locuteur"] for e in train}
    loc_validation = {e["locuteur"] for e in validation}
    loc_test = {e["locuteur"] for e in test}
    train_gros = [e for e in train if e["locuteur"] == "locuteur_gros"]
    toutes_les_entrees = {e["chemin_audio"] for e in train} | {e["chemin_audio"] for e in validation}
    aucun_doublon = len(toutes_les_entrees) == len(train) + len(validation)

    return [
        ("D: les 2 locuteurs de test entièrement en TEST",
         len(test) == 10 and loc_test == {"locuteur_test_a", "locuteur_test_b"}),
        ("D: locuteurs de test absents du train", loc_train.isdisjoint({"locuteur_test_a", "locuteur_test_b"})),
        ("D: locuteurs de test absents de la validation",
         loc_validation.isdisjoint({"locuteur_test_a", "locuteur_test_b"})),
        ("D: plafond respecté (locuteur_gros <= 25 à l'entraînement)", len(train_gros) == 25),
        # round(5 * 0.10) == 0 (arrondi bancaire de Python) : avec si peu de
        # vocaux, locuteur_petit part entièrement à l'entraînement.
        ("D: locuteur_petit entièrement en entraînement (arrondi à 0 validation)",
         sum(1 for e in train if e["locuteur"] == "locuteur_petit") == 5),
        ("D: validation ~10% du reste (locuteur_gros)",
         sum(1 for e in validation if e["locuteur"] == "locuteur_gros") == 3),
        ("D: validation ~10% du reste (locuteur_petit, arrondie à 0)",
         sum(1 for e in validation if e["locuteur"] == "locuteur_petit") == 0),
        ("D: train et validation disjoints (aucun doublon)", aucun_doublon),
        ("D: reproductible (même graine => même découpage)",
         module.decouper_jeux(exemples, graine=1337,
                               locuteurs_test=["locuteur_test_a", "locuteur_test_b"])[0] == train),
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    module = _charger_module()
    travail = Path(tempfile.mkdtemp(prefix="test_finetune_"))
    try:
        verifications: list[tuple[str, bool]] = []
        verifications += _charger_metadata_ok(module, travail)
        verifications += _decouper_jeux_ok(module)

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
