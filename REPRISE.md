# Reprise — carnet

Fichier à lire en premier dans une nouvelle session, et à mettre à jour à chaque fin de session, dans le même commit que le code.

## État (11/11/2026)

- **2.7.1 sur `main`** : la 2.7.0 (nouvel habillage) plus la sonde avant la 2.8.0. Julien a la 2.7.0 en service ; « À traiter » est vide chez lui.
- **2.8.0 : grill terminé** ([`docs/2.8-grill.md`](docs/2.8-grill.md)) **et sonde faite** ([`docs/sonde-2.8.md`](docs/sonde-2.8.md)) : 437 fiches incomplètes sur 563, dont 406 faute de photo ; aucun mariage dans Treemich ; champs nouveaux absents partout.
- Dossier « tel que construit » : [`docs/dossier.md`](docs/dossier.md).

## Prochaine étape

1. Trancher avec Julien ce que la sonde a ouvert : attentes de photo, groupe personnel sans attentes, mariage sans Treemich.
2. Écrire le dossier de la 2.8.0 à partir du grill et de la sonde, puis un passage au conseil (deux si le conseil le juge : c'est une grosse version).
3. Plan d'implémentation, puis code, en une seule livraison.
4. Après une semaine d'usage de la 2.7.0 : document du socle et planche de couleurs.

## Décisions tranchées

- iCloud est la source maître ; toute modification faite sur l'iPhone repasse par « À traiter ».
- Aucune suppression automatique ; la nuit n'écrit que les mises à jour sûres.
- Trois onglets : À traiter, Contacts, État.
- Le nouvel habillage (minimalisme, tuiles bento pour État, sombre par défaut et clair selon l'appareil, shadcn-svelte, ocre conservé) **remplace** l'actuel, sans version en parallèle (décision du 11/11/2026).
- L'habillage ne change aucune route de l'API ni le schéma de la base, ni les textes, ni la navigation ; les tests d'interface ne sont pas réécrits.
- L'anneau de progression, la jauge autour de l'avatar et l'index en tranche sont gardés et reteintés.
- Le mot de passe reste `CARNET_PASSWORD` ; connexion unique plus tard, avec l'Anneau unique.
- Conseil du 11/11/2026 : ménage, habillage et parcours sont trois livraisons séparées.
- Habillage 2.7.0 : les couleurs gardent leurs noms d'origine (`--color-cuir`, `--color-papier`…), seules leurs valeurs changent ; le clair se fait par `prefers-color-scheme`, sans bouton. Julien a trouvé le premier essai (neutres froids, bouton plein neutre) trop froid : les neutres sont teintés vers l'ocre et le bouton plein est en ocre.
- shadcn-svelte n'est pas introduit dans carnet en 2.7.0 : les classes maison portent l'habillage. Il viendra avec le premier composant qui en a besoin (fenêtre, menu), sans doute en 2.8.0.

## Pièges

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
