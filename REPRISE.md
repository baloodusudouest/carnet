# Reprise — carnet

Fichier à lire en premier dans une nouvelle session, et à mettre à jour à chaque fin de session, dans le même commit que le code.

## État (11/11/2026)

- **En service : 2.6.4** (branche `main`), 80 tests du back et 19 tests d'interface.
- Dossier « tel que construit » écrit : [`docs/dossier.md`](docs/dossier.md), avec le parcours des clics et des écrans et 9 écarts par rapport au socle.
- Branche `habillage-socle` : le dossier et ce fichier ; aucun code modifié.

## Prochaine étape

1. Passage au conseil sur les écarts.
2. Nouvel habillage, plan en 7 étapes de la section 6 du dossier, sur la branche `habillage-socle`.
3. Mise en service en 2.7.0, à la place de l'habillage actuel.

## Décisions tranchées

- iCloud est la source maître ; toute modification faite sur l'iPhone repasse par « À traiter ».
- Aucune suppression automatique ; la nuit n'écrit que les mises à jour sûres.
- Trois onglets : À traiter, Contacts, État.
- Le nouvel habillage (minimalisme, tuiles bento pour État, sombre par défaut et clair selon l'appareil, shadcn-svelte, ocre conservé) **remplace** l'actuel, sans version en parallèle (décision du 11/11/2026).
- L'habillage ne change aucune route de l'API ni le schéma de la base.

## Pièges

- carnet écrit dans le vrai compte iCloud : Watchtower est désactivé, toute mise à jour est manuelle dans Portainer.
- Treemich limite les connexions et le rythme des requêtes : une seule session réutilisée.
- Pousser sur `main` reconstruit et republie l'image `latest`.
- Les 19 tests d'interface s'appuient sur des textes et des rôles d'accessibilité : un changement de libellé les casse.

## Retour arrière

- Copier `/state` avant la mise en service de la 2.7.0.
- Mettre `CARNET_VERSION=2.6.4` dans Portainer pour revenir à l'habillage actuel ; la base est la même.

## Non-objectifs

- Pas de multi-utilisateur, pas d'import Gmail ni Outlook, pas de graphique.
