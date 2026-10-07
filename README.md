# GuindiMa AI

**Assistant vocal en wolof pour trouver sa ligne de bus à Dakar.**

🚀 **Démo en ligne :** [huggingface.co/spaces/TIJAANI/guindima-ai](https://huggingface.co/spaces/TIJAANI/guindima-ai) (parlez ou écrivez votre trajet en wolof)

On lui parle, il répond en wolof. GuindiMa AI écoute une demande de trajet
parlée en wolof, la transcrit, en extrait le départ et l'arrivée, puis indique
les lignes de bus (Dakar Dem Dikk / Tata AFTU) qui relient les deux points.

L'interface est pensée aussi pour les personnes qui ne lisent pas, ou lisent peu
couramment : on peut tout faire à la voix, et la réponse est donnée en parlé,
avec le numéro de ligne énoncé en wolof plutôt qu'en chiffres.

## Pipeline

| Étape | Modèle | Rôle |
| ----- | ------ | ---- |
| 1. Transcription | `AIHubSN/Kiriku-Wolof-ASR` (en ligne, GPU) · `M9and2M/whisper-small-wolof` (local, CPU) | Transcrit la demande vocale wolof. Kiriku (AI Hub Sénégal) reconnaît bien mieux les noms d'arrêts ; whisper-small, quantifié en int8, reste en local car Kiriku (taille Whisper large) ne tient pas sur un laptop. |
| 2. Extraction | `meta/llama-3.2-11b-vision-instruct` (NVIDIA Build) | Extrait `depart` et `arrivee` en JSON. Le prompt système contient la liste des lieux du réseau, le modèle ne peut donc pas inventer un quartier. Repli local automatique si l'API ne répond pas ou renvoie une réponse incomplète. |
| 3. Correspondance | — | Recherche arrêt par arrêt sur 112 lignes : une ligne convient si elle passe par le départ puis par l'arrivée, pas seulement si ce sont ses terminus. Sans ligne directe, propose un trajet avec un changement. Tolère l'orthographe phonétique et les variantes (« wakaam » → Ouakam, « Liberté VI » → Liberté 6). |
| 4. Réponse | — | Affiche le trajet en texte **et** le fait dire en wolof (`bilalfaye/speecht5_tts-wolof`). |

La voix des lignes historiques est pré-générée dans `data/tts_cache/` ; les
autres réponses (nouvelles lignes, trajets avec changement) passent par le TTS
direct. `python src/tts/pregenerer.py` régénère le cache pour toutes les lignes.

## Données

- `data/lignes_dakar.csv` — 112 lignes : 40 Dakar Dem Dikk (urbaines, banlieue,
  dessertes du TER, TAF TAF) et 72 Tata AFTU, avec leurs terminus officiels.
  Sources : [demdikk.sn/info-voyageurs](https://demdikk.sn/info-voyageurs/) et
  [aftu-senegal.org](https://aftu-senegal.org/infos-pratiques/), relevées le 07/10/2026.
- `data/itineraires_dakar.csv` — les arrêts de chaque ligne, dans l'ordre
  (environ 1 150). Généré par `python data/sources/build_dataset.py` à partir de
  `data/sources/` : itinéraires officiels AFTU, et arrêts DDD relevés dans
  OpenStreetMap (© contributeurs OpenStreetMap, ODbL). Les lignes DDD sans
  itinéraire publié ne sont connues que par leurs terminus.
- `data/tts_cache/` — les 33 audios de réponse pré-générés (31 lignes + « aucune ligne »
  + « walla »), versionnés pour que la démo n'ait rien à télécharger.
- `data/demo_audio/` — enregistrements de secours, pour quand le micro de la
  salle ne coopère pas.

## Installation

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuration

Copier `.env.example` vers `.env` et renseigner la clé NVIDIA Build, utilisée
pour l'extraction départ / arrivée :

```bash
cp .env.example .env
# puis éditer .env : NVIDIA_API_KEY=xxxx
```

## Lancer l'application

```bash
streamlit run src/app/app.py
```

Puis ouvrir l'URL affichée (http://localhost:8501) et, dans l'onglet
« 🎙️ Parler », dire son trajet en wolof.

Le premier lancement télécharge les modèles (Whisper, SpeechT5) et peut prendre
quelques minutes. Les suivants démarrent immédiatement.

## Tests

```bash
python -X utf8 src/app/check_examples.py
```

Le script fait passer les quatre phrases d'exemple de `EXEMPLES` dans
l'extraction LLM puis dans la correspondance, et vérifie que chacune trouve bien
sa ligne.

## IA responsable

### Modèles et licences

| Modèle | Licence |
| ------ | ------- |
| `M9and2M/whisper-small-wolof` (transcription) | MIT |
| `bilalfaye/speecht5_tts-wolof` (synthèse vocale) | MIT |
| `microsoft/speecht5_hifigan` (vocodeur) | MIT |
| `z-ai/glm-5.3-flash` (extraction) | servi par NVIDIA Build ; les poids GLM de z-ai sont en MIT, le point de service applique ses propres conditions d'utilisation |

L'extraction passe par l'API NVIDIA Build : la phrase transcrite est envoyée à
ce service pour en extraire le départ et l'arrivée. Les modèles de transcription
et de synthèse tournent en local, sur la machine.

### Données collectées

Aucune. Rien n'est enregistré, ni stocké, ni transmis à un service tiers, hormis
la phrase envoyée à l'API NVIDIA pour l'extraction. Pas de compte utilisateur, pas
de cookie, pas de journalisation des requêtes.

### Plutôt qu'inventer

Quand un lieu dit n'existe pas dans le réseau, l'application le dit et propose
le lieu le plus proche avec son score de similarité. Elle n'invente jamais un
quartier, et n'annonce jamais une ligne qui ne relie pas les deux points.

### Limites connues

- **Latence CPU** : environ 25 s par transcription sur CPU (le chargement du
  modèle se fait une fois, au démarrage). Sur GPU (voir ci-dessous), c'est quasi
  instantané.
- **Couverture partielle** : 112 lignes DDD et AFTU, mais les arrêts
  intermédiaires ne sont connus que pour les lignes AFTU et 7 lignes DDD ; les
  autres lignes DDD ne sont trouvées que d'un terminus à l'autre. Les lieux
  absents des itinéraires publiés (Sandaga, par exemple) ne sont pas reconnus.
- **Un seul changement** : au-delà d'une correspondance, aucun trajet n'est proposé.
- **L'ASR se trompe** : la reconnaissance wolof est imparfaite, d'où le matching
  flou et la normalisation phonétique.
- **Wolof uniquement** : ni le français, ni le multilingue ne sont pris en charge,
  et le numéro de ligne est énoncé en wolof, pas en chiffres.

## Déploiement GPU

L'application a été prévue pour tenir sur un CPU ordinaire, mais la transcription
est le goulot d'étranglement. Sur une instance NVIDIA Brev (GPU),
`whisper-small-wolof` se charge vite et transcrit en moins d'une seconde, ce qui
rend la démonstration fluide de bout en bout.

Pour changer de matériel : installer la version CUDA de PyTorch
(`pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124`)
puis relancer l'application. Le reste du code est inchangé — les modèles sont
chargés par `transformers` et suivent le matériel disponible.
