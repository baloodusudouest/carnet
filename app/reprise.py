"""Reprise unique depuis la base de carnet 1.3 (SQLCipher, clé CARNET_DB_KEY déjà dans la stack).

Faite une seule fois, au premier démarrage, après la première lecture d'iCloud (il faut connaître
les UID iCloud des fiches). L'ancienne base est seulement lue, jamais modifiée. Sont repris :
les liaisons Immich/Treemich et leurs refus, les portraits choisis, les affiches et leur pose,
les relations LinkedIn (profil → fiche, relations détachées).
Dans la 1.3, une fiche s'appelait par un identifiant interne ; son UID iCloud se trouve dans
le suivi iCloud (`icloud_suivi`) ou, à défaut, dans la source iCloud importée.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

from .carnet import Carnet
from .temps import iso, maintenant

log = logging.getLogger("carnet")


def a_faire(c: Carnet) -> bool:
    p = c.cfg.ancienne_base
    return bool(p and p.is_file() and c.cfg.ancienne_cle and not c.base.lire("reprise")
                and c.base.lire("reference"))


def _ouvrir(chemin: Path, cle: str):
    import sqlcipher3   # seulement pour la reprise
    # Copie de travail : l'ancienne base (et son journal WAL) n'est jamais touchée
    dossier = Path(tempfile.mkdtemp(prefix="carnet-reprise-"))
    for suffixe in ("", "-wal", "-shm"):
        src = chemin.with_name(chemin.name + suffixe)
        if src.exists():
            shutil.copy2(src, dossier / (chemin.name + suffixe))
    cx = sqlcipher3.connect(str(dossier / chemin.name))
    cx.row_factory = sqlcipher3.Row
    # Paramètre lié impossible avec PRAGMA : apostrophes échappées (même façon que la 1.3)
    cx.execute("PRAGMA key = '" + cle.replace("'", "''") + "'")
    cx.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return cx, dossier


def _etat(cx, cle: str, defaut):
    l = cx.execute("SELECT valeur FROM etat WHERE cle = ?", (cle,)).fetchone()
    return json.loads(l["valeur"]) if l and l["valeur"] else defaut


def reprendre(c: Carnet) -> dict:
    bilan = {"le": iso(maintenant()), "liaisons": 0, "refus": 0, "portraits": 0, "affiches": 0, "linkedin": 0,
             "ignorees": 0, "erreur": None}
    try:
        cx, dossier = _ouvrir(c.cfg.ancienne_base, c.cfg.ancienne_cle)
    except Exception as exc:  # noqa: BLE001
        bilan["erreur"] = f"Ancienne base illisible ({exc.__class__.__name__}) : vérifie CARNET_DB_KEY."
        c.base.ecrire("reprise_essai", bilan)
        c.base.noter("reprise", bilan["erreur"])
        return bilan
    try:
        uids = c.fiches()
        pid_uid: dict[str, str] = {}
        for pid, info in _etat(cx, "icloud_suivi", {}).items():
            if info.get("uid") in uids:
                pid_uid[pid] = info["uid"]
        for l in cx.execute("SELECT personne_id, uid FROM sources WHERE source = 'icloud' AND uid IS NOT NULL"):
            if l["personne_id"] and l["personne_id"] not in pid_uid and l["uid"] in uids:
                pid_uid[l["personne_id"]] = l["uid"]
        quand = iso(maintenant())
        with c.base.transaction() as nx:
            for pid, lien in _etat(cx, "liaisons", {}).items():
                uid = pid_uid.get(pid)
                if not uid:
                    bilan["ignorees"] += 1
                    continue
                for service in ("immich", "treemich"):
                    if lien.get(service):
                        nx.execute("INSERT OR IGNORE INTO liaisons(uid, service, ext_id, statut, le) VALUES (?,?,?,?,?)",
                                   (uid, service, lien[service], "confirmee", quand))
                        bilan["liaisons"] += 1
            for r in _etat(cx, "liaisons_refusees", []):
                pid, _, ext = str(r).partition("|")
                if pid_uid.get(pid) and ext:
                    for service in ("immich", "treemich"):
                        nx.execute("INSERT OR IGNORE INTO refus(uid, service, ext_id) VALUES (?,?,?)",
                                   (pid_uid[pid], service, ext))
                    bilan["refus"] += 1
            candidats = _etat(cx, "photos_hd_candidats", {})
            for pid, hd in _etat(cx, "photos_hd", {}).items():
                uid = pid_uid.get(pid)
                if not uid:
                    continue
                cands = [{k: x.get(k) for k in ("asset", "boite", "taille", "type", "le", "ratio")}
                         for x in candidats.get(pid, []) if x.get("asset") and x.get("boite")]
                nx.execute("INSERT OR REPLACE INTO portraits(uid, candidats, asset, manuel, le) VALUES (?,?,?,?,?)",
                           (uid, json.dumps(cands[:6]), hd.get("asset"), int(bool(hd.get("manuel"))), quand))
                bilan["portraits"] += 1
            for pid, a in _etat(cx, "affiches", {}).items():
                uid = pid_uid.get(pid)
                if uid and a.get("immich_asset"):
                    nx.execute("INSERT OR REPLACE INTO affiches(uid, source, immich, posee, le) VALUES (?,?,?,?,?)",
                               (uid, a.get("source"), a["immich_asset"], a.get("posee"), quand))
                    bilan["affiches"] += 1
            try:
                lignes = cx.execute("SELECT id, uid, donnees, personne_id FROM sources WHERE source = 'linkedin' "
                                    "AND uid IS NOT NULL").fetchall()
                separees = {r[0] for r in cx.execute("SELECT a FROM distinctes UNION SELECT b FROM distinctes")}
            except Exception:  # noqa: BLE001 — base d'avant la migration 3
                lignes, separees = [], set()
            for l in lignes:
                d = json.loads(l["donnees"])
                donnees = {"societe": d.get("societe", ""), "fonction": d.get("fonction", ""),
                           "courriel": (d.get("courriels") or [{}])[0].get("valeur", ""),
                           "nom": f"{d.get('prenom', '')} {d.get('nom', '')}".strip()}
                uid = pid_uid.get(l["personne_id"]) if l["personne_id"] else None
                nx.execute("INSERT OR REPLACE INTO linkedin(url, uid, detachee, donnees, le) VALUES (?,?,?,?,?)",
                           (l["uid"], uid, int(not l["personne_id"] and l["id"] in separees), json.dumps(donnees, ensure_ascii=False), quand))
                bilan["linkedin"] += 1
    except Exception as exc:  # noqa: BLE001
        log.exception("Reprise")
        bilan["erreur"] = f"Reprise interrompue : {exc}"
    finally:
        cx.close()
        shutil.rmtree(dossier, ignore_errors=True)
    c.oublier()
    # Enregistrée seulement si elle a réussi : sinon, nouvel essai au prochain démarrage
    c.base.ecrire("reprise" if not bilan["erreur"] else "reprise_essai", bilan)
    c.base.noter("reprise", f"Reprise de la 1.3 : {bilan['liaisons']} liaison(s), {bilan['refus']} refus, "
                 f"{bilan['portraits']} portrait(s), {bilan['affiches']} affiche(s), {bilan['linkedin']} relation(s) LinkedIn"
                 + (f" — {bilan['erreur']}" if bilan["erreur"] else ""), bilan)
    return bilan
