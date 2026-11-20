# Lot B-divergentes : lignes Dem Dikk divergentes et douteuses

Rapport seulement, aucune donnée modifiée. Produit le 20/11/2026 sans réseau, à partir des fichiers locaux :

- `data/itineraires_dakar.csv` et `data/corrections/corrections_geo_ddd_proposees.csv`, combinés comme l'app le fait (`src/matching/itineraires_app.py`, `src/routing/data.py` : une ligne Dem Dikk présente dans les corrections remplace entièrement la nôtre, en mémoire) ;
- `data/reference/arrets_toutes_lignes_ddd.csv` (page demdikk.sn/reseau-urbain-dakar, consultée le 12/11/2026, non datée) et `data/reference/verification_ecarts.md` ;
- `data/reference/lignes_reference.csv`, `trajets_reference.csv` et l'audit `data/audit/comparaison_lignes_officielles.csv`.

Lignes examinées : divergentes 23, 208, 501 ; douteuses 6, 217, 220, 233.

Comparaison des noms : minuscules, sans accents ni ponctuation, préfixe « Terminus » retiré, et quelques graphies évidentes rapprochées à la main (« Parcelles Assainies » = « Terminus des Parcelles », « Hôpital Principal » = « Hopitale Principale », « Sahm » = « Rond Point Sahm », « Thiaroye » = « Dépôt Thiaroye »). Rien d'autre n'est deviné.

**À retenir** : pour 6 des 7 lignes (toutes sauf la 233), l'app ne sert plus nos anciens terminus mais la liste officielle elle-même. Les écarts « divergents » de l'audit du 18/11 mesuraient notre ancien CSV (2 à 10 arrêts) contre l'officiel ; ils ne disent donc pas que l'app est fausse, mais que la question se déplace sur la fiabilité de la liste officielle.

## Ligne 23 (divergente)

**Verdict : nos données suivent l'officiel.** L'app sert les 40 points officiels dans l'ordre ; le seul écart est le titre de la page (« Palais 1 ») contre la fin de la liste (« Terminus Palais 2 »), et lignes_dakar.csv garde Palais 1.

### 1. Nos arrêts, tels que l'app les utilise

Source : `data/corrections/corrections_geo_ddd_proposees.csv`, qui remplace en mémoire la ligne de `itineraires_dakar.csv` (moteur v2, extraction, geo.py ; préfixe « Terminus » retiré). Terminus : **Des Parcelles** → **Palais 2**.

1. Des Parcelles
2. Ecole Dior
3. Diamalaye
4. Hlm Grand Médine
5. Dior
6. Acapes
7. Dispensaire Norade
8. Hopital Mame Abdou
9. Eglise
10. Unité 11
11. Croisement 22
12. Police Parcelles
13. Pont Emergent
14. Ecole Hyacinthe Thiandoum
15. Rond point Liberté 6
16. Khar Yalla
17. Front de Terre
18. Cité des Eaux
19. Station castor
20. Avenue Bourguiba
21. Stade Demba Diop
22. Ecole Normale
23. Poste Fann
24. Avenue Cheikh Anta Diop
25. UCAD
26. Rond Point  Sahm
27. Canal 4
28. Gueule Tapée
29. Rue 6
30. DAF
31. Poste Médina
32. Difoncé
33. Sandaga
34. ASECNA
35. Bld de la République
36. Avenue Léopold Sédar Senghor
37. Hopitale Principale
38. Rond point assemblée nationale
39. Institut Pasteur
40. Palais 2

Avant remplacement, `itineraires_dakar.csv` contenait 10 arrêt(s) : Parcelles Assainies · École Dior · Diamalaye · Police Parcelles · Tally Bou Bess · Khar Yalla · UCAD · Sahm · Hôpital Principal · Palais 1. Fiche `lignes_dakar.csv` : Parcelles Assainies → Palais 1.

### 2. Liste officielle

`data/reference/arrets_toutes_lignes_ddd.csv` : 40 points, statut confirmé, consultée le 12/11/2026 (page non datée). Source(s) : https://demdikk.sn/reseau-urbain-dakar/.

1. Terminus des Parcelles
2. Ecole Dior
3. Diamalaye
4. Hlm Grand Médine
5. Dior
6. Acapes
7. Dispensaire Norade
8. Hopital Mame Abdou
9. Eglise
10. Unité 11
11. Croisement 22
12. Police Parcelles
13. Pont Emergent
14. Ecole Hyacinthe Thiandoum
15. Rond point Liberté 6
16. Khar Yalla
17. Front de Terre
18. Cité des Eaux
19. Station castor
20. Avenue Bourguiba
21. Stade Demba Diop
22. Ecole Normale
23. Poste Fann
24. Avenue Cheikh Anta Diop
25. UCAD
26. Rond Point Sahm
27. Canal 4
28. Gueule Tapée
29. Rue 6
30. DAF
31. Poste Médina
32. Difoncé
33. Sandaga
34. ASECNA
35. Bld de la République
36. Avenue Léopold Sédar Senghor
37. Hopitale Principale
38. Rond point assemblée nationale
39. Institut Pasteur
40. Terminus Palais 2

`lignes_reference.csv` : Parcelles Assainies → Palais 1 ; Terminus des Parcelles ; Ecole Dior ; Diamalaye ; HLM Grand Médine ; Acapes ; Unité 11 ; Croisement 22 ; Police Parcelles ; Pont de l'Emergence ; Rond point Liberté 6 ; Khar Yalla ; Front de Terre ; Cité des Eaux ; Station Castor ; Avenue Bourguiba ; Stade Demba Diop ; Ecole Normale ; Poste Fann ; U…

