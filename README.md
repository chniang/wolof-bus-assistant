# GuindiMa AI — Assistant Vocal Bus Wolof (Dakar)

Assistant (hackathon GOMYCODE x NVIDIA, 27 sept 2026) qui aide à choisir la ligne de
bus (Dakar Dem Dikk / Tata AFTU) entre deux points de Dakar.

## Pipeline prévu

| Module              | Rôle                                                        |
| ------------------- | ----------------------------------------------------------- |
| `src/asr/`          | Transcription des commandes vocales en wolof (à venir)      |
| `src/intent/`       | Extraction départ / destination via LLM NVIDIA Build (à venir) |
| `src/matching/`     | Correspondance avec le CSV des lignes (en place)            |
| `src/app/`          | Interface Streamlit (en place)                              |

## Données

- `data/arrets_lignes_dakar.csv` — colonnes : `ligne, depart, arrivee, categorie`.

## Installation

```bash
python -m venv .venv
# Windows
.env\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuration (optionnel pour le squelette)

Copier `.env.example` vers `.env` et renseigner la clé NVIDIA :

```bash
cp .env.example .env
# puis éditer .env : NVIDIA_API_KEY=xxxx
```

La clé signifie la clé API NVIDIA Build ; elle n'est pas encore utilisée.

## Lancer l'application

```bash
cp .env.example .env           # si pas déjà fait
streamlit run src/app/app.py
```

Ouvrir l'URL affichée (http://localhost:8501), saisir un départ et une arrivée
(quartiers de Dakar), puis cliquer sur « Chercher ma ligne ».

## Tester le matching en ligne de commande

```bash
python -c "from src.matching.stops_matcher import StopsMatcher; m = StopsMatcher(); print(m.find_line('liberté cinq', 'palais 2'))"
```

## Prochaines étapes

1. ASR wolof (`src/asr/`)
2. Extraction départ / destination via LLM NVIDIA Build (`src/intent/`)
3. Intégration de l'audio dans l'interface Streamlit