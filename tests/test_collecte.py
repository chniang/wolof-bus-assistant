r"""Teste scripts/preparer_collecte.py sur une fausse discussion WhatsApp.

    .\.venv\Scripts\python.exe tests\test_collecte.py

Deux faux exports :
- collecte_awa.zip : un vieux vocal daté d'avant --depuis (ignoré), une photo
  .jpg et un message supprimé juste après un vocal (sautés comme les médias
  omis), une phrase « magui parcelle dama beugg dm petersen » (uniformisée),
  un vocal suivi de « Les écritures 🥺 » (statut sans_lieu) ;
- collecte_collecteur.zip : vocal de Awa, vocal de Moi, texte de Awa, lancé
  avec collecteur="Moi" -> le vocal de Awa reçoit le texte, le vocal de Moi
  est ignoré.

Code de sortie : 0 si tout passe.
"""

from __future__ import annotations

import csv
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "scripts" / "preparer_collecte.py"

PHRASE_1 = "Maa ngi Guédiawaye, dama bëgg dem Palais"
PHRASE_2 = "Maa ngi Thiaroye, bëgg naa dem Ouakam"
PHRASE_3 = "magui parcelle dama beugg dm petersen"
PHRASE_3_UNIFORMIsee = "maa ngi parcelle dama bëgg dem petersen"
PHRASE_SANS_LIEU = "Les écritures 🥺"
PHRASE_TAPEE = "Maa ngi Liberté 6, bëgg naa dem Ouakam"

NOMS_A = [
    "PTT-20261009-WA0001",
    "PTT-20261009-WA0002",
    "PTT-20261009-WA0003",
    "PTT-20261009-WA0004",
    "PTT-20261009-WA0005",
    "PTT-20261008-WA0006",  # vocal daté d'avant --depuis : doit être ignoré
]
NOMS_B = ["PTT-20261009-WA0010", "PTT-20261009-WA0011"]


