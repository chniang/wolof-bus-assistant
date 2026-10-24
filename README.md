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
| 1. Transcription | `AIHubSN/Kiriku-Wolof-ASR` (en ligne, GPU) · `TIJAANI/whisper-small-wolof-dakar-essai3` (secours et local, CPU) | Transcrit la demande vocale wolof. Kiriku (AI Hub Sénégal) reconnaît bien mieux les noms d'arrêts (~9 sur 10 contre 1 sur 10 au banc d'essai micro, voir `kiriku_test/`). Quand le GPU gratuit de Hugging Face n'est pas attribué, l'app bascule seule sur notre whisper fine-tuné sur les voix collectées (WER 89,7 % → 74,1 % sur 22 vocaux de voix jamais vues), quantifié en int8 sur CPU, qui sert aussi en local (Kiriku, taille Whisper large, ne tient pas sur un laptop). Dépôt privé : il faut le secret `HF_TOKEN`, sinon l'app repart seule de `M9and2M/whisper-small-wolof`. |
| 2. Extraction | extraction locale, puis `meta/llama-3.2-11b-vision-instruct` (NVIDIA Build) | Repère `depart` et `arrivee`. D'abord en local, par correspondance floue sur les lieux du réseau, en tenant compte des écritures phonétiques de l'ASR (« wakaam », « liberti sënk », « pale ») et des numéros dits en lettres ou en wolof. Le LLM n'intervient que si ce repérage ne donne pas de trajet complet ; son prompt contient la liste des lieux du réseau. |
| 3. Correspondance | — | Recherche arrêt par arrêt sur 112 lignes : une ligne convient si elle passe par le départ puis par l'arrivée, pas seulement si ce sont ses terminus. Sans ligne directe, propose un trajet avec un changement. Tolère l'orthographe phonétique et les variantes (« wakaam » → Ouakam, « Liberté VI » → Liberté 6) ; Palais 1 et Palais 2 valent tous deux « Palais ». |
| 4. Réponse | Adia_TTS (CONCREE), pré-généré | Affiche le trajet en texte **et** joue les segments wolof déjà générés dans `data/tts_cache/`. |

La voix est entièrement pré-générée : **637 audios Adia_TTS (CONCREE)**, construits
depuis `scripts/phrases_voix.json` et `scripts/prononciations_wolof.json`. La
génération se fait dans `notebooks/voix_adia_colab.ipynb` : trois prises par
segment, puis la meilleure est choisie avec un contrôle Whisper. Aucun modèle TTS
n'est chargé au runtime ; si un segment manque, l'app joue les morceaux présents
et laisse le reste silencieux. `scripts/installer_voix_adia.py` installe une
archive complète dans `data/tts_cache/`.

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
- `data/tts_cache/` — les **637 audios Adia** de réponse pré-générés (112 lignes,
  6 services, 519 lieux), versionnés pour que la démo n'ait rien à télécharger.
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

Version en ligne (Gradio, celle du Space Hugging Face) :

```bash
python app.py
```

Puis ouvrir l'URL affichée et dire son trajet en wolof, ou l'écrire.

Le premier lancement télécharge les modèles de transcription (Whisper CPU et
Kiriku GPU) et peut prendre quelques minutes. Les suivants démarrent
immédiatement ; la voix Adia est déjà dans `data/tts_cache/`.

## Tests

Les suites locales couvrent les trajets de référence, la collecte de voix, la
seconde chance ASR et le repli Whisper CPU :

```bash
# Local, sans télécharger ni charger de modèle
python tests/test_trajets.py
python tests/test_collecte.py
python tests/test_seconde_chance.py
python tests/test_asr_secours.py

# App publiée, comme un visiteur : trajets et audios envoyés au Space
python tests/test_trajets.py --en-ligne
```

Le mode local se lance après chaque modification du code ou des données, le mode
en ligne après chaque déploiement. Code de sortie 0 si tout passe.

## IA responsable

### Modèles et licences

| Modèle | Licence |
| ------ | ------- |
| `AIHubSN/Kiriku-Wolof-ASR` (transcription en ligne) | modèle protégé de l'AI Hub Sénégal : accès après acceptation de ses conditions |
| `TIJAANI/whisper-small-wolof-dakar-essai3` (transcription de secours et locale) | fine-tuning de `M9and2M/whisper-small-wolof` (MIT), dépôt privé |
| `M9and2M/whisper-small-wolof` (repli si le dépôt fine-tuné est inaccessible) | MIT |
| `meta/llama-3.2-11b-vision-instruct` (extraction, en dernier recours) | Llama 3.2 Community License, servi par NVIDIA Build selon ses conditions d'utilisation |

La transcription tourne sur la machine qui héberge l'app (le Space Hugging Face
en ligne, ou le PC en local). La voix Adia est pré-générée : aucun modèle TTS
n'est chargé au runtime. La phrase transcrite n'est envoyée à l'API NVIDIA Build
que si l'extraction locale ne trouve pas le trajet.

### Données collectées

Aucune. Rien n'est enregistré, ni stocké, ni transmis à un service tiers, hormis
la phrase envoyée à l'API NVIDIA quand l'extraction locale ne suffit pas. Pas de compte utilisateur, pas
de cookie, pas de journalisation des requêtes.

### Plutôt qu'inventer

Quand un lieu dit n'existe pas dans le réseau, l'application le dit et propose
le lieu le plus proche avec son score de similarité. Elle n'invente jamais un
quartier, et n'annonce jamais une ligne qui ne relie pas les deux points.

### Limites connues

- **GPU partagé** : en ligne, le GPU gratuit de Hugging Face (ZeroGPU) est
  rarement attribué aux visiteurs non connectés à un compte Hugging Face. Ils
  passent alors par notre whisper fine-tuné sur CPU : réponse en ~5 à 25 s,
  transcription moins précise que Kiriku, mais trajets toujours retrouvés grâce
  à la normalisation phonétique.
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
`TIJAANI/whisper-small-wolof-dakar-essai3` se charge vite et transcrit en moins
d'une seconde, ce qui rend la démonstration fluide de bout en bout.

Pour changer de matériel : installer la version CUDA de PyTorch
(`pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124`)
puis relancer l'application. Le reste du code est inchangé — les modèles sont
chargés par `transformers` et suivent le matériel disponible.

## Licence

Code © 2026 Cheikh Niang — tous droits réservés (voir `LICENSE`) : consultable, mais aucune réutilisation, copie ou modification sans autorisation écrite ; les modèles tiers gardent les licences déjà listées plus haut.

