r"""Supprime du dépôt privé tout ce qui correspond à un code (GM-XXXXXX).

Par défaut, le script montre seulement ce qui serait supprimé :

    .\.venv\Scripts\python.exe scripts\supprimer_enregistrement.py GM-XXXXXX
    .\.venv\Scripts\python.exe scripts\supprimer_enregistrement.py GM-XXXXXX --executer

Un simple commit de suppression laisserait la voix dans l'historique du dépôt.
--executer retire donc aussi le fichier audio du stockage LFS, puis écrase
l'historique (les fiches JSON y restaient lisibles). C'est irréversible.

Le jeton est lu dans HF_TOKEN_COLLECTE (environnement ou .env), jamais affiché.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from app.collecte import DEPOT, MOTIF_CODE, TYPE_DEPOT, VARIABLE_JETON, dossier_du_code  # noqa: E402


def code_valide(brut: str) -> str | None:
    """Le code normalisé, ou None : rien d'autre ne doit devenir un chemin à effacer."""
    code = (brut or "").strip().upper()
    return code if MOTIF_CODE.fullmatch(code) else None


def supprimer(api, code: str, executer: bool = False) -> int:
    """Liste (et supprime si demandé) les fichiers du code ; renvoie leur nombre."""
    prefixe = dossier_du_code(code) + "/"
    # Seuls les fichiers ont un attribut `lfs` (None s'ils ne sont pas en LFS).
    arbre = [
        e for e in api.list_repo_tree(DEPOT, recursive=True, repo_type=TYPE_DEPOT)
        if hasattr(e, "lfs")
    ]
    fichiers = [e.path for e in arbre if e.path.startswith(prefixe)]
    empreintes_ici = {e.lfs.sha256 for e in arbre if e.lfs and e.path.startswith(prefixe)}
    empreintes_ailleurs = {e.lfs.sha256 for e in arbre if e.lfs and not e.path.startswith(prefixe)}
    # L'audio peut survivre dans LFS même si le dossier a déjà disparu du dépôt.
    candidats = [
        f for f in api.list_lfs_files(DEPOT, repo_type=TYPE_DEPOT)
        if f.file_oid in empreintes_ici or (f.filename or "").startswith(prefixe)
    ]
    # Deux envois du même fichier partagent un seul objet LFS : le purger casserait
    # l'enregistrement de l'autre code.
    audios = [f for f in candidats if f.file_oid not in empreintes_ailleurs]
    for chemin in fichiers:
        print(f"  {chemin}")
    print(f"{len(fichiers)} fichier(s), {len(audios)} objet(s) LFS pour {code}")
    if len(audios) < len(candidats):
        print(f"{len(candidats) - len(audios)} objet(s) LFS conservé(s) : utilisés aussi par un autre code.")
    if not fichiers and not candidats:
        print("Rien à supprimer. Un code tout récent peut mettre 30 min à arriver : réessaie plus tard.")
        return 0
    if not executer:
        print("Simulation : rien n'a été supprimé. Ajoute --executer pour supprimer.")
        return len(fichiers)

    if fichiers:
        api.delete_folder(
            prefixe.rstrip("/"), DEPOT, repo_type=TYPE_DEPOT,
            commit_message="Suppression sur demande",
        )
    if audios:
        api.permanently_delete_lfs_files(DEPOT, audios, rewrite_history=True, repo_type=TYPE_DEPOT)
    api.super_squash_history(DEPOT, repo_type=TYPE_DEPOT, commit_message="Historique nettoyé")
    print("Supprimé, historique compris.")
    return len(fichiers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Supprime les fichiers d'un code de collecte.")
    parser.add_argument("code", help="le code reçu, par exemple GM-7K4QX2")
    parser.add_argument("--executer", action="store_true", help="supprime vraiment (irréversible)")
    choix = parser.parse_args()

    code = code_valide(choix.code)
    if code is None:
        print("Code invalide : format attendu GM- suivi de 6 signes.")
        return 2

    from dotenv import load_dotenv
    from huggingface_hub import HfApi

    load_dotenv(RACINE / ".env")
    jeton = os.getenv(VARIABLE_JETON, "").strip()
    if not jeton:
        print(f"{VARIABLE_JETON} est absent (environnement ou .env).")
        return 2
    supprimer(HfApi(token=jeton), code, executer=choix.executer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
