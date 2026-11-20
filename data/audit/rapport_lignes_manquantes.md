# Lignes Dem Dikk « manquantes » : 311, 319, 327, TO1, Express AIBD

Lot B5-état, 20/11/2026. Rapport seulement : aucun CSV, aucun audio, aucun code
modifié. Aucun accès réseau : tout vient du dépôt, et d'une exécution locale du
moteur v2 hors ligne (`_matcher_hors_ligne()` de `tests/test_trajets.py`, sans
Nominatim).

## Constat principal : quatre de ces lignes sont déjà servies par l'app (en local)

Aucune des cinq lignes n'est dans `data/lignes_dakar.csv` ni dans
`data/itineraires_dakar.csv` (vérifié aussi dans l'historique Git : jamais
présentes). Mais l'app ne lit pas seulement ces deux fichiers.

`src/routing/data.py` (`_integrer_dem_dikk_officiel`) remplace **en mémoire**
les itinéraires Dem Dikk par les listes officielles de
`data/corrections/corrections_geo_ddd_proposees.csv`, via
`rangees_ddd_officielles()` (`src/matching/itineraires_app.py`). La docstring le
dit : « Une ligne officielle que nous n'avions pas (311, 319…) est ajoutée. »
Le moteur v2 est le moteur par défaut (`GUINDIMA_MOTEUR`, défaut `v2`,
`app.py:224`), et `upload_space.py` envoie bien `data/corrections/` sur le Space.

Résultat de `load_data()` en local :

