# Fiabilité GuindiMa : premier audit face à la vérité terrain (F1/F2)

Date : 12/11/2026. Données de référence : `data/reference/` (copiées le 11/11/2026).
Script : `scripts/audit_fiabilite.py` (lecture seule, sans réseau). Aucune
modification du moteur dans cette étape : ce rapport dit **quoi** corriger,
pas encore **comment**.

## Les scores (F2, 67 trajets de référence : 62 « confirmé », 5 « indice »)

| Statut | Sous « Tous » | Sous le filtre de la compagnie |
| --- | ---: | ---: |
| OK : la ligne de référence est proposée | **36** (54 %) | **42** (63 %) |
| AUTRE_LIGNE : d'autres lignes seulement | 25 | 21 |
| LIGNE_FAUSSE : une ligne ne passe pas par le lieu | 2 | 0 |
| ABSENT : pas de réponse / lieu non reconnu | 4 | 4 |

Comment lire ce tableau :
- **AUTRE_LIGNE n'est pas forcément une erreur.** Pour Colobane → UCAD, nous
  proposons DDD 502A ou Tata 62 au lieu de DDD 18 : ce sont aussi de bonnes
  réponses. Sous « Tous », il faut aussi rappeler que l'app ne montre que
  3 lignes : la ligne de référence peut être juste plus lente.
- **LIGNE_FAUSSE est prudent.** 47 lignes de référence n'ont que leurs deux
  terminus, sans liste d'arrêts : on ne peut pas prouver qu'une de ces lignes
  ne passe pas par un lieu. Le statut n'est donné que face à une vraie liste
  d'arrêts.
- Trois erreurs graves sont classées AUTRE_LIGNE parce que le lieu porte un
  nom trompeur : Colobane → Rufisque, Thiaroye → Colobane (filtre Tata) et
  Malika → UCAD. Elles sont en tête de la liste ci-dessous.

Détail par trajet : `data/audit/verite_terrain.csv` (notre réponse sous les
deux filtres, la référence, les noms de lieux effectivement utilisés).

## F1 : fiabilité des lignes (`data/audit/fiabilite_lignes.csv`)

| | Dem Dikk | Tata AFTU |
| --- | ---: | ---: |
| Lignes dans nos données | 47 | 72 |
| Source officielle (itinéraire DDD / trace AFTU) | 38 | 65 |
| Lignes devinées, réduites à leurs 2 terminus | 9 | 7 |
| Arrêts à position **mesurée** (pondéré par arrêt) | 33 % | 38 % |
| Absentes de `lignes_reference.csv` | 10 | 0 |
| Présentes, mais terminus différents | 7 | 2 |

- **Lignes réduites à leurs terminus (devinées)** :
  - Dem Dikk : DDD 15A, 15B, 233, 502A, 502B, 503A, 503B, 504A et 504B.
  - Tata : Tata 84, 85, 86, 87, 88, 89 et 91.
- **Absentes de la référence** : DDD 15, 15A, 15B, 16A, 16B, 311, 319, 327, 502 et 503. La référence ne les détaille pas ; c'est à compléter de son côté, pas forcément une erreur chez nous.
- **Terminus différents** :
  - Tata 26 : chez nous Parcelles → Poste Thiaroye, la référence dit Guédiawaye.
  - Tata 64 : chez nous Guédiawaye ↔ Rufisque, la référence dit Diamniadio ↔ Notaire.
  - DDD 6 : chez nous Guédiawaye, la référence dit Cambérène 2.
  - DDD 217 : chez nous Aéroport LSS, la référence dit Ouakam.
  - DDD 208 : chez nous Gorom 01, la référence dit Bayakh.
  - DDD 18 et 20 : ce sont des lignes circulaires, la différence n'est qu'une question de nom.
- **Moins de 25 % de positions mesurées**, alors que la ligne a ses arrêts :
  - Tata à 0 % : 28, 36, 57 et 74.
  - Tata entre 10 et 22 % : 4, 25, 27, 32, 37, 42, 45, 50, 55, 56, 64, 65 et 72.
  - Dem Dikk entre 7 et 24 % : DDD 4, 10, 16B, 18, 20, 121 et 319.

  Pour ces lignes, la durée et l'arrêt proche sont des estimations.

