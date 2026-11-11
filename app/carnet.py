"""Le contexte commun de carnet : configuration, base, verrou d'écriture et accès aux services.

Un seul verrou couvre toute écriture vers iCloud (Valider, Annuler, Restaurer, fusion, nuit) :
il n'y a jamais deux écrivains en même temps. Les tests remplacent les accès réseau par de
faux serveurs (`transports`).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any

import httpx

from . import normalisation
from .base import Base
from .carddav import CardDAV
from .config import Config
from .garde import ErreurCarnet, LectureSeule, Occupe  # noqa: F401 — réexportés pour les autres modules
from .liens import Immich, Treemich

log = logging.getLogger("carnet")



class Carnet:
    def __init__(self, cfg: Config, transports: dict[str, httpx.BaseTransport] | None = None):
        self.cfg = cfg
        self.base = Base(cfg.db_path)
        self.transports = transports or {}
        self.verrou = threading.Lock()
        self.annulations: dict[str, dict] = {}    # jeton → écriture à défaire (10 s)
        self._memo: dict[str, tuple[Any, Any]] = {}
        self._treemich: Treemich | None = None
        self.tache: dict = {"nom": None, "etat": "libre", "message": ""}
        normalisation.configurer_emojis(cfg.emoji_groupes)

    # ------------------------------------------------------------ verrou

    @contextmanager
    def ecriture(self, attendre: float = 0):
        """Prend le verrou d'écriture. attendre : secondes d'attente avant de renoncer."""
        pris = self.verrou.acquire(timeout=attendre) if attendre > 0 else self.verrou.acquire(blocking=False)
        if not pris:
            raise Occupe("Une autre opération écrit en ce moment dans iCloud : réessaie dans un instant.")
        try:
            yield
        finally:
            self.verrou.release()

    # ------------------------------------------------------------ services

    def exiger_ecriture(self, service: str) -> None:
        """À appeler à l'entrée de toute opération qui écrit hors de carnet."""
        if self.cfg.lecture_seule:
            raise LectureSeule(service)

    def icloud(self) -> CardDAV:
        dav = CardDAV(self.cfg.icloud_url, self.cfg.icloud_user, self.cfg.icloud_password,
                      transport=self.transports.get("icloud"))
        dav.lecture_seule = self.cfg.lecture_seule
        return dav

    def synology(self) -> CardDAV:
        dav = CardDAV(self.cfg.synology_url, self.cfg.synology_user, self.cfg.synology_password,
                      transport=self.transports.get("synology"), nom_carnet=self.cfg.synology_carnet,
                      verifier_tls=self.cfg.synology_verifier_tls, service="Synology")
        dav.lecture_seule = self.cfg.lecture_seule
        return dav

    def immich(self) -> Immich:
        im = Immich(self.cfg.immich_url, self.cfg.immich_cle, transport=self.transports.get("immich"))
        im.lecture_seule = self.cfg.lecture_seule
        return im

    def treemich(self) -> Treemich:
        # Une seule session, gardée : Treemich limite le nombre de connexions
        if self._treemich is None:
            self._treemich = Treemich(self.cfg.treemich_url, self.cfg.treemich_email, self.cfg.treemich_password,
                                      transport=self.transports.get("treemich"))
        self._treemich.lecture_seule = self.cfg.lecture_seule
        return self._treemich

    def http(self, nom: str, **kw) -> httpx.Client:
        return httpx.Client(timeout=60, follow_redirects=True, transport=self.transports.get(nom), **kw)

    # ------------------------------------------------------------ calculs gardés en mémoire

    def memo(self, cle: str, calcul, duree: float | None = None):
        """Résultat gardé tant que la base ne change pas (ou pendant `duree` secondes)."""
        marque = time.monotonic() // duree if duree else self.base.generation
        trouve = self._memo.get(cle)
        if trouve and trouve[0] == marque:
            return trouve[1]
        valeur = calcul()
        self._memo[cle] = (marque, valeur)
        return valeur

    def memo_present(self, cle: str, duree: float):
        """Valeur gardée si elle est encore valable, sans la recalculer (None sinon)."""
        trouve = self._memo.get(cle)
        return trouve[1] if trouve and trouve[0] == time.monotonic() // duree else None

    def oublier(self, prefixe: str = "") -> None:
        # Sans préfixe : tout sauf les données d'Immich et de Treemich (gardées 26 h)
        for cle in [k for k in self._memo if (k.startswith(prefixe) if prefixe else not k.startswith("liens"))]:
            self._memo.pop(cle, None)

    # ------------------------------------------------------------ fiches lues

    def fiches(self) -> dict[str, dict]:
        """uid → fiche (avec « a_photo »), d'après la dernière lecture d'iCloud."""
        def calcul():
            res = {}
            for l in self.base.tous("SELECT uid, fiche, photo FROM fiches"):
                f = json.loads(l["fiche"])
                f["a_photo"] = bool(l["photo"])
                res[l["uid"]] = f
            return res
        return self.memo("fiches", calcul)

    def fiche(self, uid: str) -> dict:
        f = self.fiches().get(uid)
        if f is None:
            raise ErreurCarnet("Ce contact n'existe plus dans iCloud (supprimé ou fusionné).")
        return {k: (list(v) if isinstance(v, list) else v) for k, v in f.items()}

    def liaison(self, uid: str) -> dict:
        res = {}
        for l in self.base.tous("SELECT service, ext_id, statut FROM liaisons WHERE uid = ?", (uid,)):
            res[l["service"]] = l["ext_id"]
            res[l["service"] + "_statut"] = l["statut"]
        return res

    def liaisons(self) -> dict[str, dict]:
        def calcul():
            res: dict[str, dict] = {}
            for l in self.base.tous("SELECT uid, service, ext_id, statut FROM liaisons"):
                res.setdefault(l["uid"], {})[l["service"]] = l["ext_id"]
                res[l["uid"]][l["service"] + "_statut"] = l["statut"]
            return res
        return self.memo("liaisons", calcul)
