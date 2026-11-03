"""Import manuel des contacts Telegram (API officielle de compte utilisateur, Telethon).

Rien ne reste sur le NAS : la session vit en mémoire le temps d'un import (StringSession), puis
elle est fermée côté Telegram (déconnexion) et oubliée. Il faut donc un code à chaque import.
Étapes : demander le code (numéro de Julien) → saisir le code (et le mot de passe si la double
authentification est active) → lecture des contacts → déconnexion. Aucune donnée de session,
aucun code ni numéro n'est écrit dans les journaux.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from . import normalisation, reseaux
from .carnet import Carnet, ErreurCarnet

log = logging.getLogger("carnet")
DUREE_MAX = 10 * 60   # une connexion commencée et non terminée est abandonnée après 10 min


class _Boucle:
    """Une boucle asyncio dans son propre fil : Telethon est asynchrone, FastAPI appelle en synchrone."""

    def __init__(self):
        self.boucle = asyncio.new_event_loop()
        threading.Thread(target=self.boucle.run_forever, name="telegram", daemon=True).start()

    def faire(self, coroutine, delai: float = 60):
        return asyncio.run_coroutine_threadsafe(coroutine, self.boucle).result(delai)


_boucle: _Boucle | None = None
_verrou = threading.RLock()   # une seule opération Telegram à la fois (double clic, deux onglets)


def _executer(coroutine, delai: float = 60):
    global _boucle
    with _verrou:
        if _boucle is None:
            _boucle = _Boucle()
    return _boucle.faire(coroutine, delai)


def _client(c: Carnet):
    """Client Telethon en mémoire seulement (tests : c.transports['telegram'] fournit une fabrique)."""
    fabrique = c.transports.get("telegram")
    if fabrique:
        return fabrique()
    if not (c.cfg.telegram_api_id and c.cfg.telegram_api_hash):
        raise ErreurCarnet("Renseigne CARNET_TELEGRAM_API_ID et CARNET_TELEGRAM_API_HASH (my.telegram.org) dans la stack.")
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(), int(c.cfg.telegram_api_id), c.cfg.telegram_api_hash,
                          device_model="carnet", app_version="carnet", system_version="NAS")


def _en_cours(c: Carnet) -> dict | None:
    e = c.__dict__.get("_telegram")
    if e and time.monotonic() > e["jusqua"]:
        abandonner(c)
        return None
    return e


def _expirer(c: Carnet, e: dict) -> None:
    """Minuteur : la connexion commencée est fermée et oubliée au bout de 10 min, même sans
    nouvel appel."""
    with _verrou:
        if c.__dict__.get("_telegram") is e:
            abandonner(c)


def demander_code(c: Carnet, telephone: str) -> dict:
    t = normalisation.telephone(telephone, "mobile", c.cfg.region)
    if not t or not t.get("valide"):
        raise ErreurCarnet("Numéro non reconnu : écris ton numéro Telegram, par exemple 06 12 34 56 78.")
    if not _verrou.acquire(blocking=False):
        raise ErreurCarnet("Une connexion à Telegram est déjà en cours.")
    try:
        return _demander_code(c, t["valeur"])
    finally:
        _verrou.release()


def _demander_code(c: Carnet, numero: str) -> dict:
    abandonner(c)
    client = _client(c)

    async def envoyer():
        await client.connect()
        return await client.send_code_request(numero)
    try:
        envoi = _executer(envoyer())
    except ErreurCarnet:
        raise
    except Exception as exc:  # noqa: BLE001 — message de Telegram, sans données personnelles
        _executer(client.disconnect())
        raise ErreurCarnet(f"Telegram refuse l'envoi du code ({exc.__class__.__name__}).") from exc
    e = {"client": client, "telephone": numero, "hash": envoi.phone_code_hash, "jusqua": time.monotonic() + DUREE_MAX}
    c._telegram = e
    minuteur = threading.Timer(DUREE_MAX, _expirer, args=(c, e))
    minuteur.daemon = True
    minuteur.start()
    return {"ok": True, "message": "Code envoyé dans ton application Telegram."}


def importer(c: Carnet, code: str, mot_de_passe: str = "") -> dict:
    """Connexion avec le code reçu, lecture des contacts, puis déconnexion (session effacée).
    Après une connexion réussie, la déconnexion a lieu quoi qu'il arrive."""
    if not _verrou.acquire(blocking=False):
        raise ErreurCarnet("Import Telegram déjà en cours.")
    try:
        return _importer(c, code, mot_de_passe)
    finally:
        _verrou.release()


