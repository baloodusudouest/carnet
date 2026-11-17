# Journal des versions


## 2.29.0 — 17 novembre 2026
- **« Pour les journaux »** (fiche › Pour les journaux) : ce qu'on sait d'une personne (passions, manies, petites histoires), pour les rumeurs loufoques de La Récidive (Gazette 0.10). Rangé par identifiant maison dans la base de carnet seulement, jamais dans iCloud, Synology Contacts ou le kit ; le journal de carnet ne porte jamais le texte. Permis en lecture seule.
- **Gazette** : `GET /gazette/personnes` donne `journaux` ; nouvelle adresse `PUT /gazette/personnes/{personne_id}/journaux` (jeton commun) pour que Gazette garde ici ce que Julien a écrit dans l'édition.
- **Coffre « Contacts »** : section « Pour les journaux (Gazette) » dans le bloc écrit par carnet.
- Schéma 6 (table `journaux`) : la 2.28 rouvre la base sans rien perdre.

## 2.28.0 — 17 novembre 2026
- **Identifiant maison stable.** Chaque fiche reçoit un identifiant propre à carnet (`personne_id`, « p- » + 10 caractères), créé une fois et jamais réutilisé. L'UID iCloud n'en est plus qu'un attribut. Une fiche supprimée garde son identifiant (et son alimentation) ; « Annuler » le remet ; une carte recréée peut le reprendre (`POST /api/personnes/{id}/rattacher`). Une fusion garde l'identifiant de la fiche gardée ; celui de la fiche absorbée pointe vers lui. `personne_id` est ajouté à `/ha/contacts`, `/ha/invite`, `/sillage/personnes`, `/gazette/personnes`, `/douze-points/personnes` (rien d'autre ne change dans ces réponses).
- **Alimentation** (fiche › Alimentation) : allergies, intolérances, « aucune allergie ni intolérance connue », vérifiée le, aliments non aimés, plaisirs coupables. Dans la base de carnet seulement : jamais écrite dans iCloud, Synology Contacts ou le kit. Le journal ne porte jamais son contenu.
- **Home Assistant** : `/ha/invite` donne aussi `allergies` (statut : `inconnu`, `aucune`, `a_connaitre`) et `allergies_verifiees_le` ; nouvelle adresse `/ha/allergies?personne_id=` (ou `?nom=`), statut et date seulement, jamais la liste. Absence d'information = « inconnu », jamais « rien à signaler ».
- **Coffre Obsidian « Contacts »** (volume `/contacts`) : une note par personne dans `Personnes/`, avec un bloc écrit par carnet (fiche, famille et proches reliés par `[[…]]`, alimentation, notes iCloud, liens, identifiants) et une zone « Mes notes » jamais touchée. Les clés ajoutées à la main dans l'en-tête sont gardées ; une note déplacée ou renommée est retrouvée par son `personne_id` ; aucune note n'est renommée, déplacée ni supprimée ; une note sans bloc carnet est laissée telle quelle ; une fiche retirée donne `carnet: retirée`. Garde-fou : rien n'est écrit sans le dossier `Personnes/`. Chaque nuit (interrupteur Connexion › Coffre Contacts, sauvegardé avec les réglages) et à la demande.
- **Base chiffrée** (SQLCipher 4, `CARNET_DB_KEY`) : une base en clair est chiffrée au démarrage après vérification ; la copie en clair est gardée 14 jours pour revenir à la 2.27, puis effacée. Base chiffrée sans clé ou mauvaise clé : carnet ne démarre pas. Les sondes lisent aussi une copie chiffrée.
- Stack : `CARNET_DB_KEY`, volume `/contacts`, `/state` et `/contacts` montés avec `create_host_path: false` (dossiers partagés chiffrés).
- Tests : 18 nouveaux (identifiant, fusion, suppression, rattachement, alimentation, Home Assistant, chiffrement, coffre) ; 165 du serveur et 75 de l'interface au vert.
## 2.27.0 — 17 novembre 2026
- **Genre pour Gazette.** `GET /gazette/personnes` donne aussi `genre` (« femme », « homme », « autre », vide si inconnu), le genre choisi dans carnet ou repris de Treemich. Gazette 0.9.0 s'en sert pour accorder le titre de son journal à scandale (« Elle est revenue » / « Il est revenu »). Elle donne aussi `immich_id` (la personne d'Immich liée à la fiche, vide sinon), pour que Gazette cherche les photos de l'invité entre deux séjours. Rien d'autre ne change ; toujours ouvert seulement par `MAISON_JETON`.
- Tests : `genre` vide sans genre, suit un genre défini ; `immich_id` d'une fiche liée.

## 2.26.0 — 16 novembre 2026
- **Réglages dans l'appli.** L'heure de la nuit (ou nuit désactivée), les émojis → groupes, le nom du carnet d'adresses de Synology Contacts et la vérification de son certificat se changent dans Réglages › « Réglages d'usage », plus dans la stack. Ils sont gardés dans `/state/reglages.json`. Une nouvelle heure de nuit prend effet tout de suite, sans redémarrer.
  - Au premier démarrage de la 2.26, chaque réglage reprend son ancienne variable si elle est encore dans la stack (`CARNET_VEILLE_HEURE`, `CARNET_EMOJI_GROUPES`, `CARNET_SYNOLOGY_CARNET`, `CARNET_SYNOLOGY_VERIFIER_TLS`), avec une ligne au journal ; ensuite la variable n'est plus jamais lue.
  - Une valeur de mauvais type ou une heure impossible est refusée avec un message clair, rien n'est changé.
- **Sauvegarde pour l'Anneau.** Nouvelle adresse `/externe/sauvegarde`, ouverte seulement par le jeton commun `MAISON_JETON` (fermée s'il est vide) : les réglages d'usage et les interrupteurs « la nuit » de chaque service, la version de carnet, rien d'autre (ni variable, ni chemin, ni secret).
- **Restaurer les réglages.** Dans Réglages : choisir une date parmi les sauvegardes de l'Anneau, voir ce qui changerait (avant → sauvegardé), confirmer. Seuls les réglages changent, une ligne au journal ; permis même en lecture seule. Anneau injoignable : un message, rien d'autre.
- **Anciens noms retirés.** carnet ne lit plus :
  - `CARNET_PASSWORD` : seulement `MAISON_PASSWORD`, 12 caractères au moins, sinon carnet ne démarre pas ;
  - `CARNET_JETON_SILLAGE`, `CARNET_JETON_GAZETTE`, `CARNET_JETON_DOUZE_POINTS` : `/sillage/`, `/gazette/` et `/douze-points/` ne s'ouvrent plus qu'avec `MAISON_JETON` ;
  - `CARNET_MILLESIME_JETON` et `KIT_API_TOKEN` : carnet envoie `MAISON_JETON` à Millésime et au kit d'urgence (kit 2.4.0) ;
  - `CARNET_SILLAGE_URL` : le lien « Sillage » de la fiche vient seulement de l'annuaire de l'Anneau.
- `CARNET_LECTURE_SEULE` reste (forçage de carnet seul), comme `CARNET_HA_TOKEN` (Home Assistant).
- Tests : 147 du serveur (réglages, reprise une seule fois, mauvais types, nuit réveillée, sauvegarde, restauration, anciens jetons refusés) et l'écran Réglages sur PC et iPhone.
## 2.25.0 — 16 novembre 2026
- **Variables communes de la maison** (module `app/maison.py` du socle 0.5.0, copié tel quel) :
  - mot de passe : `MAISON_PASSWORD`, repli sur `CARNET_PASSWORD` ;
  - lecture seule : `MAISON_LECTURE_SEULE` pour toute la maison ; `CARNET_LECTURE_SEULE`, si elle dit oui ou non, l'emporte ;
  - jeton commun `MAISON_JETON` (et `MAISON_JETON_ANCIEN` pendant un changement) accepté sur `/sillage/`, `/gazette/` et `/douze-points/`, en plus des jetons propres actuels ; `/ha/` garde son jeton de Home Assistant ;
  - jetons envoyés au kit d'urgence et à Millésime : l'ancien jeton de la paire tant qu'il est dans la stack, puis `MAISON_JETON` ;
  - lien « Sillage » de la fiche : adresse lue dans l'Anneau (`/externe/services`, Anneau 0.7.0 ; adresse privée quand carnet est ouvert par Tailscale), repli sur `CARNET_SILLAGE_URL`.
