"""Lecture de Connections.csv (archive « Télécharger mes données » de LinkedIn).

Le fichier commence par quelques lignes « Notes: … » avant l'en-tête :
First Name,Last Name,URL,Email Address,Company,Position,Connected On
Ces fiches enrichissent les contacts existants ; elles n'en créent jamais.
"""
from __future__ import annotations

import csv
import io
import re

from . import normalisation as n
from .modele import fiche_vide
from .vcard import FicheLue


def lire(texte: str, region: str = "FR") -> tuple[list[FicheLue], list[str]]:
    lignes = texte.splitlines()
    debut = next((i for i, l in enumerate(lignes) if l.lstrip('"').startswith("First Name")), None)
    if debut is None:
        return [], ["En-tête « First Name,Last Name,URL… » introuvable : est-ce bien Connections.csv ?"]
    fiches = []
    for v in csv.DictReader(io.StringIO("\n".join(lignes[debut:]))):
        v = {k: (val or "").strip() for k, val in v.items() if k}
        f = fiche_vide()
        f["prenom"] = n.formater_prenom(v.get("First Name", ""))
        f["nom"] = n.formater_nom(v.get("Last Name", ""))
        f["societe"] = v.get("Company", "")
        f["fonction"] = v.get("Position", "")
        c = n.courriel(v.get("Email Address", ""), "travail")
        if c:
            f["courriels"].append(c)
        s = n.site(v.get("URL", ""), "linkedin")
        if s:
            f["sites"].append(s)
        if f["prenom"] or f["nom"]:
            fiches.append(FicheLue(fiche=f, uid=uid_profil(v.get("URL", "")), brut=",".join(v.values())))
    return fiches, []


def uid_profil(url: str) -> str | None:
    """Identifiant stable d'une relation : l'adresse de son profil (« linkedin.com/in/claire-martin »),
    sans protocole, sous-domaine ni paramètres. Un réimport retrouve ainsi la même relation."""
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", url or "", re.I)
    return f"linkedin.com/in/{m.group(1).lower()}" if m else None


# ================================================================ import dans carnet 2

COLONNES = ["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"]
API = "https://api.linkedin.com/rest/memberSnapshotData"
CHAMPS_SUIVIS = ("societe", "fonction")


def _cible(fiches: dict[str, dict], lue) -> str | None:
    """Fiche correspondant à une relation : profil dans les sites, courriel, puis nom identique
    (unique). LinkedIn ne crée jamais de fiche."""
    url = lue.uid
    for uid, f in fiches.items():
        if any(uid_profil(s.get("valeur", "")) == url for s in f.get("sites", [])):
            return uid
    courriels = {x["valeur"].lower() for x in lue.fiche.get("courriels", [])}
    if courriels:
        trouves = [u for u, f in fiches.items() if courriels & {x["valeur"].lower() for x in f.get("courriels", [])}]
        if len(trouves) == 1:
            return trouves[0]
    cle = n.cle_texte(f"{lue.fiche.get('prenom', '')} {lue.fiche.get('nom', '')}")
    trouves = [u for u, f in fiches.items() if n.cle_texte(f"{f.get('prenom', '')} {f.get('nom', '')}") == cle]
    return trouves[0] if len(trouves) == 1 and cle else None