def _charger_module():
    spec = importlib.util.spec_from_file_location("preparer_collecte", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fabriquer_bip(dossier: Path, noms: list[str], ffmpeg: str) -> list[Path]:
    """Crée les petits bips .m4a et renvoie leurs chemins."""
    import numpy as np
    import soundfile as sf

    chemins = []
    for i, nom in enumerate(noms):
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


def _ecrire_zip(dossier: Path, lignes: list[str], noms: list[str]) -> Path:
    txt = dossier / "WhatsApp Chat with Awa.txt"
    txt.write_text("\n".join(lignes) + "\n", encoding="utf-8")

    archive_path = dossier / "collecte.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(txt, arcname=txt.name)
        for nom in noms:
            archive.write(dossier / f"{nom}.m4a", arcname=f"{nom}.m4a")
    return archive_path


def _fabriquer_zip_a(dossier: Path) -> Path:
    lignes = [
        "09/10/2026 19:20 - Awa: PTT-20261009-WA0001.m4a (fichier joint)",
        f"\u200e09/10/2026 19:20 - Awa: {PHRASE_1}",
        "\u200e09/10/2026 19:21 - Awa: PTT-20261009-WA0002.m4a (fichier joint)",
        "\u200e09/10/2026 19:21 - Moi: d'accord",
        "\u200e09/10/2026 19:21 - Awa: Maa ngi Thiaroye,",
        "bëgg naa dem Ouakam",
        "\u200e09/10/2026 19:22 - Awa: PTT-20261009-WA0003.m4a (fichier joint)",
        # Photo juste après le vocal : jamais prise comme transcription.
        "\u200e09/10/2026 19:22 - Awa: IMG-20261009-WA0001.jpg (fichier joint)",
        # Message supprimé : jamais pris comme transcription.
        "\u200e09/10/2026 19:22 - Moi: Ce message a été supprimé",
        f"\u200e09/10/2026 19:22 - Awa: {PHRASE_3}",
        "\u200e09/10/2026 19:23 - Awa: PTT-20261009-WA0004.m4a (fichier joint)",
        f"\u200e09/10/2026 19:23 - Moi: {PHRASE_SANS_LIEU}",
        "\u200e09/10/2026 19:24 - Awa: PTT-20261009-WA0005.m4a (fichier joint)",
        # Vieux vocal daté d'avant --depuis : vocal ET texte doivent être ignorés.
        "\u200e08/10/2026 10:00 - Awa: PTT-20261008-WA0006.m4a (fichier joint)",
        "\u200e08/10/2026 10:00 - Awa: Maa ngi Cambérène, dama bëgg dem Ouakam",
    ]
    return _ecrire_zip(dossier, lignes, NOMS_A)


def _fabriquer_zip_b(dossier: Path) -> Path:
    lignes = [
        "09/10/2026 20:00 - Awa: PTT-20261009-WA0010.m4a (fichier joint)",
        "\u200e09/10/2026 20:01 - Moi: PTT-20261009-WA0011.m4a (fichier joint)",
        f"\u200e09/10/2026 20:01 - Moi: {PHRASE_TAPEE}",
    ]
    return _ecrire_zip(dossier, lignes, NOMS_B)


def _lire_metadata(collecte: Path) -> list[dict]:
    meta = collecte / "metadata.csv"
    if not meta.exists():
        return []
    with open(meta, encoding="utf-8") as fichier:
        return list(csv.DictReader(fichier))


def _migration_ok(module, travail: Path) -> bool:
    """Un metadata.csv ancien (sans transcription_brute) est migré proprement."""
    ancien = travail / "migration" / "metadata.csv"
    ancien.parent.mkdir(parents=True, exist_ok=True)
    ancien.write_text(
        "file_name,transcription,locuteur,duree_s,statut\n"
        "locuteur_09/bip.wav,magui parcelle,locuteur_09,2.00,ok\n",
        encoding="utf-8",
    )
    module._migrer_metadata(ancien)
    lignes = _lire_metadata(ancien.parent)
    ligne = lignes[0]
    return (
        ligne["transcription_brute"] == "magui parcelle"
        and ligne["transcription"] == "maa ngi parcelle"
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    module = _charger_module()
    ffmpeg = module._ffmpeg(installer_si_besoin=False)

    travail = Path(tempfile.mkdtemp(prefix="test_collecte_"))
    try:
        verifications: list[tuple[str, bool]] = []

        # --- Scénario A : date, photo, message supprimé, uniformisation, sans_lieu.
        dossier_a = travail / "scenario_a"
        dossier_a.mkdir(exist_ok=True)
        _fabriquer_bip(dossier_a, NOMS_A, ffmpeg)
        archive_a = _fabriquer_zip_a(dossier_a)
        rapport_a = module.traiter_zip(
            archive_a,
            brut_dir=dossier_a / "brut",
            collecte_dir=dossier_a / "collecte",
            installer_si_besoin=False,
            depuis=date(2026, 10, 9),
        )
        lignes_a = _lire_metadata(dossier_a / "collecte")
        transcriptions_a = {l.lower() for l in (l["transcription"] for l in lignes_a)}
        brutes_a = {l["transcription_brute"] for l in lignes_a}

        verifications += [
            ("A: 2 messages ignorés (--depuis)", rapport_a["ignores_date"] == 2),
            ("A: 5 vocaux retenus", rapport_a["trouves"] == 5),
            ("A: 4 vocaux associés", rapport_a["associes"] == 4),
            ("A: 1 vocal sans texte", rapport_a["sans_texte"] == 1),
            ("A: 4 lignes dans metadata.csv", len(lignes_a) == 4),
            ("A: photo ignorée", not any("img-" in t for t in transcriptions_a)),
            ("A: message supprimé ignoré", not any("supprimé" in t for t in transcriptions_a)),
            ("A: transcriptions uniformisées", PHRASE_3_UNIFORMIsee.lower() in transcriptions_a),
            ("A: texte d'origine conservé", PHRASE_3 in brutes_a),
            ("A: 1 statut sans_lieu", sum(l["statut"] == "sans_lieu" for l in lignes_a) == 1),
            ("A: 3 statuts ok", sum(l["statut"] == "ok" for l in lignes_a) == 3),
            ("A: rapport sans_lieu", rapport_a["sans_lieu"] == 1),
            ("A: vieux vocal ignoré", not any("WA0006" in l["file_name"] for l in lignes_a)),
            ("A: pseudo-anonymisation", all(l["locuteur"].startswith("locuteur_") for l in lignes_a)),
            ("A: vrai nom absent des sorties", "Awa" not in (dossier_a / "collecte" / "metadata.csv").read_text(encoding="utf-8")),
            ("A: wav 16 kHz mono", all(
                (dossier_a / "collecte" / l["file_name"]).exists()
                and _est_wav_16k_mono(dossier_a / "collecte" / l["file_name"])
                for l in lignes_a
            )),
        ]

        # --- Scénario B : collecteur "Moi".
        dossier_b = travail / "scenario_b"
        dossier_b.mkdir(exist_ok=True)
        _fabriquer_bip(dossier_b, NOMS_B, ffmpeg)
        archive_b = _fabriquer_zip_b(dossier_b)
        rapport_b = module.traiter_zip(
            archive_b,
            brut_dir=dossier_b / "brut",
            collecte_dir=dossier_b / "collecte",
            installer_si_besoin=False,
            collecteur="Moi",
        )
        lignes_b = _lire_metadata(dossier_b / "collecte")
        transcriptions_b = {l["transcription"] for l in lignes_b}

        verifications += [
            ("B: 1 vocal retenu (Awa)", rapport_b["trouves"] == 1),
            ("B: 1 vocal associé", rapport_b["associes"] == 1),
            ("B: 1 vocal du collecteur ignoré", rapport_b["collecteur_vocaux_ignores"] == 1),
            ("B: vocal de Awa reçoit le texte", transcriptions_b == {PHRASE_TAPEE}),
            ("B: fichier de Awa (pas celui de Moi)", all("WA0010" in l["file_name"] for l in lignes_b)),
        ]

        # --- Migration d'anciens metadata.csv.
        verifications.append(("M: migration d'un ancien metadata.csv", _migration_ok(module, travail)))

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