| Ligne (nom dans l'app) | Dans `data.lignes` | Terminus affichés | Arrêts |
| --- | --- | --- | --- |
| Ligne 311 | oui | Lac rose croissement Niague / Retour vers Lac Rose | 6 |
| Ligne 319 | oui | Liberté 6 / Ouakam | 17 |
| Ligne 327 | oui | Keur Massar / Parcelles | 11 |
| TAF TAF OUAKAM (TO1) | oui | Ouakam / Palais 2 | 10 |
| Express AIBD | **non** | — | 0 |

Requêtes réelles au moteur (hors ligne) :

| Demande | Lignes proposées |
| --- | --- |
| Liberté 6 → Ouakam | Ligne 219, **Ligne 319**, Ligne 49 |
| Boulangerie Jaune → Ouakam | Ligne 219, **Ligne 319** |
| IHO → Liberté 6 | **Ligne 319** |
| Keur Massar → Parcelles Assainies | **Ligne 327**, Ligne 45, Ligne 63 |
| Malibu → Keur Massar | **Ligne 327**, Ligne 83 |
| Case bi → Keur Massar | Ligne 227, **Ligne 327** |
| Ouakam → Palais 2 | Ligne 7, **TAF TAF OUAKAM (TO1)** |
| Ouakam → Monument de la Renaissance | **TAF TAF OUAKAM (TO1)** |
| Corniche Ouest → Ouakam | **TAF TAF OUAKAM (TO1)** |
| Keur Massar → Lac Rose | Ligne 73 (pas la 311) |
| Niague → Keur Massar | Ligne 53, 73, 79 (pas la 311) |
| Tivaouane Peulh → Keur Massar | Ligne 74, 79, 80 (pas la 311) |
| Grand Yoff → AIBD | TAF TAF (pas d'Express AIBD) |

Donc en local : **319, 327 et TO1 sont proposées** ; **311 est chargée mais
presque jamais proposée** ; **Express AIBD est réellement absente**.

Non vérifié (réseau interdit) : que le Space publié tourne avec cette version.
À contrôler après le prochain déploiement avec
`tests\test_trajets.py --en-ligne` sur une des requêtes ci-dessus.

Les audits plus anciens qui les disent « absentes »
(`data/audit/comparaison_lignes_officielles.csv`, classe
`ABSENTE_DE_NOS_DONNEES` ; `data/audit/fiabilite_rapport.md`, « Ordre de
correction » point 5) comparent l'officiel à `lignes_dakar.csv` seul : ils ne
voient pas l'ajout en mémoire.

## Sources présentes dans le dépôt

| Fichier | Contenu pour ces lignes |
| --- | --- |
| `data/sources/ddd_itineraires_officiels.csv` | Listes brutes de demdikk.sn : 311 (banlieue, 6), 319 (urbain, 17), 327 (banlieue, 11), TO1 (urbain, 10). Pas d'Express AIBD. |
| `data/reference/arrets_toutes_lignes_ddd.csv` | Mêmes listes, statut **confirmé**, source https://demdikk.sn/reseau-urbain-dakar/ consultée le 12/11/2026 (page non datée). Express AIBD : 3 points **confirmés**, source https://demdikk.sn/offres-de-transport/. TAF TAF (vers Sphère Ministérielle) : 2 points, **indice** (info-voyageurs). |
| `data/reference/lignes_reference.csv` | Express AIBD : HLM Grand-Yoff (face stade LSS) → AIBD, « Autoroute à péage ». TAF TAF : Ouakam → AIBD / Sphère ministérielle. Rien pour 311, 319, 327, TO1. |
| `data/reference/sources_inventaire.md` | Express AIBD : départ HLM Grand-Yoff, 6 000 FCFA, 24 h/24 (offres-de-transport). |
| `data/reference/verification_ecarts.md` | « Express AIBD » = nom de service confirmé (officiel). Rien sur 311/319/327/TO1. |
| `data/corrections/corrections_geo_ddd_proposees.csv` | **Ce que l'app charge** : 311, 319, 327, TO1 avec positions (source par arrêt, voir plus bas). Pas d'Express AIBD. |
| `data/corrections/audit_ddd_par_ligne.csv` | 311 : 6 arrêts, 4 ancres sûres, 2 inconnus, ~6,4 km. 319 : 17, 3 ancres, 10 interpolés, ~8,3 km. 327 : 11, 6 ancres, 2 interpolés, ~24,7 km. TO1 : 10, 2 ancres, 6 Nominatim, ~12,1 km. Aucune n'a de trace OSM. |
| `data/audit/fiabilite_lignes.csv` | Part des positions mesurées : 311 67 %, 319 18 %, 327 55 %, TO1 30 %. |
| `data/corrections/lignes_officiel_exclues.csv`, `terminus_ddd_officiels.csv` | Aucune de ces lignes (seulement 217, 233 et 501). |
| `tests/test_trajets.py` | Seule TO1 est testée (jamais annoncée « ligne 1 », se dit « Taf Taf Wakaam »). Aucun test sur 311, 319, 327, Express AIBD. |

## Voix

`data/tts_cache_ajouts/rapport_voix_ajouts.csv` (Adia, 3 prises, aucune
marquée douteuse) :

| Fichier | Texte généré | Prise retenue |
| --- | --- | --- |
| `dakar_dem_dikk_311.wav` | « Jëlal bus bu Dem Dikk, numero ñetti téeméer ak fukk ak benn. » | 1 (0,81) |
| `dakar_dem_dikk_319.wav` | « Jëlal bus bu Dem Dikk, numero ñetti téeméer ak fukk ak juróom ñeent. » | 2 (0,939) |
| `dakar_dem_dikk_327.wav` | « Jëlal bus bu Dem Dikk, numero ñetti téeméer ak ñaar fukk ak juróom ñaar. » | 2 (0,90) |
| `dakar_dem_dikk_taf_taf_ouakam_to1.wav` | « Jëlal bus bu Dem Dikk, TAF TAF Wakaam. » | 3 (0,892) |

Les nombres sont justes (311 = 300 + 10 + 1 ; 319 = 300 + 10 + 5 + 4 ;
327 = 300 + 20 + 5 + 2).

`data/audit/voix_complete.csv` (liste de référence) a les mêmes phrases avec
« biis » au lieu de « bus », et les WAV Oolel correspondants sont installés
dans `data/tts_cache_oolel/` (`dakar_dem_dikk_311/319/327.wav`,
`dakar_dem_dikk_taf_taf_ouakam_to1.wav`) : c'est cette voix qui passe en
premier. Les WAV de `data/tts_cache_ajouts/` sont le secours ; ils ne sont pas
suivis par Git (`??` dans `git status`) mais partent sur le Space avec le
dossier.

**Express AIBD : aucune voix** (ni Oolel, ni ajouts, ni plan).

Remarque : « TAF TAF Wakaam » ne se distingue de « TAF TAF » que par le mot
« Wakaam », alors que les deux partent de Ouakam. À l'oreille, l'usager peut
confondre la navette Palais 2 et celle de l'AIBD.

## Ligne par ligne

### 311 — Lac Rose ↔ Keur Massar (banlieue)

- **Titre officiel** : « LAC ROSE CROISSEMENT KEUR MASSAR ».
- **Liste connue** (confirmé, demdikk.sn/reseau-urbain-dakar) : Lac rose
  croissement Niague · Croissement Tivaoune Peulh · Terminus keur Massar ·
  Station Keur Massar · Croissement Keur Massar · Retour vers Lac Rose.
- **Positions** : 4 ancres (Tivaoune Peulh OSM, 3 ancres Tata Keur Massar),
  les deux bouts Lac Rose **inconnus**. « Croissement Tivaoune Peulh » et
  « Croissement Keur Massar » ont exactement les mêmes coordonnées
  (14.786355, -17.294528) : l'une des deux est fausse.
- **Pourquoi l'app ne la propose pas** : elle est chargée, mais ses arrêts
  propres ne deviennent pas des lieux. « Croissement » est écarté comme faute
  de frappe (`raison_ecart`, `itineraires_app.py`), « Retour vers Lac Rose »
  comme indication de trajet (règle « vers »), et Lac Rose n'a pas de
  position. Il ne reste que ses arrêts de Keur Massar, déjà servis par
  d'autres lignes.
- **Terminus affichés incohérents** : « Lac rose croissement Niague / Retour
  vers Lac Rose » (premier et dernier point de la liste). La liste décrit une
  boucle Lac Rose → Keur Massar → retour Lac Rose, pas deux terminus.
- **Manque** : le vrai terminus côté Lac Rose (Niague ? village du Lac ?), une
  position sûre pour Lac Rose, le sens de circulation (boucle ou aller-retour),
  une 2ᵉ source.

### 319 — Liberté 6 ↔ Ouakam (urbain)

- **Liste connue** (confirmé, 17 points) : Terminus liberté 6 · Rond Point
  Liberté 6 · Deux voies liberté 6 · Rond point JVC · Boulangerie Jaune ·
  Immeuble Mariama · Rond point Cheikh Bethio · Ancien Piste · IHO · Entrée
  ouakam · Pharmacie cité Aviaon · Pharmacie Mame Seynabou · Case des tous
  petit · Station shell · Lycée d'excellence privée · Boulangerie N'wely ·
  Terminus Ouakam.
- **Positions** : 18 % mesurées. Les 9 arrêts entre Ancien Piste et Ouakam
  sont interpolés en ligne droite.
- **État dans l'app** : servie (Liberté 6 → Ouakam, IHO → Liberté 6…).
- **Manque** : positions réelles des arrêts de Ouakam (IHO, Cité Avion,
  Mame Seynabou…), un test dans `tests/test_trajets.py`, une 2ᵉ source.
  `sources_inventaire.md` disait n'avoir que le « début de la 319 » : la liste
  complète est arrivée depuis (12/11).

### 327 — Keur Massar ↔ Parcelles Assainies (banlieue)

- **Liste connue** (confirmé, 11 points) : Terminus Keur Massar · Tolou
  Abdoulaye Wade · Croissement Tivaoune Peulh · APIX · Malika plage · Malibu ·
  Hôpital Dalal Diam · Case bi · Croisement 22 · Eglise PA · Terminus
  Parcelles.
- **Positions** : 55 % mesurées. « APIX » (Nominatim) a les mêmes
  coordonnées que « Croissement Tivaoune Peulh » (14.798860, -17.287006).
  « Croissement Tivaoune Peulh » n'a pas la même position ici que dans la 311.
- **État dans l'app** : servie (Keur Massar → Parcelles, Malibu → Keur
  Massar…).
- **Manque** : position sûre d'APIX et de Tivaouane Peulh, un test, une 2ᵉ
  source.

### TAF TAF OUAKAM (TO1) — Ouakam ↔ Palais 2 (urbain)

- **Titre officiel** : « OUAKAM PALAIS 2 ».
- **Liste connue** (confirmé, 10 points) : Terminus Ouakam · Brioche d'orée
  Ouakam · Monument de la Renaissance · Corniche ouest · Avenue Peytavin ·
  Avenue Pompidou · Place de l'Indépendance · Avenue Léopold Sédar Senghor ·
  Avenue Nelson Mandela · Palais 2.
- **Positions** : 30 % mesurées. « Corniche ouest » est géocodée au Palais de
  Justice (14.670, -17.444, Cap Manuel), à ~8 km à vol d'oiseau du Monument : le tronçon intermédiaire
  n'existe pas dans nos données. « Monument de la Renaissance » vient d'un
  résultat Nominatim au libellé douteux (« cambre avec balcon »).
- **État dans l'app** : servie (Ouakam → Palais 2, Monument, Corniche Ouest)
  et testée côté voix.
- **Manque** : le parcours réel sur la Corniche (arrêts entre le Monument et
  le Plateau), des positions sûres, une 2ᵉ source.
  `comparaison_lignes_officielles.csv` précise que TO1 et la variante Sphère
  Ministérielle ne correspondent pas à notre TAF TAF (Ouakam → AIBD).

### Express AIBD — HLM Grand-Yoff ↔ AIBD

- **Terminus connus** (confirmé, demdikk.sn/offres-de-transport) : terminus
  HLM Grand-Yoff, en face du stade Léopold Sédar Senghor → Aéroport
  International Blaise Diagne. Via l'autoroute à péage. 6 000 FCFA, 24 h/24
  (`sources_inventaire.md`).
- **Liste d'arrêts** : aucune. Les 3 « points » de la référence sont deux
  terminus et une route (« autoroute à péage »), pas des arrêts.
- **Pourquoi l'app ne la propose pas** : absente de `lignes_dakar.csv`, de
  `itineraires_dakar.csv` **et** de `corrections_geo_ddd_proposees.csv` ;
  `ddd_itineraires_officiels.csv` ne l'a pas (elle n'est pas sur la page
  réseau urbain). Aucune voix. Aujourd'hui « Grand Yoff → AIBD » répond TAF
  TAF.