### 3. Côte à côte

**Ce que l'app sert contre l'officiel :**

| | App (40) | Officiel (40) |
|---|---|---|
| Arrêts communs | 40 : Des Parcelles · Ecole Dior · Diamalaye · Hlm Grand Médine · Dior · Acapes · Dispensaire Norade · Hopital Mame Abdou · Eglise · Unité 11 · Croisement 22 · Police Parcelles · Pont Emergent · Ecole Hyacinthe Thiandoum · Rond point Liberté 6 · Khar Yalla · Front de Terre · Cité des Eaux · Station castor · Avenue Bourguiba · Stade Demba Diop · Ecole Normale · Poste Fann · Avenue Cheikh Anta Diop · UCAD · Rond Point  Sahm · Canal 4 · Gueule Tapée · Rue 6 · DAF · Poste Médina · Difoncé · Sandaga · ASECNA · Bld de la République · Avenue Léopold Sédar Senghor · Hopitale Principale · Rond point assemblée nationale · Institut Pasteur · Palais 2 | idem |
| Seulement chez nous | 0 : — | |
| Seulement dans l'officiel | | 0 : — |
| Inversions d'ordre | aucune | |

**Notre CSV d'origine (`itineraires_dakar.csv`) contre l'officiel :**

| | CSV brut (10) | Officiel (40) |
|---|---|---|
| Arrêts communs | 8 : Parcelles Assainies · École Dior · Diamalaye · Police Parcelles · Khar Yalla · UCAD · Sahm · Hôpital Principal | idem |
| Seulement chez nous | 2 : Tally Bou Bess · Palais 1 | |
| Seulement dans l'officiel | | 32 : Hlm Grand Médine · Dior · Acapes · Dispensaire Norade · Hopital Mame Abdou · Eglise · Unité 11 · Croisement 22 · Pont Emergent · Ecole Hyacinthe Thiandoum · Rond point Liberté 6 · Front de Terre · Cité des Eaux · Station castor · Avenue Bourguiba · Stade Demba Diop · Ecole Normale · Poste Fann · Avenue Cheikh Anta Diop · Canal 4 · Gueule Tapée · Rue 6 · DAF · Poste Médina · Difoncé · Sandaga · ASECNA · Bld de la République · Avenue Léopold Sédar Senghor · Rond point assemblée nationale · Institut Pasteur · Terminus Palais 2 |
| Inversions d'ordre | aucune | |

Audit du 18/11 (`comparaison_lignes_officielles.csv`, classe DIVERGENTE) : terminus différents (nous : Parcelles Assainies / Palais 1 ; officiel : Terminus des Parcelles / Terminus Palais 2) ; 32 point(s) officiel(s) non retrouvé(s) ; 2 arrêt(s) de notre itinéraire absent(s) de la fiche.

### Ce que disent les références

verification_ecarts.md ne traite pas la 23. `trajets_reference.csv` relève que « la page officielle titre « Palais 1 » mais finit la liste par « Terminus Palais 2 » » (OSM relation 7108131).

### Action proposée

Aucune correction : l'app affiche déjà Des Parcelles → Palais 2 (terminus recalculés depuis la liste officielle) ; seul `lignes_dakar.csv` garde Palais 1, sans effet sur les réponses (Palais 1 et Palais 2 sont à 200 m).

## Ligne 208 (divergente)

**Verdict : vraie divergence à trancher.** L'app suit l'officiel (Gorom 01 → Rufisque) mais notre fiche et le catalogue disent Bayakh → Rufisque, et Bayakh n'apparaît nulle part dans la liste officielle.

### 1. Nos arrêts, tels que l'app les utilise

Source : `data/corrections/corrections_geo_ddd_proposees.csv`, qui remplace en mémoire la ligne de `itineraires_dakar.csv` (moteur v2, extraction, geo.py ; préfixe « Terminus » retiré). Terminus : **Gorom 01** → **Rufisque**.

1. Gorom 01
2. Gororm 02
3. Bambilor
4. Noflaye
5. Sangalkam
6. Keur Ndiaye Lo
7. Rufisque

Avant remplacement, `itineraires_dakar.csv` contenait 2 arrêt(s) : Bayakh · Rufisque. Fiche `lignes_dakar.csv` : Bayakh → Rufisque.

### 2. Liste officielle

`data/reference/arrets_toutes_lignes_ddd.csv` : 7 points, statut confirmé, consultée le 12/11/2026 (page non datée). Source(s) : https://demdikk.sn/reseau-urbain-dakar/.

1. Gorom 01
2. Gororm 02
3. Bambilor
4. Noflaye
5. Sangalkam
6. Keur Ndiaye Lo
7. Rufisque

