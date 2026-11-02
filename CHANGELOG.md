# Journal des versions

## 1.3.0 — en cours

### Lot 1 · Filet de sécurité
- Une seule opération longue à la fois, tenue jusqu'à la fin du travail entier (la tâche de nuit ne laisse plus passer une écriture iCloud entre deux étapes). Si une opération tourne à l'heure de la nuit, la tâche réessaie toutes les 10 min pendant 3 h au lieu de sauter la nuit.
- La nuit commence par une copie chiffrée de la base, avant toute écriture ; chaque étape est isolée (une veille en erreur n'empêche plus la sauvegarde).
- Écritures « d'un seul tenant » dans `etat` : une recherche de photos HD ou d'affiches ne peut plus effacer un choix manuel ni une coche « posée » faits pendant qu'elle tournait. Les liaisons relisent la fiche juste avant de l'écrire.
- Un contact remis en révision garde son affiche et sa coche « posée ».
- Version du schéma de la base (`PRAGMA user_version`), migrations numérotées, copie `carnet.db.avant-vN` avant chaque migration.
- Images Docker étiquetées `latest`, `1.3.0` et `sha-<commit>` : retour à une image précédente possible dans Portainer.
- Liste, statut et bilan gardés en mémoire tant que la base ne change pas ; un seul appel au bilan au chargement.

### Lot 2 · L'iPhone ne perd plus rien
- La veille de nuit remet toujours en Révision ce qui a changé sur l'iPhone (le mode « journal » disparaît) : fiche modifiée, vérifiée ou pas encore, fiche nouvelle, fiche supprimée.
- Une fiche supprimée sur l'iPhone n'est plus recréée en silence : le contact repasse en Révision (« Valider » la recrée, « Mettre de côté » la laisse supprimée).
- Avant d'écrire, carnet compare l'ETag de chaque carte à la dernière lecture : une carte changée sur l'iPhone entre-temps n'est pas écrasée, elle part en Révision avec sa nouvelle version.
- Une carte créée par carnet (UID « carnet-… ») et modifiée sur l'iPhone revient à son contact par l'UID au lieu de devenir un nouveau contact.
- Fusion : liaisons Immich/Treemich, photo HD, affiche et fiche iCloud du contact absorbé passent au contact gardé ; sa carte iCloud en double est proposée au retrait.

### Lot 4 · Liaisons sûres et LinkedIn incrémental
- Chaque nuit, après relecture d'Immich et Treemich, les correspondances sûres sont liées seules : même nom, une seule personne Immich et un seul contact de ce nom, même date de naissance complète des deux côtés ; la personne Treemich suit si elle est reliée à ce visage dans Treemich. Journal « liaisons_auto » ; « Annuler » délie et ne repropose plus.
- Une personne Immich ou Treemich ne peut plus être liée à deux contacts (validation refusée).
- LinkedIn : la relation est reconnue par l'adresse de son profil. Un réimport identique ne change rien ; un nouveau poste, une nouvelle société ou un nouveau courriel remplace l'ancienne ligne et, si la fiche portait encore l'ancienne valeur, va dans son brouillon avec le motif « LinkedIn · Poste : X → Y ». Si tu avais retenu autre chose, rien ne te dérange.
- Migration 3 : les lignes LinkedIn déjà importées reçoivent leur identifiant de profil et les doublons laissés par les réimports passés sont retirés (copie de la base faite avant).
