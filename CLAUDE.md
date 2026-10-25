# GuindiMa AI — consignes pour les agents de code

Assistant vocal wolof pour les bus de Dakar : l'usager dit son trajet en wolof,
l'app répond avec la compagnie (Dem Dikk ou Tata AFTU), la ligne, l'arrêt de
montée, l'arrêt de descente, un éventuel changement, à l'écran et à voix haute.

- App en ligne : Hugging Face Space `TIJAANI/guindima-ai` (Gradio, ZeroGPU)
- Code : GitHub `chniang/wolof-bus-assistant`
- Environnement : Windows, PowerShell, Python 3.12, venv `.venv`

## Règles absolues

1. **Ne jamais redéployer** (`upload_space.py`) ni pousser (`git push`) sans demande explicite.
2. **Ne jamais modifier** les CSV de `data/` (`lignes_dakar.csv`, `itineraires_dakar.csv`, `arrets_geo.csv`, `lieux_geo.csv`).
3. **Ne jamais toucher aux audios** de `data/collecte/`, `data/collecte_brut/`, `data/sources/` et `data/demo_audio/`, ni aux **637 WAV du plan** dans `data/tts_cache/`.
4. **Aucun secret** dans le code, les logs ou les messages (`.env` est exclu de Git et du Space).
5. **Chaque correction = un test** dans `tests/test_trajets.py`, puis lancer les tests avant de conclure.
6. **Mieux vaut ne rien répondre que répondre faux** : en cas de doute sur un lieu, laisser vide plutôt que deviner.
7. Les tâches longues (transcrire des dizaines d'audios, entraîner un modèle) : **écrire le script sans le lancer**, donner la commande à l'utilisateur.

## Commandes

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe tests\test_trajets.py              # tests locaux (doivent tous passer)
.\.venv\Scripts\python.exe tests\test_collecte.py             # tests de la collecte de voix
.\.venv\Scripts\python.exe tests\test_seconde_chance.py       # tests de la seconde chance ASR
.\.venv\Scripts\python.exe tests\test_asr_secours.py           # tests du chargement Whisper CPU (repli)
.\.venv\Scripts\python.exe tests\test_trajets.py --en-ligne   # tests contre l'app publiée (après déploiement)
```

Astuce PowerShell : un script Python passé en « here-string » perd les accents.
Écrire plutôt un fichier `.py` temporaire, l'exécuter, puis le supprimer.
`rg` n'est pas installé : utiliser l'outil de recherche de l'agent ou `Select-String`.

## Architecture (chemin d'une question)

1. **Transcription** (`src/asr/transcribe.py`, `app.py`)
   - Kiriku-Wolof-ASR sur GPU, **chargé au niveau module** au démarrage (règle ZeroGPU) ;
     `@spaces.GPU(duration=30)` ne fait que le calcul, **ne jamais y charger un modèle**.
   - Secours / local : notre Whisper fine-tuné sur la collecte,
     `TIJAANI/whisper-small-wolof-dakar-essai3` (CPU, int8, préchargé au démarrage).
     Dépôt **privé** : lit le secret `HF_TOKEN` ; sans token, repli automatique sur
     `M9and2M/whisper-small-wolof` (message dans le journal). Seuls les fichiers de
     la racine sont téléchargés, jamais les dossiers `checkpoint-*`.
   - Seconde chance : si aucun trajet, réessai avec l'autre modèle.
2. **Compréhension** (`src/intent/extract_intent.py`)
   - Extraction locale d'abord : n-grammes, `LIEUX`, `LIEUX_SUPPLEMENTAIRES`, `REPLACEMENTS_PHRASE`,
     `MOTS_DE_LA_PHRASE`, `MOTS_TROP_VAGUES`, `MOTS_HORS_LIEUX`, chiffres wolof.
   - Départ : « maa ngi X », « X laa nekk », « diougué / jóge / juge X ». Arrivée : après « dem ».
   - Secours : Llama 3.2 via NVIDIA Build.
3. **Recherche** (`src/matching/stops_matcher.py`, `lieux.py`, `geo.py`, `compagnie.py`)
   - Comparaison arrêt par arrêt, sens, trajet direct d'abord, sinon un changement.
   - `lieux.py` : `ALIAS`, `FAUX_AMIS` (Route de Rufisque, Garage Guédiawaye…), `score`.
   - `geo.py` : position seulement si le nom ne suffit pas ; arrêts « bonne » uniquement ;
     rues numérotées et noms génériques (Préfecture, Police…) jamais situés ;
     « Département de X » compte seulement pour Guédiawaye, Pikine, Rufisque.
4. **Réponse** (`app.py`)
   - Cartes HTML (montée, descente, arrêts du trajet, quartier si sûr, lien AFTU).
   - Voix : Oolel-Voices (voix Adia, CONCREE), **637 réponses pré-générées** dans `data/tts_cache/`.
     À l'oral on dit « numero » (pas « ligne ») et « Tata » / « Dem Dikk ».
     Pour régénérer : `scripts/phrases_voix.json` + `scripts/prononciations_wolof.json`
     + `notebooks/voix_oolel_colab.ipynb` (Colab GPU, 3 prises, meilleure choisie avec Whisper).
     Installation : `scripts/installer_voix_adia.py tts_cache_oolel.zip`. Aucun modèle TTS n'est chargé au runtime :
     un segment absent est sauté, jamais synthétisé en direct.

## Données

| Fichier | Contenu |
| --- | --- |
| `data/lignes_dakar.csv` | 112 lignes (40 Dem Dikk, 72 Tata) |
| `data/itineraires_dakar.csv` | ~1 150 arrêts ordonnés |
| `data/arrets_geo.csv` | 560 arrêts géolocalisés + confiance |
| `data/lieux_geo.csv` | lieux dits précalculés |
| `data/collecte/metadata.csv` | vocaux collectés (transcription, transcription_propre, locuteur, statut) |
| `data/collecte/asr_whisper.csv` | transcriptions Whisper des vocaux (score avant fine-tuning) |

## Scripts

- `scripts/preparer_collecte.py` : import d'un export WhatsApp (`--depuis`, `--collecteur`, `--locuteur`).
- `scripts/nettoyer_transcriptions.py` : orthographe des lieux → colonne `transcription_propre`.
- `scripts/transcrire_collecte.py` : transcrit les vocaux avec Whisper, **reprend où il s'est arrêté**.
- `scripts/finetune_whisper.py` : fine-tuning de Whisper small (à lancer sur GPU Brev, pas en local).
- `scripts/installer_voix_adia.py` : installe l'archive Oolel-Voices dans `data/tts_cache/`.
- `upload_space.py` : déploiement vers le Space (**uniquement sur demande**).

## Style

- Code et commentaires **en français**, commentaires humains qui expliquent le *pourquoi*
  (souvent avec l'exemple réel qui a motivé la règle).
- Réponses à l'utilisateur : courtes, en français, avec les commandes PowerShell exactes.
