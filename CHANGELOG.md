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