def importer(c, texte: str) -> dict:
    """Relations LinkedIn (CSV ou API) → seulement les changements depuis le dernier import.
    - fiche qui porte encore l'ancienne valeur LinkedIn : nouveau poste ou société écrit la nuit ;
    - autre cas (fiche vide, valeur différente, nouveau courriel) : proposé dans « À traiter » ;
    - une relation détachée reste détachée."""
    import json
    from . import traiter
    from .temps import iso, maintenant
    lues, avertissements = lire(texte, c.cfg.region)
    if not lues and avertissements:
        from .carnet import ErreurCarnet
        raise ErreurCarnet(avertissements[0])
    fiches = c.fiches()
    connues = {l["url"]: l for l in c.base.tous("SELECT * FROM linkedin")}
    bilan = {"lues": len(lues), "rattachees": 0, "sans_contact": 0, "proposees": 0, "automatiques": 0, "inchangees": 0}
    quand = iso(maintenant())
    with c.base.transaction() as cx:
        for lue in lues:
            if not lue.uid:
                continue
            nouveau = {"societe": lue.fiche.get("societe", ""), "fonction": lue.fiche.get("fonction", ""),
                       "courriel": (lue.fiche.get("courriels") or [{}])[0].get("valeur", ""),
                       "nom": f"{lue.fiche.get('prenom', '')} {lue.fiche.get('nom', '')}".strip()}
            ancienne = connues.get(lue.uid)
            ancien = json.loads(ancienne["donnees"]) if ancienne else {}
            detachee = bool(ancienne and ancienne["detachee"])
            uid = ancienne["uid"] if ancienne and ancienne["uid"] in fiches else (None if detachee else _cible(fiches, lue))
            cx.execute("INSERT INTO linkedin(url, uid, detachee, donnees, le) VALUES (?,?,?,?,?) ON CONFLICT(url) DO UPDATE "
                       "SET uid = excluded.uid, donnees = excluded.donnees, le = excluded.le",
                       (lue.uid, uid, int(detachee), json.dumps(nouveau, ensure_ascii=False), quand))
            if detachee or not uid:
                bilan["sans_contact"] += 0 if detachee else 1
                continue
            bilan["rattachees"] += 1
            f = fiches[uid]
            auto, propose = {}, {}
            for champ in CHAMPS_SUIVIS:
                v = nouveau[champ]
                if not v or v == f.get(champ, "") or (ancienne and v == ancien.get(champ, "")):
                    continue
                if ancien.get(champ) and f.get(champ, "") == ancien.get(champ):
                    auto[champ] = v
                else:
                    propose[champ] = v
            courriel = nouveau["courriel"]
            if courriel and courriel != ancien.get("courriel") and \
                    courriel.lower() not in {x["valeur"].lower() for x in f.get("courriels", [])}:
                propose["courriel"] = courriel
            if auto:
                cx.execute("INSERT OR REPLACE INTO en_attente(uid, motif, donnees) VALUES (?, 'linkedin', ?)",
                           (uid, json.dumps(auto, ensure_ascii=False)))
                bilan["automatiques"] += 1
            if propose:
                cle = f"{lue.uid}|{traiter.empreinte(propose)}"
                if traiter.ajouter(cx, "linkedin", uid, cle, {"url": lue.uid, "changements": propose,
                                                              "actuel": {k: f.get(k, "") for k in CHAMPS_SUIVIS}}):
                    bilan["proposees"] += 1
            if not auto and not propose:
                bilan["inchangees"] += 1
    c.oublier()
    c.base.noter("linkedin", f"Import LinkedIn : {bilan['lues']} relations, {bilan['proposees']} changement(s) "
                 f"proposé(s), {bilan['automatiques']} écrit(s) la nuit", bilan)
    return bilan


def sans_contact(c) -> list[dict]:
    import json
    return [{"url": l["url"], **json.loads(l["donnees"])}
            for l in c.base.tous("SELECT * FROM linkedin WHERE uid IS NULL AND detachee = 0 ORDER BY url")]


def rattacher(c, url: str, uid: str | None) -> None:
    """uid None : relation détachée (plus jamais rattachée toute seule)."""
    if uid:
        c.fiche(uid)
        c.base.executer("UPDATE linkedin SET uid = ?, detachee = 0 WHERE url = ?", (uid, url))
    else:
        c.base.executer("UPDATE linkedin SET uid = NULL, detachee = 1 WHERE url = ?", (url,))
    c.oublier()


# ------------------------------------------------------------ API de portabilité (membres UE)

