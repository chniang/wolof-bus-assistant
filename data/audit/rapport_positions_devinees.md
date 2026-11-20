# Positions d'arrêts devinées (lot F4)

20/11/2026. Aucun réseau : ni Nominatim, ni téléchargement ; les caches
`data/sources/cache_nominatim.json` et `cache_lieux_nominatim.json` sont lus
seulement (empreintes identiques avant et après). Aucun CSV existant modifié.

## Méthode

`scripts/inventaire_positions_devinees.py` lit le réseau tel que le moteur v2
le construit en mémoire et écrit :

- `data/audit/positions_devinees.csv` : **999 positions** arrêt × ligne
  non mesurées (état avant le lot F4) :
  913 « non mesurée » (interpolée à vue ou le long de la trace AFTU, géocodée,
  position générale estimée), 6 « sans position »,
  80 « mesurée mais loin de ses voisins mesurés » (à plus de 3 km
  des deux : homonyme probable) ;
- `data/audit/positions_candidates.csv` : pour ces arrêts, une position
  fiable trouvée ailleurs dans le dépôt, et pourquoi elle est retenue ou non ;
- avec `--ecrire` : `data/corrections/positions_corrigees.csv`.

Sources admises : un arrêt OSM nommé (`data/sources/osm_bus_dakar/arrets_osm.csv`,
tous les nœuds du nom dans 300 m), ou un arrêt identique « bonne »
d'`arrets_geo.csv` que `geo.py` ne juge pas douteux. Jamais un géocodage.
`data/reference/` n'a aucune coordonnée, et les fiches AFTU n'ont que les
terminus (déjà utilisés).

Une candidate est retenue si elle est cohérente sur **chaque** ligne qui porte
le nom : entre les deux voisins mesurés, le détour ne dépasse pas 1,5 fois la
distance directe + 1 km. Elle est écartée si le nom est une zone (quartier ou
commune de `lieux_geo.csv` : Médina, Rufisque, Maristes…) ou une voie (Route,
Avenue, Rocade, Allées… : une position « bonne » n'y est qu'un point de la voie).

## Positions corrigées et rétrogradées

| Arrêt | Avant | Après | Source |
| --- | --- | --- | --- |
| AIBD | 14.745133, -17.468034 (« bonne », à Grand Yoff, arrets_geo.csv et lieux_geo.csv) | 14.670000, -17.073300 (sûre) | repere_connu : Aéroport International Blaise Diagne (Diass), repère du TAF TAF |
| Croisement 22 | 14.751739, -17.446301 (interpolation_sur_trace, non mesurée) | 14.753688, -17.433658 (sûre) | osm_arret_nomme : arrets_osm.csv (même nom) |
| Croisement Gadaye | 14.786474, -17.368853 (arrets_geo, mesurée mais loin de ses voisins mesurés) | 14.786474, -17.368853 (sûre) | arret_identique_bonne : arrets_geo.csv « Croisement Gadaye » |
| Croisement Grand Mbao | 14.730658, -17.302734 (interpolation_sur_trace, non mesurée) | 14.731241, -17.316679 (sûre) | arret_identique_bonne : arrets_geo.csv « Croisement Grand Mbao » |
| Croisement Tivaouane Peulh | 14.786455, -17.296853 (interpolation_sur_trace, non mesurée) | 14.786355, -17.294528 (sûre) | osm_arret_nomme : arrets_osm.csv « Croisement tivavouane Peulh » (lien revu) |
| Croissement Tivaoune Peulh | 14.798860, -17.287006 (ancre_tata, mesurée mais loin de ses voisins mesurés) | 14.786355, -17.294528 (sûre) | osm_arret_nomme : arrets_osm.csv « Croisement tivavouane Peulh » (lien revu) |
| Gare de Dakar | 14.675604, -17.433252 (nominatim, non mesurée) | 14.676464, -17.433683 (sûre) | arret_identique_bonne : arrets_geo.csv « Gare de Dakar » |
| Giratoire Liberté VI | 14.729218, -17.459404 (arrets_geo, mesurée mais loin de ses voisins mesurés) | 14.729218, -17.459404 (sûre) | arret_identique_bonne : arrets_geo.csv « Giratoire Liberté VI » |
| Rond Point Colobane | 14.697751, -17.443939 (nominatim, non mesurée) | 14.697751, -17.443939 (sûre) | arret_identique_bonne : arrets_geo.csv « Rond-Point Colobane » |
| Rond Point Liberté 6 | 14.728551, -17.456967 (nominatim, non mesurée) | 14.728629, -17.457233 (sûre) | arret_identique_bonne : arrets_geo.csv « Rond-Point Liberté 6 » |
| Rond Point liberté 6 | 14.728838, -17.457082 (nominatim, non mesurée) | 14.728629, -17.457233 (sûre) | arret_identique_bonne : arrets_geo.csv « Rond-Point Liberté 6 » |
| Rond point JVC | 14.738917, -17.458362 (interpolation_sur_trace_osm, non mesurée) | 14.722283, -17.463934 (sûre) | osm_arret_nomme : arrets_osm.csv « Arret JVC » (lien revu) |
| Rond point Liberté 6 | 14.728551, -17.456967 (nominatim, non mesurée) | 14.728629, -17.457233 (sûre) | arret_identique_bonne : arrets_geo.csv « Rond-Point Liberté 6 » |
| Sortie Pikine | 14.747739, -17.397461 (interpolation_sur_trace, non mesurée) | 14.766579, -17.397455 (sûre) | arret_identique_bonne : arrets_geo.csv « Sortie Pikine » |
| Apix | 14.798860, -17.287006 (nominatim, confiance bonne) | même position, **estimée** | data/corrections/positions_estimees.csv |
| Av Cheikh Anta Diop | 14.690177, -17.458503 (interpolation_sur_trace, confiance bonne) | même position, **estimée** | data/corrections/positions_estimees.csv |
| Avenue Cheikh Anta Diop | 14.686829, -17.455859 (nominatim, confiance bonne) | même position, **estimée** | data/corrections/positions_estimees.csv |
| Avenue Cheikh Anta Diop (Hôpital Fann) | 14.691628, -17.459839 (interpolation, confiance estimee) | même position, **estimée** | data/corrections/positions_estimees.csv |
| Avenue Cheikh Antadiop | 14.689806, -17.457825 (arrets_geo, confiance estimee) | même position, **estimée** | data/corrections/positions_estimees.csv |

