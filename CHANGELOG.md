# Journal des versions

## 2.0.1 — 3 novembre 2026
- **iPhone** : plus rien ne passe sous l'heure et la batterie. En-tête des contacts fixé en haut (recherche, tri, groupes). Groupes dans un menu au lieu de la rangée qui débordait. Index fin des lettres sur le bord droit, à parcourir du pouce comme dans Contacts. Le titre de chaque lettre reste en haut jusqu'à la suivante.
- **PC** : liste et fiche côte à côte dans Contacts (la liste garde sa place) ; dans « À traiter », la liste à gauche et le point choisi à droite, le suivant s'affiche après chaque décision.
- **Tri** par prénom ou par nom (prénom par défaut), gardé sur chaque appareil ; les noms restent affichés « Prénom NOM ».

## 2.0.0 — 3 novembre 2026 — réécriture simplifiée

carnet n'est plus un outil de migration : le grand ménage est fini, **iCloud est la source maître** et carnet en est le gardien. Mêmes services rendus, beaucoup moins de mécanique.

### Ce qui change pour toi
- **3 onglets**, identiques sur PC et iPhone : **À traiter** (toutes les décisions au même endroit), **Contacts** (photo, affiche et logo dans la fiche), **État**.
- **Valider écrit tout de suite** dans iCloud, après un aperçu des champs qui changent, avec « Annuler » pendant 10 s.
- **La nuit** n'écrit que ce qui est sûr : liaison exacte, photo d'une fiche liée qui n'en a pas, date de naissance manquante connue sans conflit, nouveau poste ou société LinkedIn quand la fiche portait l'ancien. 20 fiches au plus, jamais de suppression, une carte changée sur l'iPhone n'est jamais écrasée.
- Toute fiche **modifiée, créée ou supprimée sur l'iPhone** arrive dans « À traiter » : Garder, Revenir à avant (carte remise à l'identique), Remettre la fiche.
- **Sauvegardes** : copie complète d'iCloud avant la première écriture du jour et chaque nuit, dans `/state/sauvegardes` (hors OneDrive), 30 jours puis une par mois pendant un an, 2 Go au plus. Bouton pour **remettre une ou plusieurs fiches** comme dans une sauvegarde.
- **Portraits** : recadrés à partir des visages déjà repérés par Immich ; tu choisis parmi les 6 plus grands.
- **Home Assistant** : nouvelle adresse `/ha/contacts` (avec `carnet_id` stable). Les adresses de la 1.3 (`/ha/personnes`, `/ha/anniversaires`, `/ha/invite`, `/ha/portraits/candidats`, `/ha/portrait`) et les champs de `/status` lus par le paquet restent identiques : **rien à changer dans HA**.
- **LinkedIn** : CSV ou API de portabilité, comme avant ; seuls les changements remontent.

### Garde-fous ajoutés après une relecture indépendante
- Une écriture ne remplace que les propriétés des champs qui changent : titre et suffixe du nom, service, boîte postale, étiquettes personnalisées, IMPP, notes… restent tels qu'iCloud les a.
- Une page restée ouverte n'écrase jamais une modification faite sur l'iPhone entre-temps : l'interface renvoie la version qu'elle a affichée ; si elle a changé, rien n'est écrit et les deux versions vont en conflit.
- La nuit ne touche jamais une fiche qui attend ta relecture, et revérifie le poste LinkedIn au moment d'écrire.
- Une carte annoncée par iCloud mais non fournie est relue seule ; s'il en manque encore, la lecture est refusée (plus jamais prise pour une suppression).
- Photo par lien : le mot de passe iCloud ne part que vers iCloud.
- La base suit iCloud aussitôt la carte écrite, même si un groupe échoue ensuite ; fusion : la carte est supprimée avant de toucher aux groupes ; « Remettre la fiche » et la restauration remettent aussi les groupes ; deux groupes du même nom sont gérés.
- Jamais d'écriture ni de suppression sans ETag ; reprise retentée tant qu'elle n'a pas réussi ; plus de journal d'accès (les adresses HA contiennent des noms).

### Reprise de la 1.3
Au premier démarrage : lecture complète d'iCloud (elle sert de référence, rien n'est signalé ni écrit), puis reprise unique depuis l'ancienne base (`/state/carnet.db`, clé `CARNET_DB_KEY` déjà présente) : liaisons et refus, photos choisies, affiches et leur pose, relations LinkedIn. L'ancienne base n'est jamais modifiée. La copie Synology faite par la 1.3 (identifiants « carnet-… ») est remplacée par un miroir exact d'iCloud.

### Retiré
Lecteurs Gmail et Outlook (un import .vcf générique reste), SQLCipher pour la nouvelle base (`carnet2.db` en SQLite simple, dossier protégé), test de restauration de base et clé Enpass, OpenCV et le modèle YuNet, simulation manuelle d'écriture, plafonds réglables, période à blanc, table `etat` à 38 clés. Serveur : 8 100 → 6 000 lignes (aucun fichier au-delà de 600), 88 → 54 adresses, 34 → 21 variables ; interface : 5 200 → 1 500 lignes.

