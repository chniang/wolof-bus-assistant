r"""Fine-tune M9and2M/whisper-small-wolof sur les voix collectées par WhatsApp.

Sur Brev (GPU, facturé à l'heure) :
    python scripts/finetune_whisper.py

Sur le laptop (CPU, essai à blanc, ne touche ni data/ ni models/) :
    .\.venv\Scripts\python.exe scripts\finetune_whisper.py --essai-a-blanc

Les réglages de décodage sont repris tels quels de src/asr/transcribe.py :
tâche « transcribe », aucune langue forcée (Whisper ne connaît pas le wolof,
« wo » le fait planter), décodage glouton, 48 tokens au plus.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from matching.lieux import forme, lieux_reconnaissables  # noqa: E402

# --- Réglages de décodage identiques à l'app (src/asr/transcribe.py) --------- #
TACHE = "transcribe"      # task="transcribe"
LANGUE = None             # pas de language : Whisper ne connaît pas le wolof
MAX_NEW_TOKENS = 48       # anti-hallucination, comme dans l'app
NUM_BEAMS = 1             # décodage glouton
SAMPLE_RATE = 16000

MODEL_DEFAUT = "M9and2M/whisper-small-wolof"
MODELE_ESSAI = "openai/whisper-tiny"
DEPOT_HUB = "TIJAANI/whisper-small-wolof-dakar"

# Révisions épinglées (HfApi.model_info, sans télécharger les poids). Le dépôt
# d'entraînement ne doit pas changer entre deux runs : sinon le WER n'est plus
# comparable d'une exécution à l'autre.
REVISIONS_CONNUES = {
    MODEL_DEFAUT: "8cc20b3c6e77ecb490210103d3b4fd0b85c3d1d8",
    MODELE_ESSAI: "169d4a4341b33bc18d8881c4b69c2e104e1cc0af",
}


def revision_pour(nom_modele: str, revision: str | None = None) -> str | None:
    """Révision à charger : locale = None, Hub connu = SHA, Hub inconnu = erreur."""
    if Path(nom_modele).exists():
        return None
    if revision:
        return revision
    if nom_modele in REVISIONS_CONNUES:
        return REVISIONS_CONNUES[nom_modele]
    raise ValueError(
        f"révision inconnue pour {nom_modele} : passer --revision <sha> "
        "pour ne pas charger une branche mobile."
    )

GRAINE = 1337
LR = 1e-5

# Découpage des jeux (voir decouper_jeux) : LOCUTEURS_TEST sont TOUJOURS le jeu
# de TEST (jamais vus à l'entraînement ni à la validation, condition sine qua
# non pour une évaluation honnête — comme le fait déjà scripts/analyser_whisper.py
# --locuteur). D'autres locuteurs de test arriveront au fil de la collecte, d'où
# une liste plutôt qu'un seul nom (surchargeable avec --locuteurs-test). Le
# reste est découpé PAR LOCUTEUR en entraînement et validation, puis
# l'entraînement est plafonné à MAX_TRAIN_PAR_LOCUTEUR vocaux par locuteur pour
# qu'un locuteur très bavard (locuteur_08, locuteur_09...) ne domine pas
# l'entraînement face aux locuteurs qui ont peu contribué.
LOCUTEURS_TEST = ["locuteur_10", "locuteur_11"]
PART_VALIDATION = 0.10
MAX_TRAIN_PAR_LOCUTEUR = 25


# --------------------------------------------------------------------------- #
# Lieux : on réutilise la normalisation de src/matching/lieux.py
# --------------------------------------------------------------------------- #

def _charger_formes_lieux() -> set[str]:
    """Formes normalisées des lieux du réseau, pour repérer les noms dans une phrase."""
    arrets: set[str] = set()
    csv_itineraires = RACINE / "data" / "itineraires_dakar.csv"
    if csv_itineraires.exists():
        with open(csv_itineraires, newline="", encoding="utf-8") as fichier:
            for rangee in csv.DictReader(fichier):
                if rangee.get("arret"):
                    arrets.add(rangee["arret"])
    formes = {forme(lieu) for lieu in lieux_reconnaissables(sorted(arrets))}
    formes.add(forme("Palais"))  # terminologie employée par les voyageurs
    return {f for f in formes if f}


def _lieux_dans(phrase: str, formes: set[str]) -> set[str]:
    """Lieux du réseau présents dans la phrase (via la normalisation de lieux.py)."""
    phrase_forme = forme(phrase)
    trouves: set[str] = set()
    for lieu in formes:
        if re.search(r"(?:^| )" + re.escape(lieu) + r"(?: |$)", phrase_forme):
            trouves.add(lieu)
    # On garde le nom le plus précis : « palais 1 » plutôt que « palais ».
    return {a for a in trouves if not any(a != b and a in b for b in trouves)}


def _motif(lieu: str) -> re.Pattern:
    return re.compile(r"(?:^| )" + re.escape(lieu) + r"(?: |$)")


# --------------------------------------------------------------------------- #
# WER
# --------------------------------------------------------------------------- #

def _levenshtein(a: list[str], b: list[str]) -> int:
    precedente = list(range(len(b) + 1))
    for i, mot_a in enumerate(a, start=1):
        courante = [i]
        for j, mot_b in enumerate(b, start=1):
            cout = 0 if mot_a == mot_b else 1
            courante.append(min(courante[-1] + 1, precedente[j] + 1, precedente[j - 1] + cout))
        precedente = courante
    return precedente[-1]


def calculer_wer(references: list[str], hypotheses: list[str]) -> float:
    """WER (0-1). Use jiwer si présent, sinon calcul interne sur les mots."""
    try:
        import jiwer

        return float(jiwer.wer(references, hypotheses))
    except Exception:
        erreurs = 0
        total = 0
        for ref, hyp in zip(references, hypotheses):
            ref_mots = ref.lower().split()
            hyp_mots = hyp.lower().split()
            erreurs += _levenshtein(ref_mots, hyp_mots)
            total += len(ref_mots)
        return erreurs / total if total else 0.0


def exactitude_lieux(references: list[str], hypotheses: list[str], formes: set[str]) -> float:
    """% de phrases dont TOUS les lieux attendus réapparaissent dans la transcription."""
    bons = 0
    total = 0
    for ref, hyp in zip(references, hypotheses):
        attendus = _lieux_dans(ref, formes)
        if not attendus:
            continue
        total += 1
        hyp_forme = forme(hyp)
        if all(_motif(lieu).search(hyp_forme) for lieu in attendus):
            bons += 1
    return 100.0 * bons / total if total else 0.0


# --------------------------------------------------------------------------- #
# Données
# --------------------------------------------------------------------------- #

def _charger_audio_16k(chemin: Path):
    """Lit un wav et le ramène à 16 kHz mono float32."""
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(str(chemin), dtype="float32")
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    if sr != SAMPLE_RATE:
        duree = len(audio) / sr
        n_cible = int(duree * SAMPLE_RATE)
        x = np.linspace(0, duree, num=len(audio), endpoint=False)
        xc = np.linspace(0, duree, num=n_cible, endpoint=False)
        audio = np.interp(xc, x, audio).astype("float32")
    return np.asarray(audio, dtype="float32")


def charger_metadata(metadata_csv: Path) -> list[dict]:
    """Charge metadata.csv : audios « ok » dont transcription_propre est remplie.

    Le texte vient de transcription_propre (orthographe des lieux uniformisée
    par scripts/nettoyer_transcriptions.py), jamais de transcription brute. Une
    ligne « ok » sans transcription_propre (nettoyage pas encore passé dessus)
    est sautée plutôt que d'entraîner sur un texte non relu.
    """
    metadata_csv = Path(metadata_csv)
    if not metadata_csv.exists():
        return []
    dossier = metadata_csv.parent
    exemples: list[dict] = []
    with open(metadata_csv, newline="", encoding="utf-8") as fichier:
        for rangee in csv.DictReader(fichier):
            if (rangee.get("statut") or "").strip() != "ok":
                continue
            texte = (rangee.get("transcription_propre") or "").strip()
            chemin = dossier / (rangee.get("file_name") or "")
            if not texte or not chemin.exists():
                continue
            try:
                duree_s = float(rangee.get("duree_s") or 0.0)
            except ValueError:
                duree_s = 0.0
            exemples.append(
                {
                    "chemin_audio": chemin,
                    "transcription": texte,
                    "locuteur": (rangee.get("locuteur") or "inconnu").strip(),
                    "duree_s": duree_s,
                }
            )
    return exemples


def decouper_jeux(
    exemples: list[dict],
    graine: int,
    locuteurs_test: list[str] = LOCUTEURS_TEST,
    part_validation: float = PART_VALIDATION,
    max_train_par_locuteur: int = MAX_TRAIN_PAR_LOCUTEUR,
):
    """locuteurs_test = jeu de TEST en entier, jamais vus à l'entraînement ni à
    la validation. Le reste est découpé PAR LOCUTEUR (chaque locuteur contribue
    à peu près part_validation à la validation, le tirage est stable d'un
    lancement à l'autre pour une même graine), puis l'entraînement de chaque
    locuteur est plafonné à max_train_par_locuteur vocaux (le surplus, tiré au
    sort, est perdu pour l'entraînement — jamais déplacé vers la validation ni
    le test).
    """
    import random

    locuteurs_test_ens = set(locuteurs_test)
    rng = random.Random(graine)
    test = [e for e in exemples if e["locuteur"] in locuteurs_test_ens]

    reste_par_locuteur: dict[str, list[dict]] = {}
    for exemple in exemples:
        if exemple["locuteur"] in locuteurs_test_ens:
            continue
        reste_par_locuteur.setdefault(exemple["locuteur"], []).append(exemple)

    train: list[dict] = []
    validation: list[dict] = []
    for locuteur in sorted(reste_par_locuteur):
        vocaux = list(reste_par_locuteur[locuteur])
        rng.shuffle(vocaux)
        n_validation = round(len(vocaux) * part_validation)
        validation.extend(vocaux[:n_validation])
        a_entrainer = vocaux[n_validation:]
        if len(a_entrainer) > max_train_par_locuteur:
            a_entrainer = a_entrainer[:max_train_par_locuteur]
        train.extend(a_entrainer)

    return train, validation, test


# --------------------------------------------------------------------------- #
# Torch Dataset + collateur
# --------------------------------------------------------------------------- #

def _fabriquer_jeu_et_collateur(processor):
    from torch.utils.data import Dataset

    class JeuAudio(Dataset):
        """Un exemple = un wav 16 kHz et sa transcription."""

        def __init__(self, exemples: list[dict]):
            self.exemples = exemples
            self.processor = processor

        def __len__(self) -> int:
            return len(self.exemples)

        def __getitem__(self, i: int) -> dict:
            exemple = self.exemples[i]
            audio = _charger_audio_16k(exemple["chemin_audio"])
            caracteristiques = self.processor.feature_extractor(
                audio, sampling_rate=SAMPLE_RATE
            ).input_features[0]
            etiquettes = self.processor.tokenizer(exemple["transcription"]).input_ids
            return {"input_features": caracteristiques, "labels": etiquettes}

    class Collateur:
        """Padded le lot : features audio + labels, en masquant le padding."""

        def __init__(self, processeur):
            self.processor = processeur

        def __call__(self, features: list[dict]) -> dict:
            lot = self.processor.feature_extractor.pad(
                [{"input_features": f["input_features"]} for f in features],
                return_tensors="pt",
            )
            etiquettes = self.processor.tokenizer.pad(
                [{"input_ids": f["labels"]} for f in features],
                return_tensors="pt",
            )
            labels = etiquettes["input_ids"].masked_fill(etiquettes.attention_mask.ne(1), -100)
            if (labels[:, 0] == self.processor.tokenizer.bos_token_id).all().item():
                labels = labels[:, 1:]
            lot["labels"] = labels
            return lot

    return JeuAudio, Collateur


# --------------------------------------------------------------------------- #
# Évaluation
# --------------------------------------------------------------------------- #

def _decode(model, processor, audios: list, device: str) -> list[str]:
    """Décode un lot d'audios avec EXACTEMENT les réglages de l'app.

    Whisper exige 3000 trames de mel (30 s) : on extrait chaque audio
    séparément (le feature extractor padde tout seul) avant de passer le lot.
    """
    import numpy as np
    import torch

    lots = [
        processor.feature_extractor(audio, sampling_rate=SAMPLE_RATE).input_features[0]
        for audio in audios
    ]
    features = torch.tensor(np.stack(lots), dtype=torch.float32, device=device)
    kwargs = {"task": TACHE, "num_beams": NUM_BEAMS, "max_new_tokens": MAX_NEW_TOKENS}
    if LANGUE:
        kwargs["language"] = LANGUE
    with torch.no_grad():
        ids = model.generate(features, **kwargs)
    return [t.strip() for t in processor.batch_decode(ids, skip_special_tokens=True)]


def evaluer(model, processor, exemples: list[dict], formes: set[str], device: str, batch: int = 8) -> dict:
    """Renvoie WER (%) et exactitude des lieux (%) sur la liste d'exemples."""
    model.eval()
    references: list[str] = []
    transcriptions: list[str] = []
    for i in range(0, len(exemples), batch):
        lot = exemples[i : i + batch]
        if not lot:
            continue
        audios = [_charger_audio_16k(e["chemin_audio"]) for e in lot]
        transcriptions.extend(_decode(model, processor, audios, device))
        references.extend(e["transcription"] for e in lot)
    return {
        "wer": 100.0 * calculer_wer(references, transcriptions),
        "exactitude_lieux": exactitude_lieux(references, transcriptions, formes),
        "n": len(exemples),
    }


def _fabriquer_compute_metrics(processor, formes: set[str]):
    def compute_metrics(pred) -> dict:
        predictions = pred.predictions
        if isinstance(predictions, tuple):
            predictions = predictions[0]
        labels = pred.label_ids.copy()
        labels[labels == -100] = processor.tokenizer.pad_token_id
        hypotheses = processor.batch_decode(predictions, skip_special_tokens=True)
        references = processor.batch_decode(labels, skip_special_tokens=True)
        return {
            "wer": 100.0 * calculer_wer(references, hypotheses),
            "exactitude_lieux": exactitude_lieux(references, hypotheses, formes),
        }

    return compute_metrics


# --------------------------------------------------------------------------- #
# Entraînement
# --------------------------------------------------------------------------- #

def executer(
    metadata_csv: Path,
    dossier_sortie: Path,
    nom_modele: str,
    epochs: int,
    degeler: bool,
    pousser_hub: bool,
    max_steps: int | None = None,
    batch: int | None = None,
    mettre_en_gros: bool = True,
    forcer_cpu: bool = False,
    locuteurs_test: list[str] | None = None,
    revision: str | None = None,
) -> int:
    import torch
    from transformers import (
        Seq2SeqTrainer,
        Seq2SeqTrainingArguments,
        WhisperForConditionalGeneration,
        WhisperProcessor,
    )

    locuteurs_test = list(locuteurs_test) if locuteurs_test else list(LOCUTEURS_TEST)

    debut = time.perf_counter()
    exemples = charger_metadata(Path(metadata_csv))
    if not exemples:
        print(f"Aucun audio « ok » à entraîner dans {metadata_csv}. Arrêt.")
        return 1

    formes = _charger_formes_lieux()
    train, validation, test = decouper_jeux(exemples, GRAINE, locuteurs_test=locuteurs_test)
    if not test:
        print(f"Aucun vocal pour les locuteurs de test ({locuteurs_test}). Arrêt.")
        return 1
    loc_train = sorted({e["locuteur"] for e in train})
    loc_validation = sorted({e["locuteur"] for e in validation})
    loc_test = sorted({e["locuteur"] for e in test})

    def _duree_min(lot: list[dict]) -> float:
        return sum(e.get("duree_s", 0.0) for e in lot) / 60.0

    print(f"Train      : {len(train)} audios ({_duree_min(train):.1f} min) / "
          f"{len(loc_train)} locuteurs -> {loc_train}")
    print(f"Validation : {len(validation)} audios ({_duree_min(validation):.1f} min) / "
          f"{len(loc_validation)} locuteurs -> {loc_validation}")
    print(f"Test       : {len(test)} audios ({_duree_min(test):.1f} min) / locuteurs {loc_test} "
          "(jamais entraînés dessus)")

    device = "cpu" if forcer_cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    fp16 = device == "cuda"
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    revision = revision_pour(nom_modele, revision)
    print(
        f"Modèle : {nom_modele} | révision : {revision or 'locale'} | "
        f"appareil : {device} | fp16 : {fp16}"
    )

    print("Chargement du processor et du modèle…")
    processor = WhisperProcessor.from_pretrained(nom_modele, revision=revision)
    model = WhisperForConditionalGeneration.from_pretrained(
        nom_modele, revision=revision
    ).to(device)
    # Mêmes réglages de décodage que l'app : tâche transcribe, pas de langue forcée.
    model.generation_config.task = TACHE

    if not degeler:
        print("Encodeur gelé (--degeler-encodeur pour l'entraîner aussi).")
        if hasattr(model, "freeze_encoder"):
            model.freeze_encoder()
        else:
            for param in model.model.encoder.parameters():
                param.requires_grad = False
    model.config.use_cache = False

    print("\nÉvaluation AVANT entraînement (sur le jeu de TEST, "
          f"{loc_test})…")
    avant = evaluer(model, processor, test, formes, device, batch=(batch or 8))
    print(f"  WER = {avant['wer']:.1f} % | lieux = {avant['exactitude_lieux']:.1f} %")

    JeuAudio, Collateur = _fabriquer_jeu_et_collateur(processor)
    jeu_train = JeuAudio(train)
    # La validation guide le choix du meilleur modèle (metric_for_best_model) ;
    # le jeu de TEST, lui, n'est JAMAIS vu par le Trainer, ni à l'entraînement
    # ni à la validation : seulement pour les évaluations avant/après ci-dessus
    # et ci-dessous.
    a_une_validation = bool(validation)
    jeu_validation = JeuAudio(validation) if a_une_validation else None

    pas = max_steps
    # transformers 5 a retiré warmup_ratio : on calcule 10 % du nombre de pas
    # prévus, comme avant (--max-steps prime sur les époques).
    if pas and pas > 0:
        total_pas = pas
    else:
        pas_par_epoque = math.ceil(len(train) / (batch or 8))
        total_pas = pas_par_epoque * max(1, epochs)
    warmup_steps = max(1, int(0.1 * total_pas))

    arguments = Seq2SeqTrainingArguments(
        output_dir=str(dossier_sortie),
        per_device_train_batch_size=batch or 8,
        per_device_eval_batch_size=batch or 8,
        gradient_checkpointing=True,
        gradient_accumulation_steps=1,
        learning_rate=LR,
        warmup_steps=warmup_steps,
        num_train_epochs=epochs,
        max_steps=pas if pas else -1,
        fp16=fp16,
        eval_strategy=("steps" if pas else "epoch") if a_une_validation else "no",
        eval_steps=pas if (pas and a_une_validation) else None,
        save_strategy="steps" if pas else "epoch",
        save_steps=pas if pas else 500,
        logging_steps=1,
        predict_with_generate=True,
        generation_max_length=MAX_NEW_TOKENS,
        load_best_model_at_end=a_une_validation,
        metric_for_best_model="wer" if a_une_validation else None,
        greater_is_better=False if a_une_validation else None,
        save_total_limit=2,
        report_to="none",
        remove_unused_columns=False,
        dataloader_num_workers=0,
        seed=GRAINE,
    )

    entraineur = Seq2SeqTrainer(
        model=model,
        args=arguments,
        train_dataset=jeu_train,
        eval_dataset=jeu_validation,
        data_collator=Collateur(processor),
        compute_metrics=_fabriquer_compute_metrics(processor, formes) if a_une_validation else None,
        processing_class=processor.feature_extractor,
    )

    print("\nEntraînement…")
    entraineur.train()

    print(f"\nÉvaluation APRÈS entraînement (meilleur modèle, sur le jeu de TEST, "
          f"{loc_test})…")
    apres = evaluer(model, processor, test, formes, device, batch=(batch or 8))
    print(f"  WER = {apres['wer']:.1f} % | lieux = {apres['exactitude_lieux']:.1f} %")

    dossier_sortie = Path(dossier_sortie)
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    print(f"\nSauvegarde dans {dossier_sortie} …")
    model.save_pretrained(str(dossier_sortie))
    processor.save_pretrained(str(dossier_sortie))

    duree = time.perf_counter() - debut
    resultats = {
        "modele": nom_modele,
        "date": datetime.now().isoformat(timespec="seconds"),
        "learning_rate": LR,
        "epochs": epochs,
        "encodeur_gele": not degeler,
        "audios": {"train": len(train), "validation": len(validation), "test": len(test)},
        "locuteurs": {"train": loc_train, "validation": loc_validation, "test": loc_test},
        "avant": {"wer": round(avant["wer"], 2), "exactitude_lieux": round(avant["exactitude_lieux"], 2)},
        "apres": {"wer": round(apres["wer"], 2), "exactitude_lieux": round(apres["exactitude_lieux"], 2)},
        "duree_s": round(duree, 1),
    }
    if mettre_en_gros:
        resultats["pousse_hub"] = False
    with open(dossier_sortie / "resultats.json", "w", encoding="utf-8") as fichier:
        json.dump(resultats, fichier, ensure_ascii=False, indent=2)

    print("\n--- Bilan avant / après ---")
    print(f"{'Métrique':<22}{'Avant':>10}{'Après':>10}")
    print(f"{'WER':<22}{avant['wer']:>9.1f}%{apres['wer']:>9.1f}%")
    print(f"{'Exactitude des lieux':<22}{avant['exactitude_lieux']:>9.1f}%{apres['exactitude_lieux']:>9.1f}%")

    if pousser_hub:
        _pousser_sur_hub(model, processor, dossier_sortie)

    if mettre_en_gros:
        minutes, secondes = divmod(int(duree), 60)
        print("\n" + "=" * 62)
        print("  ENTRAÎNEMENT TERMINÉ — ARRÊTE LA MACHINE BREV MAINTENANT")
        print("=" * 62)
        print(f"  Durée totale : {minutes} min {secondes} s")
    return 0


def _pousser_sur_hub(model, processor, dossier_sortie: Path) -> None:
    """Envoie le modèle sur Hugging Face en dépôt PRIVÉ. Token lu de la connexion hf."""
    print(f"\nEnvoi vers {DEPOT_HUB} (privé)…")
    try:
        model.push_to_hub(DEPOT_HUB, private=True)
        processor.push_to_hub(DEPOT_HUB, private=True)
        print(f"Modèle envoyé : https://huggingface.co/{DEPOT_HUB}")
    except Exception as erreur:  # pas de traceback : on prévient, c'est tout
        print(f"Envoi impossible ({type(erreur).__name__}: {erreur}). Modèle gardé dans {dossier_sortie}.")


# --------------------------------------------------------------------------- #
# Essai à blanc (CPU, tout en dossier temporaire)
# --------------------------------------------------------------------------- #

PHRASES_ESSAI = [
    "Maa ngi Guédiawaye, dama bëgg dem Palais",
    "Maa ngi Liberté 6, bëgg naa dem Palais",
    "Dama bëgg dem Ouakam, maa ngi Grand Yoff",
    "Maa ngi Pikine, dama bëgg dem Colobane",
    "Maa ngi Thiaroye, bëgg naa dem Ouakam",
    "Maa ngi Keur Massar, dama bëgg dem UCAD",
    "Maa ngi Yoff, bëgg naa dem Place Leclerc",
    "Maa ngi Médina, dama bëgg dem Sacré Coeur",
    "Maa ngi Ouakam, bëgg naa dem Petersen",
    "Maa ngi Cambérène, dama bëgg dem Guédiawaye",
]


def _fabriquer_faux_jeu(travail: Path) -> tuple[Path, Path]:
    """Crée des bips de 2 s pour 4 locuteurs d'entraînement + LOCUTEURS_TEST, un
    metadata.csv (transcription_propre remplie), dans un dossier temporaire.
    """
    import numpy as np
    import soundfile as sf

    collecte = travail / "data" / "collecte"
    collecte.mkdir(parents=True, exist_ok=True)
    locuteurs = [f"locuteur_{i:02d}" for i in range(1, 5)] + list(LOCUTEURS_TEST)
    lignes: list[dict] = []

    for i in range(60):
        locuteur = locuteurs[i % len(locuteurs)]
        dossier = collecte / locuteur
        dossier.mkdir(parents=True, exist_ok=True)
        nom = f"bip_{i:02d}.wav"
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2.0), endpoint=False)
        signal = (0.3 * np.sin(2 * np.pi * (300 + 40 * i) * t)).astype("float32")
        sf.write(str(dossier / nom), signal, SAMPLE_RATE)
        texte = PHRASES_ESSAI[i % len(PHRASES_ESSAI)]
        lignes.append(
            {
                "file_name": f"{locuteur}/{nom}",
                "transcription": texte,
                "transcription_propre": texte,
                "locuteur": locuteur,
                "duree_s": "2.00",
                "statut": "ok",
            }
        )

    metadata = collecte / "metadata.csv"
    with open(metadata, "w", encoding="utf-8", newline="") as fichier:
        redacteur = csv.DictWriter(
            fichier,
            fieldnames=["file_name", "transcription", "transcription_propre", "locuteur", "duree_s", "statut"],
        )
        redacteur.writeheader()
        redacteur.writerows(lignes)
    return metadata, collecte