- Rien ne change tant que la stack n'a pas les nouvelles variables : chaque ancien nom reste lu.
- Tests : jeton commun sur les trois portes (pas sur `/ha/`), variables communes et replis, copie du module non retouchée.

## 2.24.2 — 15 novembre 2026
- **Genre synchronisé avec Treemich.**
  - Les genres validés par lot (« Enregistrer les genres proposés ») partent **tout de suite** dans Treemich pour les personnes reliées dont l'arbre ne connaît pas le genre (avant : à la nuit suivante). La nuit et « Synchroniser » rattrapent ce qui a échoué. Rien n'est écrasé dans l'arbre.
  - **« Autre »** s'écrit aussi dans l'arbre (`OTHER`), et un « Autre » de l'arbre est repris dans carnet.
  - **Désaccord** : quand le genre choisi dans carnet n'est pas celui de l'arbre, un point « Genre différent dans Treemich » arrive dans À traiter › Liens. « Garder … (carnet) » l'écrit dans l'arbre (seul cas où carnet y écrase un genre), « Prendre … (Treemich) » remplace le choix fait dans carnet, « Laisser comme ça » ne repose plus la question.
- Tests : 140 du serveur.

## 2.24.1 — 15 novembre 2026
- **Sillage reçoit la date de décès.** L'adresse `/sillage/personnes` donne maintenant, pour chaque fiche liée à Immich, la date de décès que carnet connaît (`deces` : carte iCloud, Treemich ou saisie dans carnet ; vide sinon). Sillage 0.14 y arrête le chemin de la personne. Rien d'autre ne change ; lecture seule, comme avant.
- Tests : 137 du serveur.

## 2.24.0 — 15 novembre 2026
Tous les champs de la fiche de contact de l'iPhone, d'après la sonde 2.22.4 passée sur une vraie carte (iOS 27). Le numéro 2.23 reste réservé au dossier Paperless.
- **Champs de nom** : titre, second prénom, suffixe, nom de naissance, prénom / second prénom / nom de famille / société phonétiques, prononciation du prénom et du nom. Le nom affiché reste « Prénom NOM » partout (carnet, Immich, Treemich, Home Assistant). Le second prénom a maintenant son champ : il n'est plus collé au prénom.
- **Libellés corrigés** : ce que carnet appelait « Prononciation du prénom / du nom » depuis la 2.8 est en réalité le prénom et le nom *phonétiques* de l'iPhone ; ils portent maintenant ce nom, et la vraie « prononciation » de l'iPhone a ses deux champs.
- **Dates libres** : toute date de la fiche avec son libellé (celui d'Apple ou un libellé écrit à la main, « Diplôme »), en plus de Fête, Mariage et Décès.
- **Messageries instantanées** : Skype, MSN, GoogleTalk, Facebook, AIM, Yahoo, ICQ, Jabber, écrites comme le fait l'iPhone.
- **Types gardés** : numéros « école », Apple Watch, fax domicile, fax travail, pager (ils devenaient « autre ») ; courriels et adresses « école », « autre » ou à libellé écrit à la main ; URL domicile, travail, école ; profils Flickr, Myspace, Sina Weibo ; noms associés fils, fille, mari, épouse (ils devenaient « enfant » et « autre »). Ces numéros particuliers ne sont touchés par aucune règle de groupe et ne comptent pas comme « second portable ».
- **Sonnerie et son SMS** : montrés sur la fiche, en lecture seule (ils se règlent sur l'iPhone).
- **Éditeur comme l'iPhone** : les champs courants sont toujours là ; les autres s'ajoutent par « Ajouter un champ » et restent visibles dès qu'ils sont remplis, dans l'ordre de l'iPhone.
- **Rien n'est perdu à l'écriture** : comme avant, seules les lignes du champ modifié sont réécrites ; le reste de la carte iCloud reste tel que l'iPhone l'a écrit.
- Au premier démarrage, les cartes déjà lues sont relues une fois avec la nouvelle lecture, sans rien signaler ni écrire dans iCloud.
- **Ce que carnet ne fait pas** : les pronoms (iCloud les donne chiffrés par Apple : ni lus ni écrits, gardés tels quels) ; le code de validation (absent de la carte) ; QQ et Gadu-Gadu (gardés dans la carte, pas montrés) ; le libellé « iPhone » d'un numéro (reste « mobile ») ; un libellé écrit à la main sur un numéro (comme avant) ; créer dans carnet un nouveau libellé libre pour un courriel ou une adresse (ceux de l'iPhone sont gardés).
- Jamais essayé sur la vraie installation. À regarder au premier essai : la copie vers Synology Contacts avec les nouveaux champs.
- Tests : 209 réussis (serveur et écrans PC et iPhone).

## 2.22.4 — 15 novembre 2026
- **Sonde des champs de la fiche iPhone** (`python -m app.sonde_champs "Essai Champs"`), avant d'ajouter à carnet tous les champs de l'iPhone. Lecture seule, sur une copie de la base : iCloud n'est pas contacté. Elle liste les propriétés des cartes (noms, paramètres, nombre de cartes, sans aucune valeur ni nom) et montre en entier la seule fiche d'essai demandée, sans sa photo. Rapport dans le dossier de données (`rapport-sonde-champs.md`). Aucun changement dans l'appli elle-même.

## 2.22.3 — 15 novembre 2026
- **Le genre pour tous les contacts.** Toute fiche qui a un prénom ou un nom et pas encore de genre a sa question « Femme ou homme ? » (une entreprise seule n'en a pas). Elles sont dans une tuile à part d'À traiter, « Genre à préciser », qui ne compte pas dans le chiffre de l'onglet ; la tuile des liens s'appelle « Liens à corriger ». La question n'est pas répétée en tête de fiche : le champ Genre y est déjà.
- **Genre proposé d'après le prénom, validé par lot.** Chaque question dit le genre que le prénom laisse supposer, quand il est sans ambiguïté (Camille, Dominique, Claude, Stéphane… n'ont pas de proposition). « Enregistrer les genres proposés » les enregistre tous d'un coup, après annonce ; rien n'est enregistré sans cette validation. Le lot n'écrit ni dans iCloud ni dans Treemich : l'arbre reçoit les genres qui lui manquent à « Synchroniser » ou la nuit.
- Nouvelle dépendance : `gender-guesser` 0.4.0 (liste de prénoms par pays ; licence GPLv3, données sous GNU FDL), installée à côté de carnet, rien n'en est copié dans le dépôt. Sans elle, carnet ne propose rien et le reste marche.
- Les listes d'À traiter s'affichent par tranches de 30 (« Afficher la suite »).
- Tests : 202 réussis (serveur et écrans PC et iPhone).

## 2.22.2 — 15 novembre 2026
- **« Femme ou homme ? » : trois boutons de couleur.** Dans À traiter › Liens et genre, chaque question porte Femme en rose, Homme en bleu et Autre en violet, puis Ignorer. Les mêmes couleurs marquent le genre choisi sur la fiche.

## 2.22.1 — 15 novembre 2026
- **Douze points lit les prénoms et les noms.** Nouvelle adresse `/douze-points/personnes`, ouverte par son propre jeton (`CARNET_JETON_DOUZE_POINTS` ; dans la stack : `DOUZE_POINTS_CARNET_JETON`, la même valeur des deux côtés) ; vide : adresse fermée. Elle ne donne que le prénom et le nom des fiches (ni date, ni téléphone, ni groupe), sans les fiches d'entreprise ni les personnes décédées. Sert à choisir les invités d'une soirée en tapant leur nom. carnet n'écrit rien. Jamais essayée sur la vraie installation.

## 2.22.0 — 15 novembre 2026
- **Une sœur n'est plus notée « frère ».** Quand Treemich ne connaît pas le genre d'une personne, carnet proposait « frère » pour toute la fratrie. Il propose maintenant « frère ou sœur », comme il proposait déjà « parent » faute de savoir père ou mère. « frère ou sœur » est un nouveau type de nom associé ; Apple n'a pas de libellé neutre pour la fratrie, il est donc écrit dans iCloud comme libellé personnalisé, que l'iPhone affiche tel quel.
- **Champ genre sur la fiche** : Femme, Homme, Autre, sous les informations ; toucher le genre choisi le retire. Le genre reste dans la base de carnet (l'iPhone n'a pas ce champ, rien n'est écrit dans iCloud). Il décide du libellé des liens : sœur ou frère, mère ou père ; « Autre » donne « frère ou sœur » et « parent ».
- **Treemich dans les deux sens, sans rien écraser.** Le genre des personnes reliées est repris de l'arbre à chaque lecture (« d'après Treemich »). Un genre choisi dans carnet passe avant, et il est écrit dans Treemich seulement si l'arbre ne le connaît pas : tout de suite, sinon à « Synchroniser » de Connexion › Treemich, ou la nuit si la nuit de Treemich est allumée. Si l'arbre dit autre chose, la fiche le signale et rien n'y est écrit. « Autre » n'est pas écrit dans Treemich. **L'écriture du genre dans Treemich n'a jamais été essayée sur la vraie installation** (forme supposée : `PATCH /people/<id>` avec `gender`) : carnet relit l'arbre juste après, et s'il n'y retrouve pas le genre, il arrête d'en écrire et le note au journal.
- **Les liens déjà écrits se corrigent dans À traiter**, nouvelle tuile « Liens et genre ». D'abord « Femme ou homme ? » pour chaque personne notée « frère » (ou « frère ou sœur ») dont le genre est inconnu : une seule question par personne, même si elle est notée sur plusieurs fiches. Ensuite une ligne par lien à accorder (frère → sœur, parent → mère…), avec « Corriger », ou « Corriger tous les liens » par lot (plafond d'écritures habituel). carnet ne corrige rien tout seul. Seuls les noms associés portés par une seule fiche sont concernés.
- Base : table `genres` (schéma 4, un ajout : la 2.21 rouvre la base).
- Tests : 199 réussis (serveur et écrans PC et iPhone).

