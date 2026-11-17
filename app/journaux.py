"""2.29 : « Pour les journaux » — ce que Julien sait d'une personne (passions, manies, petites histoires) pour
les journaux de Gazette (rumeurs loufoques de La Récidive).

Rangé par identifiant maison (app/personnes.py), dans la base de carnet seulement : jamais écrit dans iCloud,
Synology Contacts ou le kit. Gazette le lit (GET /gazette/personnes, champ `journaux`) et l'écrit
(PUT /gazette/personnes/{personne_id}/journaux, jeton commun) ; la fiche de carnet le montre et le modifie ;
le coffre « Contacts » le recopie dans la note de la personne. Le journal de carnet ne porte jamais le texte.
Permis en lecture seule : rien ne sort de carnet.

2.30 : « Journaux parus » — chaque numéro de La Récidive approuvé dans Gazette arrive ici (date du séjour, N°,
événement du séjour, indices, descriptions des photos écrites pour l'IA, textes imprimés) : la fiche contact garde
toute l'histoire des journaux de la personne, Gazette la relit pour ne pas se répéter et broder dessus, le coffre
« Contacts » la recopie. PUT /gazette/personnes/{personne_id}/parus/{cle} (jeton commun).

2.31 : « Livre d'or » — les mots laissés par les invités dans le livre d'or de la maison (carte de Home Assistant),
envoyés par Home Assistant à chaque signature (POST /ha/livre-or). Chaque signataire reconnu reçoit le mot sur sa
fiche ; un nom que carnet ne reconnaît pas attend d'être rattaché depuis une fiche. Gazette les lit pour ses rumeurs,
son courrier des lecteurs et son droit de réponse."""
from __future__ import annotations

import json
import re

from . import personnes
from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

MAX = 600
PARUS_LISTE = 10            # numéros donnés à Gazette (les plus récents) ; la fiche les montre tous
LIMITES = {"evenement": 200, "indices": 600, "titre": 200}
LISTES = {"descriptions": (12, 400), "textes": (60, 500)}


def tous(c: Carnet) -> dict[str, dict]:
    """identifiant maison → {texte, le, par}."""
    return c.memo("journaux", lambda: {l["personne"]: {"texte": l["texte"], "le": l["le"], "par": l["par"]}
                                       for l in c.base.tous("SELECT * FROM journaux")})


def de_personne(c: Carnet, ident: str | None) -> str:
    return (tous(c).get(ident) or {}).get("texte", "") if ident else ""


def fiche(c: Carnet, uid: str) -> dict:
    ident = personnes.de(c, uid)
    j = tous(c).get(ident) or {}
    return {"personne_id": ident, "texte": j.get("texte", ""), "le": j.get("le"), "par": j.get("par", ""),
            "parus": parus(c, ident),                     # 2.30
            "livre_or": livre_or(c, ident), "orphelins": orphelins(c)}     # 2.31


def _propre(texte) -> str:
    if texte is None:
        return ""
    if not isinstance(texte, str):
        raise ErreurCarnet("Un texte est attendu.")
    texte = "\n".join(" ".join(l.split()) for l in texte.replace("\r", "").split("\n")).strip()
    if len(texte) > MAX:
        raise ErreurCarnet(f"Texte trop long ({MAX} caractères au plus).")
    return texte


def ecrire(c: Carnet, ident: str, texte, par: str) -> dict:
    """Enregistre le texte d'une personne (vide : retiré). `par` : « carnet » ou « gazette »."""
    if not ident or not personnes.uid_de(c, ident):
        raise ErreurCarnet("Personne inconnue de carnet.")
    texte = _propre(texte)
    if not texte:
        c.base.executer("DELETE FROM journaux WHERE personne = ?", (ident,))
    else:
        c.base.executer("INSERT INTO journaux(personne, texte, le, par) VALUES (?, ?, ?, ?) ON CONFLICT(personne) DO UPDATE "
                        "SET texte = excluded.texte, le = excluded.le, par = excluded.par", (ident, texte, iso(maintenant()), par))
    c.base.noter("journaux", "« Pour les journaux » d'une fiche mis à jour", {"personne_id": ident, "par": par})
    return {"personne_id": ident, "texte": texte}


