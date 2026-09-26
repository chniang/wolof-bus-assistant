"""Test ASR wolof (whisper-small) sur le dataset urban-bus-wolof.

Usage:
    python src/asr/test_asr_models.py [--samples 3]

Modèle testé (inférence seule, en CPU) :
    - M9and2M/whisper-small-wolof

SpeechBrain (speechbrain/asr-wav2vec2-dvoice-wolof) est désactivé :
trop gourmand en RAM (wav2vec2-large) pour cette machine (8 Go).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
# --- SpeechBrain désactivé (RAM insuffisante) ---
# import tempfile
# MODEL_SPEECHBRAIN = "speechbrain/asr-wav2vec2-dvoice-wolof"
#
# def _load_speechbrain():
#     from speechbrain.inference.ASR import EncoderASR
#     from speechbrain.utils.fetching import LocalStrategy
#
#     return EncoderASR.from_hparams(
#         source=MODEL_SPEECHBRAIN,
#         savedir="pretrained_models/asr-wav2vec2-dvoice-wolof",
#         run_opts={"device": "cpu"},
#         local_strategy=LocalStrategy.COPY,
#     )
#
#
# def _transcribe_speechbrain(model, audio_array, sample_rate):
#     """Transcrit un tableau numpy avec SpeechBrain (batch, puis fichier temporaire)."""
#     import torch
#     import soundfile as sf
#
#     waveform = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0)
#     wav_lens = torch.tensor([1.0])
#     try:
#         out = model.transcribe_batch(waveform, wav_lens)
#     except Exception:
#         fd, path = tempfile.mkstemp(suffix=".wav")
#         os.close(fd)
#         try:
#             sf.write(path, audio_array, sample_rate)
#             out = model.transcribe_file(path)
#         finally:
#             try:
#                 os.unlink(path)
#             except OSError:
#                 pass
#     if isinstance(out, (tuple, list)):
#         out = out[0]
#     if isinstance(out, str):
#         return out
#     return out[0] if out else ""


MODEL_WHISPER = "M9and2M/whisper-small-wolof"
DATASET_NAME = "vonewman/urban-bus-wolof"


def _load_whisper():
    from transformers import pipeline

    return pipeline(
        "automatic-speech-recognition",
        model=MODEL_WHISPER,
        device=-1,
    )


def _transcribe_whisper(model, audio_array: list[float], sample_rate: int) -> str:
    prediction = model(
        {"array": audio_array, "sampling_rate": sample_rate},
        generate_kwargs={
            "task": "transcribe",
            "max_new_tokens": 48,
            "num_beams": 1,
        },
    )
    if isinstance(prediction, dict):
        text = prediction.get("text", "")
    else:
        text = str(prediction)
    return re.sub(r"\s+", " ", text).strip()


def _probably_error(text: str) -> bool:
    return text.startswith("[ERREUR]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Évalue un modèle ASR wolof.")
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="Nombre d'échantillons à tester (1 à 10).",
    )
    args = parser.parse_args()
    n_samples = max(1, min(args.samples, 10))

    print("=" * 72)
    print("Test ASR wolof — GuindiMa AI")
    print(f"Dataset : {DATASET_NAME} — {n_samples} échantillons, CPU")
    print("=" * 72)

    try:
        from datasets import load_dataset, Audio

        dataset = load_dataset(DATASET_NAME, split=f"train[:{n_samples}]")
        dataset = dataset.cast_column("audio", Audio(sampling_rate=16000, decode=False))
        print(f"Dataset chargé ({len(dataset)} échantillons).")
    except Exception as exc:
        print(f"[ERREUR] Impossible de charger le dataset : {exc}")
        return 1

    # --- Chargement SpeechBrain désactivé : trop gourmand en RAM ---
    # speechbrain_model = None
    # try:
    #     print(f"\nChargement de {MODEL_SPEECHBRAIN} …")
    #     speechbrain_model = _load_speechbrain()
    #     print("Modèle SpeechBrain prêt.")
    # except Exception as exc:
    #     print(f"[SKIP] Échec du chargement du modèle SpeechBrain : {exc}")

    whisper_model = None
    try:
        print(f"\nChargement de {MODEL_WHISPER} …")
        whisper_model = _load_whisper()
        print("Modèle Whisper prêt.")
    except Exception as exc:
        print(f"[SKIP] Échec du chargement du modèle Whisper : {exc}")

    if whisper_model is None:
        print("\nAucun modèle disponible, test impossible.")
        return 1

    import numpy as np
    import jiwer

    results = []
    wer_by_model = {MODEL_WHISPER: []}

    for i, sample in enumerate(dataset, start=1):
        try:
            import soundfile as sf

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(sample["audio"]["bytes"])
                tmp_path = tmp.name
            try:
                audio, sample_rate = sf.read(tmp_path, dtype="float32")
            finally:
                os.unlink(tmp_path)
            audio = np.asarray(audio, dtype=np.float32)
        except Exception as exc:
            print(f"\n[ERREUR] Décodage audio de l'échantillon {i} impossible : {exc}")
            continue
        reference = str(sample["sentence"]).strip()

        print("\n" + "-" * 72)
        print(f"Échantillon {i}/{n_samples}")
        print(f"Référence  : {reference}")

        row = {"reference": reference}

        # --- Appel SpeechBrain désactivé ---
        # if speechbrain_model is not None:
        #     t0 = time.perf_counter()
        #     try:
        #         hypothesis = _transcribe_speechbrain(speechbrain_model, audio, sample_rate)
        #     except Exception as exc:
        #         hypothesis = f"[ERREUR] {exc}"
        #     elapsed = time.perf_counter() - t0
        #     print(f"\n[{MODEL_SPEECHBRAIN}] ({elapsed:.1f}s)")
        #     print(f"  Hypothèse : {hypothesis}")
        #     if _probably_error(hypothesis):
        #         print("  WER       : non calculé (erreur d'inférence)")
        #     else:
        #         wer = jiwer.wer(reference, hypothesis)
        #         wer_by_model[MODEL_SPEECHBRAIN].append(wer)
        #         row[MODEL_SPEECHBRAIN] = hypothesis
        #         print(f"  WER       : {wer:.3f}")

        if whisper_model is not None:
            t0 = time.perf_counter()
            try:
                hypothesis = _transcribe_whisper(whisper_model, audio, sample_rate)
            except Exception as exc:
                hypothesis = f"[ERREUR] {exc}"
            elapsed = time.perf_counter() - t0
            print(f"\n[{MODEL_WHISPER}] ({elapsed:.1f}s)")
            print(f"  Hypothèse : {hypothesis}")
            if _probably_error(hypothesis):
                print("  WER       : non calculé (erreur d'inférence)")
            else:
                wer = jiwer.wer(reference, hypothesis)
                wer_by_model[MODEL_WHISPER].append(wer)
                row[MODEL_WHISPER] = hypothesis
                print(f"  WER       : {wer:.3f}")

        results.append(row)

    print("\n" + "=" * 72)
    print("RÉSUMÉ — WER moyen (plus bas = meilleur)")
    print("=" * 72)
    for model_name, wers in wer_by_model.items():
        if wers:
            mean_wer = sum(wers) / len(wers)
            print(f"{model_name:<45} WER moyen = {mean_wer:.3f}  ({len(wers)}/{n_samples} échantillons)")
        else:
            print(f"{model_name:<45} pas de WER calculable")

    best = min(wer_by_model, key=lambda m: sum(wer_by_model[m]) / len(wer_by_model[m])) if any(wer_by_model[m] for m in wer_by_model) else None
    if best and wer_by_model[best]:
        print(f"\nModèle recommandé sur ce test : {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())