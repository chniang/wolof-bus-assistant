r"""Teste scripts/preparer_collecte.py sur une fausse discussion WhatsApp.

    .\.venv\Scripts\python.exe tests\test_collecte.py

On fabrique un zip avec 3 notes vocales de bip (2 s), leurs textes, un
« d'accord » à ignorer et un vocal resté sans texte. Le script doit associer
2 vocaux sur 3 et anonymiser le locuteur. Code de sortie : 0 si tout passe.
"""

from __future__ import annotations

import csv
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "scripts" / "preparer_collecte.py"

PHRASE_1 = "Maa ngi Guédiawaye, dama bëgg dem Palais"
PHRASE_2 = "Maa ngi Thiaroye, bëgg naa dem Ouakam"
NOMS = ["PTT-20261009-WA0001", "PTT-20261009-WA0002", "PTT-20261009-WA0003"]


def _charger_module():
    spec = importlib.util.spec_from_file_location("preparer_collecte", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fabriquer_bip(dossier: Path, ffmpeg: str) -> list[Path]:
    """Crée 3 petits bips .m4a et renvoie leurs chemins."""
    import numpy as np
    import soundfile as sf

    chemins = []
    for i, nom in enumerate(NOMS):
        wav = dossier / f"{nom}.wav"
        frequence = 440 * (i + 1)
        t = np.linspace(0, 2.0, int(16000 * 2.0), endpoint=False)
        signal = (0.3 * np.sin(2 * np.pi * frequence * t)).astype("float32")
        sf.write(str(wav), signal, 16000)

        m4a = dossier / f"{nom}.m4a"
        subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(wav), "-c:a", "aac", "-b:a", "64k", str(m4a)],
            check=True,
        )
        wav.unlink()
        chemins.append(m4a)
    return chemins


def _fabriquer_zip(dossier: Path) -> Path:
    lignes = [
        "09/10/2026 19:20 - Awa: PTT-20261009-WA0001.m4a (fichier joint)",
        f"\u200e09/10/2026 19:20 - Awa: {PHRASE_1}",
        "\u200e09/10/2026 19:21 - Awa: PTT-20261009-WA0002.m4a (fichier joint)",
        "\u200e09/10/2026 19:21 - Moi: d'accord",
        "\u200e09/10/2026 19:21 - Awa: Maa ngi Thiaroye,",
        "bëgg naa dem Ouakam",
        "\u200e09/10/2026 19:22 - Awa: PTT-20261009-WA0003.m4a (file attached)",
    ]
    txt = dossier / "WhatsApp Chat with Awa.txt"
    txt.write_text("\n".join(lignes) + "\n", encoding="utf-8")

    archive_path = dossier / "collecte_awa.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(txt, arcname=txt.name)
        for nom in NOMS:
            archive.write(dossier / f"{nom}.m4a", arcname=f"{nom}.m4a")
    return archive_path


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    module = _charger_module()
    ffmpeg = module._ffmpeg(installer_si_besoin=False)

    travail = Path(tempfile.mkdtemp(prefix="test_collecte_"))
    try:
        _fabriquer_bip(travail, ffmpeg)
        archive = _fabriquer_zip(travail)

        rapport = module.traiter_zip(
            archive,
            brut_dir=travail / "brut",
            collecte_dir=travail / "collecte",
            installer_si_besoin=False,
        )

        meta = travail / "collecte" / "metadata.csv"
        lignes = list(csv.DictReader(open(meta, encoding="utf-8"))) if meta.exists() else []
        transcriptions = {ligne["transcription"] for ligne in lignes}

        verifications = [
            ("3 vocaux trouvés", rapport["trouves"] == 3),
            ("2 vocaux associés", rapport["associes"] == 2),
            ("1 vocal sans texte", rapport["sans_texte"] == 1),
            ("2 lignes dans metadata.csv", len(lignes) == 2),
            ("les 2 phrases sont transcrites", transcriptions == {PHRASE_1, PHRASE_2}),
            ("« d'accord » ignoré", not any("d'accord" in t.lower() for t in transcriptions)),
            ("pseudo-anonymisation", all(
                ligne["locuteur"].startswith("locuteur_") for ligne in lignes
            )),
            ("vrai nom absent des sorties", "Awa" not in meta.read_text(encoding="utf-8")),
            ("wav 16 kHz mono", all(
                (travail / "collecte" / ligne["file_name"]).exists()
                and _est_wav_16k_mono(travail / "collecte" / ligne["file_name"])
                for ligne in lignes
            )),
        ]

        echecs = 0
        for titre, bon in verifications:
            echecs += not bon
            print(f"{'OK ' if bon else 'ÉCHEC'} | {titre}")
        print(f"\n{len(verifications) - echecs}/{len(verifications)} réussis")
        return 1 if echecs else 0
    finally:
        shutil.rmtree(travail, ignore_errors=True)


def _est_wav_16k_mono(chemin: Path) -> bool:
    import soundfile as sf

    info = sf.info(str(chemin))
    return info.samplerate == 16000 and info.channels == 1


if __name__ == "__main__":
    sys.exit(main())
