# Données de référence (vérité terrain)

Copiées telles quelles depuis `C:\Users\Lenovo\taches-web\` le 11/11/2026 :

- `trajets_reference.csv` : 67 trajets types (départ, arrivée, opérateur, ligne, arrêts de montée et de descente, statut, sources).
- `lignes_reference.csv` : 111 lignes Dem Dikk et Tata AFTU (terminus, arrêts principaux, source, date de consultation).
- `sources_inventaire.md` : l'inventaire des sources consultées.

Règle : **« confirmé » = une source officielle (demdikk.sn, AFTU) ou deux sources
indépendantes concordantes** (par exemple le site officiel et une relation OSM).
Le reste est « à vérifier » et ne sert jamais à corriger nos données tout seul.

Ces fichiers ne sont pas modifiés : ils servent à mesurer l'app
(`data/audit/verite_terrain.csv`), pas à la faire tourner.
