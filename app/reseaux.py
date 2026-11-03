"""Réseaux sociaux (carnet 2.1) : Telegram (import manuel), Instagram (export), WhatsApp et
Facebook (profil sur la fiche).

Les personnes lues sont gardées dans `personnes_externes` le temps d'être rattachées (90 jours
au plus si jamais liées). Rien n'est lié seul : chaque rapprochement passe par « À traiter »
(motif « reseau »), au plus 150 propositions par import. « Pas lui » est définitif (table
`refus`), même après un nouvel import. « Lier » écrit le profil dans iCloud (X-SOCIALPROFILE)
par l'écriture partielle habituelle ; un numéro absent de la fiche n'est ajouté que si tu le
demandes. « Délier » retire le profil de la carte.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import timedelta

from . import normalisation, traiter
from .carnet import Carnet, ErreurCarnet
from .modele import nom_affiche
from .normalisation import cle_texte
from .temps import iso, maintenant

PLAFOND_PROPOSITIONS = 150
CONSERVATION_JOURS = 90
SERVICES = {"telegram": "Telegram", "instagram": "Instagram", "facebook": "Facebook", "whatsapp": "WhatsApp"}


def url_profil(service: str, valeur: str) -> str:
    v = (valeur or "").strip().lstrip("@")
    if service == "telegram":
        return f"https://t.me/{v}"
    if service == "instagram":
        return f"https://www.instagram.com/{v}"
    if service == "whatsapp":
        return f"https://wa.me/{re.sub(r'[^0-9]', '', v)}"
    return v


# ------------------------------------------------------------ enregistrement des personnes lues

def enregistrer(c: Carnet, service: str, personnes: list[dict]) -> int:
    """personnes : [{ext_id, nom, telephone (E.164 ou vide), pseudo}]. Remplace la liste du service."""
    quand = iso(maintenant())
    with c.base.transaction() as cx:
        for p in personnes:
            cx.execute("INSERT OR REPLACE INTO personnes_externes(service, ext_id, nom, donnees, vu_le) VALUES (?,?,?,?,?)",
                       (service, str(p["ext_id"]), p.get("nom") or p.get("pseudo") or "",
                        json.dumps({k: p.get(k) for k in ("telephone", "pseudo", "prenom", "nom_famille")}, ensure_ascii=False),
                        quand))
    dernier = c.base.lire("reseaux_imports") or {}
    dernier[service] = quand
    c.base.ecrire("reseaux_imports", dernier)
    c.oublier()
    return len(personnes)


def purger(c: Carnet) -> int:
    """Personnes lues mais jamais rattachées : effacées après 90 jours (données de tiers)."""
    limite = iso(maintenant() - timedelta(days=CONSERVATION_JOURS))
    lies = {(l["service"], l["ext_id"]) for l in c.base.tous("SELECT service, ext_id FROM liaisons")}
    anciens = [(l["service"], l["ext_id"]) for l in c.base.tous("SELECT service, ext_id FROM personnes_externes WHERE vu_le < ?", (limite,))
               if (l["service"], l["ext_id"]) not in lies]
    with c.base.transaction() as cx:
        for s, e in anciens:
            cx.execute("DELETE FROM personnes_externes WHERE service = ? AND ext_id = ?", (s, e))
    return len(anciens)


# ------------------------------------------------------------ rapprochement → « À traiter »

def _compact(texte: str) -> str:
    return re.sub(r"[^a-z0-9]", "", cle_texte(texte))


def proposer(c: Carnet) -> int:
    """Propositions de rattachement pour les personnes lues (au plus 150 nouvelles par passage).
    Très sûr : même numéro. Sûr : nom identique et unique (Instagram : pseudo = prénom+nom collés)."""
    fiches = c.fiches()
    liaisons = c.liaisons()
    refus = {(l["uid"], l["service"], l["ext_id"]) for l in c.base.tous("SELECT * FROM refus")}
    lies = {(l["service"], l["ext_id"]) for l in c.base.tous("SELECT service, ext_id FROM liaisons")}
    par_tel: dict[str, list[str]] = {}
    par_nom: dict[str, list[str]] = {}
    par_compact: dict[str, list[str]] = {}
    for uid, f in fiches.items():
        for t in f.get("telephones", []):
            if t.get("valide"):
                par_tel.setdefault(t["valeur"].split(";")[0], []).append(uid)
        n = nom_affiche(f)
        par_nom.setdefault(cle_texte(n), []).append(uid)
        par_compact.setdefault(_compact(f"{f.get('prenom', '')}{f.get('nom', '')}"), []).append(uid)
    deja = {l["cle"] for l in c.base.tous("SELECT cle FROM a_traiter WHERE motif = 'reseau'")}
    nouvelles = 0
    with c.base.transaction() as cx:
        for l in cx.execute("SELECT * FROM personnes_externes ORDER BY service, nom").fetchall():
            if nouvelles >= PLAFOND_PROPOSITIONS:
                break
            service, ext_id = l["service"], l["ext_id"]
            if (service, ext_id) in lies:
                continue
            d = json.loads(l["donnees"])
            uid, raison = None, ""
            tel = d.get("telephone") or ""
            if tel and len(set(par_tel.get(tel, []))) == 1:
                uid, raison = par_tel[tel][0], "même numéro"
            elif service == "instagram":
                trouves = set(par_compact.get(_compact(d.get("pseudo") or ""), []))
                if len(trouves) == 1 and len(_compact(d.get("pseudo") or "")) >= 6:
                    uid, raison = trouves.pop(), "pseudo = prénom et nom"
            else:
                trouves = set(par_nom.get(cle_texte(l["nom"]), []))
                if len(trouves) == 1 and cle_texte(l["nom"]):
                    uid, raison = trouves.pop(), "même nom"
            if not uid or (uid, service, ext_id) in refus or liaisons.get(uid, {}).get(service):
                continue
            cle = f"{service}|{ext_id}"
            if cle in deja:
                continue
            ajout_tel = tel if tel and tel not in {t["valeur"] for t in fiches[uid].get("telephones", [])} else ""
            if traiter.ajouter(cx, "reseau", uid, cle, {"service": service, "ext_id": ext_id, "nom": l["nom"],
                                                         "pseudo": d.get("pseudo") or "", "telephone": ajout_tel,
                                                         "raison": raison}):
                nouvelles += 1
    c.oublier()
    return nouvelles


def lier(c: Carnet, uid: str, service: str, ext_id: str, pseudo: str = "", telephone: str = "",
         ajouter_numero: bool = False) -> dict:
    """Rattache la personne : liaison, profil écrit dans la carte iCloud, numéro si demandé."""
    from . import actions
    deja = c.base.un("SELECT uid FROM liaisons WHERE service = ? AND ext_id = ?", (service, ext_id))
    if deja and deja["uid"] != uid:
        raise ErreurCarnet("Cette personne est déjà rattachée à une autre fiche : délie-la d'abord.")
    f = c.fiche(uid)
    change = False
    if pseudo:
        url = url_profil(service, pseudo)
        if url not in {s.get("valeur") for s in f.get("sites", [])}:
            f["sites"] = list(f.get("sites", [])) + [{"valeur": url, "type": service}]
            change = True
    if ajouter_numero and telephone and telephone not in {t.get("valeur") for t in f.get("telephones", [])}:
        f["telephones"] = list(f.get("telephones", [])) + [{"valeur": telephone, "type": "mobile"}]
        change = True
    res = {"ok": True}
    if change:
        res = actions.valider(c, uid, f, origine=SERVICES.get(service, service), motif="profil social",
                              etag_vu=actions._etag(c, uid))
    with c.base.transaction() as cx:
        cx.execute("INSERT OR REPLACE INTO liaisons(uid, service, ext_id, statut, le) VALUES (?,?,?,?,?)",
                   (uid, service, ext_id, "confirmee", iso(maintenant())))
        cx.execute("DELETE FROM a_traiter WHERE motif = 'reseau' AND cle = ?", (f"{service}|{ext_id}",))
    c.oublier()
    return res


def refuser(c: Carnet, uid: str, service: str, ext_id: str) -> None:
    with c.base.transaction() as cx:
        cx.execute("INSERT OR IGNORE INTO refus(uid, service, ext_id) VALUES (?,?,?)", (uid, service, ext_id))
        cx.execute("DELETE FROM a_traiter WHERE motif = 'reseau' AND cle = ?", (f"{service}|{ext_id}",))
    c.oublier()


def delier(c: Carnet, uid: str, service: str) -> dict:
    """Retire la plateforme de la fiche : liaison, et profil de la carte iCloud (sites de ce
    réseau). La personne n'est plus proposée pour cette fiche."""
    from . import actions
    f = c.fiche(uid)
    motif = {"facebook": ("facebook.com", "messenger.com"), "instagram": ("instagram.com",),
             "telegram": ("t.me/", "telegram"), "whatsapp": ("wa.me/", "whatsapp")}.get(service, ())
    gardes = [s for s in f.get("sites", []) if s.get("type") != service and not any(m in s.get("valeur", "") for m in motif)]
    res = {"ok": True}
    if len(gardes) != len(f.get("sites", [])):
        f["sites"] = gardes
        res = actions.valider(c, uid, f, origine="Délier", motif=f"profil {SERVICES.get(service, service)} retiré",
                              etag_vu=actions._etag(c, uid))
    ligne = c.base.un("SELECT ext_id FROM liaisons WHERE uid = ? AND service = ?", (uid, service))
    with c.base.transaction() as cx:
        if ligne:
            cx.execute("INSERT OR IGNORE INTO refus(uid, service, ext_id) VALUES (?,?,?)", (uid, service, ligne["ext_id"]))
        cx.execute("DELETE FROM liaisons WHERE uid = ? AND service = ?", (uid, service))
    c.oublier()
    return res


