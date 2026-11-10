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

def _verifier_service(service: str) -> None:
    if service not in SERVICES:
        raise ErreurCarnet("Réseau inconnu.")


def _oublier_personnes(cx, cles: list[tuple[str, str]]) -> None:
    """Efface des personnes lues et leurs propositions encore ouvertes (nom, pseudo, numéro)."""
    for s, e in cles:
        cx.execute("DELETE FROM personnes_externes WHERE service = ? AND ext_id = ?", (s, e))
        cx.execute("DELETE FROM a_traiter WHERE motif = 'reseau' AND cle = ?", (f"{s}|{e}",))


def enregistrer(c: Carnet, service: str, personnes: list[dict]) -> int:
    """personnes : [{ext_id, nom, telephone (E.164 ou vide), pseudo}]. Remplace la liste du
    service : une personne qui n'y est plus (et jamais liée) est oubliée avec sa proposition."""
    _verifier_service(service)
    quand = iso(maintenant())
    lies = {l["ext_id"] for l in c.base.tous("SELECT ext_id FROM liaisons WHERE service = ?", (service,))}
    nouveaux = {str(p["ext_id"]) for p in personnes}
    with c.base.transaction() as cx:
        partis = [(service, l["ext_id"]) for l in cx.execute("SELECT ext_id FROM personnes_externes WHERE service = ?",
                                                             (service,)).fetchall()
                  if l["ext_id"] not in nouveaux and l["ext_id"] not in lies]
        _oublier_personnes(cx, partis)
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
    """Personnes lues mais jamais rattachées : effacées après 90 jours (données de tiers), avec
    leurs propositions. Appelée au démarrage, la nuit, à chaque import et à l'analyse globale."""
    limite = iso(maintenant() - timedelta(days=CONSERVATION_JOURS))
    lies = {(l["service"], l["ext_id"]) for l in c.base.tous("SELECT service, ext_id FROM liaisons")}
    anciens = [(l["service"], l["ext_id"]) for l in c.base.tous("SELECT service, ext_id FROM personnes_externes WHERE vu_le < ?", (limite,))
               if (l["service"], l["ext_id"]) not in lies]
    with c.base.transaction() as cx:
        _oublier_personnes(cx, anciens)
    if anciens:
        c.oublier()
    return len(anciens)


def purger_si_besoin(c: Carnet) -> None:
    """Une purge par jour au plus, même la nuit désactivée (appelée à l'ouverture de carnet)."""
    jour = iso(maintenant())[:10]
    if c.base.lire("purge_reseaux_le") != jour:
        purger(c)
        c.base.ecrire("purge_reseaux_le", jour)


# ------------------------------------------------------------ rapprochement → « À traiter »

def _compact(texte: str) -> str:
    return re.sub(r"[^a-z0-9]", "", cle_texte(texte))


def _jetons(nom: str) -> str:
    return " ".join(sorted(cle_texte(nom).split()))


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
    par_jetons: dict[str, list[str]] = {}
    for uid, f in fiches.items():
        for t in f.get("telephones", []):
            if t.get("valide"):
                par_tel.setdefault(t["valeur"].split(";")[0], []).append(uid)
        n = nom_affiche(f)
        par_nom.setdefault(cle_texte(n), []).append(uid)
        par_jetons.setdefault(_jetons(n), []).append(uid)
        par_compact.setdefault(_compact(f"{f.get('prenom', '')}{f.get('nom', '')}"), []).append(uid)
    points = c.base.tous("SELECT cle, uid FROM a_traiter WHERE motif = 'reseau'")
    deja = {l["cle"] for l in points}
    # Une seule proposition ouverte par fiche et par réseau
    proposes = {(l["uid"], l["cle"].split("|", 1)[0]) for l in points}
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
                elif not trouves and " " in l["nom"].strip():
                    # « Dupont Jean » ou « Jean Dupont » : mêmes mots, dans un autre ordre
                    trouves = set(par_jetons.get(_jetons(l["nom"]), []))
                    if len(trouves) == 1:
                        uid, raison = trouves.pop(), "même nom (mots dans un autre ordre)"
            if not uid or (uid, service, ext_id) in refus or liaisons.get(uid, {}).get(service):
                continue
            cle = f"{service}|{ext_id}"
            if cle in deja or (uid, service) in proposes:
                continue
            ajout_tel = tel if tel and tel not in {t["valeur"] for t in fiches[uid].get("telephones", [])} else ""
            if traiter.ajouter(cx, "reseau", uid, cle, {"service": service, "ext_id": ext_id, "nom": l["nom"],
                                                         "pseudo": d.get("pseudo") or "", "telephone": ajout_tel,
                                                         "raison": raison}):
                nouvelles += 1
                proposes.add((uid, service))
    c.oublier()
    return nouvelles