def _importer(c: Carnet, code: str, mot_de_passe: str) -> dict:
    e = _en_cours(c)
    if not e:
        raise ErreurCarnet("Demande d'abord un code (il est valable quelques minutes).")
    client = e["client"]

    async def lire():
        from telethon.errors import SessionPasswordNeededError
        from telethon.tl.functions.contacts import GetContactsRequest
        try:
            await client.sign_in(phone=e["telephone"], code=(code or "").strip(), phone_code_hash=e["hash"])
        except SessionPasswordNeededError:
            if not mot_de_passe:
                return None
            await client.sign_in(password=mot_de_passe)
        reponse = await client(GetContactsRequest(hash=0))
        return list(getattr(reponse, "users", []) or [])
    try:
        utilisateurs = _executer(lire(), delai=120)
    except Exception as exc:  # noqa: BLE001
        abandonner(c)
        raise ErreurCarnet(f"Connexion à Telegram impossible ({exc.__class__.__name__}) : redemande un code.") from exc
    if utilisateurs is None:
        return {"ok": False, "mot_de_passe": True,
                "message": "Ton compte a la double authentification : saisis aussi ton mot de passe Telegram."}
    try:
        personnes = []
        for u in utilisateurs:
            if getattr(u, "bot", False) or getattr(u, "deleted", False):
                continue
            tel = normalisation.telephone("+" + u.phone if getattr(u, "phone", None) else "", "mobile", c.cfg.region)
            pseudo = getattr(u, "username", None) or next((x.username for x in (getattr(u, "usernames", None) or [])
                                                            if getattr(x, "active", True)), "") or ""
            nom = " ".join(x for x in (getattr(u, "first_name", "") or "", getattr(u, "last_name", "") or "") if x).strip()
            personnes.append({"ext_id": str(u.id), "nom": nom or pseudo,
                              "telephone": tel["valeur"] if tel and tel.get("valide") else "", "pseudo": pseudo,
                              "prenom": getattr(u, "first_name", "") or "", "nom_famille": getattr(u, "last_name", "") or ""})
    finally:
        abandonner(c, deconnecter=True)     # session fermée côté Telegram et oubliée, même après une erreur
    reseaux.enregistrer(c, "telegram", personnes)
    reseaux.purger(c)
    n = reseaux.proposer(c)
    c.base.noter("reseaux", f"Telegram : {len(personnes)} contacts lus, {n} rattachement(s) proposé(s) ; session fermée et effacée")
    return {"ok": True, "lues": len(personnes), "proposees": n}


def abandonner(c: Carnet, deconnecter: bool = True) -> None:
    """Ferme la session côté Telegram (elle n'est plus utilisable) et l'oublie."""
    e = c.__dict__.pop("_telegram", None)
    if not e:
        return
    client = e["client"]

    async def fermer():
        try:
            if deconnecter and await client.is_user_authorized():
                await client.log_out()
        finally:
            await client.disconnect()
    try:
        _executer(fermer(), delai=30)
    except Exception:  # noqa: BLE001 — la session en mémoire est oubliée de toute façon
        log.info("Telegram : déconnexion incomplète, session oubliée")


def etat(c: Carnet) -> dict:
    return {"configure": bool(c.cfg.telegram_api_id and c.cfg.telegram_api_hash) or "telegram" in c.transports,
            "code_demande": bool(_en_cours(c))}