## Les 15 écarts les plus importants

| # | Trajet | Référence | Nous proposons | Cause probable |
| ---: | --- | --- | --- | --- |
| 1 | Colobane → Rufisque (filtre Tata) | Tata 60 | Tata 57 depuis « Marché Colobane Rufisque », 14 min | **Homonyme** : « Colobane » est pris pour un arrêt de Rufisque. Réponse fausse. |
| 2 | Thiaroye → Colobane (filtre Tata) | Tata 40 | Tata 57 jusqu'à « Marché Colobane Rufisque » | Même homonyme, cette fois à l'arrivée. Sous « Tous », DDD 11 n'a pas Colobane dans la liste de référence (liste non officielle, à vérifier). |
| 3 | Malika → UCAD | Tata 75 puis DDD 18 | DDD 220 jusqu'à Sipres, 27 min | La descente est à Sipres, à environ 3 km de l'UCAD. Il faudrait l'arrêt le plus proche du lieu, pas un arrêt vague. |
| 4 | Ouakam, Yoff, Liberté 6, Grand Yoff → Aéroport AIBD (4 trajets) | TAF TAF, Express AIBD | rien | **Lieu non reconnu** : « Aéroport AIBD » n'est pas compris (« AIBD » seul l'est). Le TAF TAF donne alors 175 min (positions devinées). |
| 5 | Parcelles Assainies → Colobane (Tous) | Tata 30 | DDD 6 jusqu'à « Église Sainte Thérèse » | LIGNE_FAUSSE : la DDD 6 de référence ne passe pas à Colobane, et l'arrêt de descente en est loin. |
| 6 | Liberté 5 (Dieuppeul) → UCAD | DDD 4 | DDD 20 et 23 depuis Stade Demba Diop | **Lieu mal reconnu** : « Terminus Liberté 5 (Dieuppeul) » n'est pas retrouvé et la montée glisse vers Stade Demba Diop. |
| 7 | Yoff → Petersen (Sandaga) | Tata 3 | Tata 4 seulement | La Tata 3 (88 min) est retirée par la règle « 1,8 fois et +30 min » du lot précédent. Mais 71 % de ses positions sont interpolées : sa durée est probablement trop longue. |
| 8 | Plateau (Lat Dior) → Liberté 6 | Tata 1 | Tata 46, 29, 47 | **Orthographe** : l'arrêt de la Tata 1 s'appelle « Giratoire de Liberté VI », que « Liberté 6 » ne retrouve pas. |
| 9 | Médina (Gueule Tapée) → Parcelles (HLM Grand Médine) | Tata 1 | DDD 1, Tata 25, Tata 29 | Lieu non reconnu sous son nom entier : il a fallu chercher « Médina → Parcelles ». Les arrêts de la Tata 1 portent des noms de rues. |
| 10 | Parcelles Assainies → Petersen | Tata 2 | Tata 25 | Les arrêts officiels AFTU de la Tata 2 portent des noms de rues (« Route Principale des Parcelles Assainies ») que le lieu ne retrouve pas. |
| 11 | Guédiawaye → Colobane | Tata 30 | DDD 16A ; sous filtre Tata, la Tata 27 descend à « Rocade Fann Bel Air » | Guédiawaye pointe vers Stade Amadou Barry ou Notaire, pas vers Gadaye. La Tata 30 est interpolée à 70 %. |
| 12 | Malika → Colobane (filtre Tata) | Tata 75 | Tata 37, 173 min | Durée absurde : la Tata 37 est interpolée à 82 %. La Tata 75 (75 % mesurée) n'est pas retenue. |
| 13 | Maristes (Hann) → Rufisque | Tata 75 puis Tata 62 | Tata 75 puis DDD 213 ; sous filtre Tata, 75 puis 68 (127 min) | La Tata 62 est interpolée à 75 % et ses arrêts sont à plus de 800 m du point « Rufisque » (déjà vu au lot 3). |
| 14 | Yoff → UCAD (filtre Tata) | Tata 4 | Tata 35 puis 38 (57 min) | L'arrêt de la Tata 4 s'appelle « Avenue Cheikh Anta Diop » (nom de rue) et n'est pas relié à l'UCAD. 83 % de ses positions sont interpolées. |
| 15 | Rufisque → Guédiawaye (filtre Tata) | Tata 64 | Tata 72 (SONADIS → Cité des Enseignants), 93 min | Nos terminus de la Tata 64 diffèrent de la référence, et 89 % de ses positions sont interpolées. |