# Adresse de profil écrite par carnet, par fiche et par réseau : « Délier » ne retire qu'elle
def _profils(c: Carnet) -> dict:
    return c.base.lire("profils_ecrits") or {}


def _noter_profil(c: Carnet, uid: str, service: str, url: str | None) -> None:
    p = _profils(c)
    if url:
        p[f"{uid}|{service}"] = url
    else:
        p.pop(f"{uid}|{service}", None)
    c.base.ecrire("profils_ecrits", p)


def lier(c: Carnet, uid: str, service: str, ext_id: str, pseudo: str = "", telephone: str = "",
         ajouter_numero: bool = False) -> dict:
    """Rattache la personne : liaison, profil écrit dans la carte iCloud, numéro si demandé."""
    from . import actions
    _verifier_service(service)
    deja = c.base.un("SELECT uid FROM liaisons WHERE service = ? AND ext_id = ?", (service, ext_id))
    if deja and deja["uid"] != uid:
        raise ErreurCarnet("Cette personne est déjà rattachée à une autre fiche : délie-la d'abord.")
    f = c.fiche(uid)
    change = False
    url = url_profil(service, pseudo) if pseudo else ""
    if url and normalisation.cle_site({"valeur": url}) not in {normalisation.cle_site(s) for s in f.get("sites", [])}:
        f["sites"] = list(f.get("sites", [])) + [{"valeur": url, "type": service}]
        change = True
    if ajouter_numero and telephone and telephone not in {t.get("valeur") for t in f.get("telephones", [])}:
        f["telephones"] = list(f.get("telephones", [])) + [{"valeur": telephone, "type": "mobile"}]
        change = True
    res = {"ok": True}
    if change:
        res = actions.valider(c, uid, f, origine=SERVICES[service], motif="profil social", etag_vu=actions._etag(c, uid))
    if url:
        _noter_profil(c, uid, service, url)
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


def delier(c: Carnet, uid: str, service: str, etag_vu: str | None = None) -> dict:
    """Retire la plateforme de la fiche : la liaison, et dans la carte iCloud seulement l'adresse
    de profil que carnet y a écrite (ou, à défaut, l'unique profil de ce réseau sur la fiche).
    Le reste de la carte n'est pas touché. La personne n'est plus proposée pour cette fiche."""
    from . import actions
    _verifier_service(service)
    f = c.fiche(uid)
    ecrite = _profils(c).get(f"{uid}|{service}")
    cles = [normalisation.cle_site(s) for s in f.get("sites", [])]
    if ecrite and normalisation.cle_site({"valeur": ecrite}) in cles:
        retirer = normalisation.cle_site({"valeur": ecrite})
    else:
        du_reseau = [normalisation.cle_site(s) for s in f.get("sites", []) if s.get("type") == service]
        if len(du_reseau) > 1:
            raise ErreurCarnet(f"Plusieurs adresses {SERVICES[service]} sur la fiche : retire celle à enlever avec le stylo.")
        retirer = du_reseau[0] if du_reseau else None
    ligne = c.base.un("SELECT ext_id FROM liaisons WHERE uid = ? AND service = ?", (uid, service))
    if not retirer and not ligne:
        raise ErreurCarnet(f"Ce profil {SERVICES[service]} vient de la messagerie de l'iPhone : retire-le depuis la fiche "
                           "sur l'iPhone.")
    res = {"ok": True}
    if retirer:
        f["sites"] = [s for s in f.get("sites", []) if normalisation.cle_site(s) != retirer]
        res = actions.valider(c, uid, f, origine="Délier", motif=f"profil {SERVICES[service]} retiré",
                              etag_vu=etag_vu or actions._etag(c, uid))
    _noter_profil(c, uid, service, None)
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


