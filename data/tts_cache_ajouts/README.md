# Audios ajoutés

Les audios générés après le plan des 637 phrases (nouvelles lignes Dem Dikk,
nouveaux arrêts des itinéraires officiels) vont ici, sous le nom de fichier donné
par `data/audit/voix_a_generer.csv` (colonne `fichier_wav`).

`data/tts_cache/` reste intact : l'app cherche d'abord un fichier là, puis ici
(`tts.speak.chemin_audio`).  Pour refaire la liste :

```powershell
.\.venv\Scripts\python.exe scripts\couverture_voix.py
```
