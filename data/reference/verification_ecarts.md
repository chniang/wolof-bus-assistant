# Vérification des lignes derrière les 15 plus gros écarts de GuindiMa

Consulté le 12/11/2026. Lecture seule, sans connexion, sans formulaire. aftu-senegal.org a été lu dans le navigateur Chrome (pas en ligne de commande). Google Maps et Moovit n'ont pas été utilisés.
Règle : **confirmé** = source officielle, ou 2 sources indépendantes qui concordent. Sinon : **indice**.
Détail arrêt par arrêt : `arrets_lignes_prioritaires.csv` (264 lignes, noms recopiés tels qu'écrits).

## 1. Fiches lues

| Ligne | Source | Date | Remarque |
|---|---|---|---|
| Tata 37 (nouvelle) | aftu-senegal.org/map/dakar-urbain-ligne-37/ | 29 juin 2026 | APIX → UCAD (Claudel), 35 points, passe par Colobane |
| Tata 74 (nouvelle) | …/dakar-urbain-ligne-74/ | 13 juil. 2026 | Bargny (gare ferroviaire) → Cité Cocehas, via « COLOBANE RUFISQUE » et Keur Massar. **Le terminus ne correspond pas au catalogue** (« Tivaouane Peul ») : Tivaouane Peul n'est qu'un point avant « TERMINUS CITE COCEHAS » |
| Tata 3, 4, 30, 40, 57, 60, 62, 64, 75 | fiches AFTU | 21 mai – 13 juil. 2026 | Relues en entier : les listes sont maintenant complètes et dans l'ordre (avant, elles étaient résumées) |
| DDD 4, 18, 220 | demdikk.sn/reseau-urbain-dakar/ | page non datée | La 4 a deux arrêts de plus qu'avant (« Eglise Martyrs de l'ouganda », « Avenue Léopold Sédar Senghor »). La 18 est listée deux fois à l'identique |

Les fiches AFTU ne décrivent qu'**un seul sens**. Ce sont souvent des rues ou des repères, pas de vrais arrêts.
La page demdikk.sn/info-voyageurs/ affiche « Il y a eu une erreur critique sur ce site » (12/11/2026). Le spam de jeux d'argent reste présent en pied de page du site Dem Dikk.

## 2. Questions précises

- **Tata 60 dessert-elle Colobane (Dakar) ?** Oui, **confirmé** (fiche AFTU, 7 juil. 2026). « TERMINUS COLOBANE – AUTO ROUTE – ROUTE NATIONALE 1… ». Comme la ligne prend ensuite l'autoroute, il s'agit bien de Colobane à Dakar. Rien n'indique Colobane Rufisque.
- **Tata 60 dessert-elle Rufisque ?** Oui, **confirmé** (même fiche). « DIOUTYBA (RUFISQUE) – SONADIS – SOCOCIM – TERMINUS BARGNY ». Elle traverse Rufisque, mais n'y a pas de terminus.
- **Tata 40 dessert-elle Thiaroye ?** Oui, **confirmé** (fiche AFTU, 29 juin 2026), avec « POSTE THIAROYE ». Le 11/11, la relation OSM de la ligne 40 avait aussi été vue.
- **Tata 40 dessert-elle Colobane ?** Oui, **confirmé** : « AUTOROUTE – COLOBANE – TERMINUS PETERSEN ».
- **Un arrêt « Marché Colobane » à Rufisque ?** Oui, **confirmé** (officiel), sur la Tata 57 : « MARCHE COLOBANE RUFISQUE » (2e point). La Tata 74 a « COLOBANE RUFISQUE » (2e point), mais sans le mot « Marché ».
- **Existe-t-il un quartier Colobane à Rufisque ?** Oui, **confirmé** par 2 sources indépendantes :
  - les fiches AFTU 57 et 74 ;
  - Dakaractu (déc. 2021), qui cite le « quartier Colobane Gouye Mouride » dans la commune de Rufisque-Est.

  Le terminus de la 57, « RUFISQUE GOUYE MOURIDE », renvoie au même secteur.
  ⚠ Risque d'homonymie : une app qui lit « Colobane » sans « Rufisque » peut confondre avec la gare de Colobane à Dakar.

## 3. Écart majeur : DDD 220

- **demdikk.sn (page non datée)** : 220 = « RUFISQUE <--> GUÉDIAWAYE ». Le trajet passe par Djoutiba, Jaxaay, Station Keur Massar, Malika, Gadaye et Lycée Limamoulaye.
- **Senego (15/07/2026)** : « La ligne 220, au départ de l'Espace BRT du terminus Dem Dikk de Guédiawaye », présentée comme une navette **Guédiawaye → AIBD**, un départ toutes les 2 h, 6 000 FCFA. Ground.news reprend la même information, mais ce n'est probablement pas une source indépendante.
- → Ces deux versions se contredisent. Les deux sont marquées **indice** dans le CSV. La page officielle est peut-être ancienne, ou le numéro 220 a été réutilisé. À trancher auprès de Dem Dikk (33 824 10 10). C'est à faire avant toute correction dans GuindiMa.

## 4. Noms de l'aéroport Blaise Diagne (Diass)

| Nom | Où | Statut |
|---|---|---|
| AIBD | demdikk.sn (dernier arrêt de la ligne TAF TAF), Senego, Dakaractu | confirmé |
| Aéroport international Blaise Diagne (AIBD) | Senego (15/07/2026), demdikk.sn onglet « Express AIBD » (« …Blaise Diagne (AIBD)… ») | confirmé |
| Express AIBD | demdikk.sn/offres-de-transport/ (nom du service) | confirmé (officiel) |
| Dakar-AIBD / Diamniadio–AIBD (TER) | AllAfrica et Senego (déc. 2025), Dakaractu (mise en service sur 19 km) | confirmé (presse, 2 sources) |
| Aéroport de Diass | Seneplus (« Le TER prêt pour l'aéroport de Diass ») | indice (1 source) |
| Diass (seul) | commentaire de lecteur sur Senego | indice faible |

Aucune des fiches Tata vérifiées ne mentionne l'AIBD. Dans l'app, il faut accepter au minimum ces synonymes : « AIBD », « Blaise Diagne », « Aéroport Blaise Diagne », « Diass ». Il faut aussi ne pas le confondre avec « Aéroport LSS / L S SENGHOR » (Yoff) ni avec « Avenue Blaise Diagne » (Dakar, sur les lignes 3 et 4) ou « Lycée Blaise Diagne » (DDD 9 et 121).

## Sources
- https://aftu-senegal.org/map/dakar-urbain-ligne-{3,4,30,37,40,57,60,62,64,74,75}/
- https://demdikk.sn/reseau-urbain-dakar/ ; https://demdikk.sn/offres-de-transport/
- https://www.dakaractu.com/Inauguration-du-commissariat-de-Rufisque-Est-les-delegues-de-quartier-listent-leurs-priorites_a212280.html
- https://senego.com/navette-dem-dikk-guediawaye-aibd-toutes-les-2h-6-000-fcfa_1983793.html
- https://ground.news/article/its-just-6-000-cfaf-dakar-dem-dikk-announces-good-news-for-its-users
- https://www.dakaractu.com/TER-la-desserte-de-l-AIBD-officiellement-mise-en-service_a276475.html
- https://fr.allafrica.com/stories/202512160280.html
- https://www.seneplus.com/index%2Ephp/article/le-ter-pret-pour-laeroport-de-diass