- **Manque** : savoir s'il y a des arrêts intermédiaires (probablement aucun :
  service express), une position sûre pour « HLM Grand-Yoff face stade LSS »,
  une voix, et une décision : l'ajouter comme ligne à 2 arrêts, ou seulement la
  mentionner dans la carte AIBD.

## Résumé

| Ligne | Ce qu'on a | Source | Ce qui manque |
| --- | --- | --- | --- |
| 311 | Liste de 6 points ; chargée en mémoire mais quasi jamais proposée ; voix Oolel + Adia | demdikk.sn/reseau-urbain-dakar (confirmé, 12/11/2026) | Vrai terminus Lac Rose et sa position ; sens (boucle) ; terminus affichés à corriger ; arrêts « Croissement… » non reconnus comme lieux ; position en double avec Croissement Keur Massar ; test |
| 319 | Liste complète de 17 points ; **servie** ; voix Oolel + Adia | demdikk.sn/reseau-urbain-dakar (confirmé, 12/11/2026) | Positions réelles côté Ouakam (9 arrêts interpolés) ; test ; 2ᵉ source |
| 327 | Liste complète de 11 points ; **servie** ; voix Oolel + Adia | demdikk.sn/reseau-urbain-dakar (confirmé, 12/11/2026) | Positions APIX / Tivaouane Peulh (identiques) ; test ; 2ᵉ source |
| TO1 | Liste de 10 points ; **servie** ; voix « TAF TAF Wakaam » ; test voix | demdikk.sn/reseau-urbain-dakar (confirmé, 12/11/2026) | Arrêts de la Corniche entre Monument et Plateau ; positions sûres ; voix moins proche de « TAF TAF » ; test de trajet |
| Express AIBD | 2 terminus + « autoroute à péage », prix, horaires | demdikk.sn/offres-de-transport (confirmé, 12/11/2026) | Absente de tous les fichiers chargés ; pas de liste d'arrêts ; pas de position pour HLM Grand-Yoff (face stade LSS) ; pas de voix ; décision d'intégration |

À vérifier en ligne après le prochain déploiement : que le Space propose bien
319, 327 et TO1 comme en local.
