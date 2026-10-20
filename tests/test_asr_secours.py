r"""Vérifie le chargement du Whisper CPU de `asr.transcribe` : fine-tuné d'abord,
repli automatique.

Aucun modèle n'est téléchargé ni exécuté : `_telecharger_modele` et
`_charger_pipeline` sont remplacés par des bouchons, pour ne tester que la
logique — le dépôt TIJAANI privé en tête, le repli sur M9and2M/whisper-small-wolof
quand le premier ne se charge pas (token absent, dépôt protégé, erreur réseau),
le téléchargement des seuls fichiers de la racine (jamais les checkpoints) et
le libellé affiché sous chaque résultat, qui doit dire quel Whisper a servi.

    .\.venv\Scripts\python.exe tests\test_asr_secours.py

Code de sortie : 0 si tout passe, 1 sinon.
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from asr import transcribe  # noqa: E402

# Liste telle que la renvoie le dépôt fine-tuné : poids et configs à la racine,
# checkpoints de l'entraînement en sous-dossiers.
FICHIERS_DEPOT = [
    ".gitattributes",
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "checkpoint-32/config.json",
    "checkpoint-32/model.safetensors",
    "checkpoint-32/optimizer.pt",
    "checkpoint-48/config.json",
    "checkpoint-48/model.safetensors",
]


def _charger_avec_bouchons(fuites: dict, depot_qui_lève: str | None = None):
    """Lance `load_model` avec des bouchons ; renvoie (modèle, journal, dépôts appelés).

    `fuites` permet de simuler un échec : si un dépôt y figure, son chargement
    lève la RuntimeError indiquée. `depot_qui_lève` force l'échec du dépôt
    fine-tuné même si `fuites` est vide.
    """
    depots: list[tuple[str, str | None]] = []

    def faux_telechargement(depot: str, token: str | None = None) -> str:
        depots.append((depot, token))
        if depot in fuites or depot == depot_qui_lève:
            raise RuntimeError(fuites.get(depot, "Repository not found"))
        return f"/tmp/{depot}"

    def faux_pipeline(dossier: str):
        return f"pipeline de {dossier}"

    journal = io.StringIO()
    transcribe.MODELE_CHARGE = None
    with patch.object(transcribe, "_telecharger_modele", faux_telechargement), patch.object(
        transcribe, "_charger_pipeline", faux_pipeline
    ), redirect_stdout(journal):
        modele = transcribe.load_model()
    return modele, journal.getvalue(), depots


def cas_finetune_dabord() -> int:
    """Quand le dépôt fine-tuné est accessible, c'est lui qui est chargé (et seul)."""
    modele, journal, depots = _charger_avec_bouchons({})
    attendu = f"pipeline de /tmp/{transcribe.MODEL_WHISPER}"
    bon = (
        modele == attendu
        and depots == [(transcribe.MODEL_WHISPER, os.getenv("HF_TOKEN"))]
        and transcribe.MODEL_WHISPER_SECOURS not in journal
    )
    print(f"{'OK ' if bon else 'ÉCHEC'} | modèle fine-tuné chargé en premier ({depots})")
    return not bon


def cas_libelle_du_modele_charge() -> int:
    """La mention « Transcription : … » dit quel Whisper a servi, et triche jamais.

    Le libellé vient de `libelle_charge()` : l'app l'affiche sous chaque
    résultat. Textes fixés par l'interface — un repli doit se voir.
    """
    _charger_avec_bouchons({})
    fine_tune = transcribe.libelle_charge()
    _charger_avec_bouchons({}, depot_qui_lève=transcribe.MODEL_WHISPER)
    repli = transcribe.libelle_charge()
    ancien = transcribe.MODELE_CHARGE
    transcribe.MODELE_CHARGE = None
    rien = transcribe.libelle_charge()
    transcribe.MODELE_CHARGE = ancien

    attendus = {
        "fine-tuné": ("Whisper fine-tuné Dakar (CPU)", fine_tune),
        "repli": ("Whisper wolof de base (CPU, repli)", repli),
        "rien chargé": ("Whisper wolof (CPU)", rien),
    }
    bon = all(voulu == dit for _, (voulu, dit) in attendus.items()) and not any(
        "Kiriku" in dit for _, dit in attendus.values()
    )
    print(f"{'OK ' if bon else 'ÉCHEC'} | libellés : {fine_tune!r} / {repli!r}")
    if not bon:
        for nom, (voulu, dit) in attendus.items():
            if voulu != dit:
                print(f"    {nom}: attendu {voulu!r}, obtenu {dit!r}")
    return not bon


