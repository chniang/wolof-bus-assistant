r"""Crée (ou met à jour) le Space de test TIJAANI/kiriku-test et y envoie ce dossier.

Lancement depuis la racine du projet :
    .\.venv\Scripts\python.exe kiriku_test\creer_space_test.py

Le token est celui enregistré par `hf auth login`. Il est copié dans les secrets
du Space (HF_TOKEN) pour que le Space puisse télécharger Kiriku, qui est protégé.
Il n'est écrit dans aucun fichier.
"""

from pathlib import Path

from huggingface_hub import HfApi, get_token

REPO = "TIJAANI/kiriku-test"
DOSSIER = Path(__file__).parent

api = HfApi()
api.create_repo(REPO, repo_type="space", space_sdk="gradio", exist_ok=True)
api.add_space_secret(REPO, "HF_TOKEN", get_token())
try:
    api.request_space_hardware(REPO, "zero-a10g")
except Exception as erreur:
    print("ZeroGPU non activé automatiquement :", erreur)
    print("-> Space > Settings > Space hardware > ZeroGPU, à la main.")

api.upload_folder(
    repo_id=REPO,
    repo_type="space",
    folder_path=str(DOSSIER),
    ignore_patterns=["creer_space_test.py", "__pycache__/*", "*.pyc"],
    commit_message="Banc d'essai Kiriku vs whisper-small-wolof",
)
print(f"Envoyé : https://huggingface.co/spaces/{REPO}")
