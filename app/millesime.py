"""Millésime (2.21) : l'appli qui date les scans d'Immich par l'âge des visages.

carnet vient lire `GET /api/etat` de Millésime (jeton MILLESIME_JETON_CARNET) :
- l'état du calcul (photos à dater, visages à analyser, message « allume le PC »), montré dans
  Connexion › Millésime ;
- les personnes des scans qui n'ont pas de date de naissance dans Immich, montrées dans la tuile
  « Sans anniversaire » d'À traiter. Ce n'est pas une décision : la tuile ne compte pas dans le
  chiffre de l'onglet. La date se saisit sur la fiche ; carnet la reporte dans Immich (Connexion ›
  Immich › Synchroniser, ou la nuit), puis Millésime peut dater les scans de cette personne.

carnet n'écrit rien dans Millésime.
"""
from __future__ import annotations

import httpx

from .carnet import Carnet
from .modele import nom_affiche
from .temps import iso, maintenant

DUREE = 600          # secondes : une lecture de Millésime toutes les 10 minutes au plus


def configure(c: Carnet) -> bool:
    return bool(c.cfg.millesime_jeton)


def lire(c: Carnet, forcer: bool = False) -> dict:
    """{"ok": bool, "etat": {...} | None, "erreur": str, "le": iso}. Gardé 10 minutes."""
    if not configure(c):
        return {"ok": False, "etat": None, "erreur": "", "le": None}
    if forcer:
        c._memo.pop("millesime", None)

    def calcul():
        try:
            with c.http("millesime") as client:
                r = client.get(f"{c.cfg.millesime_url}/api/etat", timeout=5,
                               headers={"Authorization": f"Bearer {c.cfg.millesime_jeton}"})
            if r.status_code == 401:
                return {"ok": False, "etat": None, "le": iso(maintenant()),
                        "erreur": "Millésime refuse le jeton (CARNET_MILLESIME_JETON = MILLESIME_JETON_CARNET)."}
            r.raise_for_status()
            return {"ok": True, "etat": r.json(), "erreur": "", "le": iso(maintenant())}
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "etat": None, "le": iso(maintenant()),
                    "erreur": f"Millésime injoignable ({exc.__class__.__name__})."}
    return c.memo("millesime", calcul, DUREE)


def resume(c: Carnet) -> str:
    l = lire(c)
    if not l["ok"]:
        return "non configuré" if not configure(c) else "injoignable"
    e = l["etat"]
    if e.get("a_analyser"):
        return f"{e['a_analyser']} visage(s) à analyser sur le PC"
    return f"{e.get('a_dater', 0)} photo(s) à dater"


def sans_anniversaire(c: Carnet) -> list[dict]:
    """Personnes des scans sans date de naissance dans Immich, avec la fiche carnet reliée s'il y en a
    une : [{person_id, nom, scans, uid, fiche}] (le plus de scans d'abord)."""
    l = lire(c)
    if not l["ok"]:
        return []
    par_immich = {v["immich"]: uid for uid, v in c.liaisons().items() if v.get("immich")}
    fiches = c.fiches()
    res = []
    for p in (l["etat"] or {}).get("sans_naissance") or []:
        uid = par_immich.get(p.get("person_id"))
        f = fiches.get(uid) if uid else None
        res.append({"person_id": p.get("person_id"), "nom": p.get("nom") or "", "scans": int(p.get("scans") or 0),
                    "uid": uid if f else None, "fiche": nom_affiche(f) if f else None})
    return res


def detail(c: Carnet) -> dict:
    """Pour Connexion › Millésime."""
    l = lire(c)
    e = l["etat"] or {}
    return {"configure": configure(c), "ok": l["ok"], "erreur": l["erreur"], "le": l["le"],
            "message": e.get("message"), "a_dater": e.get("a_dater"), "a_trancher": e.get("a_trancher"),
            "a_nommer": e.get("a_nommer"), "a_analyser": e.get("a_analyser"), "validees": e.get("validees"),
            "pc_connecte": e.get("pc_connecte"), "sans_anniversaire": len(e.get("sans_naissance") or [])}
