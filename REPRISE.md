# Reprise — carnet

Fichier à lire en premier dans une nouvelle session, et à mettre à jour à chaque fin de session, dans le même commit que le code.

## État (11/11/2026)

- **2.7.2 sur `main`** : la 2.7.0 (nouvel habillage), la sonde, et l'essai avant la 2.8.0. Julien a la 2.7.0 en service.
- **2.8.0** : grill, sonde, dossier en version 2 et conseil faits ([`docs/2.8-dossier.md`](docs/2.8-dossier.md), [`docs/2.8-conseil.md`](docs/2.8-conseil.md)). **L'essai est en cours côté Julien** ([`docs/essai-2.8.md`](docs/essai-2.8.md)) : on attend ses deux rapports et ce qu'il voit sur l'iPhone.
- Dossier « tel que construit » : [`docs/dossier.md`](docs/dossier.md).

## Prochaine étape

1. Lire les deux rapports de l'essai et les réponses de Julien ; appliquer le tableau « Ce qui en dépend » de `docs/essai-2.8.md` au dossier.
2. Coder la 2.8.0 en suivant le plan du dossier (étapes 1 à 13), en une seule livraison ; l'import unique est la ligne de coupe.
3. Après une semaine d'usage de la 2.7.0 : document du socle et planche de couleurs.

## Décisions tranchées

- iCloud est la source maître ; toute modification faite sur l'iPhone repasse par « À traiter ».
- Aucune suppression automatique ; la nuit n'écrit que les mises à jour sûres.
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

- Treemich range le mariage et le divorce sur le couple, pas sur la personne : lire `GET /relationships`, écrire par `PATCH /people/<id>/relationships`. Les évènements de vie d'une personne ne les contiennent jamais.
- carnet écrit dans le vrai compte iCloud : Watchtower est désactivé, toute mise à jour est manuelle dans Portainer.
- Treemich limite les connexions et le rythme des requêtes : une seule session réutilisée.
- Pousser sur `main` reconstruit et republie l'image `latest`.
- Les 19 tests d'interface s'appuient sur des textes, des rôles d'accessibilité et quelques noms internes (`.ligne`, `.message`, `nav.onglets`, `.tranche`, `.jauge`, `.volet-liste`) : les conserver pendant l'habillage.
- Tant que l'ancien et le nouvel habillage coexistent, un écran pas encore refait peut se dégrader sans qu'un test le voie : regarder les captures de tous les écrans à chaque étape.
- Mode lecture seule : toute nouvelle écriture vers un service extérieur doit appeler `c.exiger_ecriture(...)` et passer par un client gardé (`_garde`).

## Retour arrière

- Copier `/state` avant la mise en service de la 2.7.0.
- Mettre `CARNET_VERSION=2.6.4` dans Portainer pour revenir à l'habillage actuel ; la base est la même.

## Non-objectifs

- Pas de multi-utilisateur, pas d'import Gmail ni Outlook, pas de graphique.