def essai_a_blanc() -> int:
    """Vérifie tout le code sur whisper-tiny, CPU, 2 pas, en dossier temporaire."""
    print("=== ESSAI À BLANC (whisper-tiny, CPU, 2 pas, dossier temporaire) ===")
    travail = Path(tempfile.mkdtemp(prefix="essai_whisper_"))
    try:
        metadata, _ = _fabriquer_faux_jeu(travail)
        code = executer(
            metadata_csv=metadata,
            dossier_sortie=travail / "models" / "whisper-tiny-essai",
            nom_modele=MODELE_ESSAI,
            epochs=1,
            degeler=False,
            pousser_hub=False,
            max_steps=2,
            batch=2,
            mettre_en_gros=False,
            forcer_cpu=True,
            revision=REVISIONS_CONNUES[MODELE_ESSAI],
        )
        if code == 0:
            print("\nESSAI À BLANC TERMINÉ : rien n'a été écrit dans data/ ni models/ de ton PC.")
        return code
    finally:
        shutil.rmtree(travail, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    analyseur = argparse.ArgumentParser(description="Fine-tune whisper-small-wolof sur les voix wolof.")
    analyseur.add_argument("--essai-a-blanc", action="store_true", help="Test rapide CPU sur whisper-tiny.")
    analyseur.add_argument("--epochs", type=int, default=8, help="Nombre d'époques (défaut : 8).")
    analyseur.add_argument("--degeler-encodeur", action="store_true", help="Entraîne aussi l'encodeur.")
    analyseur.add_argument("--pousser-hub", action="store_true", help="Envoie le modèle sur le Hub (privé).")
    analyseur.add_argument(
        "--revision",
        default=None,
        help="SHA du commit Hub à charger (obligatoire pour un modèle Hub inconnu).",
    )
    analyseur.add_argument(
        "--locuteurs-test",
        nargs="+",
        metavar="LOCUTEUR",
        default=None,
        help=f"locuteurs formant le jeu de TEST, jamais entraînés dessus "
             f"(défaut : {' '.join(LOCUTEURS_TEST)}).",
    )
    args = analyseur.parse_args(argv)

    if args.essai_a_blanc:
        return essai_a_blanc()

    return executer(
        metadata_csv=RACINE / "data" / "collecte" / "metadata.csv",
        dossier_sortie=RACINE / "models" / "whisper-small-wolof-dakar",
        nom_modele=MODEL_DEFAUT,
        epochs=args.epochs,
        degeler=args.degeler_encodeur,
        pousser_hub=args.pousser_hub,
        locuteurs_test=args.locuteurs_test,
        revision=args.revision,
    )


if __name__ == "__main__":
    sys.exit(main())
