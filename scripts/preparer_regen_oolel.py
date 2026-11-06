r"""La liste complète des audios jouables par l'app : data/audit/voix_complete.csv.

GuindiMa passe à la voix native d'Oolel-Voices (8_1_c.wav du Space
soynade-research/Oolel-Voices-Demo) : TOUTES les réponses sont régénérées, en
une seule série. Cette liste fait le compte :

- les 637 réponses du plan courant (scripts/phrases_voix.json) ;
- les 232 ajouts Adia (décrits dans notebooks/voix_ajouts_colab.ipynb),
  aujourd'hui dans data/tts_cache_ajouts/.

soit 869 fichiers, chacun avec le texte final envoyé à la voix — c'est-à-dire
la phrase du plan, une fois le lexique de prononciation
(`src/tts/lexique_prononciation.py`) appliqué. Toutes les phrases sont déjà en
écriture parlée validée (« Tataa », « Taf Taf », chiffres en mots) ; le lexique
les retouche mot à mot au besoin.

C'est ce CSV que lit scripts/preparer_notebook_oolel.py pour construire
notebooks/voix_oolel_complete.ipynb, et scripts/installer_voix_oolel.py pour
vérifier l'archive rentrée de Colab. La nouvelle voix s'installe dans
data/tts_cache_oolel/ (lu en premier par l'app) ; data/tts_cache/ et
data/tts_cache_ajouts/ restent intacts, en secours.

Il réécrit data/audit/voix_complete.csv à chaque lancement : après l'écoute des
variantes, le relancer pour intégrer un lexique rempli.

Il ne modifie ni phrases_voix.json, ni tts_cache/, ni tts_cache_ajouts/, ni les
audios d'aucune sorte (aucun fichier son n'est créé ici).

    .\.venv\Scripts\python.exe scripts\preparer_regen_oolel.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from tts.lexique_prononciation import appliquer

PLAN = RACINE / "scripts" / "phrases_voix.json"
NOTEBOOK_AJOUTS = RACINE / "notebooks" / "voix_ajouts_colab.ipynb"
COMPLETE = RACINE / "data" / "audit" / "voix_complete.csv"

CHAMPS = ["type", "texte_a_prononcer", "fichier_wav", "origine"]


def plan_ajouts() -> list[dict[str, str]]:
    """Les 232 ajouts : le PLAN embarqué dans le notebook des ajouts.

    Colab n'a pas accès au dépôt ; la liste est copiée dans le notebook. On l'y
    relit plutôt que de la reconstruire, pour que le CSV reprenne exactement les
    phrases déjà générées une fois (les mêmes textes, aucune surprise d'écart).
    """
    notebook = json.loads(NOTEBOOK_AJOUTS.read_text(encoding="utf-8"))
    source = next(
        "".join(cellule["source"])
        for cellule in notebook["cells"]
        if cellule["cell_type"] == "code"
        and "".join(cellule["source"]).startswith("PLAN = ")
    )
    portee: dict = {}
    exec(source, portee)  # noqa: S102 - un fichier de ce dépôt, jamais une entrée
    return list(portee["PHRASES"])


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    ajouts = plan_ajouts()

    rangees: list[dict[str, str]] = []
    vus: set[str] = set()
    for phrases, origine in (
        (plan["phrases"], "tts_cache"),
        (ajouts, "tts_cache_ajouts"),
    ):
        for entree in phrases:
            fichier = entree["fichier"]
            if fichier in vus:
                raise SystemExit(f"fichier en double dans la liste : {fichier}")
            vus.add(fichier)
            rangees.append(
                {
                    "type": entree["type"],
                    # Le texte final envoyé à la voix : lexique appliqué, l'écran
                    # garde toujours le nom affiché (il n'est pas dans la phrase).
                    "texte_a_prononcer": appliquer(entree["phrase"]),
                    "fichier_wav": fichier,
                    "origine": origine,
                }
            )

    chiffres = [r for r in rangees if any(c.isdigit() for c in r["texte_a_prononcer"])]
    if chiffres:
        raise SystemExit(
            "Oolel lit mal les chiffres : les phrases doivent être en mots. "
            f"Ex. {chiffres[0]['fichier_wav']}"
        )
    longues = [(r["fichier_wav"], len(r["texte_a_prononcer"])) for r in rangees if len(r["texte_a_prononcer"]) > 200]
    if longues:
        raise SystemExit(f"phrases au-delà de 200 caractères : {longues[:5]}")

    COMPLETE.parent.mkdir(parents=True, exist_ok=True)
    with COMPLETE.open("w", encoding="utf-8", newline="") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=CHAMPS)
        redacteur.writeheader()
        redacteur.writerows(rangees)
    print(f"{COMPLETE.name} : {len(rangees)} audios "
          f"({sum(1 for r in rangees if r['origine'] == 'tts_cache')} du plan + "
          f"{sum(1 for r in rangees if r['origine'] == 'tts_cache_ajouts')} ajouts), "
          f"lexique appliqué ({appliquer.__module__}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