def bilan(c: Carnet) -> dict:
    """Par réseau : personnes lues (gardées 90 jours au plus) et fiches liées."""
    lues = {l["service"]: l["n"] for l in c.base.tous("SELECT service, COUNT(*) AS n FROM personnes_externes GROUP BY service")}
    liees = {l["service"]: l["n"] for l in c.base.tous("SELECT service, COUNT(*) AS n FROM liaisons GROUP BY service")}
    dernier = c.base.lire("reseaux_imports") or {}
    return {s: {"lues": lues.get(s, 0), "liees": liees.get(s, 0), "importe_le": dernier.get(s)} for s in SERVICES}


def ajouter_profil(c: Carnet, uid: str, service: str, valeur: str) -> dict:
    """Profil collé ou coché sur la fiche : Facebook (adresse du profil), Instagram et Telegram
    (adresse ou pseudo), WhatsApp (numéro choisi parmi ceux de la fiche)."""
    from . import actions
    f = c.fiche(uid)
    v = (valeur or "").strip()
    if not v:
        raise ErreurCarnet("Indique l'adresse du profil ou le numéro.")
    if service == "facebook":
        if not re.search(r"(facebook\.com|fb\.com|messenger\.com)/", v):
            raise ErreurCarnet("Colle l'adresse complète du profil Facebook (facebook.com/…).")
        url = v if v.startswith("http") else f"https://{v}"
    elif service == "whatsapp":
        t = normalisation.telephone(v, "mobile", c.cfg.region)
        if not t or not t.get("valide"):
            raise ErreurCarnet("Numéro WhatsApp non reconnu.")
        url = url_profil("whatsapp", t["valeur"])
    elif service in ("instagram", "telegram"):
        m = re.search(r"(?:instagram\.com|t\.me)/([^/?#\s]+)", v)
        url = url_profil(service, m.group(1) if m else v)
    else:
        raise ErreurCarnet("Réseau inconnu.")
    if url in {s.get("valeur") for s in f.get("sites", [])}:
        return {"ok": True}
    f["sites"] = list(f.get("sites", [])) + [{"valeur": url, "type": service}]
    return actions.valider(c, uid, f, origine="Profil", motif=f"profil {SERVICES[service]} ajouté", etag_vu=actions._etag(c, uid))


