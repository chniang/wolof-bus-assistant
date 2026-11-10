# Faire tourner les notebooks voix sur une machine NVIDIA Brev

Les deux notebooks voix ont une variante **Brev** (Jupyter simple, sans Google
Drive) en plus des versions Colab :

| Notebook | Ce qu'il fabrique |
| --- | --- |
| `notebooks/voix_test_prononciation_brev.ipynb` | les 12 audios de test de prononciation → `sortie_voix/audios/` puis `sortie_voix/voix_test.zip` |
| `notebooks/voix_oolel_complete_brev.ipynb` | les 869 audios (637 + 232) → `sortie_voix/tts_cache_oolel/` puis `sortie_voix/tts_cache_oolel.zip` |

Les versions Colab restent telles quelles ; seule la partie « Colab » change
(Drive → dossier local `./sortie_voix/`, secrets Colab → jeton saisi caché).
Le plan, les réglages (graine 1234, 3 essais, Whisper garde le meilleur) et la
reprise après coupure sont identiques.

## Étapes

1. **Machine** : sur Brev, crée une machine GPU **T4 ou L4** (image avec
   PyTorch + Jupyter déjà installés). Les deux notebooks tiennent dans
   quelques Go de VRAM ; pas besoin de plus.
2. **Upload** : dans l'interface Jupyter de la machine, téléverse les deux
   fichiers `.ipynb` (le `voix_oolel_complete_brev.ipynb`, et optionnellement
   le `voix_test_prononciation_brev.ipynb` pour un essai rapide d'abord).
3. **Jeton** : à la cellule Whisper, le notebook demande le jeton
   `HF_TOKEN` en **saisie cachée** (getpass) — rien ne s'affiche, rien n'est
   écrit dans le notebook. Sinon il lit la variable d'environnement
   `HF_TOKEN`. Jeton vide → repli automatique sur le Whisper wolof public
   (`M9and2M/whisper-small-wolof`), dont la voix de contrôle est moins bonne.
4. **Lancer** : Run All. La cellule pip installe les paquets **sans** forcer
   un redémarrage du noyau ; si Jupyter en demande un malgré tout, fais-le et
   relance Run All : la reprise saute les audios déjà écrits dans
   `sortie_voix/`.
5. **Coupure / arrêt de la machine ?** Relance Run All : chaque audio est
   écrit dans `sortie_voix/` dès qu'il est fait, donc rien n'est perdu.
6. **Récupérer** : à la fin, `sortie_voix/tts_cache_oolel.zip` (ou
   `voix_test.zip` pour le test) est posé à côté du notebook — télécharge-le
   depuis le panneau de fichiers de Jupyter. Le test de prononciation, lui,
   sert à remplir `src/tts/lexique_prononciation.py` puis regénérer.

## Côté PC, une fois le zip téléchargé

Depuis la racine du dépôt :

```powershell
.\.venv\Scripts\python.exe scripts\installer_voix_oolel.py --zip C:\Users\Lenovo\Downloads\tts_cache_oolel.zip
```

(ajuste le chemin du zip ; l'option `--zip` est la même chose que l'argument
positionnel des versions Colab). Le script vérifie les 869 noms attendus
(`data/audit/voix_complete.csv`) puis remplit `data/tts_cache_oolel/` — il ne
touche ni `data/tts_cache/` ni `data/tts_cache_ajouts/`, qui restent en
secours tant que le nouveau cache n'est pas complet.

## La facture Brev

**Éteins la machine Brev** une fois le zip téléchargé, puis relance-la avec la
même image si une coupure survient : la reprise accepte un dossier
`sortie_voix/` déjà rempli.
