# carnet

Gardien de tes contacts iCloud, auto-hébergé sur le NAS. iCloud reste la **source maître** (l'iPhone est l'usage réel) ; carnet relit, signale, propose, relie les fiches à **Immich** (visages), **Treemich** (arbre) et **LinkedIn**, puis écrit dans iCloud — quand tu valides, ou la nuit pour ce qui est sûr. Il copie le résultat dans **Synology Contacts**, alimente le **kit d'urgence** et **Home Assistant**.

Accès en réseau local et par Tailscale uniquement, jamais exposé sur Internet.

## Les trois onglets

| Onglet | Rôle |
|---|---|
| **À traiter** | Tout ce qui attend une décision : fiche modifiée, créée ou supprimée sur l'iPhone, conflit d'écriture, doublon, mise en forme (« Prénom NOM », numéros), émoji sans son groupe, liaison à confirmer, date de naissance à trancher, nom à reporter dans Immich ou Treemich, liens familiaux, changement LinkedIn, réseau à rattacher, fiche importée. Un point écarté n'est plus reproposé. Sur une famille filtrée, actions groupées (Tout lier, Tout appliquer, Tout ignorer) plafonnées à 5 % des fiches écrites par lot. |
| **Contacts** | Liste avec recherche (nom, société, numéro), tri par prénom ou par nom (gardé sur l'appareil), menu des groupes et index des lettres (fin sur iPhone, à parcourir du pouce ; tranche de carnet sur PC, où la fiche s'ouvre à côté de la liste). La fiche : appeler, écrire, modifier (aperçu des changements avant d'écrire, « Annuler » 10 s), liaisons, photo et affiche depuis Immich, logo de la société, réunion avec une autre fiche. Import d'un .vcf, du Connections.csv de LinkedIn ou de l'export Instagram. Filtres de complétude, anneau de complétude autour de chaque avatar, pastilles des plateformes ; dans la fiche : Valider la fiche, profils réseaux à ajouter ou délier. |
| **État** | Lecture d'iCloud et nuit, sauvegardes et restauration, Synology Contacts, kit d'urgence, LinkedIn (API), réseaux (Telegram, Instagram), complétude et analyse globale, services configurés, journal. |

## Complétude et validation

Quatre critères : **sans année de naissance**, **sans adresse**, **sans téléphone**, **sans moyen de contact** (ni téléphone ni courriel). « Valider la fiche » la déclare complète telle quelle : elle sort des filtres « Sans … ». Si l'année, une adresse, un téléphone ou un courriel change ensuite hors de carnet, la fiche passe **À revoir**. L'analyse globale (État › Complétude) recalcule tout sans rien écrire dans iCloud ; la remise à zéro des validations demande de taper REMETTRE.

## Réseaux

| Réseau | Comment | Ce qui est gardé |
|---|---|---|
| Telegram | État › Réseaux : numéro, code reçu dans Telegram, mot de passe de double vérification si besoin (`CARNET_TELEGRAM_API_ID` / `_HASH`) | Nom, numéro et pseudo des contacts. La session Telegram n'existe qu'en mémoire : carnet se déconnecte après l'import, rien n'est écrit sur disque ni sauvegardé. |
| Instagram | Export « Abonnés et abonnements » (JSON) déposé dans État › Réseaux ou Contacts › Importer | Les pseudos seulement ; l'archive n'est pas gardée. |
| Facebook | Adresse du profil collée sur la fiche | Le lien, dans la carte iCloud. |
| WhatsApp | Numéro choisi sur la fiche (ou profil WhatsApp déjà présent sur la carte) | Le lien wa.me, dans la carte iCloud. |

Chaque rapprochement (même numéro, pseudo formé du prénom et du nom, même nom unique) arrive dans « À traiter › Réseaux », 150 au plus par import. Lier écrit le profil dans la carte iCloud ; « Pas lui » et « Délier » empêchent de le reproposer. Les personnes lues mais jamais liées sont effacées au bout de 90 jours.

## Sur l'iPhone

Safari › Partager › « Sur l'écran d'accueil » : carnet s'ouvre en plein écran avec son icône. Aucune donnée n'est gardée hors ligne.

## Dates sans année

Une date saisie en **1900** (par exemple 14/03/1900) veut dire « année inconnue » : iCloud la reçoit sans année, comme une date entrée sans année sur l'iPhone, et carnet l'affiche « 14 mars ». Une carte iCloud déjà enregistrée en 1900 est proposée dans « À traiter › Mise en forme ».

## Les règles qui protègent tes contacts

- **Référence d'abord** : la première lecture complète d'iCloud sert de point de départ. Rien n'est signalé ni écrit avant.
- **L'iPhone a toujours raison, mais tu relis** : toute fiche modifiée, créée ou supprimée sur l'iPhone arrive dans « À traiter ». Une fiche supprimée n'est jamais recréée sans ton accord.
- **Jamais d'écrasement** : chaque écriture porte l'ETag de la dernière lecture (If-Match). Une carte changée sur l'iPhone entre-temps n'est pas touchée ; les deux versions t'attendent dans « À traiter ».
- **Coupe-circuit** : lecture incomplète, ou plus de 5 % des fiches disparues d'un coup → arrêt, rien n'est changé (« Relire quand même » dans État, après vérification).
- **Un seul écrivain** : un verrou commun couvre Valider, Annuler, Restaurer, la fusion et la nuit.
- **La nuit n'écrit que du sûr**, 20 fiches au plus, jamais de suppression : liaison exacte (même nom, unique des deux côtés, même date de naissance complète), photo d'une fiche liée qui n'en a pas, date de naissance manquante connue sans conflit, nouveau poste ou société LinkedIn quand la fiche portait encore l'ancien.
- **Rien n'est perdu à l'écriture** : carnet ne remplace que les champs qu'il gère ; tout le reste de la carte iCloud (champs propres à Apple, profils iMessage…) est gardé. Une carte de plus de 110 Ko est refusée (iCloud refuserait), la photo est réduite d'abord.
- **Sauvegardes** : copie complète avant la première écriture du jour et chaque nuit, gardée 30 jours puis une par mois pendant un an (2 Go au plus). État › Sauvegardes compare une copie à iCloud et remet les fiches choisies à l'identique.
- **Suppression** : seulement quand tu réunis deux fiches (la carte absorbée est retirée, ses liaisons, photo, affiche et relation LinkedIn passent sur la fiche gardée).

## La nuit (`CARNET_VEILLE_HEURE`, 03:00)

1. Lecture complète d'iCloud (veille).
2. Relecture d'Immich et Treemich, liaisons sûres.
3. Sauvegarde, puis les écritures sûres.
4. Copie dans Synology Contacts, kit d'urgence, purge des sauvegardes.

Si une autre opération tourne, la nuit réessaie toutes les 10 min pendant 3 h. `CARNET_VEILLE_HEURE=off` la désactive.

## Home Assistant

Toutes les adresses `/ha/…` demandent `Authorization: Bearer <CARNET_HA_TOKEN>`, sont en lecture seule, et rien de personnel (nom, date) n'est écrit dans les journaux. `/status` ne donne que des compteurs, sans jeton.

| Adresse | Contenu |
|---|---|
| `/ha/contacts` | Toutes les fiches : `carnet_id` (UID iCloud), `nom` (celui d'Immich si liée), `prenom`, `immich_id`, `treemich_id`, `groupes`, `proche`, `naissance`, `jour`, `mois`, `annee` (null si inconnue) |
| `/ha/personnes` | Fiches liées à Immich et proches (carte de réservation) — identique à la 1.3 |
| `/ha/anniversaires` | Calendrier des anniversaires — identique à la 1.3 |
| `/ha/invite?nom=` | Fiche d'un invité (« Nom (dates) » accepté) ; 404 inconnu, 409 plusieurs — identique à la 1.3 |
| `/ha/portraits/candidats?immich=` et `/ha/portrait?immich=` | Portraits pour les cadres ; en-tête `X-Visage` — identiques à la 1.3 |
| `/status` | Compteurs (mêmes champs que la 1.3 pour le paquet `homeassistant/carnet.yaml`, plus `a_traiter` et `par_motif`) |

Le paquet `homeassistant/carnet.yaml` de la 1.3 fonctionne sans changement.

## Installation (Portainer, stack homelab.yml)

Le service est décrit dans `docker-compose.yml` ; les variables sont dans `.env.example` (les mêmes que pour la 1.3). Volumes :

| Volume | Dossier du NAS | Contenu |
|---|---|---|
| `/data` | `/volume1/homes/<utilisateur>/carnet` | fichiers déposés à la main (`depot/`) |
| `/state` | `/volume1/docker/carnet/state` | `carnet2.db`, `sauvegardes/`, ancienne base `carnet.db` de la 1.3 |
| `/kit-config` | `${KIT_DATA_DIR}/config` | `contacts-urgence.vcf` pour le kit |

`/state` n'est ni partagé ni synchronisé vers OneDrive : la base et les sauvegardes y restent.

### Passer de la 1.3 à la 2.0

1. Dans Portainer : **Recreate + Re-pull image** (image `latest` ou `2.0.0`). Rien d'autre à changer.
2. Au premier démarrage, carnet lit iCloud (référence), puis reprend une seule fois les choix de la 1.3 depuis `carnet.db` avec `CARNET_DB_KEY` : liaisons et refus, photos choisies, affiches et leur pose, relations LinkedIn. L'ancienne base n'est jamais modifiée. Le bilan est dans État › Services.
3. Vérifie : même nombre de fiches qu'avant (État), adresses HA qui répondent, et essaie « Remettre comme dans la sauvegarde » sur ta propre fiche.
4. La première copie Synology remplace celle de la 1.3 (identifiants « carnet-… ») par un miroir exact d'iCloud.

**Retour arrière** : `CARNET_VERSION=1.3.1` et `CARNET_VEILLE_HEURE=off` (la nuit de la 1.3 ne doit pas tourner : elle réécrirait des fiches devenues périmées), puis Recreate.

### Droits de la clé d'API Immich
`person.read`, `person.update` (liaisons, noms, dates) ; `asset.read`, `asset.view`, `asset.download`, `face.read` (portraits) ; `asset.upload`, `asset.delete`, `album.create`, `album.read`, `albumAsset.create` (affiches).

### LinkedIn
- **API de portabilité** (membres UE) : app LinkedIn Developers avec le produit « Member Data Portability API (Member) », adresse de retour `https://localhost/carnet-linkedin`. État › LinkedIn › « Se connecter », puis colle l'adresse de retour. Juste après la première autorisation, LinkedIn prépare les données environ 30 minutes : « Réessayer ».
- **Fichier** : Contacts › Importer › `Connections.csv`.
- Une relation est reconnue par l'adresse de son profil ; LinkedIn ne crée jamais de fiche ; une relation détachée reste détachée.

## Développement

- Back-end : FastAPI (Python 3.12), un module par sujet dans `app/` : `icloud.py` (lecture, écriture, sauvegardes), `traiter.py` (boîte À traiter), `actions.py` (décisions), `nuit.py`, `liaisons.py`, `photos.py`, `linkedin.py`, `sorties.py` (kit, Synology, HA), `reprise.py`, `base.py` (SQLite, schéma versionné).
- Interface : Svelte 5 et Tailwind 4 dans `frontend/`, compilée dans `app/static`.
- Tests : `python -m pytest -q tests` (faux iCloud, Immich, Treemich et Synology ; tests d'interface Playwright sur PC et iPhone si l'interface est compilée).
- Démo locale : `cd frontend && npm ci && npx vite build --outDir ../app/static --emptyOutDir`, puis `python -m tests.interface.serveur /tmp/demo 8097` (mot de passe `essai`).

Aucune donnée personnelle dans ce dépôt : les secrets vont dans les variables de la stack.