def definir(c: Carnet, uid: str, corps: dict) -> dict:
    """Depuis la fiche de carnet."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Données attendues.")
    ecrire(c, personnes.de(c, uid), corps.get("texte"), "carnet")
    return fiche(c, uid)


# ================================================================ 2.30 : journaux parus

def parus(c: Carnet, ident: str | None) -> list[dict]:
    """Les numéros parus d'une personne, du plus récent au plus ancien."""
    if not ident:
        return []
    tout = c.memo("journaux_parus", lambda: [dict(l) for l in c.base.tous(
        "SELECT * FROM journaux_parus ORDER BY le DESC, cle DESC")])
    return [{"cle": l["cle"], "le": l["le"], "maj": l["maj"], **json.loads(l["donnees"])} for l in tout if l["personne"] == ident]


def _texte(v, maxi: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, (str, int)):
        raise ErreurCarnet("Un texte est attendu.")
    return " ".join(str(v).split())[:maxi]


def ecrire_paru(c: Carnet, ident: str, cle: str, corps: dict) -> dict:
    """Enregistre (ou remplace) un numéro paru. `corps` : {journal, numero, le, titre, evenement, indices,
    descriptions[], textes[]} ; textes coupés à leur longueur maximale, listes vides retirées."""
    if not ident or not personnes.uid_de(c, ident):
        raise ErreurCarnet("Personne inconnue de carnet.")
    if not re.fullmatch(r"[a-z]+-\d{4}-\d{2}-\d{2}", cle or ""):
        raise ErreurCarnet("Clé de numéro invalide (attendu : recidive-AAAA-MM-JJ).")
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    le = str(corps.get("le") or cle[-10:])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", le):
        raise ErreurCarnet("Date du séjour invalide (AAAA-MM-JJ).")
    d = {"journal": _texte(corps.get("journal") or cle.split("-")[0], 30)}
    try:
        d["numero"] = int(corps["numero"]) if corps.get("numero") not in (None, "") else None
    except (TypeError, ValueError):
        raise ErreurCarnet("Numéro invalide.")
    for k, maxi in LIMITES.items():
        d[k] = _texte(corps.get(k), maxi)
    for k, (n, maxi) in LISTES.items():
        v = corps.get(k) or []
        if not isinstance(v, list):
            raise ErreurCarnet(f"« {k} » : une liste est attendue.")
        d[k] = [t for t in (_texte(x, maxi) for x in v) if t][:n]
    c.base.executer("INSERT INTO journaux_parus(personne, cle, le, donnees, maj) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(personne, cle) DO UPDATE SET le = excluded.le, donnees = excluded.donnees, maj = excluded.maj",
                    (ident, cle, le, json.dumps(d, ensure_ascii=False), iso(maintenant())))
    c.base.noter("journaux", "Journal paru reçu de Gazette", {"personne_id": ident, "cle": cle})
    return {"personne_id": ident, "cle": cle, "le": le, **d}


def paru_lisible(p: dict) -> str:
    """« 19/11/2026 — La Récidive N° 2 » pour la fiche et le coffre."""
    nom = {"recidive": "La Récidive", "gazette": "La Gazette"}.get(p.get("journal") or "", p.get("journal") or "Journal")
    le = p.get("le") or ""
    return f"{le[8:10]}/{le[5:7]}/{le[:4]} — {nom}" + (f" N° {p['numero']}" if p.get("numero") else "")


# ================================================================ 2.31 : livre d'or

LIVRE_LISTE = 10            # mots donnés à Gazette (les plus récents)


def _livre(c: Carnet) -> list[dict]:
    return c.memo("livre_or", lambda: [dict(l) for l in c.base.tous("SELECT * FROM livre_or ORDER BY le DESC, id DESC")])