# ------------------------------------------------------------ Instagram (export)

def _reparer(texte: str) -> str:
    """Les exports Meta codent l'UTF-8 comme du latin-1 (« Ã© » au lieu de « é »)."""
    try:
        return texte.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texte


def lire_instagram(contenu: bytes, nom_fichier: str) -> list[dict]:
    """Abonnements et abonnés d'un export Instagram (.zip ou .json). Seuls les pseudos sont lus ;
    le reste de l'archive (messages…) n'est jamais ouvert ni gardé."""
    fichiers: list[bytes] = []
    if nom_fichier.lower().endswith(".zip") or contenu[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            for n in z.namelist():
                base = n.rsplit("/", 1)[-1]
                if re.fullmatch(r"(following|followers(_\d+)?)\.json", base):
                    fichiers.append(z.read(n))
    else:
        fichiers.append(contenu)
    pseudos: dict[str, dict] = {}
    for brut in fichiers:
        try:
            d = json.loads(brut.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        entrees = d.get("relationships_following", d) if isinstance(d, dict) else d
        for e in entrees if isinstance(entrees, list) else []:
            for s in e.get("string_list_data", []) or []:
                pseudo = (s.get("value") or e.get("title") or "").strip()
                if not pseudo and s.get("href"):
                    pseudo = s["href"].rstrip("/").rsplit("/", 1)[-1]
                if pseudo:
                    pseudos[pseudo.lower()] = {"ext_id": pseudo.lower(), "nom": _reparer(pseudo), "pseudo": pseudo}
            if not e.get("string_list_data") and e.get("title"):
                p = e["title"].strip()
                pseudos[p.lower()] = {"ext_id": p.lower(), "nom": _reparer(p), "pseudo": p}
    if not pseudos:
        raise ErreurCarnet("Aucun abonnement ni abonné trouvé : dépose l'export Instagram au format JSON "
                           "(dossier followers_and_following, ou l'archive .zip entière).")
    return list(pseudos.values())


def importer_instagram(c: Carnet, contenu: bytes, nom_fichier: str) -> dict:
    personnes = lire_instagram(contenu, nom_fichier)
    enregistrer(c, "instagram", personnes)
    n = proposer(c)
    c.base.noter("reseaux", f"Instagram : {len(personnes)} comptes lus, {n} rattachement(s) proposé(s) ; archive non gardée")
    return {"source": "instagram", "lues": len(personnes), "proposees": n}
