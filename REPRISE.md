# Reprise — carnet

Fichier à lire en premier dans une nouvelle session, et à mettre à jour à chaque fin de session, dans le même commit que le code.

## État (11/11/2026)

- **2.8.4 sur `main`** : la 2.8 complète (attentes et manques, Photos, champs nouveaux, fêtes et dates de famille, import unique, suppression confirmée, logo par société, noms de société, accord immédiat avec Treemich, Réseaux dans Réglages). Julien a une 2.8 en service.
- Interrupteurs : Julien a allumé « dates de famille » le 11/11 ; « fêtes » est éteint à la livraison.
- Conseil : [`docs/2.8-conseil.md`](docs/2.8-conseil.md). Essai sur le vrai iCloud : [`docs/essai-2.8.md`](docs/essai-2.8.md).
- Dossier « tel que construit » : [`docs/dossier.md`](docs/dossier.md), à jour pour la 2.8.4.

## Prochaine étape

1. Julien met la 2.8.0 en service **en lecture seule un jour** (`CARNET_LECTURE_SEULE=oui`), copie de `/state` avant. Il vérifie : les nombres de la famille « Manques » (la sonde donnait 437 fiches incomplètes, 406 sans photo, 59 sans téléphone, avant l'exemption des fiches d'entreprise et sans la colonne Fête), le tableau des attentes, la liste « ce que carnet écrirait ».
2. Il enlève la lecture seule, puis allume « fêtes » ; une semaine plus tard, « dates de famille ». Relire « Écrit par carnet tout seul » après chaque première nuit.
3. À voir à l'usage : le calendrier des fêtes (prénoms introuvables dans la ligne « Sans fête »), le logo glissé depuis Google Images sur iPhone et sur PC, l'écriture réelle d'un mariage dans Treemich (jamais essayée sur la vraie installation).
4. Home Assistant ne lit pas encore `/ha/fetes` ni les mariages de `/ha/anniversaires` : à brancher (master doc HA) pour que les annonces existent.
5. Idée gardée : route unique d'évènements pour Home Assistant.
6. Après une semaine d'usage : document du socle et planche de couleurs.

## Décisions tranchées

- iCloud est la source maître ; toute modification faite sur l'iPhone repasse par « À traiter ».
- Aucune suppression automatique ; la nuit n'écrit que les mises à jour sûres.
- Suppression d'une fiche : seulement à la demande de Julien, depuis la modification de la fiche, et toujours après confirmation (2.8.0). Le serveur refuse sans `confirmation` vraie.
- Trois onglets jusqu'à la 2.7 ; cinq à partir de la 2.8.0 (Photos, Réglages).
- Le nouvel habillage (minimalisme, tuiles bento pour État, sombre par défaut et clair selon l'appareil, shadcn-svelte, ocre conservé) **remplace** l'actuel, sans version en parallèle (décision du 11/11/2026).
- L'habillage ne change aucune route de l'API ni le schéma de la base, ni les textes, ni la navigation ; les tests d'interface ne sont pas réécrits.
- L'anneau de progression, la jauge autour de l'avatar et l'index en tranche sont gardés et reteintés.
- Le mot de passe reste `CARNET_PASSWORD` ; connexion unique plus tard, avec l'Anneau unique.
- Conseil du 11/11/2026 : ménage, habillage et parcours sont trois livraisons séparées.
- Habillage 2.7.0 : les couleurs gardent leurs noms d'origine (`--color-cuir`, `--color-papier`…), seules leurs valeurs changent ; le clair se fait par `prefers-color-scheme`, sans bouton. Julien a trouvé le premier essai (neutres froids, bouton plein neutre) trop froid : les neutres sont teintés vers l'ocre et le bouton plein est en ocre.
- shadcn-svelte n'est pas introduit dans carnet, ni en 2.7.0 ni en 2.8.0 (avis du conseil) : fenêtre et case à cocher natives, habillées par les classes maison.
- 2.8.0 : fête et dates de famille s'écrivent sans validation mais derrière deux interrupteurs éteints à la livraison ; les dates de famille remplissent le côté vide et n'écrasent jamais ; cinq onglets.

## Pièges

- 2.8 : toute écriture automatique nouvelle passe par `famille.appliquer` (interrupteur, plafond de nuit, table `automatiques`). Une réponse de Julien dans « À traiter » écrit tout de suite et n'est pas journalisée comme automatique.
- Le logo se choisit par société (`logos_societes`) et ne remplace jamais une photo : `galerie.fiches_de_la_societe` ne rend que des fiches sans photo et non reliées à Immich.
- Les logos en attente d'un choix sont dans `c.logos`, pas dans le cache `c._memo` (vidé à chaque écriture).
- Le tableau des attentes n'est inscrit qu'une fois (`attentes_semees`) : un groupe créé plus tard n'attend rien tant que Julien ne coche pas.
- Dates supplémentaires d'une carte : l'iPhone réécrit (ordre, `type=pref`, paramètre de la date sans année retiré). Comparer des valeurs ; l'an 1604 veut dire « sans année ». Le libellé natif d'Apple pour les dates s'affiche « fête » en français : ne pas l'utiliser pour le mariage.
- La recherche automatique de logos ne couvre qu'une fiche de société sur dix : le logo glissé est le chemin principal.
- Treemich range le mariage et le divorce sur le couple, pas sur la personne : lire `GET /relationships`, écrire par `PATCH /people/<id>/relationships`. Les évènements de vie d'une personne ne les contiennent jamais.
- carnet écrit dans le vrai compte iCloud : Watchtower est désactivé, toute mise à jour est manuelle dans Portainer.
- Treemich limite les connexions et le rythme des requêtes : une seule session réutilisée.
- Pousser sur `main` reconstruit et republie l'image `latest`.
- Les 19 tests d'interface s'appuient sur des textes, des rôles d'accessibilité et quelques noms internes (`.ligne`, `.message`, `nav.onglets`, `.tranche`, `.jauge`, `.volet-liste`) : les conserver pendant l'habillage.
- Tant que l'ancien et le nouvel habillage coexistent, un écran pas encore refait peut se dégrader sans qu'un test le voie : regarder les captures de tous les écrans à chaque étape.
- Mode lecture seule : toute nouvelle écriture vers un service extérieur doit appeler `c.exiger_ecriture(...)` et passer par un client gardé (`_garde`).

## Retour arrière

- Copier `/state` avant la mise en service de la 2.7.0.
- `CARNET_VERSION=2.7.2` dans Portainer pour revenir avant la 2.8 ; la base est la même (les tables de la 2.8 sont ignorées). Ce qui a été écrit dans iCloud ou Treemich par la 2.8 ne revient pas : utiliser « Défaire » avant, ou la sauvegarde d'iCloud.

## Non-objectifs

- Pas de multi-utilisateur, pas d'import Gmail ni Outlook, pas de graphique.