def livre_or(c: Carnet, ident: str | None) -> list[dict]:
    """Les mots du livre d'or d'une personne, du plus récent au plus ancien."""
    if not ident:
        return []
    return [{k: l[k] for k in ("id", "message", "chambre", "le", "nom")} for l in _livre(c) if l["personne"] == ident]


def orphelins(c: Carnet) -> list[dict]:
    """Les mots dont le signataire n'a pas été reconnu (à rattacher depuis une fiche)."""
    return [{k: l[k] for k in ("id", "message", "chambre", "le", "nom")} for l in _livre(c) if not l["personne"]]


def _noms(corps: dict) -> list[str]:
    """`noms` (liste) ou `invites` (« Audrey & Paul », « Audrey et Paul », « Audrey, Paul »)."""
    noms = corps.get("noms")
    if isinstance(noms, str):
        noms = [noms]
    if not noms:
        noms = re.split(r"\s*(?:&|,|\bet\b|/|\+)\s*", str(corps.get("invites") or ""))
    res = []
    for n in noms or []:
        n = re.sub(r"\s*\(.*$", "", " ".join(str(n).split())).strip()     # « Nom (dates) » : dates retirées
        if n and n.casefold() not in ("invité", "invite", "invités") and n not in res:
            res.append(n[:80])
    return res[:4]


def recevoir_livre(c: Carnet, corps: dict) -> dict:
    """POST /ha/livre-or : {noms[] ou invites, message, chambre, le}. Rattache le mot à chaque signataire reconnu (même
    recherche par nom que /ha/invite, sur toutes les fiches) ; un nom inconnu ou porté par plusieurs fiches reste à
    rattacher. Un mot déjà reçu n'entre pas deux fois."""
    import hashlib
    from .normalisation import cle_texte
    from .sorties import contacts_ha
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    message = "\n".join(" ".join(l.split()) for l in str(corps.get("message") or "").replace("\r", "").split("\n")).strip()[:2000]
    if not message:
        raise ErreurCarnet("Mot vide.")
    le = str(corps.get("le") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", le):
        le = iso(maintenant())[:10]
    chambre = " ".join(str(corps.get("chambre") or "").split())[:60]
    noms = _noms(corps) or ["Invité"]
    fiches = contacts_ha(c)
    rattaches, inconnus, nouveaux = [], [], 0
    for nom in noms:
        cle_n = cle_texte(nom)
        trouves = {p["personne_id"] for p in fiches if p.get("personne_id") and cle_n in (cle_texte(p["nom"]), cle_texte(p["nom_carnet"]))}
        ident = next(iter(trouves)) if len(trouves) == 1 else ""
        (rattaches if ident else inconnus).append(nom)
        cle = hashlib.sha1(f"{cle_n}|{le}|{message}".encode()).hexdigest()[:20]
        avant = c.base.tous("SELECT id FROM livre_or WHERE cle = ?", (cle,))
        if avant:
            continue
        c.base.executer("INSERT INTO livre_or(cle, personne, nom, message, chambre, le, recu) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (cle, ident, nom, message, chambre, le, iso(maintenant())))
        nouveaux += 1
    c.base.noter("journaux", "Mot du livre d'or reçu de Home Assistant",
                 {"rattaches": len(rattaches), "a_rattacher": len(inconnus), "nouveaux": nouveaux})
    return {"rattaches": rattaches, "a_rattacher": inconnus, "nouveaux": nouveaux}


def rattacher_livre(c: Carnet, mot_id: int, uid: str) -> dict:
    """Rattache un mot du livre d'or à la fiche `uid` (depuis la fiche, « C'est elle / lui »)."""
    ident = personnes.de(c, uid)
    if not ident:
        raise ErreurCarnet("Fiche inconnue.")
    if not c.base.tous("SELECT id FROM livre_or WHERE id = ?", (int(mot_id),)):
        raise ErreurCarnet("Mot du livre d'or introuvable.")
    c.base.executer("UPDATE livre_or SET personne = ? WHERE id = ?", (ident, int(mot_id)))
    return {"ok": True}
