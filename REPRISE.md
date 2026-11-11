# Reprise — carnet

Fichier à lire en premier dans une nouvelle session, et à mettre à jour à chaque fin de session, dans le même commit que le code.

## État (11/11/2026)

- **2.6.5 prête** (branche `main`) : mode lecture seule, annonce avant un traitement par lot, restes de la 1.3 retirés, versions exactes. 83 tests du back et 20 tests d'interface verts. Pas encore mise en service sur le NAS.
- En service sur le NAS : 2.6.4.
- Dossier « tel que construit » : [`docs/dossier.md`](docs/dossier.md). Premier tour du grill de la 2.8.0 : [`docs/2.8-grill.md`](docs/2.8-grill.md).

## Prochaine étape

1. **Julien met la 2.6.5 en service**, puis essaie pour de vrai le retour à la 2.6.4 par `CARNET_VERSION` (étape 5 du plan).
2. **2.7.0, nouvel habillage seul** : commence par un écran réel (À traiter) à faire valider par Julien, en sombre et en clair, sur PC et iPhone.
3. **2.8.0, parcours et complétude** : finir le grill, écrire le dossier, passer au conseil.

## Décisions tranchées

- iCloud est la source maître ; toute modification faite sur l'iPhone repasse par « À traiter ».
- Aucune suppression automatique ; la nuit n'écrit que les mises à jour sûres.
- Trois onglets : À traiter, Contacts, État.
- Le nouvel habillage (minimalisme, tuiles bento pour État, sombre par défaut et clair selon l'appareil, shadcn-svelte, ocre conservé) **remplace** l'actuel, sans version en parallèle (décision du 11/11/2026).
- L'habillage ne change aucune route de l'API ni le schéma de la base, ni les textes, ni la navigation ; les tests d'interface ne sont pas réécrits.
- L'anneau de progression, la jauge autour de l'avatar et l'index en tranche sont gardés et reteintés.
- Le mot de passe reste `CARNET_PASSWORD` ; connexion unique plus tard, avec l'Anneau unique.
- Conseil du 11/11/2026 : ménage, habillage et parcours sont trois livraisons séparées.

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