À suivre aussi :
- Keur Massar → Sandaga : la référence dit Tata 54 puis DDD 4 ; nous proposons DDD 11 en direct, 63 min, ce qui est plausible.
- Rufisque → Yoff : la référence dit Tata 57 puis DDD 8 ; nous proposons Tata 66, 108 min.

## Ce qu'il faut corriger en premier

1. **La reconnaissance des noms** : elle explique au moins 9 des 15 écarts. C'est le moins cher à corriger et le plus visible pour l'usager.
   - Homonymes de Colobane : un arrêt « Colobane Rufisque » ne doit jamais répondre à « Colobane » seul (Tata 57, Tata 74).
   - « Liberté VI » = « Liberté 6 ».
   - Reconnaître « Aéroport AIBD ».
   - Reconnaître les noms avec parenthèses : « Liberté 5 (Dieuppeul) », « Médina (Gueule Tapée) ».
   - Relier les arrêts AFTU nommés d'après une rue aux lieux qu'ils desservent (Tata 1, 2 et 4).
2. **Les positions des lignes de référence** : Tata 3, 4, 30, 37, 57, 62, 64 et 74, toutes interpolées à 70 % ou plus (0 % mesuré pour la 57 et la 74). Elles faussent les durées, et donc la règle « 1,8 fois » (point 7).
3. **La règle « 1,8 fois et +30 min »** du lot précédent : elle ne devrait s'appliquer que si les deux durées reposent sur des positions mesurées. Sinon, elle cache une bonne ligne (la Tata 3).
4. **Les 16 lignes réduites à leurs terminus** :
   - Dem Dikk : 15A, 15B, 233, 502A, 502B, 503A, 503B, 504A et 504B.
   - Tata : 84, 85, 86, 87, 88, 89 et 91.

   Il faut remplir leurs arrêts à partir d'une source officielle, ou ne plus les proposer.
5. **Les lignes centrales Dem Dikk peu mesurées** : DDD 18 (7 %) et DDD 4 (15 %).
6. **Les durées du TAF TAF** (175 min Ouakam → AIBD) : il faut ancrer ses arrêts.

Règle pour la suite : on ne corrige nos données qu'avec une source « confirmé »
(source officielle ou 2 sources concordantes, voir `data/reference/LISEZMOI.md`).

## Comparaison avec les fiches officielles (12/11/2026)

Source : fiches AFTU et Dem Dikk copiées dans `data/reference/`, comparées par
`scripts/comparer_lignes_officielles.py` (lecture seule, sans réseau). Détail
ligne par ligne : `data/audit/comparaison_lignes_officielles.csv`. Les fiches
officielles listent des rues et des repères dans un seul sens, pas de vrais
arrêts : la comparaison est indicative.

| Classe | Dem Dikk | Tata AFTU | Total |
| --- | ---: | ---: | ---: |
| CONFORME | 0 | 50 | 50 |
| A_COMPLETER | 27 | 0 | 27 |
| TERMINUS_DIFFERENT | 0 | 15 | 15 |
| DIVERGENTE | 6 | 0 | 6 |
| DOUTEUSE | 1 | 0 | 1 |
| SANS_SOURCE | 6 | 7 | 13 |
| **Total** | **40** | **72** | **112** |

Les 7 lignes Dem Dikk de l'audit F1 sans équivalent exact dans
`lignes_dakar.csv` : 311, 319, 327, TAF TAF OUAKAM (TO1), 502 et 503 sans
lettre, et la fiche 15 (qui ne distingue pas 15A et 15B). La fiche 15 est donc
comparée à nos deux lignes 15A/15B.

Les 15 appariements d'arrêts uniquement « souples » (fuzzy, seuil 0,88) :

