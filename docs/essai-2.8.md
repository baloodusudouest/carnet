# Essai avant carnet 2.8.0 (version 2.7.2)

Décidé le 11/11/2026 après le passage au conseil. But : savoir, avant de coder, ce qu'iCloud et l'iPhone font des champs nouveaux, et ce que vaut la recherche de logos.

## Ce que l'essai écrit

**Une seule carte**, nouvelle, dans iCloud : le contact « Carnet Essai », aux données inventées. Aucune fiche existante n'est touchée. Immich et Treemich ne sont pas contactés. La base de carnet est lue sur une copie.

L'essai écrit cette carte même si carnet est en lecture seule : c'est un programme à part.

## Déroulé

| # | Geste | Où |
|---|---|---|
| 1 | Mettre à jour la stack avec le `homelab.yml` du projet (service `carnet-essai` ajouté) | Portainer |
| 2 | Le conteneur `carnet_essai` tourne deux à cinq minutes puis s'arrête. Copier son journal | Portainer, Logs |
| 3 | Ouvrir le contact « Carnet Essai » et répondre aux questions ci-dessous | iPhone |
| 4 | Sur ce contact, changer la date « Mariage » (13 juillet 2011) pour une autre, et enregistrer | iPhone |
| 5 | Attendre une minute, relancer `carnet_essai` (Start). Copier son journal | Portainer |
| 6 | Supprimer le contact « Carnet Essai » | iPhone |
| 7 | Retirer le service `carnet-essai` de la stack | Portainer |

Entre-temps, carnet verra passer la carte : un point « Fiche créée sur l'iPhone », puis « Fiche supprimée ». Répondre « Garder », puis « Confirmer la suppression ».

## Ce qu'il faut regarder sur l'iPhone (étape 3)

Chaque date de la carte est différente, pour savoir quel libellé montre laquelle.

| Question | Date à chercher |
|---|---|
| Sous quel nom s'affiche la date au libellé d'Apple ? | 12 juin 2010 |
| La date « Mariage » s'affiche-t-elle sous ce nom ? | 13 juillet 2011 |
| La « Fête » s'affiche-t-elle sans année ? Sinon, quelle année ? | 15 août |
| La date « Décès » s'affiche-t-elle sous ce nom ? | 2 janvier 2020 |
| Le service apparaît-il sous la société ? | « Service d'essai » |
| La prononciation apparaît-elle ? | « Karnè Essè » |
| Dans l'appli Calendrier, une de ces dates apparaît-elle (aller au 12 juin, au 13 juillet, au 15 août) ? | |

Une capture d'écran de la fiche suffit pour les six premières lignes.

## Ce que disent les rapports

- **A. Carte d'essai** : pour chaque champ, si iCloud l'a rendu tel quel ; les lignes qu'il a réécrites.
- **B. Logos** : parmi les fiches sans photo des groupes Clients et Artisans et services, combien ont un site ou un courriel professionnel ; sur 30 sociétés tirées au hasard, combien de logos trouvés, combien de nets. Aucun nom de société ni de site dans le rapport.
- **C. Relecture** (2e lancement) : ce que la modification faite sur l'iPhone a changé dans la carte.

Les rapports sont aussi écrits dans le dossier de données de carnet : `rapport-essai-2.8-1.md` et `rapport-essai-2.8-2.md`.

## Ce qui en dépend

| Résultat | Conséquence pour la 2.8.0 |
|---|---|
| La fête n'apparaît que dans la fiche | Julien décide si elle vaut une centaine d'écritures |
| La date sans année revient avec une année | La fête est calculée et annoncée, pas écrite |
| Le libellé d'Apple prête à confusion avec la naissance | Le mariage s'écrit avec le libellé « Mariage » |
| Moins de la moitié des logos trouvés | File Logos réduite ; attente « photo ou logo » revue pour Clients et Artisans |
| iCloud réécrit les lignes | La comparaison de carnet se fait sur les valeurs, pas sur le texte |

## Résultats (11/11/2026)

### Carte d'essai

iCloud a rendu les sept champs tels qu'envoyés. Sur l'iPhone (appli Contacts) :

| Champ | Affichage | Décision |
|---|---|---|
| Libellé natif d'Apple | **« fête »** : c'est la traduction française du libellé d'anniversaire de mariage | Ne jamais l'utiliser pour le mariage |
| « Mariage » | « Mariage », avec l'année | Le mariage s'écrit avec ce libellé libre |
| « Fête », sans année | « 15 août », sans année | La fête s'écrit avec le libellé libre « Fête » |
| « Décès » | « Décès », avec l'année | Libellé libre gardé |
| Prononciation, service | Sous le nom : « Karnè Essè · Service d'essai · Société d'essai » | Visibles |
| Calendrier | Aucune des dates n'y apparaît | L'iPhone ne rappelle rien : le rappel vient de Home Assistant |

carnet 2.7 ne montre aucun de ces champs sur sa fiche, et ne les perd pas.

### Ce que l'iPhone réécrit quand on modifie la carte

Après le changement d'une seule date sur l'iPhone :

- la première date reçoit `type=pref` ;
- la date sans année perd `X-APPLE-OMIT-YEAR=1604` mais garde l'an 1604 ;
- l'ordre des lignes change.

Règles pour carnet : comparer des valeurs, jamais des lignes ; **l'an 1604 veut dire « sans année »**, avec ou sans le paramètre ; ignorer `type=pref` et l'ordre.

### Logos

| Mesure | Nombre |
|---|---|
| Fiches Clients et Artisans et services sans photo | 210 |
| Avec un site ou un courriel professionnel | 19 |
| Sans aucun des deux | 191 |
| Sociétés différentes essayées | 17 |
| Logo trouvé | 5 (29 %) |
| dont net (180 px ou plus) | 4 |
| Durée moyenne par société | 5,4 s |

La recherche automatique ne peut traiter qu'une fiche sur dix, et en réussit moins d'une sur trois.

### Décisions de Julien après l'essai

| Sujet | Décision |
|---|---|
| Fête | Écrite dans iCloud malgré l'absence de rappel : il veut la voir sur la fiche de l'iPhone |
| Photo ou logo pour Clients et Artisans | L'attente est gardée. Il faut pouvoir **glisser un logo** depuis une recherche d'images Google, dans l'appli ou depuis le navigateur |
