"""Audit des fiches (carnet 2.1) : ce qui manque, validation, plateformes reliées.

- 4 critères : année de naissance (une date sans année, ou en 1900, compte comme manquante),
  adresse, téléphone, moyen de contact (téléphone ou courriel).
- « Validée » retire la fiche de tous les filtres de manques. L'empreinte des champs audités
  est gardée : si la fiche change ensuite (iPhone, import), elle repasse « à revoir ». Une
  écriture faite par carnet lui-même met l'empreinte à jour (icloud._enregistrer).
- Plateformes : iCloud, Immich, Treemich, LinkedIn, Facebook (Messenger), Instagram, WhatsApp,
  Telegram — d'après les liaisons et les profils de la carte iCloud.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import attentes
from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

# Depuis la 2.8, les critères sont les informations du tableau des attentes (app/attentes.py) :
# ce qui manque à une fiche dépend de ses groupes.
CRITERES = {k: v[1] for k, v in attentes.INFOS.items()}
PLATEFORMES = ["icloud", "immich", "treemich", "linkedin", "facebook", "instagram", "x", "whatsapp", "telegram"]
_WHATSAPP = re.compile(r"whatsapp|wa\.me", re.I)
_TELEGRAM = re.compile(r"telegram|t\.me/", re.I)


def empreinte(fiche: dict) -> str:
    """Hash des seuls champs audités, normalisés : la photo, les notes ou un profil social ne
    font pas repasser une fiche « à revoir »."""
    audit = {
        "annee": fiche.get("anniversaire") or "",
        "adresses": sorted(" ".join((a.get(k) or "").strip().lower() for k in ("rue", "cp", "ville", "pays"))
                           for a in fiche.get("adresses", [])),
        "telephones": sorted(t.get("valeur", "") for t in fiche.get("telephones", [])),
        "courriels": sorted(x.get("valeur", "").lower() for x in fiche.get("courriels", [])),
    }
    return hashlib.sha1(json.dumps(audit, sort_keys=True).encode()).hexdigest()[:16]


def validations(c: Carnet) -> dict[str, str]:
    return c.memo("validations", lambda: {l["uid"]: l["empreinte"] for l in c.base.tous("SELECT * FROM validations")})


def statut(c: Carnet, uid: str, fiche: dict) -> str | None:
    """« valide », « a_revoir » ou None (jamais validée)."""
    e = validations(c).get(uid)
    if e is None:
        return None
    return "valide" if e == empreinte(fiche) else "a_revoir"


def valider(c: Carnet, uid: str, etag_vu: str | None = None) -> dict:
    """Valide la fiche telle qu'elle est affichée : refus si elle a changé depuis (etag_vu)."""
    f = c.fiche(uid)
    if etag_vu:
        l = c.base.un("SELECT etag FROM fiches WHERE uid = ?", (uid,))
        if l and l["etag"] != etag_vu:
            raise ErreurCarnet("La fiche a changé depuis son affichage : recharge-la avant de la valider.")
    c.base.executer("INSERT OR REPLACE INTO validations(uid, empreinte, le) VALUES (?,?,?)",
                    (uid, empreinte(f), iso(maintenant())))
    c.oublier()
    return {"ok": True, "statut": "valide"}


def devalider(c: Carnet, uid: str) -> dict:
    c.base.executer("DELETE FROM validations WHERE uid = ?", (uid,))
    c.oublier()
    return {"ok": True, "statut": None}


def suivre_ecriture(cx, uid: str, avant: dict | None, apres: dict) -> None:
    """Écriture faite par carnet : une fiche validée et à jour le reste (empreinte suivie)."""
    l = cx.execute("SELECT empreinte FROM validations WHERE uid = ?", (uid,)).fetchone()
    if l and avant is not None and l["empreinte"] == empreinte(avant):
        cx.execute("UPDATE validations SET empreinte = ? WHERE uid = ?", (empreinte(apres), uid))


