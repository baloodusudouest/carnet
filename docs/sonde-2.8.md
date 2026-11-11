# Résultats de la sonde avant la 2.8.0 — 11/11/2026, 13:24

Sonde version 1, en lecture seule, sur la base de carnet et sur Treemich. Aucun nom de personne.

## A. Cartes iCloud

- 563 cartes, aucune validée. Liées : Immich 144, Treemich 139.
- 23 cartes ont un conjoint ou partenaire parmi les noms associés.
- 62 cartes sont des fiches d'entreprise (`X-ABSHOWAS`) ; 63 n'ont pas de prénom.

| Propriété | Cartes | | Propriété | Cartes |
|---|---|---|---|---|
| TEL | 504 | | ADR | 68 |
| ORG | 357 | | X-ABRELATEDNAMES | 43 |
| X-SOCIALPROFILE | 211 | | NICKNAME | 6 |
| PHOTO | 157 | | URL | 4 |
| BDAY | 152 | | NOTE | 4 |
| TITLE | 128 | | | |
| EMAIL | 83 | | | |

**Ce qui n'existe nulle part aujourd'hui :** aucune date supplémentaire (`X-ABDATE`), aucun service en plus de la société, aucune prononciation. Les trois champs nouveaux de la 2.8.0 partent de zéro : il n'y a rien à reprendre ni à préserver.

## B. Groupes et famille « Manques »

Aucun contact sans groupe. 51 contacts sont dans plusieurs groupes.

Avec le tableau de départ, **437 fiches sur 563** ont au moins un manque.

| Groupe | Contacts | Incomplets | Sans téléphone | Sans jour de naissance | Sans année | Sans photo ni logo | Sans Immich | Sans Treemich | Sans liens familiaux | Sans société |
|---|---|---|---|---|---|---|---|---|---|---|
| Famille | 46 | 27 | 10 | 9 | 11 | 6 | 7 | 8 | 16 | — |
| Amis | 54 | 17 | 4 | 9 | — | 8 | 10 | — | — | — |
| Jardin secret | 144 | 139 | 41 | — | — | 139 | — | — | — | — |
| Collègues | 105 | 47 | 2 | — | — | 46 | — | — | — | 0 |
| Clients | 175 | 164 | 1 | — | — | 164 | — | — | — | 0 |
| Artisans et services | 50 | 46 | 1 | — | — | 46 | — | — | — | 2 |
| Urgence | 6 | 0 | 0 | — | — | — | — | — | — | — |

| Ligne de la famille « Manques » | Fiches |
|---|---|
| Sans photo ni logo | 406 |
| Sans téléphone | 59 |
| Sans jour de naissance | 18 |
| Sans Immich | 17 |
| Sans liens familiaux | 16 |
| Sans année de naissance | 11 |
| Sans Treemich | 8 |
| Sans société ni fonction | 2 |

Deux groupes existent sans attentes dans le tableau : un groupe personnel de 46 contacts, et « Moi » (1).

## C. Prénoms

464 simples, 29 en plusieurs mots, 7 composés avec trait d'union, 63 vides.

## D. Treemich

- 221 personnes, 148 relations : 47 parent, 47 enfant, 28 fratrie, 26 conjoint (13 couples).
- Une relation ne porte que ses deux personnes et son type : **aucune date**.
- Un seul type d'évènement de vie existe : la naissance (87, toutes avec une année).
- **Aucun mariage n'est enregistré dans Treemich**, pour aucun des 13 couples.
- Treemich ne publie pas de description de son interface.

## Ce que cela impose à la conception

1. **La photo domine tout.** 406 des 437 fiches incomplètes le sont faute de photo ou de logo, dont 164 clients, 139 du Jardin secret, 46 collègues et 46 artisans. Sans changement, la famille « Manques » serait une seule ligne énorme. La recherche de logos par lot (onglet Photos) vise exactement les clients et les artisans.
2. **Hors photo, les manques sont peu nombreux** : 59 sans téléphone, puis moins de 20 fiches par ligne. La famille « Manques » restera lisible.
3. **Le groupe personnel de 46 contacts doit recevoir des attentes** dans le tableau.
4. **Le mariage ne peut pas venir de Treemich aujourd'hui** : il n'y en a aucun. Le sens Treemich vers iCloud ne produira rien tant que des mariages n'y sont pas saisis. Et rien ne dit comment en écrire un : le sens carnet vers Treemich est à vérifier avant de s'y engager.
5. **Les champs nouveaux partent de zéro** : pas de reprise, mais il faut vérifier sur une carte d'essai qu'iCloud les rend bien.
6. **Les fêtes** concernent au plus une centaine de contacts (Famille et Amis) : une centaine d'écritures dans iCloud, à faire par lots. 36 prénoms composés ou multiples demandent une règle.
7. **63 fiches sans prénom** (entreprises) n'ont ni fête ni naissance : les attentes « jour de naissance » et « fête » ne doivent pas s'appliquer à une fiche d'entreprise.
