# Inventaire des sources : bus de Dakar (DDD et AFTU/Tata)

Consulté le 11/11/2026. But : vérifier l'app GuindiMa.
Règle appliquée : un trajet est **confirmé** s'il vient d'une source officielle, ou de 2 sources indépendantes qui concordent. Sinon, c'est un **indice**.

## 1. Sources officielles

| Source | Lien | Type | Licence / conditions | Contenu | Réutilisable ? |
|---|---|---|---|---|---|
| Dem Dikk : Info voyageurs | https://demdikk.sn/info-voyageurs/ | Officiel | Aucune licence affichée (© Dem Dikk SA) | Liste des lignes urbaines, banlieue, navettes TER 501–504, TAF TAF (itinéraire et horaires), gares | Oui, comme **référence de vérification** (pas de copie massive) |
| Dem Dikk : Réseau urbain | https://demdikk.sn/reseau-urbain-dakar/ | Officiel | Idem | Liste ordonnée des arrêts des lignes 1, 4, 7, 8, 9, 10, 13, 18, 20, 23, 121 (et début de la 319) | Oui, pour vérifier. **Meilleure source DDD** |
| Dem Dikk : Offres de transport | https://demdikk.sn/offres-de-transport/ | Officiel | Idem | Express AIBD (départ HLM Grand-Yoff, 6 000 FCFA, 24h/24) | Oui, pour vérifier |
| Dem Dikk : Plan des lignes | https://demdikk.sn/wp-content/uploads/2023/01/plan-lignes-ddd.jpeg | Officiel (image 2023) | Idem | Tracés colorés sur fond de carte, illisibles pour les arrêts | Indicatif seulement |
| AFTU : Infos pratiques (catalogue) | https://aftu-senegal.org/infos-pratiques/ | Officiel | « AFTU-SENEGAL © TOUS DROITS RESERVES - 2025 » | 72 lignes Tata avec leurs 2 terminus (1–5, 24–89, 91) | Oui, pour vérifier. Pas de copie publique |
| AFTU : fiches par ligne | https://aftu-senegal.org/map/dakar-urbain-ligne-N/ | Officiel | Idem | Terminus et suite des rues/quartiers desservis, **un seul sens** le plus souvent. Fiches datées de mai à juillet 2026. J'en ai lu 24 (lignes 1–5, 24, 26, 30, 33, 35, 38, 40, 44, 47, 50, 54, 55, 57, 60, 62, 64, 67, 73, 75) | Oui, pour vérifier. **Meilleure source Tata** |
| CETUD : page AFTU | https://cetud.sn/reseaux-de-transport/aftu/ | Officiel (autorité) | Non vérifié | Contexte et plan global AFTU, d'après l'audit du dépôt dkrBus-apps | Non consulté directement |
| CETUD : études PDF (BRT, RTC, bulletins) | https://cetud.sn/wp-content/uploads/… | Officiel | Non vérifié | Études et bulletins de mobilité, pas de liste d'arrêts exploitable | Contexte seulement |

**Remarques importantes**
- Le site demdikk.sn contient des **dizaines de liens de jeux d'argent cachés** (« toto slot », « slot gacor »…) en bas de page. Le site semble piraté (spam SEO). Le contenu transport paraît normal, mais il faut le signaler à Dem Dikk et ne pas suivre ces liens.
- aftu-senegal.org renvoie une erreur 406 aux requêtes en ligne de commande. Les pages ont été lues avec l'outil de lecture web normal, sans contournement.
- Aucune source officielle ne donne de **durée de trajet**. La colonne `duree_min` est donc vide partout.
- Les fiches AFTU décrivent surtout des **rues**, pas des arrêts. La plupart ne donnent qu'**un sens**. La ligne 64 se contredit : le catalogue dit Guédiawaye – Rufisque, la fiche dit Diamniadio → Notaire.
- Sur la page DDD, la ligne 23 est titrée « Palais 1 », mais la liste se termine par « Terminus Palais 2 ».

## 2. Données ouvertes