def plateformes(c: Carnet, uid: str, fiche: dict, texte: str | None = None) -> list[str]:
    """Plateformes reliées à la fiche (iCloud toujours)."""
    res = {"icloud"}
    lien = c.liaisons().get(uid, {})
    for s in ("immich", "treemich", "telegram", "instagram", "whatsapp", "facebook", "x"):
        if lien.get(s):
            res.add(s)
    for s in fiche.get("sites", []):
        t, v = s.get("type", ""), s.get("valeur", "")
        if t in ("linkedin", "facebook", "instagram", "whatsapp", "telegram", "x"):
            res.add(t)
        elif re.search(r"(^|//|\.)(twitter|x)\.com/", v, re.I):
            res.add("x")
        elif "linkedin.com" in v:
            res.add("linkedin")
        elif "facebook.com" in v or "messenger.com" in v:
            res.add("facebook")
        elif "instagram.com" in v:
            res.add("instagram")
    if uid in c.memo("linkedin_lies", lambda: {l["uid"] for l in c.base.tous("SELECT uid FROM linkedin WHERE uid IS NOT NULL")}):
        res.add("linkedin")
    if texte:
        for ligne in texte.splitlines():
            entete = ligne.split(":", 1)[0].upper()
            if ("IMPP" in entete or "X-SOCIALPROFILE" in entete) and _WHATSAPP.search(ligne):
                res.add("whatsapp")
            if ("IMPP" in entete or "X-SOCIALPROFILE" in entete) and _TELEGRAM.search(ligne):
                res.add("telegram")
    return [p for p in PLATEFORMES if p in res]


def resume(c: Carnet) -> dict[str, dict]:
    """uid → {attendues, manques, exceptees, score, total, statut, plateformes, decede} pour toutes
    les fiches (gardé en mémoire)."""
    def calcul():
        textes = {l["uid"]: l["texte"] for l in c.base.tous("SELECT uid, texte FROM fiches")}
        res = {}
        bilans, morts = attentes.tout(c), attentes.decedes(c)
        for uid, f in c.fiches().items():
            b = bilans[uid]
            res[uid] = {**b, "statut": statut(c, uid, f), "plateformes": plateformes(c, uid, f, textes.get(uid)),
                        "decede": uid in morts}
        return res
    return c.memo("completude", calcul)


def compteurs(c: Carnet) -> dict:
    r = resume(c)
    res = {k: sum(1 for x in r.values() if k in x["manques"] and x["statut"] != "valide") for k in CRITERES}
    res["a_revoir"] = sum(1 for x in r.values() if x["statut"] == "a_revoir")
    res["validees"] = sum(1 for x in r.values() if x["statut"] == "valide")
    return res


def analyse_globale(c: Carnet, remettre_a_zero: bool = False) -> dict:
    """Recalcule tout : Immich et Treemich relus, doublons, propositions, complétude. Avec
    remettre_a_zero, toutes les validations sont effacées (demandé deux fois dans l'interface)."""
    from . import liaisons
    if remettre_a_zero:
        c.base.executer("DELETE FROM validations")
    c.oublier()
    liaisons.donnees(c, rafraichir=True)
    from . import reseaux, traiter
    reseaux.purger(c)
    reseaux.proposer(c)
    bilan = {"compteurs": compteurs(c), "a_traiter": traiter.compte(c)["total"], "remis_a_zero": remettre_a_zero}
    c.base.noter("analyse", "Analyse globale : " + ", ".join(f"{CRITERES[k].lower()} {v}" for k, v in bilan["compteurs"].items()
                                                         if k in CRITERES) + f" ; {bilan['compteurs']['a_revoir']} à revoir"
                 + (" ; validations remises à zéro" if remettre_a_zero else ""), bilan)
    return bilan


__all__ = ["empreinte", "statut", "valider", "devalider", "plateformes", "resume", "compteurs",
           "analyse_globale", "ErreurCarnet"]
