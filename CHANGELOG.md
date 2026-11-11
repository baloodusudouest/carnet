# Journal des versions

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