## 2.21.0 — 15 novembre 2026
- **Millésime dans carnet.** Connexion a une icône Millésime : photos à dater, à trancher, groupes à nommer, visages à analyser sur le PC, et le message « allume le PC » quand des visages attendent. carnet lit `GET /api/etat` de Millésime toutes les 10 minutes au plus, avec le jeton `CARNET_MILLESIME_JETON` (dans la stack : `MILLESIME_JETON_CARNET`, la même valeur des deux côtés) ; vide : Millésime n'est pas lu. carnet n'écrit rien dans Millésime.
- **Tuile « Sans anniversaire » dans À traiter** : les personnes nommées sur les scans à dater qui n'ont pas de date de naissance dans Immich, avec le nombre de scans où elles apparaissent. Une personne reliée ouvre sa fiche (la date saisie part dans Immich par Connexion › Immich ou la nuit) ; une personne sans fiche est signalée. Comme « Contact incomplet », la tuile ne compte pas dans le chiffre de l'onglet.
- Tests : 187 réussis (serveur et écrans PC et iPhone).

## 2.20.0 — 14 novembre 2026
- **Gazette lit les dates de naissance.** Nouvelle adresse `/gazette/personnes`, fermée tant que `CARNET_JETON_GAZETTE` est vide (dans la stack : `GAZETTE_CARNET_JETON`, la même valeur des deux côtés). Pour chaque fiche : le nom annoncé par Home Assistant (celui d'Immich si la fiche est liée), le nom de la fiche, le prénom, et la date de naissance complète seulement si jour, mois et année sont connus. Les personnes décédées ne sont pas données. Lecture seule : Gazette n'écrit rien dans carnet.



## 2.19.0 — 14 novembre 2026
- **Les proches s'ouvrent d'un clic.** Sur une fiche, chaque nom associé (conjoint, mère, père, frère, sœur, enfant…) devient un lien vers la fiche de cette personne quand une seule fiche porte ce nom (comparé sans accents ni majuscules, sur le nom affiché puis le surnom). Deux fiches au même nom, ou aucune : le nom reste du texte, rien n'est deviné.
## 2.18.2 — 14 novembre 2026
- **carnet passe en argent** (`#b7c0cc`, l'ocre avant). L'or est gardé pour l'Anneau, qui montre toutes les applis côte à côte : carnet, Sillage et l'Anneau avaient trois ors voisins qu'on ne distinguait plus. Boutons pleins, onglet actif, compteurs, anneau de progression et icône (onglet du navigateur, écran d'accueil) changent ; rien d'autre.

## 2.18.1 — 14 novembre 2026
- **Deux portables : une icône par type.** Dans À traiter › Mise en forme, chaque portable de la fiche est affiché sur sa ligne, avec deux boutons à icône : une mallette « Travail » et un téléphone « Mobile ». Le type actuel est déjà allumé ; un toucher change le choix, puis « Écrire dans iCloud ». La question devient « lequel est travail, lequel mobile ? ».

## 2.18.0 — 14 novembre 2026
- **Plusieurs portables sur une fiche : à traiter.** Quand une fiche a deux portables ou plus et qu'aucun n'est noté « travail » à côté d'un « mobile », elle arrive dans À traiter (tuile Mise en forme) : pour chaque numéro, Pro (écrit « travail ») ou Perso (écrit « mobile »), puis « Écrire dans iCloud ». Le choix est gardé contre les règles de groupe. « Laisser comme ça » ne repose plus la question pour ces numéros.

## 2.17.5 — 13 novembre 2026
- **Le type d'un téléphone changé à la main est gardé.** Dans une fiche d'un groupe « travail » (Collègues, Clients, Artisans et services) ou « proches » (Famille, Amis…), la règle du groupe remettait en silence le type imposé : passer un portable de « travail » à « mobile » donnait « Aucun changement », et « Écrire dans iCloud » restait grisé. Désormais, à l'enregistrement d'une fiche, un numéro déjà présent garde le type affiché dans l'éditeur ; les règles de groupe ne s'appliquent qu'aux numéros nouveaux, et restent proposées dans À traiter.

## 2.17.4 — 13 novembre 2026
- **« Voir les changements » explique un « Aucun changement ».** Un courriel sans « @ » (ou un site non reconnu) était écarté sans un mot, et une saisie qui revient au même une fois mise en forme (le même numéro écrit autrement) ne disait rien : le bouton « Écrire dans iCloud » restait grisé sans raison visible. L'aperçu le dit maintenant, en orange sous les changements.

## 2.17.3 — 13 novembre 2026
- **Les photos en lien vers iCloud ne bloquent plus la copie Synology.** Une photo de contact servie par iCloud est un lien signé qui change à chaque lecture de la carte : carnet croyait que 176 photos avaient changé (seule différence pour 172 fiches). Le lien ne compte plus ; une vraie nouvelle photo se voit toujours à ses autres champs (X-IMAGEHASH…).

## 2.17.2 — 13 novembre 2026
- **La copie Synology n'est plus bloquée par ce que Synology réécrit.** Vu le 13/11 avec Vérifier : Synology Contacts réunit les types répétés (« TYPE=CELL;TYPE=VOICE;TYPE=PREF » devient « TYPE=CELL,VOICE,PREF »), retire le « ; » vide de fin des sociétés et ne garde pas les champs Apple « X-AB… » (dates et libellés personnalisés). carnet croyait donc que 504 fiches avaient changé de téléphone, et la copie de la nuit restait bloquée. Ces réécritures ne comptent plus comme des différences ; un vrai changement de numéro, de photo ou de société compte toujours.

## 2.17.1 — 13 novembre 2026
- **Vérifier Synology montre la forme des différences**, valeurs masquées (chiffres → 9, lettres → a), pour la propriété qui diffère le plus : on voit si c'est le format d'un numéro, un type, une photo… sans aucune donnée. Vu le 13/11 : TEL diffère sur 504 fiches sur 573 (seule différence pour 106).

## 2.17.0 — 13 novembre 2026
- **Synology Contacts se vérifie** (Connexion › Synology › Vérifier) : carnet relit Synology et dit, sans rien écrire, combien de cartes la copie créerait, modifierait ou retirerait, et quelles propriétés diffèrent (PHOTO, NOTE, X-…), avec le nombre de fiches pour chacune. De quoi décider avant « Forcer la copie » quand elle est bloquée. Aucun nom ni valeur dans le rapport.
- Vu le 13/11 : la copie de la nuit est bloquée (524 fiches sur 573 changeraient d'un coup).

## 2.16.1 — 13 novembre 2026
- **Toujours sombre.** Le thème clair est retiré : l'appli est sombre partout, ouverte seule comme dans l'Anneau, quel que soit le réglage du téléphone.

## 2.16.0 — 13 novembre 2026
- **Photos : les propositions qui ne s'affichent plus.** Quand l'image d'une proposition ne se charge pas (la photo n'est plus dans Immich : remplacée par une migration, ou supprimée), la personne est retirée de la liste de Portraits ou d'Affiches. Un message dit combien de personnes sont touchées et propose la solution : « Refaire la recherche pour ces N personnes », qui relit Immich pour elles seules. Rien n'est posé ; une photo déjà en place n'est pas touchée. « Les afficher quand même » les remet dans la liste ; une proposition cassée ne peut pas être posée tant qu'elle est cachée.
- Tests : 114 du back, 35 d'interface.

## 2.15.0 — 13 novembre 2026
- **Sillage lit la liste des personnes dans carnet.** Nouvelle adresse `/sillage/personnes`, fermée tant que `CARNET_JETON_SILLAGE` n'est pas réglé, ouverte avec ce seul jeton (pas celui de Home Assistant). Elle rend les fiches liées à une personne d'Immich : identifiant de la fiche, nom, identifiant Immich, groupes, proche ou non, décédée ou non. Ni téléphone, ni adresse, ni date.
- **Fiche : « Ouvrir dans Sillage »**, dans le bloc Liaisons, quand la fiche est liée à Immich et que `CARNET_SILLAGE_URL` (l'adresse de Sillage dans le navigateur) est réglée.
- Tests : 114 du back.

## 2.14.0 — 13 novembre 2026
- **Connexion commune.** Connecté à l'Anneau, on n'a plus à se connecter ici : l'appli accepte le cookie « maison_session » que l'Anneau pose, quand elle est servie par la même adresse que lui. Le cookie est signé avec le mot de passe commun : une appli qui a un autre mot de passe continue de demander le sien. Il vaut trente jours, ou jusqu'au changement du mot de passe ; « Se déconnecter » le retire du navigateur.

## 2.13.0 — 13 novembre 2026
- **Photos : « Cocher tous ceux que carnet propose (N) »**, dans Portraits et dans Affiches. Un geste coche tous les contacts de la liste pour qui carnet a une proposition, y compris ceux qui ne sont pas encore affichés (au-delà des 20 premiers) et ceux qui ont déjà une photo. Le filtre de groupe et « Seulement sans photo » restreignent la sélection. Rien n'est posé : la pose reste par lots de 20, les suivants restent cochés. Pendant que carnet lit les propositions des contacts cochés plus bas, il l'indique (« Lecture des propositions : encore 12… »).
- Tests : 113 du back, 34 d'interface.

## 2.12.0 — 12 novembre 2026
- **Photos : « Relancer la recherche pour tous »**, dans Portraits et dans Affiches. Carnet relit Immich pour tous les contacts reliés, d'une traite, et refait son choix de photo et d'affiche pour chacun. Une confirmation précède ; l'avancement s'affiche (« 12 sur 240 »). Rien n'est posé ni changé dans iCloud ou Immich.
- **Les choix faits se replient** : un contact dont tu viens de choisir la photo (ou l'affiche) dans Photos disparaît de la liste des propositions. Le bouton à l'œil, « Afficher les N déjà choisis », les remontre. Une nouvelle recherche, pour lui ou pour tous, le fait revenir. Les photos posées avant cette version ne sont pas repliées.
- Treemich a son icône : un arbre, à la place des lettres « Tr » (fiches, liste, Connexion).
- Tests : 113 du back, 33 d'interface.

## 2.11.2 — 12 novembre 2026
- **Nom associé** : pendant la saisie, carnet propose les noms des contacts du carnet (sauf la fiche elle-même). On peut toujours écrire à la main le nom de quelqu'un qui n'y est pas.
- Tests : 112 du back, 32 d'interface.

## 2.11.1 — 12 novembre 2026
- **Treemich reprend le visage** : après qu'une photo posée a changé le visage de la personne dans Immich, carnet demande à Treemich de le recopier (Treemich garde sa propre copie, qui ne suit pas toute seule). Par lot, la reprise se fait une fois le lot posé. Si Immich a refusé, Treemich n'est pas sollicité.
- Immich refait sa vignette en tâche de fond : carnet lui laisse trois secondes. Si Treemich montre encore l'ancien visage, « Importer depuis Immich » dans Treemich le corrige.
- Tests : 112 du back, 31 d'interface.

## 2.11.0 — 11 novembre 2026
- **Photos : les tuiles « Portraits » et « Affiches » montrent tous les contacts** qui peuvent en recevoir une (reliés à Immich, ou d'une société dont le logo est gardé), y compris ceux qui ont déjà une photo. Le nombre de la tuile compte ce qui manque. « Affiches » remplace « Affiches à préparer ».
  - Chaque contact montre jusqu'à 5 propositions, telles qu'elles seraient posées. **La première est le choix de carnet** : visage entier (déjà exigé), grand, la personne seule sur la photo si possible, et plutôt au centre ; pour un contact de société, le logo.
  - Toucher une autre proposition la retient et coche le contact. « Poser les photos cochées » ou « Préparer les affiches cochées » traite le lot (20 à la fois).
  - **Rien n'est coché d'office pour un contact qui a déjà une photo** : « Cocher ce qui manque ici » ne coche que les contacts sans photo. Un remplacement est annoncé à côté du bouton.
  - Les contacts reliés avant cette version doivent être relus une fois dans Immich : cocher, puis « Chercher les propositions ». Cette recherche n'écrit rien.
- **La photo posée devient le visage de la personne dans Immich** (depuis l'onglet Photos, depuis la fiche, et la nuit). Si Immich refuse (clé sans le droit de modifier les personnes), la photo de la fiche reste posée et le refus est dit.
- Non fait : la photo de profil dans Treemich (son API n'a pas pu être vérifiée) ; le kit d'urgence n'a pas de photos dans son livre des contacts, il n'y a donc rien à lui renvoyer.
- Tests : 111 du back, 31 d'interface.

## 2.10.0 — 11 novembre 2026
- **Toucher la photo d'une fiche en modification ouvre une fenêtre de propositions** : jusqu'à 5 pour la photo du contact, jusqu'à 5 pour son affiche.
  - Contact relié à Immich : ses meilleurs visages, montrés tels qu'ils seraient posés (photo carrée, affiche cadrée). « Chercher d'autres photos dans Immich » relance la recherche. carnet garde maintenant 12 visages par personne au lieu de 6.
  - Contact non relié, avec une société : le logo de la société (gardé, déposé dans la fenêtre, ou trouvé sur son site) pour la photo, et 5 affiches de ce logo sur 5 couleurs.
  - Toucher une photo la pose dans iCloud (« Annuler » pendant 10 secondes) ; toucher une affiche la range dans l'album Immich « Affiches de contacts ».
- **Nouvelle affiche à partir du logo** : la page est à la couleur de la société (la couleur la plus présente du logo, hors blanc, gris et noir), le logo est en haut sur une plaque, le nom de la société est écrit dessous, puis le nom de la personne quand la fiche en a un. Quatre autres couleurs sont proposées : plus sombre, seconde couleur du logo ou version claire, blanc cassé, anthracite.
- **Affiches par lot** (Photos, file « Affiches à préparer ») : les contacts sans portrait possible dont la société a un logo gardé y entrent, et reçoivent l'affiche du logo à la couleur de la société.
- Tests : 107 du back, 29 d'interface.

## 2.9.2 — 11 novembre 2026
Pour Home Assistant (annonces des mariages et des fêtes).
- **Mariages par couple** : `/ha/anniversaires` renvoie, dans `mariages`, une entrée par couple (« Prénom NOM et Prénom NOM ») quand le conjoint est connu par l'arbre et a une fiche ; sinon une entrée au nom de la personne. Champs ajoutés : `noms` et `couple`. Un couple divorcé ou dont l'un est décédé n'est pas annoncé.
- Rien d'autre ne change. Tests : 106 du back, 28 d'interface.

## 2.9.1 — 11 novembre 2026
Après le retour de Julien : la date de mariage était bien dans Treemich, mais introuvable — Treemich la range sur le lien du couple, pas dans les évènements de la personne.
- **Connexion › Treemich, « Vérifier »** affiche maintenant chaque couple avec la date côté carnet et la date côté Treemich, et dit où la trouver dans Treemich (Profile › Relatives › crayon du conjoint › Marriage anniversary).
- Pendant la vérification de Treemich, carnet prévient qu'il relit l'arbre personne par personne et qu'il faut compter une minute.
- Messages corrigés : ils ne renvoient plus vers « État » ni vers l'ancien interrupteur de Réglages ; après un redémarrage, carnet dit d'appuyer sur « Vérifier » dans Connexion › Treemich.
- Rien ne change dans ce que carnet écrit. Tests : 106 du back, 28 d'interface.

## 2.9.0 — 11 novembre 2026
carnet est réorganisé autour de son rôle : faire le lien entre iCloud, Immich, Treemich et les autres outils. Les bases ne changent pas (mêmes règles d'écriture, même base, mêmes adresses pour Home Assistant).
- **Six onglets** : À traiter, Contacts, Groupes, Photos, Connexion, Réglages. « État » disparaît (son ancienne adresse ouvre Connexion). Sur iPhone, six icônes sans nom ; sur PC, le rail garde les noms.
- **À traiter s'ouvre sur une grille de tuiles**, une par type : Changé sur l'iPhone, Pas de groupe, Immich non synchronisé, Treemich non synchronisé, Doublons, Sociétés, Mise en forme, Réseaux, Imports, Contact incomplet. Seules les tuiles qui ont quelque chose s'affichent ; toucher une tuile ouvre sa liste. Le chiffre de l'onglet compte maintenant aussi les fiches sans groupe ; « Contact incomplet » n'y compte pas.
- **Connexion : une icône par service** — iCloud, Immich, Treemich, Copies (Synology), Sauvegardes, Import, LinkedIn, Telegram, Facebook, Instagram, Home Assistant, Kit d'urgence — avec son voyant et le nombre de différences qui attendent dans « À traiter ». Une icône « Attentes » ouvre le tableau de ce que chaque groupe doit avoir.
  - **Vérifier** relit le service et compare sans rien écrire : Immich (nom, date de naissance, photo de la fiche, personnes nommées sans fiche reliée), Treemich (nom, naissance, mariage, décès, liens familiaux), iCloud (relecture).
  - **Synchroniser** écrit ce qui est sûr — remplir un côté vide, jamais écraser — et envoie le reste dans « À traiter ». 20 fiches au plus par appui.
  - **Interrupteur « la nuit » par service** : la nuit ne fait que les services allumés. Celui de Treemich est l'ancien « dates de famille », celui d'iCloud l'ancien « fêtes » : leur état est repris tel quel. Les autres (Immich, Copies, Kit) sont allumés, comme avant.
- **Groupes** : la liste des groupes et leurs membres ; ajouter un contact par la recherche, retirer par lot (20 au plus) ; créer, renommer, supprimer un groupe. Supprimer demande toujours confirmation, ne supprime aucune fiche et peut s'annuler pendant 10 secondes. Les groupes d'origine de carnet ne se renomment pas et ne se suppriment pas.
- **Réglages** garde ce qui n'est pas un service : la nuit (heure, dernière nuit, lancer maintenant), l'analyse globale, ce que carnet a écrit tout seul (avec « Défaire »), les exceptions, le journal, la déconnexion.
- Corrigé en route : le rapport de vérification n'annonce plus « Aucun écart » quand rien n'est relié.
- Sécurité, vu par un test avant la livraison : la nouvelle adresse qui donne l'état des services partageait le chemin de l'envoi du mot de passe et aurait répondu sans session. Elle exige une session comme le reste.
- Tests : 106 du back, 28 d'interface (sur PC et sur iPhone).

## 2.8.5 — 11 novembre 2026
- **Vérifier l'accord avec Treemich** (Réglages) : un bouton relit Treemich et compare, date par date, les naissances, les mariages et les décès des fiches reliées à l'arbre. Un tableau donne, par sorte de date, le nombre de dates vues, égales, vides et en écart ; chaque écart est listé avec les deux valeurs et ce qui va se passer (écriture prévue, point dans « À traiter », accord éteint, date à compléter à la main).
- La vérification n'écrit rien. Si Treemich ne répond pas, elle le dit au lieu d'annoncer que tout est accordé. Les personnes de l'arbre sans fiche reliée sont comptées à part : elles ne sont pas comparées.
- Tests : 102 du back, 25 d'interface.

## 2.8.4 — 11 novembre 2026
Les restes de la 2.8. Rien ne change dans ce que carnet écrit.
- **Réseaux quitte État pour Réglages** : bilan par réseau, connexions LinkedIn et Telegram, dépôts d'archives, personnes sans fiche. État garde six tuiles.
- **Dossier « tel que construit » remis à jour** pour la 2.8 (`docs/dossier.md`).
- **Tests sur GitHub** : si les serveurs de paquets d'Ubuntu ne répondent pas, le navigateur de test est installé seul et les tests d'écran tournent quand même.
- Tests : 101 du back, 25 d'interface.

## 2.8.3 — 11 novembre 2026
Après le retour de Julien : une date de mariage saisie sur une fiche n'apparaissait pas dans Treemich, sans que carnet dise pourquoi.
- **La date part tout de suite** : quand l'accord avec Treemich est allumé, une date de mariage ou de décès saisie sur une fiche dans carnet est accordée une douzaine de secondes après l'écriture (le temps laissé à « Annuler »), sans attendre la nuit. Avant, seule la nuit le faisait ; « Relire iCloud » et « Relire Immich et Treemich » n'écrivent rien.
- **Bouton « Accorder maintenant »** dans Réglages, sous l'interrupteur, avec le bilan en retour.
- **carnet dit ce qui bloque** : Réglages affiche, en clair, pourquoi une date ne part pas — lecture seule, Treemich pas relu ou en erreur, fiche non reliée à une personne de l'arbre, pas de conjoint dans l'arbre (le mariage s'y range sur le couple), date sans année, fiche en attente de relecture. Le message après l'écriture d'une fiche le dit aussi quand l'accord est éteint.
- **Jamais écraser, vérifié au dernier moment** : avant d'écrire dans Treemich, carnet relit la valeur ; si une autre date s'y trouve déjà, il renonce et le dit.
- Une erreur d'Immich ne bloque plus l'accord avec Treemich.
- Tests : 101 du back, 25 d'interface.

## 2.8.2 — 11 novembre 2026
- **Sociétés écrites de plusieurs façons** : « aquitaineenergie », « aquitaineÉnergie », « AQUITAINEENERGIE », « Aquitaine Énergie SA »… carnet les rapproche et ajoute un point dans « À traiter » (famille Sociétés). Tu choisis l'écriture à garder, ou tu en tapes une autre ; le bouton dit combien de fiches changeront, puis carnet l'écrit dans iCloud, 20 fiches au plus par réponse (le point revient s'il en reste). Seul le nom de la société change : le service et le reste de la carte ne bougent pas.
- Le rapprochement ignore majuscules, accents, espaces, traits d'union, points et formes juridiques en fin de nom (SA, SAS, SARL…). Quand les écritures diffèrent par plus que les majuscules et les accents, le point demande de vérifier que c'est bien la même société. « Pas la même société » ne repose plus la question.
- Rien n'est écrit sans ta réponse. Tests : 100 du back, 25 d'interface.

## 2.8.1 — 11 novembre 2026
- **Logo par société** : dans Photos, la file Logos montre une ligne par société, avec le nombre de fiches sans photo. Le logo choisi (glissé, collé, ou trouvé sur le site) est posé sur **toutes les fiches sans photo de la société**, par lots de 20, et gardé : une fiche de la même société créée plus tard le retrouve, prêt à poser sans nouveau dépôt.
- **Une photo n'est jamais remplacée par un logo** : une fiche qui a déjà une photo, ou qui est reliée à Immich (elle aura un portrait), n'entre pas dans la file.
- Un logo posé depuis une fiche devient lui aussi celui de sa société.
- Base : table `logos_societes` ajoutée (la 2.7 rouvre toujours la base). Tests : 99 du back, 24 d'interface.

## 2.8.0 — 11 novembre 2026
Parcours et complétude. Dossier : `docs/2.8-dossier.md` ; conseil : `docs/2.8-conseil.md` ; essai : `docs/essai-2.8.md`. La base passe au schéma 3 (ajouts seulement : la 2.7 la rouvre).
- **Attentes par groupe** : un tableau (onglet Réglages) dit quelles informations chaque groupe doit avoir. Prérempli au premier démarrage ; un groupe hors du tableau de départ reçoit les attentes d'Amis, « Moi » aucune. Les attentes de plusieurs groupes s'additionnent. Chaque case annonce son effet avant d'être enregistrée.
- **Manques** : dans « À traiter », une ligne par information manquante avec son nombre de fiches ; elle ouvre la liste. Les manques ne comptent pas dans le compteur de l'onglet. Filtres de Contacts refaits sur les mêmes informations, plus « Sans groupe », « Sans union déclarée », « Décédés ».
- **Exceptions** : sur une fiche, « Normal pour ce contact » fait taire un manque précis ; la liste est dans Réglages, où on peut la reprendre. La jauge autour de l'avatar montre la part des attentes remplies.
- **Onglet Photos** : quatre files (logos, portraits, affiches à préparer, affiches à poser), traitées par lots de 20. **Logo déposé** : glissé depuis une autre fenêtre, collé, ou choisi comme fichier ; un bouton ouvre la recherche Google Images. Une adresse d'image n'est téléchargée que si elle est publique (jamais le réseau local), 3 Mo au plus.
- **Import unique** : un seul bouton « Importer » ; carnet dit ce qu'il a reconnu et ce qu'il fera avant d'importer, avec le mode opératoire de chaque type de fichier.
- **Champs nouveaux** : service, prononciation du prénom et du nom, fête, mariage, décès. Les trois dates sont des dates supplémentaires de la carte, aux libellés « Fête », « Mariage », « Décès » (le libellé natif d'Apple s'affiche « fête » en français : il n'est pas utilisé). L'an 1604 veut dire « sans année ». Écrire un de ces champs ne touche à rien d'autre dans la carte.
- **Fête** : d'après un calendrier embarqué (`app/fetes.py`, établi pour carnet, à corriger sur la fiche si besoin). Home Assistant la lit sur `/ha/fetes` dans tous les cas.
- **Dates de famille** : mariage et décès accordés avec Treemich — carnet remplit le côté vide, n'écrase jamais, ne propage jamais un effacement ; deux dates différentes deviennent un point. Divorce et décès lus dans Treemich : plus d'annonce (`/ha/anniversaires` porte aussi les mariages). Une croix (†) précède le nom d'une personne décédée ; une case « décédée, date inconnue » existe sur la fiche.
- **Deux interrupteurs, éteints à la livraison** (Réglages) : « écrire les fêtes », « accorder mariages et décès avec Treemich ». Éteints, carnet montre ce qu'il écrirait. Chaque écriture automatique est journalisée avec la valeur d'avant et peut être défaite ; après une écriture dans Treemich, carnet relit et coupe l'interrupteur si la valeur n'est pas revenue.
- **Supprimer une fiche** : depuis la modification d'une fiche, « Supprimer cette fiche… », toujours suivi d'une confirmation qui dit ce qui sera retiré. La carte quitte iCloud (donc l'iPhone) ; rien n'est supprimé dans Immich ni Treemich. « Annuler » la remet pendant 10 secondes, avec ses liaisons ; ensuite, la sauvegarde du jour.
- Cinq onglets : À traiter, Contacts, Photos, État, Réglages. « Se déconnecter » est aussi dans Réglages.
- **Écarts avec le dossier** : la section Réseaux reste dans État (non déplacée) ; le journal « écrit par carnet tout seul » est dans Réglages et non dans une tuile d'État ; pas de shadcn-svelte (fenêtre et cases natives).
- Au premier démarrage, les cartes déjà en base sont relues une fois pour connaître les champs nouveaux qu'elles portent déjà (rien n'est signalé ni écrit).
- Tests : 98 du back, 24 d'interface (PC et iPhone). Retour à la 2.7.2 par `CARNET_VERSION=2.7.2`.

## 2.7.2 — 11 novembre 2026
- **Essai avant la 2.8.0** (`python -m app.essai28`, mode opératoire dans `docs/essai-2.8.md`) : un programme à part qui crée **une** carte d'essai dans iCloud (« Carnet Essai », données inventées), la relit, et mesure la recherche de logos sur 30 sociétés sans photo. Relancé après une modification sur l'iPhone, il dit ce qui a changé. Aucune fiche existante n'est touchée ; le rapport ne contient ni nom ni site. carnet lui-même ne change pas.
- Dossier de la 2.8.0 (`docs/2.8-dossier.md`) et compte rendu du conseil (`docs/2.8-conseil.md`).

## 2.7.1 — 11 novembre 2026
- **Sonde avant la 2.8.0** (`python -m app.sonde28`) : un programme à part, en lecture seule, qui compte ce dont la conception de la 2.8.0 dépend (propriétés déjà présentes dans les cartes, taille de la future famille « Manques », mariages dans Treemich). Il travaille sur une copie de la base, ne contacte pas iCloud, ne fait que lire Treemich, et son rapport ne contient aucun nom de personne. carnet lui-même ne change pas.

## 2.7.0 — 11 novembre 2026
Nouvel habillage, seul. Deuxième des trois livraisons (voir `docs/dossier.md`). Mêmes écrans, mêmes textes, même navigation ; aucune route de l'API ni la base ne changent.
- **Habillage du socle, réchauffé** : fonds neutres teintés vers l'ocre, filets fins, titres en caractères sans empattements (grands et fins pour les écrans, fermes pour les noms). Le thème « cuir » disparaît ; l'ocre reste la couleur de carnet et porte l'action attendue, le filtre actif et ce qui demande l'attention.
- **Mode clair** quand l'appareil le demande ; sombre sinon. Pas de bouton dans l'appli.
- **État en tuiles bento** : « iCloud et la nuit » occupe deux colonnes, les six autres sections se rangent autour.
- **Gardés et reteintés** : l'anneau de progression des boutons, la jauge de complétude autour de l'avatar, l'index alphabétique en tranche.
- Polices : Inter remplace Spectral et Instrument Sans. Couleurs écrites en dur remplacées par des rôles.
- Les classes de carnet (`.bouton`, `.pastille`, `.feuille`) portent l'habillage ; les composants shadcn-svelte ne sont pas introduits dans cette version (aucun écran n'en a besoin et le rendu est le même).
- Tests : aucun test d'interface réécrit. Retour à la 2.6.5 par `CARNET_VERSION=2.6.5`.

## 2.6.5 — 11 novembre 2026
Ménage, sans changement d'apparence. Première des trois livraisons décidées après le passage au conseil (voir `docs/dossier.md`).
- **Mode lecture seule** (`CARNET_LECTURE_SEULE=oui`) : carnet lit et calcule tout, mais n'écrit ni dans iCloud, ni dans Immich, Treemich, Synology Contacts ou le kit d'urgence. Le refus est posé deux fois : à l'entrée de chaque opération, et dans les accès réseau eux-mêmes. Un bandeau le rappelle ; la nuit relit sans rien lier ni écrire.
- **Annonce avant un traitement par lot** : avant « Confirmer », carnet dit combien de fiches seront modifiées dans iCloud, combien attendront le lot suivant, ou que rien n'est écrit (« Tout ignorer »).
- **Restes de la 1.3 retirés** : module de reprise, dépendance SQLCipher et variable `CARNET_DB_KEY`. Si l'ancienne base est présente et n'a jamais été reprise, le journal le signale une fois.
- **Versions exactes** des dépendances de l'interface.
- Tests : 83 pour le back (3 tests de la reprise retirés avec elle, 6 ajoutés), 20 pour l'interface (1 ajouté, aucun réécrit).
- Base inchangée : le retour à la 2.6.4 se fait par `CARNET_VERSION=2.6.4`.

## 2.6.4 — 11 novembre 2026
- **Refus d'identifiants iCloud (401)** : carnet ne réessaie plus et marque une pause de 15 minutes sans aucune requête vers iCloud (nuit et boutons compris), pour ne pas faire verrouiller le compte Apple par des refus répétés. Le message explique qu'un changement du mot de passe du compte Apple annule les mots de passe d'application. Un nouveau mot de passe dans la stack suivi d'un Recreate lève la pause.

## 2.6.3 — 10 novembre 2026
- **Moins de requêtes vers iCloud** : l'adresse du carnet d'adresses est retenue une heure. Chaque écriture faisait quatre requêtes de découverte avant son envoi ; une série de validations n'en fait plus qu'une fois par heure, ce qui ménage iCloud (le 500 du 10 novembre est arrivé après une série d'écritures). Si iCloud déplace le carnet (404), la découverte est refaite.

## 2.6.2 — 10 novembre 2026
- **Ratés passagers d'iCloud** (et de Synology) : une lecture qui reçoit 429, 500, 502, 503 ou 504, ou dont la connexion coupe, est réessayée seule après 2, 6 puis 15 secondes avant d'abandonner. Les écritures ne sont jamais rejouées. Le message final précise « panne passagère du serveur, réessaie dans quelques minutes ».

## 2.6.1 — 10 novembre 2026
- **Dates sans année et Immich** : une fiche qui n'a qu'un jour et un mois (« --01-01 ») ne crée plus de point « Date de naissance à trancher » quand aucune date complète n'existe ailleurs. « Écrire partout » n'envoie jamais une date sans année à Immich ni à Treemich (ils exigent l'année ; Immich répondait « 500 ») : elle reste sur la fiche seulement.
- Les dates proposées s'affichent en clair (« 1er janvier », « 14 mars 1985 ») avec la mention « sans année : fiche seulement ».

## 2.6.0 — 10 novembre 2026 — réseaux : navigation et importés sans fiche
- **Bilan des réseaux cliquable** : un clic sur LinkedIn, Telegram, Instagram, Facebook, X ou WhatsApp amène à sa partie, brièvement surlignée.
- **Listes repliables** (Développer / Réduire, fermées par défaut) :
  - LinkedIn : relations sans fiche ;
  - Telegram, Facebook, Instagram : personnes importées liées à aucune fiche, avec le repère « proposé dans À traiter » quand une proposition est ouverte.
- Chaque liste a un filtre (nom, société, pseudo) et s'affiche par 30. « Rattacher… » ouvre une recherche de fiche pré-remplie avec le nom de famille, au lieu d'un menu de toutes les fiches sur chaque ligne (plus léger avec 500 relations).

## 2.5.0 — 10 novembre 2026 — copie Synology suivie, X (Twitter)
- **Copie vers Synology Contacts** (« Copier maintenant » et « Forcer la copie ») : tâche de fond avec bouton à anneau. L'anneau suit la lecture de Synology puis chaque fiche copiée (« 120 / 519 »), passe au vert avec le bilan ou au rouge avec la raison (coupe-circuit des 5 % compris). « Forcer la copie » est un bouton à anneau rouge. Le bandeau d'État et la tuile Copies montrent la roue pendant la copie.
- **X (Twitter)** rejoint les réseaux : pseudo (@…) ou adresse x.com/twitter.com collé sur la fiche (écrit dans la carte iCloud), pastille et logo, « Délier ». Les profils Twitter déjà présents sur les cartes sont reconnus. L'archive de X ne donne que des numéros de compte : pas d'import.
- Bilan des réseaux : compte toutes les fiches qui portent la plateforme (liaison, profil collé ou déjà sur la carte).

## 2.4.0 — 10 novembre 2026 — voyants, logos des réseaux, LinkedIn dans Réseaux
- **Voyants** :
  - en haut d'État, un bandeau : roue qui tourne et nom de l'opération en cours (lecture d'iCloud, nuit, analyse globale, Immich et Treemich) ; sinon « Tout fonctionne » avec une coche ; sinon une croix et les sections à voir ;
  - sur chaque tuile d'État : roue, coche ou croix ;
  - dans Services, un voyant par service (iCloud, Immich, Treemich, Synology, kit, Home Assistant, LinkedIn, Telegram), avec le message d'erreur ;
  - sur l'onglet État de la barre, une petite roue pendant une opération.
- **Logos des réseaux** : l'icône officielle de chaque plateforme est reprise sur son site (ou sur ton serveur pour Immich et Treemich), une seule fois, puis gardée par carnet. Elle remplace les deux lettres dans les pastilles, sur la fiche et dans État › Réseaux. Si un site ne répond pas, les deux lettres restent et carnet réessaie le lendemain.
- **LinkedIn rejoint État › Réseaux** (la tuile LinkedIn disparaît) : relations importées et liées dans le bilan, dépôt de Connections.csv par bouton ou glisser-déposer, connexion à l'API, relations sans fiche.

## 2.3.2 — 10 novembre 2026
- Instagram : un export « Contacts » (synced_contacts.json, ton carnet d'adresses synchronisé, sans pseudo) est reconnu et explique quel export demander à la place (« Abonnés et abonnements », JSON).

## 2.3.1 — 10 novembre 2026 — glisser-déposer et exports reconnus
- **Glisser-déposer** (PC) : sur « Déposer l'export Facebook », « Déposer l'export Instagram » et « Importer ». Dès qu'un fichier est tiré au-dessus de carnet, les cibles s'entourent de pointillés dorés. Un fichier lâché à côté n'ouvre plus le fichier dans le navigateur.
- Chaque bouton annonce son réseau : un export déposé sur « Instagram » est lu comme Instagram même si son contenu n'est pas reconnu d'emblée (corrige « Fichier non reconnu »).
- Instagram : nouvelles variantes de l'export JSON (« relationships_followers », pseudo dans le lien) et export au format HTML.
- Facebook : seul your_friends.json (ou le .zip) est lu. Suggestions, demandes d'amis, amis retirés et audiences sont refusés avec un message clair. Un export Facebook en HTML demande à refaire l'export en JSON.

## 2.3.0 — 10 novembre 2026 — import des amis Facebook
- **Export Facebook** (Compte Meta › Exporter vos informations › Contacts › Ami(e)s, format JSON) déposé dans État › Réseaux ou Contacts › Importer, en .zip ou your_friends.json. Seuls les fichiers d'amis et de followers sont ouverts ; l'archive est lue en mémoire puis oubliée.
- Facebook ne donne que les noms (pas de lien de profil ni de numéro). Les accents mal encodés de l'export (« Ã© ») sont réparés. Un ami est proposé dans « À traiter › Réseaux » quand son nom désigne une seule fiche, même avec les mots dans un autre ordre.
- « Lier » pose la pastille Facebook sans rien écrire dans iCloud ; pour écrire le lien du profil, colle son adresse sur la fiche. « Délier » retire la pastille.
- Une seule proposition ouverte par fiche et par réseau (tous réseaux).

## 2.2.0 — 10 novembre 2026 — barre pilule et boutons à anneau
- **iPhone** : la barre d'onglets devient une pilule sombre qui flotte en bas. Les onglets montrent leur icône seule ; l'onglet ouvert s'élargit en pastille claire avec son nom. Le nombre de points à traiter reste sur l'icône.
- **PC** : le rail de gauche reste, avec la même pastille claire pour l'onglet ouvert et des icônes.
- **Boutons à anneau** : l'anneau du bouton se remplit pendant l'opération (pourcentage quand il est connu, sinon un arc qui tourne), devient vert avec une coche en cas de réussite, et rouge avec le message d'erreur en cas d'échec. Sur :
  - Relire iCloud, Lancer la nuit (avec ses étapes), Relire Immich et Treemich, Relancer l'analyse globale ;
  - Copier vers Synology Contacts, Envoyer au kit ;
  - Importer (Contacts) et Déposer l'export Instagram, avec l'avancement de l'envoi ;
  - deux nouveaux téléchargements dans État › Sauvegardes : **Télécharger cette sauvegarde** et **Exporter tout le carnet (.vcf)** (cartes iCloud telles qu'à la dernière lecture, photos comprises).

## 2.1.0 — 3 novembre 2026 — carnet devient un hub
- **Complétude** : quatre critères par fiche (sans année de naissance, sans adresse, sans téléphone, sans moyen de contact). Dans Contacts, des filtres « Sans … », « À revoir » et « Validées » avec leur nombre ; un anneau autour de chaque avatar montre la complétude (vert si validée, rouge si à revoir).
- **Valider une fiche** : la fiche entière est déclarée complète telle quelle et sort des filtres. Si elle change ensuite ailleurs (iPhone, autre appareil) sur l'année, l'adresse, un téléphone ou un courriel, elle passe « À revoir ». Une écriture faite par carnet garde la validation.
- **Plateformes** : pastilles par réseau (Immich, Treemich, LinkedIn, Facebook, Instagram, WhatsApp, Telegram) sur chaque ligne et dans la fiche.
- **Réseaux** :
  - Telegram : import ponctuel depuis État > Réseaux (numéro, code reçu, mot de passe de double vérification si besoin). La session n'existe qu'en mémoire et carnet se déconnecte aussitôt.
  - Instagram : dépôt de l'export .zip ou .json. Seuls les pseudos sont lus et l'archive n'est pas gardée.
  - Facebook : adresse du profil collée sur la fiche.
  - WhatsApp : numéro choisi parmi ceux de la fiche.
  - Chaque rapprochement (même numéro, pseudo prénom+nom, même nom unique) arrive dans « À traiter » > Réseaux, 150 au plus par import : Lier, Lier et ajouter le numéro, Pas lui (plus jamais proposé).
  - « Délier » retire le profil de la carte iCloud et ne le propose plus.
  - Les personnes lues mais jamais liées sont effacées au bout de 90 jours.
- **Actions groupées** dans « À traiter » (Tout lier, Tout appliquer, Tout ignorer) sur une famille filtrée, avec confirmation. Les écritures sont plafonnées à 5 % des fiches (3 au moins) par lot.
- **Analyse globale** (État > Complétude) : relit Immich et Treemich, recalcule doublons, complétude et rapprochements, sans rien écrire dans iCloud. La remise à zéro des validations se confirme deux fois (bouton, puis REMETTRE à taper).
- **Application iPhone** : « Sur l'écran d'accueil » depuis Safari ouvre carnet en plein écran avec son icône (aucune donnée gardée hors ligne).
- Nouvelles variables facultatives : `CARNET_TELEGRAM_API_ID`, `CARNET_TELEGRAM_API_HASH`.

### Garde-fous ajoutés après une relecture indépendante
- **Sites et profils comparés un par un** à l'écriture : un profil Twitter avec ses paramètres, un site à étiquette personnalisée, un profil Flickr ou une page Facebook d'entreprise restent exactement tels qu'iCloud les a. Seul le site ajouté ou retiré change (vaut aussi pour l'éditeur de la fiche).
- **Délier** ne retire que l'adresse de profil écrite par carnet (ou l'unique profil de ce réseau), après une confirmation qui montre l'adresse concernée. Seuls les quatre réseaux sont acceptés.
- Une action automatique, un réseau ou une action groupée n'efface plus jamais un point « Modifiée sur l'iPhone » ou « Conflit ». Seule une modification faite par toi dans l'éditeur, depuis la version affichée, le règle.
- Validation, ajout de profil et Délier partent avec la version affichée : si la fiche a changé entre-temps, rien n'est fait.
- **Import** : le fichier est lu en mémoire, jamais écrit sur le disque, 100 Mo au plus. Le dossier temporaire du conteneur est en mémoire (tmpfs). L'archive Instagram est lue avec des plafonds (20 Mo par fichier, 60 fichiers), et une archive abîmée donne un message clair.
- **Telegram** : une seule connexion à la fois. La déconnexion a lieu même si la lecture échoue. La connexion commencée est fermée au bout de 10 min, même sans nouvel appel.
- **Purge** : les propositions « Réseau à rattacher » sont effacées avec les personnes. La purge a lieu au démarrage, une fois par jour, à chaque import et à l'analyse globale, même la nuit désactivée. Un nouvel import remplace la liste du réseau.
- Une réunion de fiches garde aussi les liaisons Telegram et Instagram. Une carte refusée par iCloud n'arrête plus une action groupée.

## 2.0.3 — 3 novembre 2026
- **État** : une grille de six sections avec icône (iCloud et la nuit, Sauvegardes, Copies, LinkedIn, Services, Journal), chacune avec un résumé d'une ligne et une pastille rouge en cas de problème ; un toucher affiche la section, un seul à la fois.
- **Dates sans année** : une année 1900 veut dire « année inconnue ». Saisie en 14/03/1900, la date part dans iCloud sans année (jour et mois, comme sur l'iPhone) ; la fiche l'affiche « 14 mars ». Une carte iCloud déjà enregistrée en 1900 est proposée en « Mise en forme » pour être réécrite sans année. Home Assistant ne calcule plus d'âge pour ces dates.

## 2.0.2 — 3 novembre 2026
- Fiche : un stylo en haut à droite ouvre la modification des informations (à la place du bouton « Modifier » en bas du bloc).

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