### Retour arrière
`CARNET_VERSION=1.3.1` et `CARNET_VEILLE_HEURE=off` (la nuit de la 1.3 ne démarre pas : sinon elle réécrirait des fiches devenues périmées), puis Recreate. L'ancienne base est restée intacte.

## 1.3.1 — 3 novembre 2026
- Photos : bouton ↻ en haut de la page, « Chercher les manquants » ou « Tout régénérer », qui enchaîne photos HD, affiches et logos pour tous les contacts, avec une barre de progression par étape (aussi visible si la recherche a été lancée ailleurs). Tes choix ne sont jamais changés.
- État › « Changements pour iCloud » : tout ce qui partirait dans iCloud, sur une seule liste à jour (relue en ouvrant la page ou avec ↻) — modifications champ par champ (avant → après), créations, suppressions, groupes. Un toucher ouvre la liste ; pour chaque fiche, **Valider** (écrite dans iCloud tout de suite) ou **Revoir** (repasse en Révision, rien n'est écrit), puis « Appliquer » ; « Tout valider » en un geste. Les suppressions s'y confirment aussi.
- Affiches pour tous les contacts liés à Immich : plus de choix par groupe (la nuit aussi). Les logos gardent leurs groupes.

## 1.3.0 — 3 novembre 2026

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

### Lot 5 · Synchro iCloud autonome
- Chaque nuit, après la veille et les liaisons, carnet écrit dans iCloud les fiches validées qui ont changé. Les deux premières semaines sont « à blanc » : le plan est noté au journal, rien n'est écrit (passage anticipé possible).
- Garde-fous : aucune suppression la nuit (contacts mis de côté, doublons, groupes : elles attendent ton accord dans la page iCloud) ; au plus max(10, 5 %) créations et max(20, 10 %) modifications par nuit, sinon rien n'est écrit et une alerte est notée ; rien d'écrit si la veille de la nuit est en erreur ; interrupteur pour couper.
- « Synchroniser maintenant » : même plan, mêmes garde-fous, écriture réelle.
- `/status` (Home Assistant) expose la dernière synchro : mode, compteurs, alerte.
- Sauvegardes d'iCloud avant écriture : toutes celles des 14 derniers jours, puis une par mois pendant un an.

### Lot 3 · Au pouce
- Même navigation sur PC et iPhone : **À traiter** (boîte unique : fiches à relire classées par motif, liaisons à confirmer en un toucher, liaisons faites seules la nuit à annuler, points à compléter, photos), **Contacts** (recherche, groupes, import), **Photos** (photo HD, affiche, logos), **État** (synchro iCloud, veille, sauvegardes, test de restauration, archives). Badges : nombre à traiter, pastille rouge sur État en cas de souci.
- Révision sur iPhone : fiche retenue en haut, une carte par champ à trancher (choix de 48 px), champs sans choix repliés, téléphones/courriels/adresses cochables et modifiables, groupes, noms proches, barre Passer · De côté · Valider fixée en bas. La fiche suivante est chargée d'avance.
- Révision sur PC : colonne « Fiche retenue » sombre (mode sombre respecté), valeur choisie en fond plein, en-tête et boutons qui restent visibles, photo illisible signalée au lieu d'une image cassée.
- Photos : groupes des affiches et recherches lancées depuis l'onglet (plus besoin du PC) ; états vides qui disent quoi faire.
- Ergonomie : champs en 16 px sur écran tactile (plus de zoom Safari), cibles de 44 px, bord des champs contrasté (3,4:1), boutons désactivés reconnaissables, « À compléter » sans sections vides, messages qui s'effacent au changement de page et proposent « Rouvrir » après une validation.
- La fiche contact sur iPhone ouvre la Révision (« Modifier la fiche »).

### Corrections après relecture indépendante
- Une relation LinkedIn détachée (« pas la même personne ») reste détachée au réimport.
- Coupe-circuit : si plus de 5 % des fiches vues la dernière fois manquent d'un coup dans iCloud, ou si la lecture est incomplète, rien n'est remis en révision ni écrit ; « Relire quand même » dans État quand les suppressions sont voulues.
- ETag relu quand iCloud ne le renvoie pas après une écriture (plus de faux conflits ni de boucle révision ↔ écriture).
- Les UID des cartes d'avant une fusion sont gardés à part (`icloud_anciens`) : la carte en double reste proposée au retrait même après une écriture.
- Écriture et veille ne réécrivent plus tout le suivi iCloud : un choix fait pendant qu'elles tournent reste.
- « Délier » refuse désormais la personne pour ce contact (pas de liaison automatique la nuit suivante) ; une liaison faite seule ne remplace jamais une photo existante.
- Veille : des cartes illisibles ne bloquent plus les nuits suivantes ; une carte reconnue par son contenu revient à son contact.
- Paquet Home Assistant : capteur `sensor.carnet_synchro_icloud`, alerte `binary_sensor.carnet_synchro_en_echec`.
