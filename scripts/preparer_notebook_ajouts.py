r"""Construit le notebook Colab des audios manquants à partir du notebook des 637.

Mêmes réglages que la première série : modèle Oolel-Voices, voix de référence
Adia, graine, 3 essais par audio, Whisper qui garde le meilleur.  Seules changent
la liste (``data/audit/voix_a_generer.csv``) et la destination dans Google Drive
(``guindima_ajouts/tts_cache_ajouts``, à copier dans ``data/tts_cache_ajouts/``).

    .\.venv\Scripts\python.exe scripts\preparer_notebook_ajouts.py

Le refaire après chaque ``scripts\couverture_voix.py`` : la liste est embarquée
dans le notebook, Colab n'a pas accès au dépôt.
"""

from __future__ import annotations

import copy
import csv
import json
import pprint
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SOURCE = RACINE / "notebooks" / "voix_oolel_colab.ipynb"
SORTIE = RACINE / "notebooks" / "voix_ajouts_colab.ipynb"
LISTE = RACINE / "data" / "audit" / "voix_a_generer.csv"
PLAN_637 = RACINE / "scripts" / "phrases_voix.json"

# Cellules reprises telles quelles du notebook des 637 : installation, outils de
# vérification, Whisper de contrôle, Oolel, génération avec reprise.
CELLULES_REPRISES = (1, 4, 5, 6, 7)


def _cellule_code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _cellule_texte(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def phrases_a_generer() -> list[dict[str, str]]:
    with LISTE.open(encoding="utf-8", newline="") as fichier:
        return [
            {
                "fichier": rangee["fichier_wav"],
                "phrase": rangee["texte_a_prononcer"],
                "type": rangee["type"],
            }
            for rangee in csv.DictReader(fichier)
        ]


def construire() -> dict:
    base = json.loads(SOURCE.read_text(encoding="utf-8"))
    plan_637 = json.loads(PLAN_637.read_text(encoding="utf-8"))
    phrases = phrases_a_generer()
    total = len(phrases)

    intro = f"""# GuindiMa AI — les {total} audios manquants avec Oolel-Voices

Mêmes réglages que les 637 audios : **Oolel-Voices**, voix de référence **Adia**, graine {plan_637['graine']},
3 essais par audio, Whisper wolof garde le meilleur. Liste : `data/audit/voix_a_generer.csv`.

**Avant :** GPU T4 · clé 🔑 `HF_TOKEN` activée dans les secrets Colab.
La voix de référence est celle de la 1re série : `Google Drive/guindima_oolel/voix_reference_adia.wav`.
Si ce fichier n'existe plus, importe l'**original** Adia `voix_reference_adia.wav` dans le dossier 📁
(pas le `aucune_ligne.wav` de `data/tts_cache/` : il a été régénéré par Oolel).

**Lancer :** Exécution → Tout exécuter. La 1re cellule redémarre la session (« session plantée » = normal).
Clique ensuite sur la **2e cellule** et fais **Ctrl + F10**. Colab demande l'accès à Google Drive : accepte.

**Coupure ?** Chaque audio est écrit dans Google Drive (`guindima_ajouts/tts_cache_ajouts`) dès qu'il est fait.
Relance de la même façon : les audios déjà présents dans Drive sont sautés.

À la fin, `tts_cache_ajouts.zip` se télécharge : son contenu va dans `data/tts_cache_ajouts/`.
"""

    drive = f"""# Google Drive : sauvegarde au fur et à mesure (reprise après coupure)
import os, glob, shutil
from google.colab import drive
drive.mount('/content/drive')
BASE = '/content/drive/MyDrive/guindima_ajouts'
SORTIE = f'{{BASE}}/tts_cache_ajouts'
RAPPORT = f'{{BASE}}/rapport_voix_ajouts.csv'
REF = f'{{BASE}}/voix_reference_adia.wav'
# La même voix de référence que les 637 audios : celle mise à l'abri par la 1re série.
REF_PREMIERE_SERIE = '/content/drive/MyDrive/guindima_oolel/voix_reference_adia.wav'
os.makedirs(SORTIE, exist_ok=True)
if not os.path.exists(REF):
    if os.path.exists(REF_PREMIERE_SERIE):
        shutil.copy(REF_PREMIERE_SERIE, REF)
    else:
        importee = glob.glob('/content/voix_reference_adia.wav')
        assert importee, (
            "Voix de référence introuvable : importe l'original Adia voix_reference_adia.wav "
            "dans le dossier 📁 à gauche, puis relance cette cellule."
        )
        shutil.copy(importee[0], REF)
print('voix de référence :', REF)
print('déjà faits :', len(glob.glob(f'{{SORTIE}}/*.wav')), '/ {total}')
"""

    plan = {
        "modele": plan_637["modele"],
        "voix_reference": plan_637["voix_reference"],
        "graine": plan_637["graine"],
        "phrases": phrases,
    }
    liste = (
        f"PLAN = {pprint.pformat(plan, width=120, sort_dicts=False)}\n"
        "PHRASES = PLAN['phrases']\n"
        "GRAINE = PLAN['graine']\n"
        "print(len(PHRASES), 'phrases')\n"
    )

    fin = f"""# Vérifier et télécharger le zip
from google.colab import files
manquants = [p['fichier'] for p in PHRASES if not os.path.exists(f"{{SORTIE}}/{{p['fichier']}}")]
assert not manquants, f"{{len(manquants)}} audios manquants (ex. {{manquants[:5]}}) : relance la cellule de génération."
shutil.copy(RAPPORT, f'{{SORTIE}}/rapport_voix_ajouts.csv')
shutil.make_archive('/content/tts_cache_ajouts', 'zip', SORTIE)
shutil.copy('/content/tts_cache_ajouts.zip', f'{{BASE}}/tts_cache_ajouts.zip')
print('{total} audios OK — copie aussi dans Google Drive/guindima_ajouts/')
files.download('/content/tts_cache_ajouts.zip')
"""

    cellules = [_cellule_texte(intro), copy.deepcopy(base["cells"][1]), _cellule_code(drive), _cellule_code(liste)]
    cellules += [copy.deepcopy(base["cells"][i]) for i in CELLULES_REPRISES[1:]]
    cellules.append(_cellule_code(fin))
    for cellule in cellules:
        if cellule["cell_type"] == "code":
            cellule["outputs"] = []
            cellule["execution_count"] = None
    return {**base, "cells": cellules}


def main() -> int:
    notebook = construire()
    SORTIE.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{SORTIE} : {len(phrases_a_generer())} audios à générer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