| Ligne | Notre arrêt | Point officiel |
| --- | --- | --- |
| DDD 1 | Place Leclerc | Terminus Leclerc |
| DDD 4 | Place Leclerc | Terminus Leclerc |
| DDD 121 | Sacré-Cœur | Collège Sacré Cœur |
| DDD 121 | Place Leclerc | Terminus Leclerc |
| DDD 23 | Parcelles Assainies | Terminus des Parcelles |
| DDD 2 | Place Leclerc | Terminus Leclerc |
| DDD 234 | Place Leclerc | Leclerc |
| DDD 228 | Yenne | Diamniadio Yenne |
| DDD 227 | Parcelles Assainies | Terminus Parcelles |
| DDD 218 | Thiaroye | Dépôt Thiaroye |
| DDD 217 | Thiaroye | Dépôt Thiaroye |
| TAF TAF | Grand Yoff | Yoff ; Police Grand Yoff |
| TAF TAF | Patte d'Oie | Pharmacie Patte d'Oie |
| Tata 37 | Cité Apix | TERMINUS APIX |
| Tata 82 | Comico Yeumbeul | TERMINUS COMICO |

Un appariement souple n'est pas une erreur : il signale un libellé plus ou
moins précis, à vérifier. Tata 37 et 82 restent `CONFORME` : seul leur terminus
est apparié en souple.

**Ce que CONFORME veut dire.** `CONFORME` signifie que la liste d'arrêts
correspond à la fiche officielle. La position GPS des arrêts est un autre
sujet : voir la part de positions mesurées dans
`data/audit/fiabilite_lignes.csv`. Une ligne CONFORME peut donc avoir des
positions estimées.

### Ordre de correction

1. **Les noms** : Colobane, aéroport Blaise Diagne, Liberté VI, parenthèses,
   arrêts AFTU nommés d'après une rue.
2. **Les 15 libellés de terminus Tata** : 1, 26, 45, 50, 52, 56, 58, 63, 64,
   65, 69, 70, 72, 74, 81.
3. **Les 27 lignes Dem Dikk à compléter** à partir des listes officielles
   (classe `A_COMPLETER` du CSV).
4. **Les 6 lignes Dem Dikk divergentes** (23, 6, 233, 217, 208, 501) suivent le
   site officiel ; 6, 217, 220 et 233 restent affichées « estimé » jusqu'à
   confirmation téléphonique de Dem Dikk.
5. **Les lignes manquantes** 311, 319, 327 et TO1.
6. **Les positions des arrêts**, une fois les listes stabilisées.

## Lot 1 des noms (12/11/2026)

Corrections de reconnaissance seulement (aucune position, vitesse ni règle « 1,8 fois » modifiée) :
Colobane seul = Dakar (« Colobane Rufisque » pour Tata 57/74), aéroport Blaise Diagne (AIBD, Diass,
« aéroport » seul ; jamais LSS, ni l'avenue ou le lycée Blaise Diagne), chiffres romains, noms à
parenthèses, et 7 arrêts AFTU nommés d'après une rue reliés à leur lieu
(`data/corrections/lieux_arrets_aftu.csv`, une source par lien).

| Statut | Tous avant | Tous après | Filtre avant | Filtre après |
| --- | ---: | ---: | ---: | ---: |
| OK | 36 | **43** | 42 | **50** |
| AUTRE_LIGNE | 25 | 21 | 21 | 16 |
| LIGNE_FAUSSE | 2 | 3 | 0 | 1 |
| ABSENT | 4 | **0** | 4 | **0** |

Écarts corrigés : 1 (Colobane -> Rufisque, Tata 60), 4 (AIBD : 3 trajets OK, Grand Yoff -> AIBD
reçoit le TAF TAF ; l'Express AIBD n'est pas dans nos données), 9 (Tata 1), 10 (Tata 2), 14 (Tata 4).
En partie : 2 (plus de « Marché Colobane Rufisque », mais la Tata 40 n'est pas dans les 3 premières)
et 6 (montée à Liberté 5 / Dieuppeul, mais pas la DDD 4).

Nouvelle LIGNE_FAUSSE : Parcelles Assainies -> Grand Yoff propose la Tata 2 jusqu'à « Route HLM
Grand Médine » (3 min), que `arrets_geo.csv` place au quartier « Hlm Grand Yoff ». À revoir avec les
positions. Thiaroye -> Aéroport LSS (Yoff) passe de OK à AUTRE_LIGNE sous « Tous » : la partie
« (Yoff) » ajoute la Tata 66, et la DDD 218 sort des 3 premières (la DDD 217 reste).
