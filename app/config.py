"""Configuration lue dans l'environnement (variables de la stack Portainer).

Les durées et plafonds sont fixés dans le code (garde-fous sans réglage). Seuls les accès et
les secrets viennent de la stack. 2.26 : les réglages d'usage (heure de la nuit, émojis, carnet
Synology, certificat) se règlent dans l'écran Réglages (app/reglages.py) ; leurs anciennes
variables ne sont lues qu'une fois, au premier démarrage, pour la reprise. Les valeurs ci-dessous
sont leurs valeurs par défaut.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from . import maison


@dataclass(frozen=True)
class Config:
    data: Path                    # dossier visible depuis le PC : depot/ (fichiers à importer)
    state: Path                   # base et sauvegardes : hors de tout partage et de OneDrive
    password: str                 # mot de passe de l'interface
    static: Path                  # interface compilée
    region: str = "FR"            # région des numéros sans indicatif
    emoji_groupes: str = ""       # réglage : règles « émoji:groupe;… » (facultatif)
    veille_heure: str = "03:00"   # réglage : heure de la nuit ; vide ou « off » : nuit désactivée
    icloud_url: str = "https://contacts.icloud.com"
    icloud_user: str = ""
    icloud_password: str = ""     # mot de passe d'application Apple, pas celui du compte
    synology_url: str = ""        # CardDAV de Synology Contacts (copie de nuit) ; vide : désactivée
    synology_user: str = "carnet"
    synology_password: str = ""
    synology_carnet: str = "My Contacts|Mes contacts"   # réglage : carnet d'adresses voulu (noms séparés par |)
    synology_verifier_tls: bool = True                  # réglage : vérifier le certificat HTTPS de Synology
    immich_url: str = "http://immich-server:2283"
    immich_cle: str = ""
    treemich_url: str = "http://treemich-api:4000"
    treemich_email: str = ""
    treemich_password: str = ""
    ha_token: str = ""            # jeton des appels de Home Assistant (/ha/…)
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect: str = "https://localhost/carnet-linkedin"
    telegram_api_id: str = ""     # my.telegram.org : import manuel des contacts Telegram
    telegram_api_hash: str = ""
    kit_config: Path | None = None   # dossier config/ du kit d'urgence (volume)
    kit_url: str = "http://kit-urgence:8095"
    kit_token: str = ""           # 2.26 : MAISON_JETON (le kit 2.4.0 l'accepte)
    millesime_url: str = "http://millesime:8098"   # 2.21 : Millésime (datation des scans)
    millesime_jeton: str = ""                      # 2.26 : MAISON_JETON ; vide : Millésime non lu
    lecture_seule: bool = False      # CARNET_LECTURE_SEULE : aucune écriture hors de carnet
    db_key: str = field(default="", repr=False)   # 2.28 : CARNET_DB_KEY, chiffrement SQLCipher de carnet2.db ; vide : en clair
    contacts: Path | None = None     # 2.28 : coffre Obsidian « Contacts » (volume) ; notes dans Personnes/

    @property
    def db_path(self) -> Path:
        return self.state / "carnet2.db"

    @property
    def sauvegardes(self) -> Path:
        return self.state / "sauvegardes"

    @property
    def depot(self) -> Path:
        return self.data / "depot"

    @property
    def nuit_active(self) -> bool:
        return bool(self.veille_heure) and self.veille_heure.lower() not in ("off", "non", "0")


def _env(nom: str, defaut: str = "") -> str:
    return os.environ.get(nom, defaut).strip()


def charger() -> Config:
    mdp = maison.mot_de_passe()                          # 2.26 : MAISON_PASSWORD seul (CARNET_PASSWORD n'est plus lu)
    if len(mdp) < 12 or mdp == "change-moi":
        raise RuntimeError("MAISON_PASSWORD est absent ou trop court (12 caractères au moins) : "
                           "carnet ne démarre pas. À définir dans la stack.")
    state = Path(_env("CARNET_STATE", "/state"))
    kit = _env("CARNET_KIT_CONFIG", "/kit-config")
    return Config(
        data=Path(_env("CARNET_DATA", "/data")),
        state=state,
        password=mdp,
        static=Path(_env("CARNET_STATIC", str(Path(__file__).parent / "static"))),
        region=_env("CARNET_REGION", "FR").upper(),
        icloud_url=_env("CARNET_ICLOUD_URL", "https://contacts.icloud.com"),
        icloud_user=_env("CARNET_ICLOUD_USER"),
        icloud_password=_env("CARNET_ICLOUD_PASSWORD"),
        synology_url=_env("CARNET_SYNOLOGY_URL"),
        synology_user=_env("CARNET_SYNOLOGY_USER", "carnet"),
        synology_password=_env("CARNET_SYNOLOGY_PASSWORD"),
        immich_url=_env("CARNET_IMMICH_URL", "http://immich-server:2283"),
        immich_cle=_env("CARNET_IMMICH_CLE"),
        treemich_url=_env("CARNET_TREEMICH_URL", "http://treemich-api:4000"),
        treemich_email=_env("CARNET_TREEMICH_EMAIL"),
        treemich_password=_env("CARNET_TREEMICH_PASSWORD"),
        ha_token=_env("CARNET_HA_TOKEN"),
        linkedin_client_id=_env("CARNET_LINKEDIN_CLIENT_ID"),
        linkedin_client_secret=_env("CARNET_LINKEDIN_CLIENT_SECRET"),
        linkedin_redirect=_env("CARNET_LINKEDIN_REDIRECT", "https://localhost/carnet-linkedin"),
        telegram_api_id=_env("CARNET_TELEGRAM_API_ID"),
        telegram_api_hash=_env("CARNET_TELEGRAM_API_HASH"),
        kit_config=Path(kit) if kit else None,
        kit_url=_env("KIT_URL", "http://kit-urgence:8095").rstrip("/"),
        kit_token=maison.jeton_a_envoyer(),           # 2.26 : MAISON_JETON seul
        millesime_url=_env("CARNET_MILLESIME_URL", "http://millesime:8098").rstrip("/"),
        millesime_jeton=maison.jeton_a_envoyer(),   # 2.26 : MAISON_JETON seul
        lecture_seule=maison.lecture_seule("CARNET_LECTURE_SEULE"),   # 2.25 : MAISON_LECTURE_SEULE, forçable ici
        db_key=os.environ.get("CARNET_DB_KEY", ""),   # 2.28 : jamais rognée, jamais écrite dans un journal
        contacts=Path(contacts) if (contacts := _env("CARNET_CONTACTS", "/contacts")) else None,
    )
