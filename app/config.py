"""Configuration lue dans l'environnement (variables de la stack Portainer).

Aucun secret n'a de valeur par défaut : sans CARNET_PASSWORD ni CARNET_DB_KEY,
l'application refuse de démarrer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data: Path              # dossier visible depuis le PC : depot/, archives/, export/
    state: Path             # base chiffrée, hors de tout partage réseau
    password: str           # mot de passe de l'interface
    db_key: str             # clé SQLCipher de la base
    region: str             # région par défaut des numéros sans indicatif
    archive_jours: int      # durée de conservation des archives
    alerte_jours: int       # préavis avant suppression d'une archive
    session_jours: int      # durée de la session sur un navigateur
    kit_config: Path | None # dossier config/ du kit d'urgence (volume)
    kit_vcf: str            # nom du fichier attendu par le kit
    kit_url: str            # URL interne du kit (réseau Docker de la stack)
    kit_token: str          # jeton des appels POST du kit
    static: Path            # interface compilée
    emoji_groupes: str      # règles « émoji:groupe;… » (facultatif)
    icloud_url: str = "https://contacts.icloud.com"
    icloud_user: str = ""       # identifiant Apple (V2 : écriture dans iCloud)
    icloud_password: str = ""   # mot de passe d'application Apple, pas celui du compte
    veille_heure: str = "03:00" # veille iCloud quotidienne (vide : désactivée)
    linkedin_client_id: str = ""      # app LinkedIn Developers (portabilité des données)
    linkedin_client_secret: str = ""
    linkedin_redirect: str = "https://localhost/carnet-linkedin"

    @property
    def depot(self) -> Path:
        return self.data / "depot"

    @property
    def archives(self) -> Path:
        return self.data / "archives"

    @property
    def export(self) -> Path:
        return self.data / "export"

    @property
    def db_path(self) -> Path:
        return self.state / "carnet.db"


def _obligatoire(nom: str) -> str:
    valeur = os.environ.get(nom, "").strip()
    if not valeur or valeur == "change-moi":
        raise RuntimeError(f"Variable d'environnement {nom} absente : à définir dans la stack.")
    return valeur


def charger() -> Config:
    kit = os.environ.get("CARNET_KIT_CONFIG", "/kit-config").strip()
    return Config(
        data=Path(os.environ.get("CARNET_DATA", "/data")),
        state=Path(os.environ.get("CARNET_STATE", "/state")),
        password=_obligatoire("CARNET_PASSWORD"),
        db_key=_obligatoire("CARNET_DB_KEY"),
        region=os.environ.get("CARNET_REGION", "FR").upper(),
        archive_jours=int(os.environ.get("CARNET_ARCHIVE_JOURS", "365")),
        alerte_jours=int(os.environ.get("CARNET_ALERTE_JOURS", "30")),
        session_jours=int(os.environ.get("CARNET_SESSION_JOURS", "30")),
        kit_config=Path(kit) if kit else None,
        kit_vcf=os.environ.get("CARNET_KIT_VCF", "contacts-urgence.vcf"),
        kit_url=os.environ.get("KIT_URL", "http://kit-urgence:8095").rstrip("/"),
        kit_token=os.environ.get("KIT_API_TOKEN", "").strip(),
        static=Path(os.environ.get("CARNET_STATIC", str(Path(__file__).parent / "static"))),
        emoji_groupes=os.environ.get("CARNET_EMOJI_GROUPES", ""),
        icloud_url=os.environ.get("CARNET_ICLOUD_URL", "https://contacts.icloud.com").strip(),
        icloud_user=os.environ.get("CARNET_ICLOUD_USER", "").strip(),
        icloud_password=os.environ.get("CARNET_ICLOUD_PASSWORD", "").strip(),
        veille_heure=os.environ.get("CARNET_VEILLE_HEURE", "03:00").strip(),
        linkedin_client_id=os.environ.get("CARNET_LINKEDIN_CLIENT_ID", "").strip(),
        linkedin_client_secret=os.environ.get("CARNET_LINKEDIN_CLIENT_SECRET", "").strip(),
        linkedin_redirect=os.environ.get("CARNET_LINKEDIN_REDIRECT", "https://localhost/carnet-linkedin").strip(),
    )