PSEUDO = {"instagram": re.compile(r"[A-Za-z0-9._]{1,30}"), "telegram": re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")}
DOMAINE = {"instagram": r"instagram\.com", "telegram": r"t\.me|telegram\.me"}


def ajouter_profil(c: Carnet, uid: str, service: str, valeur: str, etag_vu: str | None = None) -> dict:
    """Profil collé ou coché sur la fiche : Facebook (adresse du profil), Instagram et Telegram
    (adresse ou pseudo), WhatsApp (numéro choisi parmi ceux de la fiche)."""
    from . import actions
    _verifier_service(service)
    f = c.fiche(uid)
    v = (valeur or "").strip()
    if not v:
        raise ErreurCarnet("Indique l'adresse du profil ou le numéro.")
    if service == "facebook":
        if not re.match(r"^(https?://)?([a-z0-9-]+\.)?(facebook\.com|fb\.com|messenger\.com)/\S+$", v, re.I):
            raise ErreurCarnet("Colle l'adresse complète du profil Facebook (facebook.com/…).")
        url = v if v.lower().startswith("http") else f"https://{v}"
    elif service == "whatsapp":
        t = normalisation.telephone(v, "mobile", c.cfg.region)
        if not t or not t.get("valide"):
            raise ErreurCarnet("Numéro WhatsApp non reconnu.")
        url = url_profil("whatsapp", t["valeur"])
    else:
        m = re.match(rf"^(?:https?://)?(?:www\.)?(?:{DOMAINE[service]})/([^/?#\s]+)/?(?:[?#].*)?$", v, re.I)
        pseudo = m.group(1) if m else v.lstrip("@")
        if not PSEUDO[service].fullmatch(pseudo):
            raise ErreurCarnet(f"Indique le pseudo {SERVICES[service]} ou l'adresse de son profil.")
        url = url_profil(service, pseudo)
    if normalisation.cle_site({"valeur": url}) in {normalisation.cle_site(s) for s in f.get("sites", [])}:
        return {"ok": True}
    f["sites"] = list(f.get("sites", [])) + [{"valeur": url, "type": service}]
    res = actions.valider(c, uid, f, origine="Profil", motif=f"profil {SERVICES[service]} ajouté",
                          etag_vu=etag_vu or actions._etag(c, uid))
    _noter_profil(c, uid, service, url)
    return res


# ------------------------------------------------------------ type d'export déposé

def _noms_zip(contenu: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            return [i.filename.lower() for i in z.infolist()][:20000]
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError):
        return []


def source_export(contenu: bytes, nom_fichier: str) -> str | None:
    """« facebook », « instagram » ou None (vcf, csv…) d'après le contenu déposé."""
    zip_ = nom_fichier.endswith(".zip") or contenu[:2] == b"PK"
    if zip_:
        noms = [n.rsplit("/", 1)[-1] for n in _noms_zip(contenu)]
        if any(re.fullmatch(SIGNES_FACEBOOK, n) for n in noms):
            return "facebook"
        return "instagram"
    if nom_fichier.endswith(".json"):
        debut = contenu[:200000]
        if b"string_list_data" in debut:
            return "instagram"
        if re.search(rb'"(friends|followers|received_requests|sent_requests)(_v\d+)?"', debut) or b'"name"' in debut:
            return "facebook"
    return None


# ------------------------------------------------------------ Facebook (export « Ami(e)s »)

# Fichiers lus dans l'archive : amis, followers. Les messages, photos… ne sont jamais ouverts.
FICHIERS_FACEBOOK = r"(your_friends|friends|people_who_followed_you|who_you've_followed|followers)(_\d+)?\.json"
# Fichiers propres à Facebook (Instagram a aussi des followers_N.json)
SIGNES_FACEBOOK = r"(your_friends|friends|people_who_followed_you|who_you've_followed)(_\d+)?\.json"
LISTES_FACEBOOK = re.compile(r"(friends|followers|following)(_v\d+)?")


def lire_facebook(contenu: bytes, nom_fichier: str) -> list[dict]:
    """Ami(e)s et followers d'un export Facebook (.zip ou .json). L'export ne donne que le nom
    (ni identifiant, ni lien de profil, ni numéro) : l'identifiant gardé est le nom normalisé."""
    fichiers: list[bytes] = []
    if nom_fichier.lower().endswith(".zip") or contenu[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(contenu)) as z:
                retenus = [i for i in z.infolist() if not i.is_dir()
                           and re.fullmatch(FICHIERS_FACEBOOK, i.filename.lower().rsplit("/", 1)[-1])]
                if len(retenus) > FICHIERS_MAX:
                    raise ErreurCarnet("Archive Facebook invalide : trop de fichiers.")
                fichiers = [_lire_borne(z, i) for i in retenus]
        except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, EOFError, RuntimeError, OSError):
            raise ErreurCarnet("Archive .zip illisible : télécharge à nouveau l'export Facebook.")
    else:
        fichiers.append(contenu)
    personnes: dict[str, dict] = {}

    def entrees(d):
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            for k, v in d.items():
                if LISTES_FACEBOOK.fullmatch(str(k)) and isinstance(v, list):
                    return v
        return []

    for brut in fichiers:
        try:
            d = json.loads(brut.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            continue
        for e in entrees(d):
            if not isinstance(e, dict) or not isinstance(e.get("name"), str):
                continue
            nom = " ".join(_reparer(e["name"]).split())[:120]
            cle = cle_texte(nom)
            if cle:
                personnes[cle] = {"ext_id": "nom:" + cle, "nom": nom, "pseudo": ""}
    if not personnes:
        raise ErreurCarnet("Aucun ami trouvé : dans « Télécharger tes informations », choisis Contacts › Ami(e)s, "
                           "format JSON, puis dépose le .zip ou le fichier your_friends.json.")
    return list(personnes.values())


def importer_facebook(c: Carnet, contenu: bytes, nom_fichier: str) -> dict:
    personnes = lire_facebook(contenu, nom_fichier)
    enregistrer(c, "facebook", personnes)
    purger(c)
    n = proposer(c)
    c.base.noter("reseaux", f"Facebook : {len(personnes)} personne(s) lue(s), {n} rattachement(s) proposé(s) ; "
                            "archive non gardée")
    return {"source": "facebook", "lues": len(personnes), "proposees": n}


# ------------------------------------------------------------ Instagram (export)

def _reparer(texte: str) -> str:
    """Les exports Meta codent l'UTF-8 comme du latin-1 (« Ã© » au lieu de « é »)."""
    try:
        return texte.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texte


TAILLE_MAX_FICHIER = 20 * 1024 * 1024     # par fichier JSON lu dans l'archive
FICHIERS_MAX = 60                         # following.json + followers_1…N.json


def _lire_borne(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Lecture plafonnée : une archive piégée (taille annoncée fausse) ne remplit pas la mémoire."""
    if info.file_size > TAILLE_MAX_FICHIER:
        raise ErreurCarnet(f"Fichier trop gros dans l'archive Instagram : {info.filename.rsplit('/', 1)[-1]}.")
    with z.open(info) as f:
        brut = f.read(TAILLE_MAX_FICHIER + 1)
    if len(brut) > TAILLE_MAX_FICHIER:
        raise ErreurCarnet("Archive Instagram invalide.")
    return brut


def lire_instagram(contenu: bytes, nom_fichier: str) -> list[dict]:
    """Abonnements et abonnés d'un export Instagram (.zip ou .json). Seuls les pseudos sont lus ;
    le reste de l'archive (messages…) n'est jamais ouvert ni gardé."""
    fichiers: list[bytes] = []
    if nom_fichier.lower().endswith(".zip") or contenu[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(contenu)) as z:
                retenus = [i for i in z.infolist() if not i.is_dir()
                           and re.fullmatch(r"(following|followers(_\d+)?)\.json", i.filename.rsplit("/", 1)[-1])]
                if len(retenus) > FICHIERS_MAX:
                    raise ErreurCarnet("Archive Instagram invalide : trop de fichiers d'abonnés.")
                fichiers = [_lire_borne(z, i) for i in retenus]
        except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, EOFError, RuntimeError, OSError):
            raise ErreurCarnet("Archive .zip illisible : télécharge à nouveau l'export Instagram.")
    else:
        fichiers.append(contenu)
    pseudos: dict[str, dict] = {}

    def ajouter(p) -> None:
        p = p.strip() if isinstance(p, str) else ""
        if p and len(p) <= 60:
            pseudos[p.lower()] = {"ext_id": p.lower(), "nom": _reparer(p), "pseudo": p}

    for brut in fichiers:
        try:
            d = json.loads(brut.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            continue
        entrees = d.get("relationships_following", d) if isinstance(d, dict) else d
        for e in entrees if isinstance(entrees, list) else []:
            if not isinstance(e, dict):
                continue
            donnees = e.get("string_list_data")
            for s in donnees if isinstance(donnees, list) else []:
                if not isinstance(s, dict):
                    continue
                pseudo = s.get("value") or e.get("title") or ""
                if not pseudo and isinstance(s.get("href"), str):
                    pseudo = s["href"].rstrip("/").rsplit("/", 1)[-1]
                ajouter(pseudo)
            if not donnees and e.get("title"):
                ajouter(e["title"])
    if not pseudos:
        raise ErreurCarnet("Aucun abonnement ni abonné trouvé : dépose l'export Instagram au format JSON "
                           "(« Abonnés et abonnements », en .zip ou les fichiers .json).")
    return list(pseudos.values())


def importer_instagram(c: Carnet, contenu: bytes, nom_fichier: str) -> dict:
    personnes = lire_instagram(contenu, nom_fichier)
    enregistrer(c, "instagram", personnes)
    purger(c)
    n = proposer(c)
    c.base.noter("reseaux", f"Instagram : {len(personnes)} comptes lus, {n} rattachement(s) proposé(s) ; archive non gardée")
    return {"source": "instagram", "lues": len(personnes), "proposees": n}