`positions_corrigees.csv` est chargé par le moteur v2 (`routing/data.py`,
`_appliquer_positions_revues`) et par `matching/geo.py` : la position vaut
pour chaque ligne qui porte le nom, et elle devient sûre.
`positions_estimees.csv` garde la position mais ne la croit plus nulle part.

Liens revus à la main : « Rond point JVC » = arrêt OSM « Arret JVC » ;
« Croisement Tivaouane Peulh » = arrêt OSM « Croisement tivavouane Peulh ».
Pour « Croissement Tivaoune Peulh » (DDD 227 et 327), le contrôle de
cohérence échoue parce que la 327 fait un vrai aller-retour Keur Massar →
Tivaouane Peulh → Malika. La Dem Dikk 311 place déjà ce même nom à l'arrêt OSM,
donc le lien est gardé (raison écrite dans le script).

## Cas demandés

- **AIBD** : la position « bonne » d'`arrets_geo.csv` et de `lieux_geo.csv`
  (Grand Yoff) est remplacée par le repère de Diass (14.67, -17.0733), déjà
  utilisé par le TAF TAF. Le point du lieu « AIBD » / « aéroport Blaise
  Diagne » suit (geo.py).
- **APIX / Tivaouane Peulh (327, même point)** : le croisement passe à l'arrêt
  OSM (14.786355, -17.294528), 1,6 km au sud de l'ancien point. APIX garde son
  géocodage (« Croisement Apix ») mais il est **estimé** : aucune source fiable
  dans le dépôt. Sa position « bonne » d'`arrets_geo.csv` est l'agence APIX du
  Plateau, un homonyme. À relever sur place.
- **Avenue Cheikh Anta Diop** (et « Av Cheikh Anta Diop », « Avenue Cheikh
  Antadiop », « (Hôpital Fann) ») : voie de 5 km de Fann à Ouakam. La position
  « bonne » est au bout de Ouakam alors que les DDD 18, 20, 23 et les Tata 4,
  24, 25, 29 la prennent côté Fann. **Estimée** : jamais un arrêt conseillé.
- **Maristes** : nom de quartier, pas situé par son nom. Tata 40 « Maristes »
  est interpolée à 69 m de la position « bonne » ; Tata 37 « Maristes (Par
  Station Titan) » est interpolée le long de la trace, 2,8 km plus à l'est
  (Station Titan). Positions inchangées, mais la carte **nomme** désormais
  l'arrêt quand l'usager dit « Maristes » (voir plus bas).
