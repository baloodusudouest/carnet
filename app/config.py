"""Configuration lue dans l'environnement (variables de la stack Portainer).

Les durées et plafonds sont fixés dans le code (garde-fous sans réglage). Seuls les accès,
les secrets et l'heure de la nuit viennent de la stack.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data: Path                    # dossier visible depuis le PC : depot/ (fichiers à importer)
    state: Path                   # base et sauvegardes : hors de tout partage et de OneDrive
    password: str                 # mot de passe de l'interface
    static: Path                  # interface compilée
    region: str = "FR"            # région des numéros sans indicatif
    emoji_groupes: str = ""       # règles « émoji:groupe;… » (facultatif)
    veille_heure: str = "03:00"   # heure de la nuit ; vide ou « off » : nuit désactivée
    icloud_url: str = "https://contacts.icloud.com"
    icloud_user: str = ""
    icloud_password: str = ""     # mot de passe d'application Apple, pas celui du compte
    synology_url: str = ""        # CardDAV de Synology Contacts (copie de nuit) ; vide : désactivée
    synology_user: str = "carnet"
    synology_password: str = ""
    synology_carnet: str = "My Contacts|Mes contacts"
    synology_verifier_tls: bool = True
    immich_url: str = "http://immich-server:2283"
    immich_cle: str = ""
    treemich_url: str = "http://treemich-api:4000"
    treemich_email: str = ""
    treemich_password: str = ""
    ha_token: str = ""            # jeton des appels de Home Assistant (/ha/…)
    sillage_jeton: str = ""       # 2.15 : jeton de Sillage pour lire /sillage/personnes ; vide : adresse fermée
    sillage_adresse: str = ""     # 2.15 : adresse de Sillage dans le navigateur (lien « Sillage » de la fiche)
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect: str = "https://localhost/carnet-linkedin"
    telegram_api_id: str = ""     # my.telegram.org : import manuel des contacts Telegram
    telegram_api_hash: str = ""
    kit_config: Path | None = None   # dossier config/ du kit d'urgence (volume)
    kit_url: str = "http://kit-urgence:8095"
    kit_token: str = ""
    lecture_seule: bool = False      # CARNET_LECTURE_SEULE : aucune écriture hors de carnet

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
    mdp = _env("CARNET_PASSWORD")
    if not mdp or mdp == "change-moi":
        raise RuntimeError("Variable d'environnement CARNET_PASSWORD absente : à définir dans la stack.")
    state = Path(_env("CARNET_STATE", "/state"))
    kit = _env("CARNET_KIT_CONFIG", "/kit-config")
    return Config(
        data=Path(_env("CARNET_DATA", "/data")),
        state=state,
        password=mdp,
        static=Path(_env("CARNET_STATIC", str(Path(__file__).parent / "static"))),
        region=_env("CARNET_REGION", "FR").upper(),
        emoji_groupes=os.environ.get("CARNET_EMOJI_GROUPES", ""),
        veille_heure=_env("CARNET_VEILLE_HEURE", "03:00"),
        icloud_url=_env("CARNET_ICLOUD_URL", "https://contacts.icloud.com"),
        icloud_user=_env("CARNET_ICLOUD_USER"),
        icloud_password=_env("CARNET_ICLOUD_PASSWORD"),
        synology_url=_env("CARNET_SYNOLOGY_URL"),
        synology_user=_env("CARNET_SYNOLOGY_USER", "carnet"),
        synology_password=_env("CARNET_SYNOLOGY_PASSWORD"),
        synology_carnet=_env("CARNET_SYNOLOGY_CARNET", "My Contacts|Mes contacts"),
        synology_verifier_tls=_env("CARNET_SYNOLOGY_VERIFIER_TLS", "oui").lower() not in ("non", "false", "0", "no"),
        immich_url=_env("CARNET_IMMICH_URL", "http://immich-server:2283"),
        immich_cle=_env("CARNET_IMMICH_CLE"),
        treemich_url=_env("CARNET_TREEMICH_URL", "http://treemich-api:4000"),
        treemich_email=_env("CARNET_TREEMICH_EMAIL"),
        treemich_password=_env("CARNET_TREEMICH_PASSWORD"),
        ha_token=_env("CARNET_HA_TOKEN"),
        sillage_jeton=_env("CARNET_JETON_SILLAGE"),
        sillage_adresse=_env("CARNET_SILLAGE_URL").rstrip("/"),
        linkedin_client_id=_env("CARNET_LINKEDIN_CLIENT_ID"),
        linkedin_client_secret=_env("CARNET_LINKEDIN_CLIENT_SECRET"),
        linkedin_redirect=_env("CARNET_LINKEDIN_REDIRECT", "https://localhost/carnet-linkedin"),
        telegram_api_id=_env("CARNET_TELEGRAM_API_ID"),
        telegram_api_hash=_env("CARNET_TELEGRAM_API_HASH"),
        kit_config=Path(kit) if kit else None,
        kit_url=_env("KIT_URL", "http://kit-urgence:8095").rstrip("/"),
        kit_token=_env("KIT_API_TOKEN"),
        lecture_seule=_env("CARNET_LECTURE_SEULE").lower() in ("oui", "1", "true", "yes"),
    )