`lignes_reference.csv` : Bayakh → Rufisque (pas de liste d'arrêts).

### 3. Côte à côte

**Ce que l'app sert contre l'officiel :**

| | App (7) | Officiel (7) |
|---|---|---|
| Arrêts communs | 7 : Gorom 01 · Gororm 02 · Bambilor · Noflaye · Sangalkam · Keur Ndiaye Lo · Rufisque | idem |
| Seulement chez nous | 0 : — | |
| Seulement dans l'officiel | | 0 : — |
| Inversions d'ordre | aucune | |

**Notre CSV d'origine (`itineraires_dakar.csv`) contre l'officiel :**

| | CSV brut (2) | Officiel (7) |
|---|---|---|
| Arrêts communs | 1 : Rufisque | idem |
| Seulement chez nous | 1 : Bayakh | |
| Seulement dans l'officiel | | 6 : Gorom 01 · Gororm 02 · Bambilor · Noflaye · Sangalkam · Keur Ndiaye Lo |
| Inversions d'ordre | aucune | |

Audit du 18/11 (`comparaison_lignes_officielles.csv`, classe DIVERGENTE) : terminus différents (nous : Bayakh / Rufisque ; officiel : Gorom 01 / Rufisque) ; 6 point(s) officiel(s) non retrouvé(s) ; 1 arrêt(s) de notre itinéraire absent(s) de la fiche.

### Ce que disent les références

verification_ecarts.md ne traite pas la 208. `lignes_reference.csv` : Bayakh → Rufisque, sans liste d'arrêts (page info-voyageurs, 11/11/2026).

### Action proposée

Demander à Dem Dikk si la 208 part de Bayakh ou de Gorom ; garder l'itinéraire officiel en attendant.

## Ligne 501 (divergente)

**Verdict : nos données suivent l'officiel.** L'app sert la liste officielle (Palais 2 → Leclerc) ; notre ancienne fiche « Gare de Dakar → Palais 2 » désigne très probablement la même navette TER, le terminus Leclerc étant à 0,8 km de la gare (arrets_geo.csv), mais la gare elle-même n'est pas un arrêt de la liste.

### 1. Nos arrêts, tels que l'app les utilise

Source : `data/corrections/corrections_geo_ddd_proposees.csv`, qui remplace en mémoire la ligne de `itineraires_dakar.csv` (moteur v2, extraction, geo.py ; préfixe « Terminus » retiré). Terminus : **Palais 2** → **Leclerc**.

1. Palais 2
2. Avenue Nelson Mandela
3. Avenue Léopold Sédar Senghor
4. Place de l’Indépendance
5. Esso Port Embarcadère
6. Leclerc

Avant remplacement, `itineraires_dakar.csv` contenait 2 arrêt(s) : Gare de Dakar · Palais 2. Fiche `lignes_dakar.csv` : Gare de Dakar → Palais 2.

### 2. Liste officielle

`data/reference/arrets_toutes_lignes_ddd.csv` : 6 points, statut confirmé, consultée le 12/11/2026 (page non datée). Source(s) : https://demdikk.sn/reseau-urbain-dakar/.

1. Terminus Palais 2
2. Avenue Nelson Mandela
3. Avenue Léopold Sédar Senghor
4. Place de l’Indépendance
5. Esso Port Embarcadère
6. Terminus Leclerc

`lignes_reference.csv` : Gare de Dakar → Palais 2 (pas de liste d'arrêts).

### 3. Côte à côte

**Ce que l'app sert contre l'officiel :**

| | App (6) | Officiel (6) |
|---|---|---|
| Arrêts communs | 6 : Palais 2 · Avenue Nelson Mandela · Avenue Léopold Sédar Senghor · Place de l’Indépendance · Esso Port Embarcadère · Leclerc | idem |
| Seulement chez nous | 0 : — | |
| Seulement dans l'officiel | | 0 : — |
| Inversions d'ordre | aucune | |

**Notre CSV d'origine (`itineraires_dakar.csv`) contre l'officiel :**

| | CSV brut (2) | Officiel (6) |
|---|---|---|
| Arrêts communs | 1 : Palais 2 | idem |
| Seulement chez nous | 1 : Gare de Dakar | |
| Seulement dans l'officiel | | 5 : Avenue Nelson Mandela · Avenue Léopold Sédar Senghor · Place de l’Indépendance · Esso Port Embarcadère · Terminus Leclerc |
| Inversions d'ordre | aucune | |

Audit du 18/11 (`comparaison_lignes_officielles.csv`, classe DIVERGENTE) : terminus différents (nous : Gare de Dakar / Palais 2 ; officiel : Terminus Palais 2 / Terminus Leclerc) ; 5 point(s) officiel(s) non retrouvé(s) ; 1 arrêt(s) de notre itinéraire absent(s) de la fiche.

### Ce que disent les références

verification_ecarts.md ne traite pas la 501. `lignes_reference.csv` : Gare de Dakar → Palais 2, sans liste d'arrêts.

### Action proposée

Pas de correction d'itinéraire ; vérifier (test) qu'un usager qui dit « Gare de Dakar » se voit bien proposer la 501 depuis Leclerc, et faire confirmer par Dem Dikk le nom exact du terminus côté gare.

## Ligne 6 (douteuse)

**Verdict : vraie divergence à trancher.** L'app suit l'officiel (Guédiawaye → Palais 1, statut « indice ») alors que notre fiche et la couche ArcGIS disent Cambérène 2 → Palais 2 ; les deux tracés partagent seulement Cambérène et l'axe Parcelles–Liberté.

### 1. Nos arrêts, tels que l'app les utilise

Source : `data/corrections/corrections_geo_ddd_proposees.csv`, qui remplace en mémoire la ligne de `itineraires_dakar.csv` (moteur v2, extraction, geo.py ; préfixe « Terminus » retiré). Terminus : **Guédiawaye** → **Palais 1**.

1. Guédiawaye
2. Marche Jeudi
3. Hôpital Dalal Diam
4. Camberene
5. Case PA
6. Police de Parcelles Assainies
7. Marché Grand Médine
8. Rond point 26
9. Foire
10. Sipres
11. Rond point Liberté 6
12. Liberté 5
13. Allées Khalifa Ababacar Sy
14. Jet d’Eau
15. Niary Tally
16. Eglise Sainte Thérèse
17. ENA
18. Boulevard Général De Gaule
19. Allées Papa Gueye Fall
20. Avenue Faidherbe
21. Avenue Lamine Gueye
22. Avenue André Peytavin
23. Avenue Jean Jaurès
24. Boulevard de la République
25. Avenue Nelson Mandela
26. Palais 1

Avant remplacement, `itineraires_dakar.csv` contenait 2 arrêt(s) : Cambérène 2 · Palais 2. Fiche `lignes_dakar.csv` : Cambérène 2 → Palais 2.

### 2. Liste officielle

`data/reference/arrets_toutes_lignes_ddd.csv` : 25 points, statut indice, consultée le 12/11/2026 (page non datée). Source(s) : https://demdikk.sn/reseau-urbain-dakar/.

1. Terminus Guédiawaye
2. Marche Jeudi
3. Hôpital Dalal Diam
4. Camberene
5. Case PA
6. Police de Parcelles Assainies – Marché Grand Médine
7. Rond point 26
8. Foire
9. Sipres
10. Rond point Liberté 6
11. Terminus Liberté 5
12. Allées Khalifa Ababacar Sy
13. Jet d’Eau
14. Niary Tally
15. Eglise Sainte Thérèse
16. ENA
17. Boulevard Général De Gaule
18. Allées Papa Gueye Fall
19. Avenue Faidherbe
20. Avenue Lamine Gueye
21. Avenue André Peytavin
22. Avenue Jean Jaurès
23. Boulevard de la République
24. Avenue Nelson Mandela
25. Palais 1

`lignes_reference.csv` : Cambérène 2 → Palais 2 ; Terminus Cambérène ; Cambérène 2 ; Cambérène 1 ; Case Ba ; Police des Parcelles ; U.25 ; U.26 ; VDN ; Sud Foire ; Liberté 6 ; Sacré-Cœur ; Liberté 5 ; Dieuppeul ; Bd Dial Diop ; Bd Général De Gaulle ; Allées Papa Guèye Fall ; Av. Faidherbe ; Av. Jean Jaurès ; Cathédrale ; Hôpital Principal ; Terminu…

### 3. Côte à côte

**Ce que l'app sert contre l'officiel :**

| | App (26) | Officiel (25) |
|---|---|---|
| Arrêts communs | 24 : Guédiawaye · Marche Jeudi · Hôpital Dalal Diam · Camberene · Case PA · Rond point 26 · Foire · Sipres · Rond point Liberté 6 · Liberté 5 · Allées Khalifa Ababacar Sy · Jet d’Eau · Niary Tally · Eglise Sainte Thérèse · ENA · Boulevard Général De Gaule · Allées Papa Gueye Fall · Avenue Faidherbe · Avenue Lamine Gueye · Avenue André Peytavin · Avenue Jean Jaurès · Boulevard de la République · Avenue Nelson Mandela · Palais 1 | idem |
| Seulement chez nous | 2 : Police de Parcelles Assainies · Marché Grand Médine | |
| Seulement dans l'officiel | | 1 : Police de Parcelles Assainies – Marché Grand Médine |
| Inversions d'ordre | aucune | |

**Notre CSV d'origine (`itineraires_dakar.csv`) contre l'officiel :**

| | CSV brut (2) | Officiel (25) |
|---|---|---|
| Arrêts communs | 0 : — | idem |
| Seulement chez nous | 2 : Cambérène 2 · Palais 2 | |
| Seulement dans l'officiel | | 25 : Terminus Guédiawaye · Marche Jeudi · Hôpital Dalal Diam · Camberene · Case PA · Police de Parcelles Assainies – Marché Grand Médine · Rond point 26 · Foire · Sipres · Rond point Liberté 6 · Terminus Liberté 5 · Allées Khalifa Ababacar Sy · Jet d’Eau · Niary Tally · Eglise Sainte Thérèse · ENA · Boulevard Général De Gaule · Allées Papa Gueye Fall · Avenue Faidherbe · Avenue Lamine Gueye · Avenue André Peytavin · Avenue Jean Jaurès · Boulevard de la République · Avenue Nelson Mandela · Palais 1 |
| Inversions d'ordre | aucune | |

Audit du 18/11 (`comparaison_lignes_officielles.csv`, classe DIVERGENTE) : ligne douteuse : notre fiche dit Cambérène 2–Palais 2, l'officiel dit Guédiawaye–Palais 1 ; terminus différents (nous : Cambérène 2 / Palais 2 ; officiel : Terminus Guédiawaye / Palais 1) ; 24 point(s) officiel(s) non retrouvé(s) ; 1 arrêt(s) de notre itinéraire absent(s) de la fiche.

### Ce que disent les références

verification_ecarts.md ne traite pas la 6. `lignes_reference.csv` : Cambérène 2 → Palais 2, avec des arrêts tirés d'une couche ArcGIS non officielle (Cambérène, Case Ba, Police des Parcelles, U.25, U.26, VDN, Sud Foire, Liberté 6, Sacré-Cœur, Liberté 5, Dieuppeul, Bd Dial Diop, Bd Général De Gaulle, Allées Papa Guèye Fall, Av. Faidherbe, Av. Jean Jaurès, Cathédrale, Hôpital Principal, Terminus Palais de Justice). Le point officiel 6 « Police de Parcelles Assainies – Marché Grand Médine » est coupé en deux arrêts dans les corrections chargées par l'app.

### Action proposée

Confirmer par téléphone ; garder l'affichage « estimé » ; vérifier la coupure du point « Police de Parcelles Assainies – Marché Grand Médine » en deux arrêts.

## Ligne 217 (douteuse)

**Verdict : l'officiel semble faux (copie d'une autre ligne).** La liste officielle 217 est identique point pour point à la 218 (Dépôt Thiaroye → Aéroport LSS), alors que le catalogue annonce Thiaroye → Ouakam ; l'app sert donc deux fois le même tracé.

### 1. Nos arrêts, tels que l'app les utilise

Source : `data/corrections/corrections_geo_ddd_proposees.csv`, qui remplace en mémoire la ligne de `itineraires_dakar.csv` (moteur v2, extraction, geo.py ; préfixe « Terminus » retiré). Terminus : **Dépôt Thiaroye** → **Aéroport LSS**.

1. Dépôt Thiaroye
2. Sipses
3. Bountou Pikine
4. patte d’oies
5. Foire
6. VDN
7. Sipres
8. ancienne piste
9. Ouakam
10. marché Ouakam
11. Ouakam
12. route des mamelles
13. route des Almadies
14. Ngor
15. Aéroport LSS

Avant remplacement, `itineraires_dakar.csv` contenait 2 arrêt(s) : Thiaroye · Ouakam. Fiche `lignes_dakar.csv` : Thiaroye → Ouakam.

### 2. Liste officielle

`data/reference/arrets_toutes_lignes_ddd.csv` : 15 points, statut indice, consultée le 12/11/2026 (page non datée). Source(s) : https://demdikk.sn/reseau-urbain-dakar/.

1. Dépôt Thiaroye
2. Sipses
3. Bountou Pikine
4. patte d’oies
5. Foire
6. VDN
7. Sipres
8. ancienne piste
9. Ouakam
10. marché Ouakam
11. terminus Ouakam
12. route des mamelles
13. route des Almadies
14. Ngor
15. Terminus aéroport LSS

`lignes_reference.csv` : Thiaroye → Ouakam (pas de liste d'arrêts).

### 3. Côte à côte

**Ce que l'app sert contre l'officiel :**

| | App (15) | Officiel (15) |
|---|---|---|
| Arrêts communs | 14 : Dépôt Thiaroye · Sipses · Bountou Pikine · patte d’oies · Foire · VDN · Sipres · ancienne piste · Ouakam · marché Ouakam · route des mamelles · route des Almadies · Ngor · Aéroport LSS | idem |
| Seulement chez nous | 0 : — | |
| Seulement dans l'officiel | | 0 : — |
| Inversions d'ordre | aucune | |

**Notre CSV d'origine (`itineraires_dakar.csv`) contre l'officiel :**

| | CSV brut (2) | Officiel (15) |
|---|---|---|
| Arrêts communs | 2 : Thiaroye · Ouakam | idem |
| Seulement chez nous | 0 : — | |
| Seulement dans l'officiel | | 12 : Sipses · Bountou Pikine · patte d’oies · Foire · VDN · Sipres · ancienne piste · marché Ouakam · route des mamelles · route des Almadies · Ngor · Terminus aéroport LSS |
| Inversions d'ordre | aucune | |

Audit du 18/11 (`comparaison_lignes_officielles.csv`, classe DIVERGENTE) : ligne douteuse : notre fiche dit Thiaroye–Ouakam, l'officiel dit Dépôt Thiaroye–Aéroport LSS ; terminus différents (nous : Thiaroye / Ouakam ; officiel : Dépôt Thiaroye / Terminus aéroport LSS) ; 11 point(s) officiel(s) non retrouvé(s) ; fiche officielle identique à 218.

### Contrôle : 217 contre 218

Listes officielles 217 et 218 identiques point pour point : **oui** (15 et 15 points). `lignes_reference.csv` donne pourtant Thiaroye → Ouakam pour la 217 et Thiaroye → Aéroport LSS pour la 218 ; `trajets_reference.csv` note que « la couche ArcGIS 217 montre un autre tracé (Parcelles, Corniche) : à vérifier ». Le tracé officiel 217 finit d'ailleurs à l'Aéroport LSS en passant par Ouakam, ce qui est le tracé de la 218 décrit par la couche ArcGIS (Dépôt Thiaroye, Patte d'Oie, VDN, Ancienne Piste, Ouakam, Mamelles, Aéroport LSS) : la liste appartient à la 218 et a été recopiée sous le numéro 217.

La liste cite aussi Ouakam deux fois (« Ouakam » en 9e, « terminus Ouakam » en 11e) et « Sipses » / « Sipres » (2e et 7e), indices supplémentaires d'une fiche mal saisie.

### Action proposée

Ne plus servir la liste 218 sous le numéro 217 : revenir à Thiaroye → Ouakam (terminus seuls, « estimé ») jusqu'à confirmation de Dem Dikk.

## Ligne 220 (douteuse)

**Verdict : vraie divergence à trancher.** Le fichier officiel mélange deux sources : la page demdikk.sn (Rufisque → Guédiawaye, que l'app suit) et un article Senego (navette Guédiawaye → AIBD) dont 2 points ont été insérés dans la liste.

### 1. Nos arrêts, tels que l'app les utilise

Source : `data/corrections/corrections_geo_ddd_proposees.csv`, qui remplace en mémoire la ligne de `itineraires_dakar.csv` (moteur v2, extraction, geo.py ; préfixe « Terminus » retiré). Terminus : **Rufisque** → **Guediawaye**.

1. Rufisque
2. Djoutiba
3. HLM Rufisque
4. SIPRES
5. SEDIMA
6. Lycée Jaxaay
7. 2 voies
8. Jaxaay
9. Station Keur Massar
10. Malika
11. Malika Plage
12. gadaye
13. Serigne Assane
14. Marche boubess
15. Lycée Limamoulaye
16. Guediawaye

Avant remplacement, `itineraires_dakar.csv` contenait 2 arrêt(s) : Rufisque · Guédiawaye. Fiche `lignes_dakar.csv` : Rufisque → Guédiawaye.

### 2. Liste officielle

`data/reference/arrets_toutes_lignes_ddd.csv` : 18 points, statut indice, 15/07/2026 (article de presse); consultée le 12/11/2026 (page non datée). Source(s) : https://demdikk.sn/reseau-urbain-dakar/, https://senego.com/navette-dem-dikk-guediawaye-aibd-toutes-les-2h-6-000-fcfa_1983793.html.

1. Terminus Rufisque
2. Espace BRT du terminus Dem Dikk de Guédiawaye
3. Djoutiba
4. Aéroport international Blaise Diagne (AIBD)
5. HLM Rufisque
6. SIPRES
7. SEDIMA
8. Lycée Jaxaay
9. 2 voies
10. Jaxaay
11. Station Keur Massar
12. Terminus Malika
13. Malika Plage
14. gadaye
15. Serigne Assane
16. Marche boubess
17. Lycée Limamoulaye
18. Terminus Guediawaye

`lignes_reference.csv` : Rufisque → Guédiawaye (pas de liste d'arrêts).

### 3. Côte à côte

**Ce que l'app sert contre l'officiel :**

| | App (16) | Officiel (18) |
|---|---|---|
| Arrêts communs | 16 : Rufisque · Djoutiba · HLM Rufisque · SIPRES · SEDIMA · Lycée Jaxaay · 2 voies · Jaxaay · Station Keur Massar · Malika · Malika Plage · gadaye · Serigne Assane · Marche boubess · Lycée Limamoulaye · Guediawaye | idem |
| Seulement chez nous | 0 : — | |
| Seulement dans l'officiel | | 2 : Espace BRT du terminus Dem Dikk de Guédiawaye · Aéroport international Blaise Diagne (AIBD) |
| Inversions d'ordre | aucune | |

**Notre CSV d'origine (`itineraires_dakar.csv`) contre l'officiel :**

| | CSV brut (2) | Officiel (18) |
|---|---|---|
| Arrêts communs | 2 : Rufisque · Guédiawaye | idem |
| Seulement chez nous | 0 : — | |
| Seulement dans l'officiel | | 16 : Espace BRT du terminus Dem Dikk de Guédiawaye · Djoutiba · Aéroport international Blaise Diagne (AIBD) · HLM Rufisque · SIPRES · SEDIMA · Lycée Jaxaay · 2 voies · Jaxaay · Station Keur Massar · Terminus Malika · Malika Plage · gadaye · Serigne Assane · Marche boubess · Lycée Limamoulaye |
| Inversions d'ordre | aucune | |

Audit du 18/11 (`comparaison_lignes_officielles.csv`, classe DOUTEUSE) : ligne douteuse : deux versions officielles se contredisent (Rufisque–Guédiawaye vs navette Guédiawaye–AIBD) ; 15 point(s) officiel(s) non retrouvé(s).

### Ce que dit verification_ecarts.md

Section 3 « Écart majeur : DDD 220 » : la page demdikk.sn donne 220 = Rufisque ↔ Guédiawaye (Djoutiba, Jaxaay, Station Keur Massar, Malika, Gadaye, Lycée Limamoulaye) ; Senego (15/07/2026) présente la 220 comme une navette Guédiawaye → AIBD depuis l'Espace BRT. Les deux versions se contredisent, sont marquées « indice », et sont « à trancher auprès de Dem Dikk (33 824 10 10) avant toute correction ». Dans le fichier officiel, les points 2 (« Espace BRT du terminus Dem Dikk de Guédiawaye ») et 4 (« Aéroport international Blaise Diagne (AIBD) ») viennent de l'article Senego et cassent l'ordre géographique ; les corrections chargées par l'app les ont retirés.

### Action proposée

Garder Rufisque → Guédiawaye sans les 2 points de presse ; trancher avec Dem Dikk (33 824 10 10) si le numéro 220 a été réutilisé pour la navette AIBD.

## Ligne 233 (douteuse)

**Verdict : l'officiel semble faux (copie d'une autre ligne).** La liste officielle 233 est identique point pour point à la 232 (Baux Maraîchers → Aéroport LSS) ; l'app ne l'utilise pas et garde nos deux terminus Baux Maraîchers → Palais 1.

### 1. Nos arrêts, tels que l'app les utilise

Source : `data/itineraires_dakar.csv` seul (aucune liste officielle chargée pour cette ligne). Terminus : **Baux Maraîchers** → **Palais 1**.

1. Baux Maraîchers
2. Palais 1

Fiche `lignes_dakar.csv` : Baux Maraîchers → Palais 1.

### 2. Liste officielle

`data/reference/arrets_toutes_lignes_ddd.csv` : 15 points, statut indice, consultée le 12/11/2026 (page non datée). Source(s) : https://demdikk.sn/reseau-urbain-dakar/.

1. Baux Maraichers
2. Yarakh
3. Cafétéria
4. Hann Maristes
5. Cours Sainte Marie de Hann
6. Sortie Mariste
7. Usine des eaux
8. Front de terre
9. Khar Yalla
10. Rond Point Liberté 6
11. Deux voies vers Camp Leclerc
12. VDN
13. Foire
14. Yoff
15. Terminus Aéroport LSS

`lignes_reference.csv` : Baux maraîchers → Palais 1 (pas de liste d'arrêts).

### 3. Côte à côte

**Ce que l'app sert contre l'officiel :**

| | App (2) | Officiel (15) |
|---|---|---|
| Arrêts communs | 1 : Baux Maraîchers | idem |
| Seulement chez nous | 1 : Palais 1 | |
| Seulement dans l'officiel | | 14 : Yarakh · Cafétéria · Hann Maristes · Cours Sainte Marie de Hann · Sortie Mariste · Usine des eaux · Front de terre · Khar Yalla · Rond Point Liberté 6 · Deux voies vers Camp Leclerc · VDN · Foire · Yoff · Terminus Aéroport LSS |
| Inversions d'ordre | aucune | |

Audit du 18/11 (`comparaison_lignes_officielles.csv`, classe DIVERGENTE) : ligne douteuse : notre fiche dit Baux Maraîchers–Palais 1, l'officiel dit Baux Maraîchers–Aéroport LSS ; terminus différents (nous : Baux Maraîchers / Palais 1 ; officiel : Baux Maraichers / Terminus Aéroport LSS) ; 14 point(s) officiel(s) non retrouvé(s) ; 1 arrêt(s) de notre itinéraire absent(s) de la fiche ; fiche officielle identique à 232.

### 5. Indice terrain de Cheikh (18/11) et contrôle 233 / 232

Indice : un bus 233 vu à **Gueule Tapée, dans le prolongement de la rue 6, direction Palais 2**.

- **Officiel 233 = copie de la 232 ?** Oui : les deux listes sont identiques point pour point (identiques, 15 et 15 points, de « Baux Maraichers » à « Terminus Aéroport LSS »). L'audit du 18/11 l'avait déjà noté (« fiche officielle identique à 232 »). La liste appartient bien à la 232 : elle est « confirmé » sous ce numéro (« indice » sous le 233), correspond aux terminus de la 232 dans `lignes_dakar.csv` (Baux Maraîchers → Aéroport LSS) et au tracé de la couche ArcGIS 232 (Yarakh, Front de Terre, Maristes, Aéroport LSS).
- **L'officiel colle-t-il à l'indice ?** Non. La liste 233/232 va de Baux Maraîchers à l'Aéroport LSS par Hann, Front de Terre, Liberté 6, la VDN, la Foire et Yoff ; elle ne passe ni à Gueule Tapée, ni rue 6, ni au Palais.
- **Nos données collent-elles à l'indice ?** En partie seulement. Notre 233 n'a que ses deux terminus (Baux Maraîchers → Palais 1) : la direction « Palais » colle, mais nous ne pouvons pas dire si le tracé passe à Gueule Tapée, faute d'arrêts intermédiaires, et le terrain dit Palais 2 là où notre fiche dit Palais 1. Un trajet Baux Maraîchers → Plateau qui passe par Gueule Tapée et la rue 6 est plausible (approche du Plateau par la Médina), mais rien dans nos fichiers ne le confirme.
- Pour mémoire, les lignes servies par l'app qui passent à Gueule Tapée puis finissent à Palais 2 : Dakar Dem Dikk Ligne 23 (Gueule Tapée → Rue 6 → Palais 2). Le bus observé portait le numéro 233 selon Cheikh ; on ne peut pas exclure une confusion avec la 23 (même quartier, même direction), à vérifier au prochain passage (photo du fronton).

Conclusion : l'indice **contredit l'officiel** et **colle à la direction de nos terminus** (Palais), sans pouvoir confirmer le tracé, faute d'arrêts intermédiaires chez nous. L'écart Palais 1 / Palais 2 compte peu pour l'usager : les deux terminus sont à 200 m l'un de l'autre (arrets_geo.csv).

### Action proposée

Garder nos terminus ; ne pas importer la liste 232 ; reconstruire le tracé avec Dem Dikk ou un relevé terrain (indice du 18/11 : Gueule Tapée, direction Palais 2), et trancher Palais 1 / Palais 2.

## Résumé

| Ligne | Verdict | Action proposée |
|---|---|---|
| 23 | nos données suivent l'officiel | Aucune correction : l'app affiche déjà Des Parcelles → Palais 2 (terminus recalculés depuis la liste officielle) ; seul `lignes_dakar.csv` garde Palais 1, sans effet sur les réponses (Palais 1 et Palais 2 sont à 200 m). |
| 208 | vraie divergence à trancher | Demander à Dem Dikk si la 208 part de Bayakh ou de Gorom ; garder l'itinéraire officiel en attendant. |
| 501 | nos données suivent l'officiel | Pas de correction d'itinéraire ; vérifier (test) qu'un usager qui dit « Gare de Dakar » se voit bien proposer la 501 depuis Leclerc, et faire confirmer par Dem Dikk le nom exact du terminus côté gare. |
| 6 | vraie divergence à trancher | Confirmer par téléphone ; garder l'affichage « estimé » ; vérifier la coupure du point « Police de Parcelles Assainies – Marché Grand Médine » en deux arrêts. |
| 217 | l'officiel semble faux (copie d'une autre ligne) | Ne plus servir la liste 218 sous le numéro 217 : revenir à Thiaroye → Ouakam (terminus seuls, « estimé ») jusqu'à confirmation de Dem Dikk. |
| 220 | vraie divergence à trancher | Garder Rufisque → Guédiawaye sans les 2 points de presse ; trancher avec Dem Dikk (33 824 10 10) si le numéro 220 a été réutilisé pour la navette AIBD. |
| 233 | l'officiel semble faux (copie d'une autre ligne) | Garder nos terminus ; ne pas importer la liste 232 ; reconstruire le tracé avec Dem Dikk ou un relevé terrain (indice du 18/11 : Gueule Tapée, direction Palais 2), et trancher Palais 1 / Palais 2. |

## Mise à jour du 20/11/2026 : lot B-sources

Nouvelles sources : les pages officielles https://demdikk.sn/reseau-urbain-dakar/ et https://demdikk.sn/info-voyageurs/, consultées le 20/11/2026. Les corrections vivent dans deux **nouveaux** fichiers, sans toucher aux CSV existants :

- `data/corrections/itineraires_ddd_revus.csv` : la liste d'arrêts revue des lignes 6, 208, 220 et 311, qui remplace en mémoire la liste servie. Chaque position y est décidée arrêt par arrêt : « bonne » (arrêt « bonne » d'`arrets_geo.csv` ou arrêt OSM de `positions_corrigees.csv`, nommé), « estimee » (position de la liste servie jusqu'ici, gardée pour mesurer la ligne mais jamais sûre) ou « inconnue ».
- `data/corrections/statut_lignes_ddd.csv` : le statut (confirmé / à confirmer) et les terminus affichés, avec les sources.

L'AIBD n'est pas touché (Express AIBD et repère de Diass inchangés).

| Ligne | Sources du 20/11 | Ce que l'app sert maintenant | Statut |
|---|---|---|---|
| 6 | info-voyageurs : Cambérène 2 ↔ Palais 2 ; reseau-urbain : Guédiawaye ↔ Palais 1 (liste) | Terminus affichés **Cambérène 2 → Palais 2** (info-voyageurs + ArcGIS). Arrêts de la liste reseau-urbain à partir de « Camberene » jusqu'à Palais 1 (23 arrêts) : Guédiawaye, Marché Jeudi et Hôpital Dalal Diam ne sont plus servis par la 6. | à confirmer (les deux pages se contredisent) |
| 208 | les deux pages : Bayakh ↔ Rufisque | **Bayakh** (sans position : « introuvable ») → Gorom 01 → Gorom 02 → Bambilor → Noflaye → Sangalkam → Keur Ndiaye Lo → Rufisque. 6 positions « bonne » sur 7 placées, Noflaye estimée, dans l'ordre et sans zigzag. « Gororm 02 » devient « Gorom 02 ». | **confirmé** |
| 220 | les deux pages : Rufisque ↔ Guédiawaye | Les 16 arrêts des pages, sans les 2 points de l'article Senego (Espace BRT, AIBD) : pas de navette AIBD. | **confirmé** |
| 311 | Lac Rose ↔ Croisement Keur Massar (boucle) | 5 arrêts : Lac rose croissement Niague, Croissement Tivaoune Peulh, Keur Massar, Station Keur Massar, Croissement Keur Massar. « Retour vers Lac Rose » retiré (indication de sens, pas un arrêt). Terminus affichés **Lac Rose (croisement Niague) → Croisement Keur Massar**. | inchangé |
| 233 | les deux pages : Baux Maraîchers ↔ Palais 1 | Terminus confirmés ; la liste officielle reste exclue (copie de la 232). | à confirmer |

### Positions écartées (homonymes ou hors ordre)

- **6 « Rond point 26 »** : le géocodage le posait sur le Rond-Point Liberté 6, 1,8 km plus au sud (zigzag). Sans position.
- **6 « Sipres »** et **220 « SIPRES »** : le « Sipres » « bonne » d'`arrets_geo.csv` est la cité de Dakar (14,69° N), hors des deux tracés. Positions estimées.
- **220 « HLM Rufisque »** : la position « bonne » est à 14,81° N, loin de Rufisque et hors de l'ordre de la ligne. Estimée.
- **220 « SEDIMA »** : position Tata côté Keur Massar (-17,317) alors que la liste la place avant Lycée Jaxaay et Jaxaay (-17,28). Estimée, à vérifier sur le terrain.
- **220 « Serigne Assane »** : `arrets_geo.csv` la dit « douteuse » (posée à Dakar). Estimée.
- **311 « Lac rose croissement Niague »** et **208 « Bayakh »** : aucun arrêt « bonne » ni OSM. Sans position.
- **311** : « Croissement Tivaoune Peulh » (OSM) et « Croisement Keur Massar » (« bonne ») sont au même point ; la boucle repasse par le même carrefour.

### Effet sur les réponses

- La 208 et la 220 ne portent plus « itinéraire à confirmer » et ne sont plus reléguées derrière les lignes confirmées.
- **Liberté 5 → Guédiawaye** n'a plus de bus direct : la seule ligne directe était la 6 (« à confirmer »), qui ne dessert plus Guédiawaye. L'app propose un changement (Dem Dikk 13 puis 2, ou Tata 78 puis 26). À revoir si Dem Dikk confirme que la 6 part bien de Guédiawaye.
- Le point officiel « Police de Parcelles Assainies – Marché Grand Médine » de la 6 reste coupé en deux arrêts, comme avant.