def cas_repli_sans_token() -> int:
    """Dépôt privé inaccessible (token absent) : on repart du wolof public, avec un message."""
    ancien = os.environ.pop("HF_TOKEN", None)
    try:
        modele, journal, depots = _charger_avec_bouchons({}, depot_qui_lève=transcribe.MODEL_WHISPER)
    finally:
        if ancien is not None:
            os.environ["HF_TOKEN"] = ancien
    attendu = f"pipeline de /tmp/{transcribe.MODEL_WHISPER_SECOURS}"
    bon = (
        modele == attendu
        and [d for d, _ in depots] == [transcribe.MODEL_WHISPER, transcribe.MODEL_WHISPER_SECOURS]
        and "repli" in journal
        and transcribe.MODEL_WHISPER_SECOURS in journal
        and "HF_TOKEN" in journal
    )
    print(f"{'OK ' if bon else 'ÉCHEC'} | repli sur le modèle public + message dans le journal")
    if not bon:
        print(f"    journal: {journal!r}")
    return not bon


def cas_repli_sur_erreur_reseau() -> int:
    """Token présent mais coupure réseau : même repli, sans mention du token."""
    modele, journal, depots = _charger_avec_bouchons(
        {transcribe.MODEL_WHISPER: "Connection error"},
    )
    attendu = f"pipeline de /tmp/{transcribe.MODEL_WHISPER_SECOURS}"
    bon = (
        modele == attendu
        and len(depots) == 2
        and "repli" in journal
        and "Connection error" in journal
    )
    print(f"{'OK ' if bon else 'ÉCHEC'} | repli aussi sur une erreur réseau ({len(depots)} dépôts)")
    return not bon


def cas_les_deux_echouent() -> int:
    """Sans aucun modèle, on ne fait pas semblant : l'erreur remonte à l'appelant."""
    levé = False
    try:
        _charger_avec_bouchons(
            {
                transcribe.MODEL_WHISPER: "Repository not found",
                transcribe.MODEL_WHISPER_SECOURS: "Connection error",
            },
        )
    except RuntimeError as exc:
        levé = transcribe.MODEL_WHISPER in str(exc) and transcribe.MODEL_WHISPER_SECOURS in str(exc)
    print(f"{'OK ' if levé else 'ÉCHEC'} | les deux dépôts en échec → exception explicite")
    return not levé


def cas_racine_seule() -> int:
    """Le téléchargement écarte les checkpoints de l'entraînement, garde la racine."""
    from huggingface_hub.utils import filter_repo_objects

    gardes = list(
        filter_repo_objects(FICHIERS_DEPOT, ignore_patterns=transcribe.TELECHARGEMENT_RACINE)
    )
    bon = gardes == [f for f in FICHIERS_DEPOT if "/" not in f] and gardes
    print(f"{'OK ' if bon else 'ÉCHEC'} | {len(gardes)}/{len(FICHIERS_DEPOT)} fichiers gardés, sans checkpoint")
    return not bool(bon)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== Test du chargement du Whisper CPU (fine-tuné + repli) ===\n")
    echecs = 0
    for essai in (
        cas_finetune_dabord,
        cas_libelle_du_modele_charge,
        cas_repli_sans_token,
        cas_repli_sur_erreur_reseau,
        cas_les_deux_echouent,
        cas_racine_seule,
    ):
        echecs += essai()
    print(f"\n{6 - echecs}/6 réussis")
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
