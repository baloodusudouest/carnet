"""La nuit (CARNET_VEILLE_HEURE, 03:00 par défaut), sous un seul verrou :

1. lecture complète d'iCloud (arrêt si elle est incomplète ou si trop de fiches disparaissent) ;
2. relecture d'Immich et de Treemich, liaisons sûres ;
3. sauvegarde, puis au plus 20 écritures sûres : photo d'une fiche liée qui n'en a pas, date
   de naissance manquante connue sans conflit, nouveau poste ou société LinkedIn quand la fiche
   portait l'ancien ; jamais de suppression ; une carte changée sur l'iPhone n'est pas écrasée ;
4. copie dans Synology Contacts, kit d'urgence, purge des sauvegardes.
La nuit n'écrit rien tant qu'aucune lecture complète n'a servi de référence.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from . import icloud, liaisons, photos, sorties
from .carddav import ErreurICloud
from .carnet import Carnet, ErreurCarnet, Occupe
from .temps import iso, maintenant, ZONE

log = logging.getLogger("carnet")
PLAFOND = 20                      # fiches écrites au plus par nuit
REESSAI = 10 * 60                 # verrou pris : nouvel essai toutes les 10 min…
REESSAI_PENDANT = 3 * 3600        # …pendant 3 h


def passer(c: Carnet, origine: str = "nuit") -> dict:
    """Une nuit complète. Lève Occupe si une autre écriture est en cours."""
    bilan = {"le": iso(maintenant()), "origine": origine, "ecrites": 0, "liaisons": 0, "reportees": 0,
             "erreur": None, "erreur_lecture": None, "alerte": None, "details": []}
    with c.ecriture():
        c.tache = {"nom": "nuit", "etat": "en_cours", "message": "Lecture d'iCloud…"}
        try:
            try:
                lecture = icloud.relire(c, origine)
            except Exception as exc:  # noqa: BLE001 — lecture en échec : rien d'autre n'est fait
                bilan["erreur"] = bilan["erreur_lecture"] = str(exc)
                bilan["alerte"] = "lecture"
                raise
            if lecture.get("reference"):
                bilan["details"].append("Première lecture : référence enregistrée, rien n'est écrit cette fois.")
            else:
                c.tache["message"] = "Immich et Treemich…"
                d = liaisons.donnees(c, rafraichir=True)
                for e in d["erreurs"]:
                    bilan["details"].append(e)
                for s in liaisons.sures(c, d):
                    liaisons.lier(c, s["uid"], "immich", s["immich"], statut="auto")
                    if s.get("treemich"):
                        try:
                            liaisons.lier(c, s["uid"], "treemich", s["treemich"], statut="auto")
                        except ErreurCarnet:
                            pass
                    bilan["liaisons"] += 1
                c.tache["message"] = "Écritures sûres…"
                _ecritures_sures(c, d, bilan)
            c.tache["message"] = "Synology Contacts…"
            syno = sorties.copier_synology(c)
            if syno.get("erreur"):
                bilan["details"].append(f"Synology : {syno['erreur']}")
            if any(True for _ in c.base.tous("SELECT 1 FROM fiches LIMIT 1")):
                try:
                    if c.cfg.kit_config and c.cfg.kit_config.is_dir():
                        sorties.envoyer_kit(c)
                except ErreurCarnet as exc:
                    bilan["details"].append(f"Kit : {exc}")
            icloud.purger(c)
        except Exception as exc:  # noqa: BLE001
            if not bilan["erreur"]:
                bilan["erreur"] = str(exc)
                log.exception("Nuit")
        finally:
            c.tache = {"nom": "nuit", "etat": "erreur" if bilan["erreur"] else "termine",
                       "message": bilan["erreur"] or f"Nuit terminée : {bilan['ecrites']} fiche(s) écrite(s)."}
            c.base.ecrire("nuit", bilan)
            c.base.noter("nuit", f"Nuit ({origine}) : {bilan['liaisons']} liaison(s), {bilan['ecrites']} écriture(s)"
                         + (f", {bilan['reportees']} reportée(s)" if bilan["reportees"] else "")
                         + (f" — erreur : {bilan['erreur']}" if bilan["erreur"] else ""),
                         {k: bilan[k] for k in ("liaisons", "ecrites", "reportees")})
    return bilan


def _ecritures_sures(c: Carnet, d: dict, bilan: dict) -> None:
    """Au plus PLAFOND fiches, une seule écriture par fiche (tous les changements réunis)."""
    a_faire: dict[str, dict] = {}
    for x in liaisons.dates_manquantes(c, d):
        a_faire.setdefault(x["uid"], {})["anniversaire"] = x["date"]
    for l in c.base.tous("SELECT uid, donnees FROM en_attente WHERE motif = 'linkedin'"):
        a_faire.setdefault(l["uid"], {})["_linkedin"] = json.loads(l["donnees"])
    sans_photo = [u for u, f in c.fiches().items() if not f.get("a_photo") and c.liaisons().get(u, {}).get("immich")]
    for u in sans_photo:
        a_faire.setdefault(u, {})["_photo"] = True
    # Une fiche qui attend ta relecture (modifiée sur l'iPhone, conflit) n'est jamais touchée la nuit
    en_revue = {l["uid"] for l in c.base.tous("SELECT uid FROM a_traiter WHERE motif IN "
                                              "('iphone_modifiee', 'iphone_nouvelle', 'conflit')")}
    for uid in en_revue & set(a_faire):
        a_faire.pop(uid)
        bilan["details"].append("Fiche en attente de relecture : écriture sûre remise à plus tard.")
    if not a_faire:
        return
    icloud.sauvegarder(c, "nuit")
    for uid, changements in sorted(a_faire.items()):
        if bilan["ecrites"] >= PLAFOND:
            bilan["reportees"] += 1
            continue
        f = c.fiches().get(uid)
        if not f:
            continue
        fiche = {k: v for k, v in f.items() if k != "a_photo"}
        photo = None
        if changements.pop("_photo", False):
            try:
                cands = photos.candidats(c, uid)
                if cands:
                    photo = photos.portrait(c, uid, cands[0]["asset"])
            except ErreurCarnet as exc:
                bilan["details"].append(f"Photo : {exc}")
        for champ, x in changements.pop("_linkedin", {}).items():
            # Revérifié au moment d'écrire : seulement si la fiche porte encore l'ancienne valeur LinkedIn
            if champ in ("societe", "fonction") and isinstance(x, dict) and fiche.get(champ, "") == x.get("ancien"):
                fiche[champ] = x["nouveau"]
        if changements.get("anniversaire") and not fiche.get("anniversaire"):
            fiche["anniversaire"] = changements["anniversaire"]
        if photo is None and fiche == {k: v for k, v in f.items() if k != "a_photo"}:
            c.base.executer("DELETE FROM en_attente WHERE uid = ?", (uid,))
            continue
        try:
            icloud.ecrire(c, uid, fiche, photo, origine="nuit", motif="écriture sûre")
            bilan["ecrites"] += 1
            if photo is not None:
                cands = photos.candidats(c, uid)
                c.base.executer("UPDATE portraits SET asset = ? WHERE uid = ?", (cands[0]["asset"], uid))
        except (ErreurCarnet, ErreurICloud) as exc:   # conflit iPhone (carte non écrasée), carte refusée…
            bilan["details"].append(str(exc))
        # Retirée même après une erreur : la même carte ne bloque pas chaque nuit
        c.base.executer("DELETE FROM en_attente WHERE uid = ?", (uid,))


# ------------------------------------------------------------ ordonnanceur

def prochaine(heure: str, apres: datetime) -> datetime:
    h, _, m = heure.partition(":")
    cible = apres.replace(hour=int(h), minute=int(m or 0), second=0, microsecond=0)
    return cible if cible > apres else cible + timedelta(days=1)


def demarrer(c: Carnet) -> threading.Thread | None:
    if not c.cfg.nuit_active:
        log.info("Nuit désactivée (CARNET_VEILLE_HEURE)")
        return None

    def boucle():
        while True:
            cible = prochaine(c.cfg.veille_heure, datetime.now(ZONE))
            time.sleep(max(1.0, (cible - datetime.now(ZONE)).total_seconds()))
            fin = time.monotonic() + REESSAI_PENDANT
            while True:
                try:
                    passer(c)
                    break
                except Occupe:
                    if time.monotonic() > fin:
                        c.base.noter("nuit", "Nuit abandonnée : une autre opération occupait carnet depuis 3 h")
                        break
                    time.sleep(REESSAI)
                except Exception:  # noqa: BLE001 — déjà noté dans le journal
                    break
    t = threading.Thread(target=boucle, name="nuit", daemon=True)
    t.start()
    return t
