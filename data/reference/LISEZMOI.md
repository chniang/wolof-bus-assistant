# Données de référence (vérité terrain)

Copiés tels quels depuis `C:\Users\Lenovo\taches-web\` le 11/11/2026 :

- `trajets_reference.csv` : 67 trajets types (départ, arrivée, opérateur, ligne,
  arrêts de montée et de descente, statut, sources).
- `lignes_reference.csv` : 111 lignes Dem Dikk et Tata AFTU (terminus, arrêts
  principaux, source, date de consultation).
- `sources_inventaire.md` : l'inventaire des sources consultées.

Copiés tels quels depuis `C:\Users\Lenovo\taches-web\` le 12/11/2026 :

- `arrets_toutes_lignes_aftu.csv` : 1 024 points officiels des 72 lignes Tata
  AFTU (fiches aftu-senegal.org), avec ligne, ordre, arrêt, source, date et
  statut.
- `arrets_toutes_lignes_ddd.csv` : 768 points officiels Dem Dikk (page
  demdikk.sn/reseau-urbain-dakar), avec les mêmes colonnes. Certaines lignes
  sont groupées (15A & 15B, 502 et 503 sans lettre) et les services TAF TAF /
  Express AIBD y figurent aussi.
- `arrets_lignes_prioritaires.csv` : 264 points des lignes relues en priorité
  pour les 15 plus gros écarts, avec les mêmes colonnes.
- `verification_ecarts.md` : la vérification des 15 plus gros écarts (Tata 60
  et Colobane, Tata 40 et Thiaroye, DDD 220, noms de l'AIBD), avec les sources
  et les questions tranchées.

**Attention** : les fiches officielles AFTU et Dem Dikk listent des rues et des
repères dans **un seul sens**. Ce ne sont pas de vrais arrêts, et l'autre sens
n'est pas décrit. La comparaison avec nos arrêts est donc indicative : un point
officiel absent de nos données n'est pas forcément une erreur, et inversement.

Règle : **« confirmé » = une source officielle (demdikk.sn, AFTU) ou deux sources
indépendantes concordantes** (par exemple le site officiel et une relation OSM).
Le reste est « à vérifier » et ne sert jamais à corriger nos données tout seul.

Ces fichiers ne sont pas modifiés : ils servent à mesurer l'app
(`data/audit/verite_terrain.csv`), pas à la faire tourner.
