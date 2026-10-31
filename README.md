# carnet

Application auto-hébergée qui **rassemble les contacts** de plusieurs carnets (iCloud, Gmail, Outlook.com, LinkedIn en complément), les fait **relire un par un**, **fusionne les doublons champ par champ**, puis produit un export `.vcf` propre et la liste des contacts d'urgence pour [kit-urgence](https://github.com/baloodusudouest/kit-urgence).

Les contacts sont importés depuis des exports faits à la main. Depuis la V2, carnet peut **réécrire iCloud** avec les fiches vérifiées (CardDAV), après simulation et sauvegarde. Gmail et Outlook ne sont jamais modifiés.

## Ce que fait carnet

| Étape | Détail |
| --- | --- |
| Dépôt | glisser les exports dans l'interface, ou les copier dans `depot/` |
| Import | lecture des `.vcf` iCloud et Gmail, du `.csv` Outlook et de `Connections.csv` LinkedIn ; chaque fichier est archivé tel quel |
| Doublons | même mobile, même courriel, même fixe avec un nom compatible, noms proches (RapidFuzz) renforcés par la date de naissance ou la société |
| Révision | une colonne par source, la fiche retenue à droite ; tout se fait au clavier (`?` affiche les raccourcis) |
| Formats | numéros stockés en E.164 et affichés `+33 6 12 34 56 78` ; noms `Prénom NOM` |
| Export | `export/carnet-AAAA-MM-JJ_HHMM.vcf` (vCard 3.0, lisible par iCloud), contacts vérifiés seulement |
| Kit d'urgence | bouton « Envoyer au kit » : réécrit `contacts-urgence.vcf` dans le dossier du kit, puis lui demande de se régénérer |
| iCloud (V2) | onglet iCloud : simulation, essai sur sa propre fiche (groupe Moi), puis écriture ; voir ci-dessous |
| Archives | exports d'origine gardés 365 jours puis supprimés ; un onglet et Home Assistant préviennent 30 jours avant |

LinkedIn complète des contacts existants (société, poste, profil) mais n'en crée jamais.

## Écriture dans iCloud (V2)

1. **Simuler** : carnet lit tout iCloud et calcule les écritures, sans rien modifier. La simulation reste valable 30 minutes.
2. **Essai** : n'écrit que la fiche du groupe Moi, pour contrôler le rendu sur l'iPhone.
3. **Écrire** (après confirmation) : une **sauvegarde complète** d'iCloud est d'abord enregistrée dans `archives/AAAA-MM-JJ_HHMMSS_icloud-sauvegarde.vcf` (gardée 365 jours), puis :
   - chaque contact vérifié met à jour sa fiche iCloud (UID conservé) ou est créé s'il venait de Gmail ou Outlook ;
   - seules les propriétés gérées par carnet sont remplacées : les champs qu'il ne connaît pas (dates personnalisées, etc.) sont gardés, et la photo iCloud reste si carnet n'en a pas ;
   - les autres fiches iCloud d'une personne fusionnée et les contacts mis de côté sont supprimés ;
   - les groupes de carnet sont créés ou mis à jour dans iCloud ; les membres que carnet ne gère pas (contacts à réviser) restent ;
   - les groupes iCloud vides, en double ou absents de carnet sont supprimés (leurs contacts restent) ;
   - les contacts créés dans iCloud sans carnet sont importés pour révision ;
   - les contacts encore à réviser ne sont pas touchés.

### Liaisons Immich et Treemich (V3)

Onglet Liaisons : carnet propose, pour chaque contact vérifié, la personne Immich et la personne Treemich du même nom (la personne Treemich liée à ce visage Immich si elle existe). Les correspondances exactes se valident d'un clic. Ensuite, chaque nuit : le visage Immich devient la photo du contact, et les relations Treemich (conjoint, parents, enfants, frères et sœurs) complètent ses noms associés ; une relation qui contredit un nom associé saisi est proposée dans la Revue. Les orthographes différentes se tranchent ligne par ligne, et les noms Immich peuvent être mis au format « Prénom NOM ».

Dates de naissance (même onglet) : simulation, essai sur une personne, puis écriture vers Immich ou Treemich. carnet fait foi ; une date différente n'est remplacée que sur demande ; l'arbre Treemich est exporté en GEDCOM dans `archives/` avant d'écrire, et le journal garde chaque ancienne valeur.