| Source | Lien | Type | Licence | Contenu | Réutilisable ? |
|---|---|---|---|---|---|
| OpenStreetMap (via Overpass) | https://www.openstreetmap.org/relation/6951328 (exemple) | Données ouvertes | **ODbL** : réutilisable avec attribution « © contributeurs OpenStreetMap » | 25 relations « bus » autour de Dakar, dont 15 DDD (lignes 1, 4, 7, 8, 9, 10, 18, 23, 121, avec doublons par sens) et 1 Tata (ligne 40) | **Oui**. Sert de 2e source. Couverture faible pour les Tata |
| ArcGIS « Dem_dikk_mise_a_jour » | https://services1.arcgis.com/tKMirJrirprCZbnf/ArcGIS/rest/services/Dem_dikk_mise_a_jour/FeatureServer/0 | Couche publique (compte `fode.diouf_esrisenegal`, **pas** Dem Dikk) | **Aucune licence** indiquée | Arrêts DDD par ligne, banlieue comprise (2, 5, 6, 11, 12, 16A/B, 217, 218, 227, 228, 232). Mise à jour le 24/09/2024. Noms souvent génériques (« Arret Avenue Bourguiba ») et ordre incertain | **Indice seulement** |
| ArcGIS « Ligne_inter_urbain » | https://services1.arcgis.com/tKMirJrirprCZbnf/ArcGIS/rest/services/Ligne_inter_urbain/FeatureServer | Idem | Aucune | Anciennes couches d'arrêts des lignes urbaines DDD (repérées via dkrBus-apps) | Indice, non exploité |
| Digital Transport for Africa (WRI) | https://digitaltransport4africa.org/ ; https://gitlab.com/digitaltransport | Données ouvertes | Variable selon le jeu de données (souvent ouvertes) | GTFS pour 24 villes africaines (Abidjan, Accra, Bamako…), **mais aucune pour Dakar** | Sans objet pour Dakar |
| transportafrica.org/datasets | https://transportafrica.org/datasets | Données ouvertes | Non lu | Erreur 406 en ligne de commande, non contourné | Non consulté |
| arXiv 2609.29998 (GTFS4EV, BRT de Dakar) | https://arxiv.org/abs/2609.29998 | Étude universitaire | Licence arXiv de l'article | Électrification du **BRT** à partir d'un GTFS public. Ne concerne ni DDD ni Tata | Contexte. Le GTFS du BRT serait à chercher (non fait) |

## 3. Dépôts GitHub d'apps de bus à Dakar

| Dépôt | Lien | Licence | Origine des données | Usage |
|---|---|---|---|---|
| aydiarra-star/dkrBus-apps (ex-**yanks880/Dakar-Bus**, redirigé) | https://github.com/aydiarra-star/dkrBus-apps | **Aucune licence** | Le README affirme : « Aucun flux GTFS… n'est actuellement fourni ». `docs/bus-route-data-audit.md` recense très bien les sources (demdikk.sn, ArcGIS, aftu-senegal.org, CETUD, MoMove, covoiturage.sn). Les fichiers `src/data/aftu-*-directions.json` et `tata-lines.json` n'ont pas été vérifiés | Indice. **Très utile comme carnet d'adresses des sources** |
| yanks880/Dakar-trajet | https://github.com/yanks880/Dakar-trajet | Introuvable (404) | — | — |
| Lutsun/Yoonbi | https://github.com/Lutsun/Yoonbi | **MIT** | `data/places.json` et base Supabase : origine non documentée dans ce que j'ai vu | Indice. Code réutilisable (MIT), données d'origine inconnue |
| ElCep/OSM_bus | https://github.com/ElCep/OSM_bus | GPL-3.0 | Affiche des lignes de bus de Dakar depuis OSM (Overpass) | Montre que les données OSM existent. Sans données propres |
| chniang/koumba | https://github.com/chniang/koumba | MIT | Agent vocal wolof pour les bus de Dakar. Données non examinées | À examiner |
| Autres (sentransport, BusTrackDakar, dakar-bus-tracker-app, Arret-Bus…) | recherche GitHub « dakar bus » | Aucune licence | Inconnue | Ignorés |

## 4. Sources secondaires (indices seulement, non consultées)

| Source | Lien | Type | Remarque |
|---|---|---|---|
| MoMove : guide | https://momove.app/guide | Tiers (app) | Catalogue Tata non officiel, cité par dkrBus-apps |
| Covoiturage Sénégal : itinéraires Tata | https://www.covoiturage.sn/bus-tata-itineraire/ | Tiers | À comparer seulement |
| Presse (AllAfrica, Dakaractu, Seneplus) | ex. https://fr.allafrica.com/stories/202407290314.html | Presse | Réorganisation 2024 : 14 nouvelles lignes AFTU et 11 itinéraires modifiés autour du BRT. **Des itinéraires ont donc pu changer** |
| memoireonline.com (mémoire 2007 sur DDD) | https://www.memoireonline.com/03/08/1002/modelisation-transport-dakar-cas-dakar-dem-dik.html | Étude ancienne | Obsolète |

Exclus comme demandé : Google Maps, Moovit, et tout site qui demande une connexion.
