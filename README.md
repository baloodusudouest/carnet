# carnet

Application auto-hébergée qui **rassemble les contacts** de plusieurs carnets (iCloud, Gmail, Outlook.com, LinkedIn en complément), les fait **relire un par un**, **fusionne les doublons champ par champ**, puis produit un export `.vcf` propre et la liste des contacts d'urgence pour [kit-urgence](https://github.com/baloodusudouest/kit-urgence).

Cette version (V1) ne se connecte à aucun compte : tu déposes des exports faits à la main, et rien n'est jamais écrit dans iCloud, Gmail ou Outlook.

## Ce que fait la V1

| Étape | Détail |
| --- | --- |
| Dépôt | glisser les exports dans l'interface, ou les copier dans `depot/` |
| Import | lecture des `.vcf` iCloud et Gmail, du `.csv` Outlook et de `Connections.csv` LinkedIn ; chaque fichier est archivé tel quel |
| Doublons | même mobile, même courriel, même fixe avec un nom compatible, noms proches (RapidFuzz) renforcés par la date de naissance ou la société |
| Révision | une colonne par source, la fiche retenue à droite ; tout se fait au clavier (`?` affiche les raccourcis) |
| Formats | numéros stockés en E.164 et affichés `+33 6 12 34 56 78` ; noms `Prénom NOM` |
| Export | `export/carnet-AAAA-MM-JJ_HHMM.vcf` (vCard 3.0, lisible par iCloud), contacts vérifiés seulement |
| Kit d'urgence | bouton « Envoyer au kit » : réécrit `contacts-urgence.vcf` dans le dossier du kit, puis lui demande de se régénérer |
| Archives | exports d'origine gardés 365 jours puis supprimés ; un onglet et Home Assistant préviennent 30 jours avant |

LinkedIn complète des contacts existants (société, poste, profil) mais n'en crée jamais.

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
- **V2** : écriture dans iCloud en place (CardDAV, UID conservés, contrôle ETag), simulation des différences, journal annulable.
- **V3** : veille quotidienne, Home Assistant complet, liens Immich et Treemich, copie nocturne vers Synology Contacts.