Photos HD (même onglet) : pour chaque contact lié sans photo ou avec la vignette Immich, carnet cherche le visage entier le plus grand, le plus net et le plus de face (les photos d'écran et images pixélisées sont écartées), et le découpe en portrait carré depuis la photo d'origine. Il devient la photo du contact et la photo de la personne dans Immich. Un choix manuel parmi les 6 meilleurs n'est plus changé. Recherche sur bouton, puis une fois par mois pendant la tâche de nuit (seules les nouvelles photos sont lues). Les photos envoyées à iCloud sont limitées à 120 Ko (iCloud refuse les fiches de plus de ~256 Ko).

Affiches iPhone (même onglet) : pour les contacts des groupes cochés, carnet propose jusqu'à 6 photos Immich qui se prêtent au plein écran (visage de face, net, de la place autour), déjà cadrées au format écran d'iPhone, dans un tableau (agrandies au survol). Rien n'est envoyé sans ton choix : la photo choisie est rangée, archivée, dans l'album Immich « Affiches de contacts ». Les propositions sont rafraîchies chaque mois ; un choix n'est jamais changé. L'affiche de contact (plein écran à l'appel) se crée ensuite à la main sur l'iPhone : Apple ne permet pas de la remplir par CardDAV.

#### Droits de la clé d'API Immich

| Fonction | Droits |
|---|---|
| Liaisons, visages, noms, dates de naissance | `person.read`, `person.update` |
| Photos HD | `asset.read`, `asset.view`, `asset.download`, `face.read` |
| Affiches iPhone | `asset.upload`, `asset.delete`, `album.create`, `album.read`, `albumAsset.create` |

Dans Immich : Paramètres du compte › Clés d'API › modifier la clé de carnet. Un droit manquant est signalé par son nom dans l'interface.

### Sauvegarde de nuit (V3)

Après la veille, carnet écrit `archives/sauvegardes/carnet-AAAA-MM-JJ.vcf` (contacts vérifiés, sans photos, gardé 30 jours) puis recopie à l'identique les contacts vérifiés et leurs groupes dans Synology Contacts. Si plus de 5 % des fiches déjà copiées devaient être supprimées ou modifiées d'un coup, la copie s'arrête sans rien écrire (bouton « Forcer la copie » dans l'onglet Export et kit) et Home Assistant alerte.

### Veille de l'iPhone (V3)

Chaque nuit (`CARNET_VEILLE_HEURE`, 03:00 par défaut), carnet relit iCloud et compare chaque fiche à la version validée. Les différences de forme (réécritures d'iCloud, données Siri, photo, types recalculés) sont ignorées ; restent les contacts modifiés, créés ou supprimés sur l'iPhone. En **mode journal** (par défaut) ils sont seulement listés dans l'onglet iCloud ; en **mode révision** les fiches modifiées ou nouvelles sont importées et repassent « à réviser ». `/status` expose le résultat (compteurs seulement) et le paquet Home Assistant alerte si la veille échoue ou ne tourne plus.

Chaque écriture se fait avec contrôle d'ETag : une fiche modifiée sur l'iPhone depuis la simulation n'est pas écrasée, elle est signalée dans le journal.
Le compte utilise un **mot de passe d'application** Apple (account.apple.com > Connexion et sécurité > Mots de passe pour app), jamais le mot de passe du compte.

## Sécurité

- **Réseau local uniquement** : ne pas publier carnet derrière un reverse proxy.
- **Mot de passe unique** (`CARNET_PASSWORD`), session de 30 jours dans un cookie signé.
- **Base chiffrée** avec SQLCipher (`CARNET_DB_KEY`). La clé n'est jamais écrite sur disque ; sans elle, la base est illisible : note-la en lieu sûr.
- `/status` n'expose que des compteurs, pour Home Assistant.
- Le dépôt Git ne contient aucune donnée personnelle (`tests/donnees/` : contacts fictifs).

## Installation

### 1. Dossiers sur le NAS
- Crée le dossier de données **dans File Station**, par exemple `/volume1/homes/<utilisateur>/carnet`. Le conteneur adopte son propriétaire : rien à régler côté UID/GID.
- Le dossier d'état, par exemple `/volume1/docker/carnet/state`, est créé tout seul.

### 2. Service Docker
Ajoute le service de `docker-compose.yml` à la stack (dans la même stack que le kit, pour que `http://kit-urgence:8095` soit joignable), puis renseigne les variables de `.env.example` :
`CARNET_DATA_DIR`, `CARNET_STATE_DIR`, `CARNET_PASSWORD`, `CARNET_DB_KEY`, et les variables existantes du kit `KIT_DATA_DIR` et `KIT_API_TOKEN`.

L'image `ghcr.io/<propriétaire>/carnet:latest` est publiée par `.github/workflows/docker.yml` à chaque push sur `main`.

### 3. Home Assistant (facultatif)
Copie `homeassistant/carnet.yaml` dans `/config/packages/`, ajoute `carnet_status_url` dans `secrets.yaml`, puis redémarre.

## Exports à déposer

| Source | Où le faire | Fichier |
| --- | --- | --- |
| iCloud | icloud.com > Contacts > tout sélectionner > Exporter la vCard | `.vcf` |
| Gmail | contacts.google.com > Exporter > vCard (et de même pour « Autres contacts ») | `.vcf` |
| Outlook.com | Contacts > Gérer les contacts > Exporter les contacts | `.csv` |
| LinkedIn | Préférences > Confidentialité des données > Obtenir une copie de vos données | `Connections.csv` |

## Variables

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `CARNET_PASSWORD` | obligatoire | mot de passe de l'interface |
| `CARNET_DB_KEY` | obligatoire | clé SQLCipher de la base |
| `CARNET_REGION` | `FR` | indicatif par défaut des numéros nationaux |
| `CARNET_ARCHIVE_JOURS` | `365` | conservation des exports d'origine |
| `CARNET_ALERTE_JOURS` | `30` | préavis avant suppression |
| `CARNET_SESSION_JOURS` | `30` | durée de la session |
| `CARNET_EMOJI_GROUPES` | vide | règles « émoji:groupe » séparées par `;` (ex. `🍕:Amis;🔧:Artisans et services`) : un contact contenant l'émoji rejoint le groupe |
| `CARNET_ICLOUD_USER` | vide | identifiant Apple (V2) |
| `CARNET_ICLOUD_PASSWORD` | vide | mot de passe d'application Apple (V2) |
| `CARNET_LINKEDIN_CLIENT_ID` / `_SECRET` | vide | app LinkedIn (portabilité des données) pour le bouton « Se connecter à LinkedIn » |
| `CARNET_LINKEDIN_REDIRECT` | `https://localhost/carnet-linkedin` | adresse de retour déclarée dans l'onglet Auth de l'app |
| `CARNET_SYNOLOGY_URL` | vide | CardDAV de Synology Contacts, ex. `http://192.168.1.90:5000/carddav/carnet/` (copie de nuit) |
| `CARNET_SYNOLOGY_USER` / `_PASSWORD` | `carnet` / vide | compte DSM dédié, limité à l'application Contacts |
| `CARNET_SYNOLOGY_CARNET` | `My Contacts\|Mes contacts` | carnet d'adresses visé (nom CardDAV, souvent en anglais ; plusieurs noms séparés par `\|`) ; jamais un carnet partagé (« Contacts de l'équipe ») |
| `CARNET_SYNOLOGY_VERIFIER_TLS` | `oui` | `non` pour accepter le certificat du NAS joint par son adresse IP (réseau local) |
| `CARNET_SAUVEGARDE_JOURS` | `30` | exports .vcf datés gardés dans `archives/sauvegardes` |
| `CARNET_IMMICH_URL` / `CARNET_IMMICH_CLE` | `http://immich-server:2283` / vide | Immich : liaisons, photos HD, dates de naissance, affiches — droits : voir « Droits de la clé d'API Immich » |
| `CARNET_TREEMICH_URL` / `_EMAIL` / `_PASSWORD` | `http://treemich-api:4000` / vide | Treemich : relations familiales des contacts liés |
| `CARNET_HA_TOKEN` | vide | jeton des appels `/ha/…` de Home Assistant (noms et dates de naissance) |
| `CARNET_VEILLE_HEURE` | `03:00` | heure de la veille iCloud quotidienne (vide : désactivée) |
| `KIT_URL` | `http://kit-urgence:8095` | API du kit d'urgence |
| `KIT_API_TOKEN` | vide | jeton du kit ; sans lui, le kit se régénère à sa prochaine synchronisation |

## Développement

```sh
pip install -r requirements-dev.txt && python -m pytest -q
cd frontend && npm ci && npm run build      # écrit app/static
CARNET_PASSWORD=x CARNET_DB_KEY=y CARNET_DATA=./data CARNET_STATE=./state CARNET_KIT_CONFIG= \
  uvicorn app.main:app --port 8096
```

## Suite prévue
- **V3** : veille quotidienne, Home Assistant complet, liens Immich et Treemich, copie nocturne vers Synology Contacts.
