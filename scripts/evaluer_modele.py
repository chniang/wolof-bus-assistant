r"""Évalue un modèle Whisper (actuel OU fine-tuné) sur le jeu de TEST figé
(scripts/finetune_whisper.py : LOCUTEUR_TEST, jamais vu à l'entraînement).

Utilisation :
    .\.venv\Scripts\python.exe scripts\evaluer_modele.py M9and2M/whisper-small-wolof
    .\.venv\Scripts\python.exe scripts\evaluer_modele.py models\whisper-small-wolof-dakar
    .\.venv\Scripts\python.exe scripts\evaluer_modele.py M9and2M/whisper-small-wolof --locuteur locuteur_09

« modele » est soit un identifiant Hugging Face (modèle actuel, en ligne), soit
un chemin local (le modèle fine-tuné sauvegardé par finetune_whisper.py) :
WhisperForConditionalGeneration.from_pretrained gère les deux de la même façon.
Les réglages de décodage (tâche, pas de langue forcée, 48 tokens, glouton) sont
repris tels quels de scripts/finetune_whisper.py, pas réimplémentés ici.

Sort :
  - le WER (%) entre transcription_propre (référence) et la transcription du
    modèle, comme scripts/finetune_whisper.py ;
  - le nombre de trajets bien compris : extract_local sur la transcription du
    modèle, puis StopsMatcher.find_line (found OU correspondances), exactement
    la métrique de scripts/analyser_whisper.py (étape 2, "Trouve un trajet").

100 % lecture seule : aucun fichier de data/ ni de models/ n'est modifié.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from intent.extract_intent import extract_local  # noqa: E402
from matching.stops_matcher import StopsMatcher  # noqa: E402

sys.path.insert(0, str(RACINE / "scripts"))
import finetune_whisper as ft  # noqa: E402

META_DEFAUT = RACINE / "data" / "collecte" / "metadata.csv"


def charger_jeu_test(metadata_csv: Path, locuteur: str) -> list[dict]:
    """Vocaux « ok » du locuteur demandé (par défaut, le jeu de TEST figé)."""
    exemples = ft.charger_metadata(Path(metadata_csv))
    return [e for e in exemples if e["locuteur"] == locuteur]


def trajet_compris(matcher: StopsMatcher, transcription: str) -> bool:
    """Vrai si StopsMatcher trouve un trajet (direct ou avec changement) à
    partir de ce que extract_local comprend de cette transcription.

    Même définition que scripts/analyser_whisper.py (étape 2, "Trouve un trajet").
    """
    extrait = extract_local(transcription)
    resultat = matcher.find_line(extrait.get("depart") or "", extrait.get("arrivee") or "")
    return bool(resultat["found"] or resultat["correspondances"])


def evaluer_modele(
    nom_modele: str,
    exemples: list[dict],
    batch: int = 8,
    forcer_cpu: bool = False,
) -> dict:
    """Transcrit `exemples` avec `nom_modele` et renvoie WER + trajets compris.

    `nom_modele` : identifiant Hugging Face (modèle actuel) ou chemin local
    (modèle fine-tuné). Réutilise _charger_audio_16k/_decode de
    scripts/finetune_whisper.py : mêmes réglages de décodage que l'app.
    """
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    if not exemples:
        return {"n": 0, "wer": 0.0, "trajets_compris": 0, "transcriptions": []}

    device = "cpu" if forcer_cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Modèle : {nom_modele} | appareil : {device}")
    processor = WhisperProcessor.from_pretrained(nom_modele)
    model = WhisperForConditionalGeneration.from_pretrained(nom_modele).to(device)
    model.generation_config.task = ft.TACHE
    model.eval()

    matcher = StopsMatcher()
    references: list[str] = []
    transcriptions: list[str] = []
    for i in range(0, len(exemples), batch):
        lot = exemples[i : i + batch]
        audios = [ft._charger_audio_16k(e["chemin_audio"]) for e in lot]
        transcriptions.extend(ft._decode(model, processor, audios, device))
        references.extend(e["transcription"] for e in lot)

    trajets_compris = sum(trajet_compris(matcher, t) for t in transcriptions)
    return {
        "n": len(exemples),
        "wer": 100.0 * ft.calculer_wer(references, transcriptions),
        "trajets_compris": trajets_compris,
        "transcriptions": list(zip((e["chemin_audio"].name for e in exemples), references, transcriptions)),
    }


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    analyseur.add_argument("modele", help="identifiant Hugging Face ou chemin local du modèle à évaluer.")
    analyseur.add_argument(
        "--locuteur", default=ft.LOCUTEUR_TEST,
        help=f"locuteur à évaluer (défaut : {ft.LOCUTEUR_TEST}, le jeu de TEST figé).",
    )
    analyseur.add_argument("--metadata", default=str(META_DEFAUT), help="chemin de metadata.csv.")
    analyseur.add_argument("--batch", type=int, default=8)
    analyseur.add_argument("--detail", action="store_true", help="affiche chaque transcription.")
    args = analyseur.parse_args(argv[1:])

    exemples = charger_jeu_test(Path(args.metadata), args.locuteur)
    if not exemples:
        print(f"Aucun vocal « ok » pour le locuteur {args.locuteur!r} dans {args.metadata}.")
        return 1

    debut = time.perf_counter()
    resultat = evaluer_modele(args.modele, exemples, batch=args.batch)
    duree = time.perf_counter() - debut

    print(f"\n=== Évaluation sur {args.locuteur} ({resultat['n']} vocaux) ===")
    print(f"  Modèle                : {args.modele}")
    print(f"  WER                   : {resultat['wer']:.1f} %")
    print(f"  Trajets bien compris  : {resultat['trajets_compris']}/{resultat['n']}")
    print(f"  Durée                 : {duree:.1f} s")

    if args.detail:
        print("\n--- Détail ---")
        for nom, reference, hypothese in resultat["transcriptions"]:
            print(f"  {nom}")
            print(f"    référence  : {reference}")
            print(f"    transcrit  : {hypothese}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
