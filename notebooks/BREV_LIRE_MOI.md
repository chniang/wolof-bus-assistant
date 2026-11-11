# Faire tourner les notebooks voix sur une machine NVIDIA Brev

Les trois notebooks voix ont une variante **Brev** (Jupyter simple, sans Google
Drive) en plus des versions Colab :

| Notebook | Ce qu'il fabrique |
| --- | --- |
| `notebooks/voix_test_prononciation_brev.ipynb` | les 12 audios de test de prononciation → `sortie_voix/audios/` puis `sortie_voix/voix_test.zip` |
| `notebooks/voix_oolel_complete_brev.ipynb` | tous les audios du CSV (`voix_complete.csv`, 637 + ajouts) → `sortie_voix/tts_cache_oolel/` puis `sortie_voix/tts_cache_oolel.zip` |
| `notebooks/voix_ajouts_conversation_brev.ipynb` | les 4 réponses de conversation récentes + 3 essais « Tata » à écouter → `sortie_voix/audios_conversation/` puis `sortie_voix/ajouts_conversation.zip` |

Les versions Colab restent telles quelles ; seule la partie « Colab » change
(Drive → dossier local `./sortie_voix/`, secrets Colab → variable
d'environnement `HF_TOKEN`, saisie possible → rien du tout : sur Brev il n'y a
pas de clavier au premier plan, surtout en exécution sans interface).
Le plan, les réglages (graine 1234, 3 essais, Whisper garde le meilleur) et la
reprise après coupure sont identiques.

## Étapes

1. **Machine** : sur Brev, crée une machine GPU **T4 ou L4** (image avec
   Jupyter déjà installés — pip et torch peuvent manquer, la première cellule
   du notebook s'en occupe). Les deux notebooks tiennent dans quelques Go de
   VRAM ; pas besoin de plus.
2. **Upload** : dans l'interface Jupyter de la machine, téléverse les fichiers
   `.ipynb` (le `voix_oolel_complete_brev.ipynb`, et optionnellement
   le `voix_test_prononciation_brev.ipynb` pour un essai rapide d'abord,
   ou le `voix_ajouts_conversation_brev.ipynb` pour poser juste les
   nouvelles réponses de conversation).
3. **Jeton** : dans l'environnement de la machine, définis la variable
   `HF_TOKEN` avec un jeton Hugging Face (lecture seule suffit). Le notebook
   ne le demande **pas au clavier** : pas de saisie possible sur une machine
   Brev (surtout en exécution sans interface), et rien n'est écrit dans le
   notebook. Sans jeton, le dépôt privé du Whisper finetuné est inaccessible :
   le notebook passe directement au Whisper wolof public
   (`M9and2M/whisper-small-wolof`), dont la voix de contrôle est moins bonne.
4. **Lancer** : la cellule pip installe pip (`ensurepip`) puis les paquets.
   Ensuite **Kernel -> Restart Kernel**, puis Run All — la note sous le pip
   l'explique : sans ce redémarrage, numpy plante avec
   « Numpy is not available » une fois torch chargé. La reprise saute les
   audios déjà écrits dans `sortie_voix/`.
5. **Coupure / arrêt de la machine ?** Relance Run All : chaque audio est
   écrit dans `sortie_voix/` dès qu'il est fait, donc rien n'est perdu.
6. **Récupérer** : à la fin, `sortie_voix/tts_cache_oolel.zip` (ou
   `voix_test.zip` pour le test) est posé à côté du notebook — télécharge-le
   depuis le panneau de fichiers de Jupyter. Le test de prononciation, lui,
   sert à remplir `src/tts/lexique_prononciation.py` puis regénérer.

## Sans interface (nbconvert)

Le notebook ne demande jamais rien : même en exécution sans interface (aucun
navigateur, aucun pop-up), il tourne jusqu'au zip. Sur la machine, avec le
notebook déposé :

```bash
jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=-1 voix_oolel_complete_brev.ipynb --output voix_oolel_complete_brev.ipynb
```

(`--output …` écrase le fichier à la place de créer un `.nbconvert.ipynb`.)
Pour un essai rapide d'abord, même commande avec le `voix_test_prononciation_brev.ipynb`.
Le jeton reste à lire dans la variable d'environnement `HF_TOKEN` ; en cas de
coupure, relance la commande, la reprise saute les audios déjà faits.

## Côté PC, une fois le zip téléchargé

Depuis la racine du dépôt :

```powershell
.\.venv\Scripts\python.exe scripts\installer_voix_oolel.py --zip C:\Users\Lenovo\Downloads\tts_cache_oolel.zip
```

(ajuste le chemin du zip ; l'option `--zip` est la même chose que l'argument
positionnel des versions Colab). Le script vérifie les noms attendus
(`data/audit/voix_complete.csv`) puis remplit `data/tts_cache_oolel/` — il ne
touche ni `data/tts_cache/` ni `data/tts_cache_ajouts/`, qui restent en
secours tant que le nouveau cache n'est pas complet.

Pour le petit zip des ajouts de conversation, même principe avec
`--conversation` : seules les 4 réponses de conversation sont installées, les
essais « Tata » restent à écouter, et l'archive complète n'est pas requise :

```powershell
.\.venv\Scripts\python.exe scripts\installer_voix_oolel.py --conversation C:\Users\Lenovo\Downloads\ajouts_conversation.zip
```

## La facture Brev

**Éteins la machine Brev** une fois le zip téléchargé, puis relance-la avec la
même image si une coupure survient : la reprise accepte un dossier
`sortie_voix/` déjà rempli.
