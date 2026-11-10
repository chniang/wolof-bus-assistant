r"""Construit notebooks/voix_oolel_complete.ipynb : la voix native régénère tout.

La voix passe à celle du Space soynade-research/Oolel-Voices-Demo (8_1_c.wav) :
TOUTES les réponses de l'app (869 audios : les 637 du plan + les 232 ajouts)
partent dans un seul dossier, data/tts_cache_oolel/, que l'app lit en premier.
Mêmes réglages que les deux séries précédentes : Oolel-Voices, 3 essais par
audio, Whisper wolof garde le meilleur, reprise après coupure (chaque audio est
écrit dans Google Drive dès qu'il est fait).

Liste : ``data/audit/voix_complete.csv`` (texte final, lexique appliqué — voir
``scripts/preparer_regen_oolel.py``). Le refaire après l'écoute des variantes
de ``notebooks/voix_test_prononciation_colab.ipynb`` : la liste est embarquée
dans le notebook, Colab n'a pas accès au dépôt.

    .\.venv\Scripts\python.exe scripts\preparer_notebook_oolel.py            # version Colab
    .\.venv\Scripts\python.exe scripts\preparer_notebook_oolel.py --brev     # version Jupyter/Brev

``--brev`` applique les adaptations de ``scripts/brev.py`` (pas de Google
Drive, jeton caché via getpass…) ; ``--sortie`` écrit ailleurs (pour comparer
à ce qui est dans notebooks/ sans l'écraser).
"""

from __future__ import annotations

import copy
import csv
import json
import pprint
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SOURCE = RACINE / "notebooks" / "voix_oolel_colab.ipynb"
SORTIE = RACINE / "notebooks" / "voix_oolel_complete.ipynb"
LISTE = RACINE / "data" / "audit" / "voix_complete.csv"

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
    plan_637 = json.loads((RACINE / "scripts" / "phrases_voix.json").read_text(encoding="utf-8"))
    phrases = phrases_a_generer()
    total = len(phrases)

    intro = f"""# GuindiMa AI — les {total} audios avec la voix native d'Oolel

La voix passe à celle du **Space soynade-research/Oolel-Voices-Demo**
(`8_1_c.wav`) : aucun import, tout se télécharge — la voix de référence que la
documentation d'Oolel-Voices conseille elle-même. Mêmes réglages que les 637 et
les 232 ajouts : graine {plan_637['graine']}, 3 essais par audio, Whisper wolof
garde le meilleur. Liste : `data/audit/voix_complete.csv` (texte final du
lexique `src/tts/lexique_prononciation.py`).

**Avant :** GPU T4 · clé 🔑 `HF_TOKEN` activée dans les secrets Colab.
Rien d'autre : la voix de référence se télécharge depuis le Space.

**Lancer :** Exécution → Tout exécuter. La 1re cellule redémarre la session
(« session plantée » = normal). Clique ensuite sur la **2e cellule** et fais
**Ctrl + F10**. Colab demande l'accès à Google Drive : accepte.

**Coupure ?** Chaque audio est écrit dans Google Drive
(`guindima_oolel_complete/tts_cache_oolel`) dès qu'il est fait. Relance de la
même façon : les audios déjà présents dans Drive sont sautés.

Durée : environ 2 h 30 à 3 h 30 ({total} audios × 3 essais, Whisper écoute).
À la fin, `tts_cache_oolel.zip` se télécharge : **tout** son contenu (WAV et
rapport) va dans `data/tts_cache_oolel/`, via
`python scripts/installer_voix_oolel.py tts_cache_oolel.zip`.
"""

    drive = f"""# Google Drive : sauvegarde au fur et à mesure (reprise après coupure)
import os, glob, shutil
from google.colab import drive
drive.mount('/content/drive')
BASE = '/content/drive/MyDrive/guindima_oolel_complete'
SORTIE = f'{{BASE}}/tts_cache_oolel'
RAPPORT = f'{{BASE}}/rapport_voix_complete.csv'
REF = f'{{BASE}}/8_1_c.wav'
os.makedirs(SORTIE, exist_ok=True)
if not os.path.exists(REF):
    from huggingface_hub import hf_hub_download
    telecharge = hf_hub_download(
        repo_id='soynade-research/Oolel-Voices-Demo',
        repo_type='space',
        filename='8_1_c.wav',
    )
    shutil.copy(telecharge, REF)
print('voix de référence :', REF)
print('déjà faits :', len(glob.glob(f'{{SORTIE}}/*.wav')), '/ {total}')
"""

    plan = {
        "modele": plan_637["modele"],
        "voix_reference": "8_1_c.wav (Space soynade-research/Oolel-Voices-Demo)",
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
shutil.copy(RAPPORT, f'{{SORTIE}}/rapport_voix_complete.csv')
shutil.make_archive('/content/tts_cache_oolel', 'zip', SORTIE)
shutil.copy('/content/tts_cache_oolel.zip', f'{{BASE}}/tts_cache_oolel.zip')
print('{total} audios OK — installer : python scripts/installer_voix_oolel.py tts_cache_oolel.zip')
files.download('/content/tts_cache_oolel.zip')
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
    import argparse

    parseur = argparse.ArgumentParser(description="Construit le notebook des 869 audios (Colab ou Brev).")
    parseur.add_argument("--brev", action="store_true", help="adapte pour une machine Brev (Jupyter, pas Google Drive)")
    parseur.add_argument("--sortie", type=Path, default=None, help="fichier .ipynb à écrire (par défaut la version Colab ou Brev)")
    args = parseur.parse_args()

    notebook = construire()
    if args.brev:
        import brev

        notebook = brev.adapter_complet(notebook)
    cible = args.sortie or RACINE / "notebooks" / (
        "voix_oolel_complete_brev.ipynb" if args.brev else "voix_oolel_complete.ipynb"
    )
    cible.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{cible.name} : {len(phrases_a_generer())} audios à générer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