- **Péage** (« Péage », « PEAGE Pikine », « Autoroute à Péage »…) : un nom
  par ligne pour des endroits différents, douteux dans `arrets_geo.csv`. Rien de
  fiable : **estimées**, inchangées.
- **RN1** (« Route Nationale 1 / N°1 / N° 1 ») : voie de 30 km, introuvable ou
  estimée. **Estimées**, inchangées ; jamais un arrêt conseillé.
- **Dem Dikk 319, 9 arrêts côté Ouakam** (IHO → Boulangerie N'wely) :
  interpolés en ligne droite entre Ancien Piste et Terminus Ouakam. Aucun
  arrêt OSM ni « bonne » de ces noms. **Estimés**, inchangés. « Rond point
  JVC » (début de la 319) est, lui, corrigé par l'arrêt OSM.
- **Tata 3, 4, 30, 37, 57, 62, 64, 74** : surtout des interpolations le long de
  la trace officielle (route réelle, position du point approximative). Corrigés
  par une source fiable : Giratoire Liberté VI (Tata 30), Croisement Gadaye
  (Tata 37). Le reste est estimé. À revoir : « Cité COCEHAS » (Tata 74) est au
  même point que « Tivaouane Peulh » (Tata 69) ; « 30 & 42 » (Tata 37) est à
  10 km de ses voisins (note de fiche plus qu'un arrêt).

## Effet dans l'app

1. **Arrêt conseillé** (`routing/adapter.py`, `_vague`) : une étape ne
   montre « arrêt conseillé : X » que si X a une position **mesurée** (sur sa
   ligne, ou « bonne » générale) à 600 m au plus du lieu dit. Sinon : « cherche
   l'arrêt de la ligne N le plus proche ». Avant, une position interpolée ou
   géocodée suffisait.
2. **Cas inverse** : un arrêt que l'usager a demandé par son nom est toujours
   nommé, même sans position mesurée. Le nom compte (à l'orthographe près),
   le nom sans parenthèse aussi, ou le repère entre parenthèses : « Maristes »
   → « Maristes (Par Station Titan) », « Sapeurs Pompiers » → « Dieuppeul
   (Sapeurs Pompiers) », « Fass Mbao » → « Fassmbao ». Ni un lien de lieu
   (« UCAD » ne fait pas nommer l'Avenue Cheikh Anta Diop), ni un nom qui
   contient seulement le lieu (« Pikine » ne fait pas nommer « Pikine Texaco »).
3. **Durée** (`duree_devinee`) : sur une ligne sans trace officielle, une
   montée ou une descente sans position mesurée ne donne une durée que si un
   voisin mesuré est à 1 km au plus (erreur sous ~3 min), ou si sa position est
   posée le long d'une trace AFTU ou OSM, donc sur la route réelle
   (« Yoff Village » sur la DDD 8). Sinon « durée inconnue ». Deux arrêts mesurés séparés par 15 km de ligne droite (Express
   AIBD) restent aussi sans durée : la route n'est pas connue.

Sur les 308 trajets de `data/audit/audit_itineraires.csv` et les 5 trajets
démo, comparés avant/après (hors ligne) :
- 32 cartes passent de « cherche l'arrêt » à un arrêt nommé, et 5 font
  l'inverse (arrêt à position devinée : Gare Ter, Colobane sur la DDD 11, Gare
  des Parcelles Assainies, Parcelles Église) ;
- 28 durées deviennent « durée inconnue » ;
- 8 trajets changent de lignes, à cause des positions corrigées. Par exemple,
  « Stade Dembadiop → Tivaouane Peulh » perd la correspondance DDD 23 + Tata 80
  et propose deux changements (8 ou 23, 11, puis 80 ou 81) ; « Sapeurs Pompiers
  → Castors » gagne deux correspondances.
- Trajets démo : mêmes lignes. Ouakam → Petersen (Tata 3), Médina → Guédiawaye
  (Tata 12, 46, DDD 2), Guédiawaye → Maristes (Tata 37, arrêt désormais nommé),
  Malika → Pikine (DDD 16B, sans durée maintenant ; Tata 80 ; Tata 50),
  Sapeur Pompiers → Sandaga (DDD 1).

## Inventaire prioritaire (état avant F4)

Distance : jusqu'au voisin mesuré le plus proche sur la même ligne (vol
d'oiseau). La liste complète est dans `data/audit/positions_devinees.csv`.

| Arrêt | Ligne | Position actuelle | Origine | Voisin mesuré (m) | Motif | Après F4 |
| --- | --- | --- | --- | --- | --- | --- |
| AIBD | DDD Express AIBD | 14.670000, -17.073300 | arrets_geo | 41904 | non mesurée | **corrigée** : 14.670000, -17.073300 |
| Autoroute a Peage | DDD 11 | 14.727372, -17.410224 | interpolation | 4013 | non mesurée | estimée (inchangée) |
| Avenue Cheikh Anta Diop (Hôpital Fann) | DDD 12 | 14.691628, -17.459839 | interpolation | 1033 | non mesurée | **estimée** (rétrogradée) |
| Avenue Cheikh Anta Diop | DDD 18 | 14.686829, -17.455859 | nominatim | 466 | non mesurée | **estimée** (rétrogradée) |
| PEAGE Pikine | DDD 2 | 14.735346, -17.416961 | interpolation | 3165 | non mesurée | estimée (inchangée) |
| Avenue Cheikh Anta Diop | DDD 20 | 14.698974, -17.468697 | nominatim | 422 | non mesurée | **estimée** (rétrogradée) |
| péage | DDD 213 | 14.745252, -17.401217 | interpolation | 2467 | non mesurée | estimée (inchangée) |
| Croissement Tivaoune Peulh | DDD 227 | 14.798860, -17.287006 | ancre_tata | 3190 | mesurée mais loin de ses voisins mesurés | **corrigée** : 14.786355, -17.294528 |
| Apix | DDD 227 | 14.798860, -17.287006 | nominatim | 0 | non mesurée | **estimée** (rétrogradée) |
| Avenue Cheikh Anta Diop | DDD 23 | 14.698974, -17.468697 | nominatim | 422 | non mesurée | **estimée** (rétrogradée) |
| Hann Maristes | DDD 232 | 14.724564, -17.439165 | nominatim | 2017 | non mesurée | estimée (inchangée) |
| Péage | DDD 234 | 14.731237, -17.388190 | interpolation | 1960 | non mesurée | estimée (inchangée) |
| IHO | DDD 319 | 14.713789, -17.477780 | interpolation | 181 | non mesurée | estimée (inchangée) |
| Entrée ouakam | DDD 319 | 14.715158, -17.478691 | interpolation | 362 | non mesurée | estimée (inchangée) |
| Pharmacie cité Aviaon | DDD 319 | 14.716526, -17.479601 | interpolation | 543 | non mesurée | estimée (inchangée) |
| Pharmacie Mame Seynabou | DDD 319 | 14.717895, -17.480512 | interpolation | 724 | non mesurée | estimée (inchangée) |
| Case des tous petit | DDD 319 | 14.719263, -17.481423 | interpolation | 724 | non mesurée | estimée (inchangée) |
| Station shell | DDD 319 | 14.720632, -17.482334 | interpolation | 543 | non mesurée | estimée (inchangée) |
| Lycée d’excellence privée | DDD 319 | 14.722000, -17.483244 | interpolation | 362 | non mesurée | estimée (inchangée) |
| Boulangerie N’wely | DDD 319 | 14.723369, -17.484155 | interpolation | 181 | non mesurée | estimée (inchangée) |
| Croissement Tivaoune Peulh | DDD 327 | 14.798860, -17.287006 | ancre_tata | 3190 | mesurée mais loin de ses voisins mesurés | **corrigée** : 14.786355, -17.294528 |
| Apix | DDD 327 | 14.798860, -17.287006 | nominatim | 0 | non mesurée | **estimée** (rétrogradée) |
| Autoroute à Péage | DDD TAF TAF | 14.734376, -17.248786 | nominatim | 5807 | non mesurée | estimée (inchangée) |
| AIBD | DDD TAF TAF | 14.670000, -17.073300 | repere_connu | 14379 | non mesurée | **corrigée** : 14.670000, -17.073300 |
| Avenue Cheikh Anta Diop | Tata 24 | 14.697701, -17.467592 | interpolation_sur_trace | 773 | non mesurée | **estimée** (rétrogradée) |
| Avenue Cheikh Anta Diop | Tata 25 | 14.691162, -17.459754 | interpolation_sur_trace | 1580 | non mesurée | **estimée** (rétrogradée) |
| Route Nationale 1 | Tata 27 | 14.745969, -17.418868 | interpolation_sur_trace | 2375 | non mesurée | estimée (inchangée) |
| Avenue Cheikh Anta Diop | Tata 29 | 14.688691, -17.457463 | interpolation_sur_trace | 1211 | non mesurée | **estimée** (rétrogradée) |
| Autoroute Seydinalimamoulaye | Tata 3 | 14.749572, -17.491623 | interpolation_sur_trace | 1877 | non mesurée | estimée (inchangée) |
| Aéroport L S Senghor | Tata 3 | 14.751779, -17.501025 | interpolation_sur_trace | 1423 | non mesurée | estimée (inchangée) |
| Route de Ngor | Tata 3 | 14.746406, -17.513040 | arrets_geo | 4152 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Village de Ngor | Tata 3 | 14.749863, -17.491790 | interpolation_sur_trace | 1850 | non mesurée | estimée (inchangée) |
| Route de l'Aéroport | Tata 3 | 14.755450, -17.475580 | arrets_geo | 4057 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Les Mamelles (Monument Renaissance) | Tata 3 | 14.753853, -17.494308 | interpolation_sur_trace | 2022 | non mesurée | estimée (inchangée) |
| Cité ASECNA | Tata 3 | 14.723393, -17.493597 | projection_sur_trace | 3673 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Village de Ouakam | Tata 3 | 14.718729, -17.488725 | interpolation_sur_trace | 737 | non mesurée | estimée (inchangée) |
| Route de Ouakam | Tata 3 | 14.699775, -17.469718 | arrets_geo | 3015 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Avenue Cheikh Antadiop | Tata 3 | 14.689806, -17.457825 | arrets_geo | 1328 | non mesurée | **estimée** (rétrogradée) |
| Avenue Emile Badiane | Tata 3 | 14.677649, -17.447091 | arrets_geo | 451 | non mesurée | estimée (inchangée) |
| Rue Cheikh Wade | Tata 30 | 14.777185, -17.387965 | arrets_geo | 671 | non mesurée | estimée (inchangée) |
| Sam Notaire | Tata 30 | 14.776618, -17.378389 | interpolation_sur_trace | 544 | non mesurée | estimée (inchangée) |
| Route des Niayes | Tata 30 | 14.753102, -17.434399 | arrets_geo | 3779 | non mesurée | estimée (inchangée) |
| Rond-Point de Cambérène (Casebi) | Tata 30 | 14.749518, -17.442701 | interpolation_sur_trace | 2885 | non mesurée | estimée (inchangée) |
| Route des Niayes Prolongée (Police des P Assainies) | Tata 30 | 14.743304, -17.448959 | interpolation_sur_trace | 1927 | non mesurée | estimée (inchangée) |
| Avenue Hyacinthe Thiandoum | Tata 30 | 14.737058, -17.455237 | interpolation_sur_trace | 980 | non mesurée | estimée (inchangée) |
| Giratoire Liberté VI | Tata 30 | 14.729218, -17.459404 | arrets_geo | 3287 | mesurée mais loin de ses voisins mesurés | **corrigée** : 14.729218, -17.459404 |
| Allées Ababacar Sy (Dieuppeul/derklé) | Tata 30 | 14.722127, -17.457917 | interpolation_sur_trace | 805 | non mesurée | estimée (inchangée) |
| Allées Cheikh Sidaty Aïdara (Niaritalli) | Tata 30 | 14.713983, -17.455126 | interpolation_sur_trace | 1574 | non mesurée | estimée (inchangée) |
| Rue El Hadj Amadou Malick Gaye (Bopp) | Tata 30 | 14.705878, -17.452389 | interpolation_sur_trace | 708 | non mesurée | estimée (inchangée) |
| Route Nationale | Tata 35 | 14.744991, -17.454385 | interpolation_sur_trace | 1375 | non mesurée | estimée (inchangée) |
| Cité SOTRAC | Tata 37 | 14.786238, -17.298844 | interpolation_sur_trace | 1770 | non mesurée | estimée (inchangée) |
| Ecobank | Tata 37 | 14.783067, -17.323368 | interpolation_sur_trace | 34 | non mesurée | estimée (inchangée) |
| Malika Montagne | Tata 37 | 14.793758, -17.335899 | interpolation_sur_trace | 1781 | non mesurée | estimée (inchangée) |
| Malika Terminus | Tata 37 | 14.804395, -17.343542 | interpolation_sur_trace | 3202 | non mesurée | estimée (inchangée) |
| VDN | Tata 37 | 14.797438, -17.360658 | interpolation_sur_trace | 1504 | non mesurée | estimée (inchangée) |
| Croisement Gadaye | Tata 37 | 14.786474, -17.368853 | arrets_geo | 4874 | mesurée mais loin de ses voisins mesurés | **corrigée** : 14.786474, -17.368853 |
| 49 | Tata 37 | 14.740522, -17.408624 | interpolation_sur_trace | 6663 | non mesurée | estimée (inchangée) |
| 30 & 42 | Tata 37 | 14.693425, -17.447938 | arrets_geo | 10788 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Monument Serigne Saliou | Tata 37 | 14.710171, -17.441542 | interpolation_sur_trace | 1985 | non mesurée | estimée (inchangée) |
| Police Wakhinane | Tata 37 | 14.726774, -17.437074 | interpolation_sur_trace | 3888 | non mesurée | estimée (inchangée) |
| Hamo VI | Tata 37 | 14.738093, -17.423089 | interpolation_sur_trace | 5284 | non mesurée | estimée (inchangée) |
| Rond-Point Dial Mbaay | Tata 37 | 14.740431, -17.407113 | interpolation_sur_trace | 3987 | non mesurée | estimée (inchangée) |
| Allées Cherif Macky Sall | Tata 37 | 14.759417, -17.401953 | interpolation_sur_trace | 2009 | non mesurée | estimée (inchangée) |
| Croisement Cambérène | Tata 37 | 14.748801, -17.408851 | interpolation_sur_trace | 272 | non mesurée | estimée (inchangée) |
| Maristes (Par Station Titan) | Tata 37 | 14.738774, -17.407196 | interpolation_sur_trace | 1376 | non mesurée | estimée (inchangée) |
| Pharmicie Abdourahmane | Tata 37 | 14.733884, -17.418962 | interpolation_sur_trace | 792 | non mesurée | estimée (inchangée) |
| Keur Ngoor (Rond-Point École Mariste) | Tata 37 | 14.729976, -17.435736 | interpolation_sur_trace | 1172 | non mesurée | estimée (inchangée) |
| Pont Hann | Tata 37 | 14.721510, -17.440772 | interpolation_sur_trace | 2176 | non mesurée | estimée (inchangée) |
| Autoroute | Tata 37 | 14.706270, -17.441832 | interpolation_sur_trace | 1299 | non mesurée | estimée (inchangée) |
| Rond-Point Fann | Tata 37 | 14.680555, -17.460497 | interpolation_sur_trace | 280 | non mesurée | estimée (inchangée) |
| Autoroute Seydina Limamoulaye | Tata 4 | 14.740423, -17.471539 | interpolation_sur_trace | 1600 | non mesurée | estimée (inchangée) |
| Echangeur de la Foire | Tata 4 | 14.727218, -17.472135 | interpolation_sur_trace | 3061 | non mesurée | estimée (inchangée) |
| Voie de Dégagement Nord (VDN) | Tata 4 | 14.713647, -17.471890 | interpolation_sur_trace | 4360 | non mesurée | estimée (inchangée) |
| Carrefour Seydou N Tall | Tata 4 | 14.700302, -17.468792 | interpolation_sur_trace | 2986 | non mesurée | estimée (inchangée) |
| Avenue Cheikh Anta Diop | Tata 4 | 14.690640, -17.459148 | interpolation_sur_trace | 1493 | non mesurée | **estimée** (rétrogradée) |
| Avenue Emile Badiane | Tata 4 | 14.677649, -17.447091 | arrets_geo | 451 | non mesurée | estimée (inchangée) |
| Route Nationale 1 | Tata 40 | 14.746953, -17.321682 | interpolation_sur_trace | 1828 | non mesurée | estimée (inchangée) |
| Maristes | Tata 40 | 14.726629, -17.429036 | interpolation_sur_trace | 69 | non mesurée | estimée (inchangée) |
| Route Nationale 1 | Tata 44 | 14.743074, -17.314367 | interpolation_sur_trace | 1339 | non mesurée | estimée (inchangée) |
| Route Nationale | Tata 46 | 14.745719, -17.420690 | interpolation_sur_trace | 1174 | non mesurée | estimée (inchangée) |
| Avenue Cheikh Antadiop | Tata 46 | 14.689806, -17.457825 | arrets_geo | 1328 | non mesurée | **estimée** (rétrogradée) |
| Av Cheikh Anta Diop | Tata 47 | 14.690177, -17.458503 | interpolation_sur_trace | 1563 | non mesurée | **estimée** (rétrogradée) |
| Route Nationale 1 | Tata 48 | 14.747100, -17.359752 | interpolation_sur_trace | 3409 | non mesurée | estimée (inchangée) |
| Croisement Tivaouane Peulh | Tata 53 | 14.786455, -17.296853 | interpolation_sur_trace | 1300 | non mesurée | **corrigée** : 14.786355, -17.294528 |
| Route Nationale N° 1 | Tata 54 | 14.746692, -17.362582 | interpolation_sur_trace | 1690 | non mesurée | estimée (inchangée) |
| Route Nationale N° 1 | Tata 55 | 14.743771, -17.315012 | interpolation_sur_trace | 5385 | non mesurée | estimée (inchangée) |
| Av Hyacinthe Thiandoum | Tata 57 | 14.732656, -17.455023 | arrets_geo | 507 | non mesurée | estimée (inchangée) |
| Pont de l'Émergence | Tata 57 | 14.743032, -17.449582 | arrets_geo | 787 | non mesurée | estimée (inchangée) |
| Croisement Cambérène | Tata 57 | 14.744520, -17.427124 | interpolation_sur_trace | 2819 | non mesurée | estimée (inchangée) |
| Croisement Keur Massar | Tata 57 | 14.748812, -17.346675 | interpolation_sur_trace | 3373 | non mesurée | estimée (inchangée) |
| Keur Mbaye Fall | Tata 57 | 14.745044, -17.315549 | arrets_geo | 6747 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Route Nationale N°1 | Tata 57 | 14.745847, -17.389610 | arrets_geo | 7964 | non mesurée | estimée (inchangée) |
| Bd Maurice Gueye | Tata 57 | 14.747330, -17.357846 | interpolation_sur_trace | 4555 | non mesurée | estimée (inchangée) |
| Poste Courant | Tata 57 | 14.748058, -17.326530 | interpolation_sur_trace | 1227 | non mesurée | estimée (inchangée) |
| Marché Colobane Rufisque | Tata 57 | 14.730435, -17.302013 | interpolation_sur_trace | 2181 | non mesurée | estimée (inchangée) |
| Rufisque Gouye Mouride | Tata 57 | 14.716417, -17.273844 | arrets_geo | 5500 | non mesurée | estimée (inchangée) |
| Route Nationale 1 | Tata 58 | 14.725666, -17.444900 | interpolation_sur_trace | 10331 | non mesurée | estimée (inchangée) |
| Péage | Tata 58 | 14.745942, -17.410601 | interpolation_sur_trace | 3475 | non mesurée | estimée (inchangée) |
| Route Nationale 1 | Tata 60 | 14.746642, -17.405090 | interpolation_sur_trace | 5862 | non mesurée | estimée (inchangée) |
| Route Nationale 1 | Tata 61 | 14.752124, -17.324604 | interpolation_sur_trace | 1862 | non mesurée | estimée (inchangée) |
| Arafat | Tata 62 | 14.726437, -17.265962 | interpolation_sur_trace | 214 | non mesurée | estimée (inchangée) |
| Marché Mardi | Tata 62 | 14.725265, -17.267439 | interpolation_sur_trace | 380 | non mesurée | estimée (inchangée) |
| Poste Courant | Tata 62 | 14.723872, -17.268674 | interpolation_sur_trace | 330 | non mesurée | estimée (inchangée) |
| SONADIS | Tata 62 | 14.722849, -17.270006 | interpolation_sur_trace | 289 | non mesurée | estimée (inchangée) |
| HLM Rufisque | Tata 62 | 14.729985, -17.301226 | interpolation_sur_trace | 2673 | non mesurée | estimée (inchangée) |
| Dioutyba | Tata 62 | 14.747056, -17.322057 | interpolation_sur_trace | 5484 | non mesurée | estimée (inchangée) |
| Route Nationale 1 | Tata 62 | 14.748423, -17.349619 | interpolation_sur_trace | 3094 | non mesurée | estimée (inchangée) |
| Poste Thiaroye | Tata 62 | 14.746040, -17.378287 | arrets_geo | 7481 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Autoroute A Péage | Tata 62 | 14.745842, -17.414438 | interpolation_sur_trace | 3887 | non mesurée | estimée (inchangée) |
| Fass | Tata 62 | 14.695591, -17.453011 | interpolation_sur_trace | 682 | non mesurée | estimée (inchangée) |
| Diamniadio | Tata 64 | 14.720219, -17.184244 | arrets_geo | 5629 | non mesurée | estimée (inchangée) |
| Boulevard Maurice Gueye | Tata 64 | 14.717783, -17.277465 | interpolation_sur_trace | 2606 | non mesurée | estimée (inchangée) |
| Rond-Point Dioutyba | Tata 64 | 14.728670, -17.298761 | interpolation_sur_trace | 2564 | non mesurée | estimée (inchangée) |
| Keur Mbaye Fall | Tata 64 | 14.745044, -17.315549 | arrets_geo | 6747 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Croisement Keur Massar | Tata 64 | 14.748827, -17.346574 | interpolation_sur_trace | 3363 | non mesurée | estimée (inchangée) |
| Tally Boumack | Tata 64 | 14.752613, -17.399679 | interpolation_sur_trace | 785 | non mesurée | estimée (inchangée) |
| Route des Niayes | Tata 64 | 14.761445, -17.392981 | interpolation_sur_trace | 796 | non mesurée | estimée (inchangée) |
| Croisement PAI | Tata 64 | 14.770743, -17.398402 | interpolation_sur_trace | 407 | non mesurée | estimée (inchangée) |
| 72 | Tata 64 | 14.772526, -17.402868 | interpolation_sur_trace | 653 | non mesurée | estimée (inchangée) |
| Dial Mbaay | Tata 64 | 14.775408, -17.402755 | interpolation_sur_trace | 619 | non mesurée | estimée (inchangée) |
| Tivaouane Peulh | Tata 69 | 14.802122, -17.283128 | arrets_geo | 3328 | mesurée mais loin de ses voisins mesurés | estimée (inchangée) |
| Route Nationale N°1 | Tata 72 | 14.747300, -17.357262 | interpolation_sur_trace | 2265 | non mesurée | estimée (inchangée) |
| Colobane Rufisque | Tata 74 | 14.706228, -17.239321 | interpolation_sur_trace | 1409 | non mesurée | estimée (inchangée) |
| Poste Courant | Tata 74 | 14.709228, -17.251161 | interpolation_sur_trace | 2662 | non mesurée | estimée (inchangée) |
| Route Nationale N°1 | Tata 74 | 14.715265, -17.264792 | interpolation_sur_trace | 4273 | non mesurée | estimée (inchangée) |
| Bld Maurice Gueye | Tata 74 | 14.716694, -17.275499 | interpolation_sur_trace | 5138 | non mesurée | estimée (inchangée) |
| Rond-Point Djouti Ba Rufisque | Tata 74 | 14.725559, -17.282303 | interpolation_sur_trace | 3945 | non mesurée | estimée (inchangée) |
| Route des HLM Rufisque | Tata 74 | 14.737989, -17.288083 | interpolation_sur_trace | 2433 | non mesurée | estimée (inchangée) |
| Echangeur Rufisque-Ouest | Tata 74 | 14.751056, -17.285371 | interpolation_sur_trace | 1379 | non mesurée | estimée (inchangée) |
| Keurmassar | Tata 74 | 14.786463, -17.297234 | interpolation_sur_trace | 2547 | non mesurée | estimée (inchangée) |
| Cité COCEHAS | Tata 74 | 14.802122, -17.283128 | arrets_geo | 2546 | non mesurée | estimée (inchangée) |
| Route Nationale N°1 | Tata 75 | 14.745847, -17.389610 | arrets_geo | 1218 | non mesurée | estimée (inchangée) |
| Route Nationale N° 1 | Tata 77 | 14.738387, -17.310203 | interpolation_sur_trace | 937 | non mesurée | estimée (inchangée) |
| Croisement Tivaouane Peulh | Tata 79 | 14.785105, -17.302337 | interpolation_sur_trace | 3079 | non mesurée | **corrigée** : 14.786355, -17.294528 |
| Croisement Tivaouane Peulh | Tata 80 | 14.786367, -17.292707 | interpolation_sur_trace | 2040 | non mesurée | **corrigée** : 14.786355, -17.294528 |
| Autoroute A Péage | Tata 82 | 14.743594, -17.429817 | interpolation_sur_trace | 5548 | non mesurée | estimée (inchangée) |