def autorisation(c) -> dict:
    import secrets
    import time
    from urllib.parse import urlencode
    from .carnet import ErreurCarnet
    if not (c.cfg.linkedin_client_id and c.cfg.linkedin_client_secret):
        raise ErreurCarnet("Renseigne CARNET_LINKEDIN_CLIENT_ID et CARNET_LINKEDIN_CLIENT_SECRET dans la stack.")
    etat = secrets.token_urlsafe(24)
    etats = {k: v for k, v in c.__dict__.setdefault("_etats_linkedin", {}).items() if v > time.monotonic()}
    etats[etat] = time.monotonic() + 15 * 60
    c._etats_linkedin = etats
    parametres = {"response_type": "code", "client_id": c.cfg.linkedin_client_id,
                  "redirect_uri": c.cfg.linkedin_redirect, "state": etat, "scope": "r_dma_portability_self_serve"}
    return {"url": "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(parametres)}


def code(c, adresse: str) -> dict:
    """Adresse de retour collée (…?code=…&state=…) → jeton → relations importées."""
    import time
    from urllib.parse import parse_qs, urlsplit
    import httpx
    from .carnet import ErreurCarnet
    requete = parse_qs(urlsplit((adresse or "").strip()).query)
    if "error" in requete:
        raise ErreurCarnet("LinkedIn a refusé : " + (requete.get("error_description") or requete["error"])[0])
    code_, etat = (requete.get("code") or [""])[0], (requete.get("state") or [""])[0]
    if not code_:
        raise ErreurCarnet("Pas de « code= » dans cette adresse : colle l'adresse complète où LinkedIn t'a renvoyé.")
    if c.__dict__.get("_etats_linkedin", {}).pop(etat, 0) < time.monotonic():
        raise ErreurCarnet("Lien expiré ou déjà utilisé : recommence « Se connecter à LinkedIn ».")
    try:
        with c.http("linkedin") as client:
            r = client.post("https://www.linkedin.com/oauth/v2/accessToken", data={
                "grant_type": "authorization_code", "code": code_, "redirect_uri": c.cfg.linkedin_redirect,
                "client_id": c.cfg.linkedin_client_id, "client_secret": c.cfg.linkedin_client_secret})
    except httpx.HTTPError as exc:
        raise ErreurCarnet(f"LinkedIn injoignable ({exc.__class__.__name__}).") from exc
    if r.status_code >= 400 or "access_token" not in r.text:
        raise ErreurCarnet(f"Échange du code refusé par LinkedIn : {' '.join(r.text.split())[:200]}")
    return api(c, r.json()["access_token"])


def api(c, jeton: str) -> dict:
    """Relations lues par l'API de portabilité (portée r_dma_portability_self_serve). Le jeton
    n'est jamais enregistré ; il reste en mémoire si LinkedIn prépare encore les données."""
    import csv
    import io as io_
    import httpx
    from .carnet import ErreurCarnet
    jeton = (jeton or "").strip() or c.__dict__.get("_jeton_linkedin") or ""
    if not jeton:
        raise ErreurCarnet("Connecte-toi d'abord à LinkedIn.")
    entetes = {"Authorization": f"Bearer {jeton}", "LinkedIn-Version": "202312", "X-Restli-Protocol-Version": "2.0.0"}
    lignes: list[dict] = []
    with c.http("linkedin") as client:
        for page in range(500):
            try:
                r = client.get(API, headers=entetes, params={"q": "criteria", "domain": "CONNECTIONS", "start": page})
            except httpx.HTTPError as exc:
                raise ErreurCarnet(f"LinkedIn injoignable ({exc.__class__.__name__}).") from exc
            if r.status_code in (401, 403):
                raise ErreurCarnet("LinkedIn refuse le jeton (expiré ou sans la portée de portabilité) : reconnecte-toi.")
            if r.status_code == 404 or (r.status_code >= 400 and "No data found" in r.text):
                break
            if r.status_code >= 400:
                raise ErreurCarnet(f"LinkedIn a répondu {r.status_code} : {' '.join(r.text.split())[:200]}")
            elements = r.json().get("elements") or []
            if isinstance(elements, dict):
                elements = [elements]
            donnees = [x for e in elements if e.get("snapshotDomain") == "CONNECTIONS" for x in (e.get("snapshotData") or [])]
            if not donnees:
                break
            lignes += donnees
    if not lignes:
        c._jeton_linkedin = jeton
        raise ErreurCarnet("LinkedIn prépare encore tes données (environ 30 minutes après la première autorisation) : "
                           "réessaie plus tard avec « Réessayer ».")
    c._jeton_linkedin = None
    tampon = io_.StringIO()
    ecrivain = csv.DictWriter(tampon, fieldnames=COLONNES, extrasaction="ignore")
    ecrivain.writeheader()
    for ligne in lignes:
        ecrivain.writerow({k: str(ligne.get(k, "") or "") for k in COLONNES})
    return importer(c, tampon.getvalue())
