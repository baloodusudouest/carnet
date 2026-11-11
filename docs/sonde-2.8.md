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
- Aucune relation ne porte de date remplie. D'après le code de Treemich (lu le 11/11/2026, voir plus bas), la liste des relations renvoie pour chaque couple `marriageAnniversaryDate` et `divorceDate` : ils sont donc vides pour les 13 couples.
- Évènements de vie rattachés aux personnes : seulement des naissances (87, toutes avec une année). Aucun décès.
- **Aucun mariage n'a de date dans Treemich aujourd'hui.** Réserve : cela suppose que la version installée renvoie bien ces deux champs ; la 2.8.0 le saura dès sa première nuit.
- Treemich ne publie pas de description de son interface ; son code source, lui, est public.

### Ce que dit le code de Treemich (dépôt `ShailChoksi/treemich`, état du 21/10/2026)

Correction d'une première version de ce rapport, qui disait que le mariage n'existait pas dans Treemich.

- Douze types d'évènements de vie existent, dont le mariage et le divorce.
- **Mariage et divorce se rangent sur le couple**, pas sur une personne. La sonde n'avait lu que les évènements des personnes.
- Lire : `GET /relationships` donne pour chaque lien de conjoint `marriageAnniversaryDate` et `divorceDate`.
- Écrire : `PATCH /people/<id>/relationships` avec `toPersonId` et `marriageAnniversaryDate` (date au format année-mois-jour) ; Treemich crée ou met à jour l'évènement de mariage du couple. Une valeur vide l'efface.
- Le décès se lit sur la personne (`deathDate`, ou évènement de vie de type décès).

## Ce que cela impose à la conception

1. **La photo domine tout.** 406 des 437 fiches incomplètes le sont faute de photo ou de logo, dont 164 clients, 139 du Jardin secret, 46 collègues et 46 artisans. Sans changement, la famille « Manques » serait une seule ligne énorme. La recherche de logos par lot (onglet Photos) vise exactement les clients et les artisans.
2. **Hors photo, les manques sont peu nombreux** : 59 sans téléphone, puis moins de 20 fiches par ligne. La famille « Manques » restera lisible.
3. **Le groupe personnel de 46 contacts doit recevoir des attentes** dans le tableau.
4. **Le mariage part de zéro des deux côtés** : aucune date dans Treemich, aucune dans iCloud. Les deux sens sont possibles techniquement (lecture et écriture vérifiées dans le code de Treemich). Les premières dates viendront de la saisie de Julien, dans carnet ou dans Treemich.
5. **Les champs nouveaux partent de zéro** : pas de reprise, mais il faut vérifier sur une carte d'essai qu'iCloud les rend bien.
6. **Les fêtes** concernent au plus une centaine de contacts (Famille et Amis) : une centaine d'écritures dans iCloud, à faire par lots. 36 prénoms composés ou multiples demandent une règle.
7. **63 fiches sans prénom** (entreprises) n'ont ni fête ni naissance : les attentes « jour de naissance » et « fête » ne doivent pas s'appliquer à une fiche d'entreprise.
