"""Opérations de carnet : import, rapprochement, révision, export, kit, archives."""
from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
import json
import logging
import re
import secrets
import shutil
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import HTTPException
from rapidfuzz import fuzz

from . import doublons, export, fusion, portraits, synchro
from .carddav import CardDAV, Conflit, ErreurICloud
from .liens import TYPES_FAMILLE, ErreurLien, Immich, Treemich, relations_de
from .config import Config
from .db import Base
from .modele import (CHAMPS_MULTIPLES, GROUPE_A_CLASSER, GROUPE_MOI, GROUPE_URGENCE, GROUPE_VERIFIES, GROUPES, GROUPES_PERSO,
                     GROUPES_TRAVAIL, LIBELLES_SOURCES, REGLES_GROUPES, completer, fiche_vide, groupes_reconnus, nom_affiche)
from .normalisation import (CLES, GROUPES_PROCHES, MESSAGERIES, formater_nom, formater_prenom, note, configurer_groupes, ValeurInvalide, cle_texte, domaine_pro, regle_proches,
                            emojis_sans_groupe, nature, reseau_detecte, type_pro_attendu, nettoyer, normaliser_fiche,
                            societe_depuis_domaine)
from .sources import detecter_source, lire_texte, linkedin, outlook, vcard

log = logging.getLogger("carnet")
LECTEURS = {"icloud": vcard.lire, "gmail": vcard.lire, "outlook": outlook.lire,
            "linkedin": linkedin.lire}
EXTENSIONS = {".vcf", ".vcard", ".csv"}


# Mots qui ne distinguent pas une société (formes juridiques, articles)
MOTS_SOCIETE_VIDES = {"sa", "sas", "sasu", "sarl", "eurl", "sci", "scop", "gmbh", "ltd", "inc", "llc",
                      "group", "groupe", "la", "le", "les", "de", "des", "du", "et", "the", "and", "france"}


# Changer cette valeur fait réécrire toutes les fiches à la prochaine synchro (correctif d'écriture)
VERSION_SYNCHRO = ":2"


class ErreurCarnet(Exception):
    """Erreur à afficher telle quelle à l'utilisateur."""


def maintenant() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _empreinte(fiche: dict, photo: bytes | None) -> str:
    h = hashlib.sha256(json.dumps(fiche, sort_keys=True, ensure_ascii=False).encode())
    if photo:
        h.update(photo)
    return h.hexdigest()


class Carnet:
    def __init__(self, cfg: Config, base: Base):
        self.cfg, self.base = cfg, base
        for dossier in (cfg.depot, cfg.archives, cfg.export):
            dossier.mkdir(parents=True, exist_ok=True)
        # iCloud (V2) : une seule opération à la fois, exécutée en arrière-plan
        self.transport_icloud = None          # remplacé par un faux serveur dans les tests
        self._tache: dict = {"etat": "repos"}
        self._plan: dict | None = None
        self._verrou_icloud = threading.Lock()
        configurer_groupes(self.base.etat("groupes_perso", []))
        self._rattrapage_linkedin()

    # ================================================================ dépôt et import

    def depot(self) -> list[dict]:
        fichiers = []
        for f in sorted(self.cfg.depot.iterdir()):
            if f.is_file() and f.suffix.lower() in EXTENSIONS and not f.name.startswith("."):
                fichiers.append({"nom": f.name, "taille": f.stat().st_size,
                                 "source": detecter_source(f)})
        return fichiers

    def deposer(self, nom: str, contenu: bytes) -> dict:
        nom = Path(nom).name
        if Path(nom).suffix.lower() not in EXTENSIONS:
            raise ErreurCarnet("Seuls les fichiers .vcf et .csv sont acceptés.")
        cible = self.cfg.depot / nom
        n = 2
        while cible.exists():  # deux exports du même nom : on n'écrase jamais
            cible = self.cfg.depot / f"{Path(nom).stem} ({n}){Path(nom).suffix}"
            n += 1
        cible.write_bytes(contenu)
        return {"nom": cible.name, "taille": len(contenu), "source": detecter_source(cible)}

    def importer(self, nom: str, source: str) -> dict:
        chemin = self.cfg.depot / Path(nom).name
        if not chemin.is_file():
            raise ErreurCarnet(f"{nom} n'est plus dans le dossier de dépôt.")
        if source not in LECTEURS:
            raise ErreurCarnet("Source inconnue : choisis iCloud, Gmail, Outlook ou LinkedIn.")
        contenu = chemin.read_bytes()
        sha = hashlib.sha256(contenu).hexdigest()
        if self.base.un("SELECT id FROM imports WHERE sha256 = ?", (sha,)):
            raise ErreurCarnet(f"{nom} a déjà été importé (même contenu).")
        fiches, avertissements = LECTEURS[source](lire_texte(chemin), self.cfg.region)
        if not fiches:
            raise ErreurCarnet("Aucun contact lu dans ce fichier. " + " ".join(avertissements[:3]))

        quand = maintenant()
        nom_archive = f"{quand:%Y-%m-%d_%H%M%S}_{source}_{chemin.name}"
        shutil.copy2(chemin, self.cfg.archives / nom_archive)
        enrichit = 1 if source == "linkedin" else 0
        nouveaux, identiques, mises_a_jour = [], 0, 0
        try:
            with self.base.transaction() as cx:  # import entier ou rien
                import_id, nouveaux, identiques, mises_a_jour = self._inserer(
                    cx, source, chemin.name, sha, nom_archive, quand, fiches, enrichit)
                bilan = self._rattacher(cx, nouveaux, enrichit=bool(enrichit))
                if not enrichit:  # des relations LinkedIn importées avant trouvent enfin leur contact
                    orphelines = [l["id"] for l in cx.execute(
                        "SELECT id FROM sources WHERE enrichissement = 1 AND personne_id IS NULL").fetchall()]
                    bilan["enrichies"] = self._rattacher_enrichissement(cx, orphelines)["enrichies"]
        except BaseException:
            (self.cfg.archives / nom_archive).unlink(missing_ok=True)
            raise
        chemin.unlink(missing_ok=True)  # l'original est dans archives/
        log.info("Import %s (%s) : %d lus, %d ajoutés, %d identiques, %d mis à jour",
                 chemin.name, source, len(fiches), len(nouveaux), identiques, mises_a_jour)
        return {"source": source, "lus": len(fiches), "ajoutes": len(nouveaux),
                "identiques": identiques, "mises_a_jour": mises_a_jour,
                "avertissements": avertissements[:20], **bilan}

    def _inserer(self, cx, source, nom_fichier, sha, nom_archive, quand, fiches, enrichit):
        """Enregistre les fiches lues. Une fiche dont l'UID est déjà connu (nouvel export du
        même carnet) remplace l'ancienne auprès du même contact, qui repasse en révision."""
        nouveaux, identiques, mises_a_jour = [], 0, 0
        cur = cx.execute(
            "INSERT INTO imports(source, nom_fichier, sha256, archive, importe_le, expire_le, nb_lus)"
            " VALUES(?,?,?,?,?,?,?)",
            (source, nom_fichier, sha, nom_archive, _iso(quand),
             _iso(quand + timedelta(days=self.cfg.archive_jours)), len(fiches)))
        import_id = cur.lastrowid
        for lue in fiches:
            emp = _empreinte(lue.fiche, lue.photo)
            if cx.execute("SELECT 1 FROM sources WHERE source = ? AND empreinte = ?",
                          (source, emp)).fetchone():
                identiques += 1
                continue
            ancienne = cx.execute(
                "SELECT id, personne_id FROM sources WHERE source = ? AND uid = ? "
                "AND personne_id IS NOT NULL ORDER BY id DESC", (source, lue.uid)).fetchone() \
                if lue.uid else None
            cur = cx.execute(
                "INSERT INTO sources(import_id, source, uid, empreinte, donnees, photo, photo_type,"
                " brut, enrichissement, personne_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (import_id, source, lue.uid, emp, json.dumps(lue.fiche, ensure_ascii=False),
                 lue.photo, lue.photo_type, lue.brut, enrichit,
                 ancienne["personne_id"] if ancienne else None))
            if ancienne:
                nouvelle = cur.lastrowid
                cx.execute("UPDATE sources SET personne_id = NULL WHERE id = ?", (ancienne["id"],))
                cx.execute("INSERT OR IGNORE INTO distinctes(a, b) SELECT "
                           "min(?, CASE WHEN a = ? THEN b ELSE a END), max(?, CASE WHEN a = ? THEN b ELSE a END) "
                           "FROM distinctes WHERE a = ? OR b = ?",
                           (nouvelle, ancienne["id"], nouvelle, ancienne["id"], ancienne["id"], ancienne["id"]))
                cx.execute("UPDATE personnes SET statut = CASE WHEN statut = 'ecarte' THEN 'ecarte' ELSE 'a_reviser' END, a_revoir = 'fiche mise à jour "
                           "dans ' || ?, modifie_le = ? WHERE id = ?",
                           (LIBELLES_SOURCES.get(source, source), _iso(quand), ancienne["personne_id"]))
                mises_a_jour += 1
            else:
                nouveaux.append(cur.lastrowid)
        cx.execute("UPDATE imports SET nb_ajoutes = ?, nb_identiques = ? WHERE id = ?",
                   (len(nouveaux) + mises_a_jour, identiques, import_id))
        return import_id, nouveaux, identiques, mises_a_jour

    # ================================================================ rapprochement

    def _signatures(self, condition: str, params: tuple = ()) -> list[doublons.Signature]:
        lignes = self.base.lire(f"SELECT id, donnees FROM sources WHERE {condition}", params)
        return [doublons.signature(l["id"], json.loads(l["donnees"])) for l in lignes]

    def _interdits(self) -> set[tuple[int, int]]:
        return {(min(l["a"], l["b"]), max(l["a"], l["b"]))
                for l in self.base.lire("SELECT a, b FROM distinctes")}

    def _personne_de(self) -> dict[int, str]:
        return {l["id"]: l["personne_id"] for l in
                self.base.lire("SELECT id, personne_id FROM sources WHERE personne_id IS NOT NULL")}

    def _rattacher(self, cx, nouveaux: list[int], enrichit: bool) -> dict:
        if not nouveaux:
            return {"personnes_creees": 0, "personnes_completees": 0, "enrichies": 0}
        if enrichit:
            return self._rattacher_enrichissement(cx, nouveaux)
        nouv = set(nouveaux)
        sigs = self._signatures("enrichissement = 0")
        paires = [p for p in doublons.rapprochements(sigs, self._interdits())
                  if p[0] in nouv or p[1] in nouv]
        personne_de = self._personne_de()
        parent = {i: i for i in nouv}

        def racine(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b, _, _ in paires:
            if a in nouv and b in nouv:
                parent[racine(a)] = racine(b)
        groupes: dict[int, list[int]] = {}
        for i in nouv:
            groupes.setdefault(racine(i), []).append(i)

        creees = completees = 0
        quand = _iso(maintenant())
        for membres in groupes.values():
            ens = set(membres)
            liees = [p for p in paires if (p[0] in ens) != (p[1] in ens)]  # nouveau ↔ existant
            internes = [p for p in paires if p[0] in ens and p[1] in ens]
            meilleur: tuple[int, str] | None = None
            for a, b, score, _ in liees:
                ancien = b if a in ens else a
                pid = personne_de.get(ancien)
                if pid and (meilleur is None or score > meilleur[0]):
                    meilleur = (score, pid)
            raisons = [{"a": a, "b": b, "score": s, "raisons": r}
                       for a, b, s, r in internes + [p for p in liees
                                                     if meilleur and personne_de.get(
                                                         p[1] if p[0] in ens else p[0]) == meilleur[1]]]
            if meilleur:
                pid = meilleur[1]
                ligne = cx.execute("SELECT raisons, statut FROM personnes WHERE id = ?", (pid,)).fetchone()
                anciennes = json.loads(ligne["raisons"] or "[]")
                motif = "nouvelle fiche importée" if ligne["statut"] == "verifie" else None
                cx.execute("UPDATE personnes SET statut = CASE WHEN statut = 'ecarte' THEN 'ecarte' ELSE 'a_reviser' END, raisons = ?, "
                           "a_revoir = COALESCE(?, a_revoir), modifie_le = ? WHERE id = ?",
                           (json.dumps(anciennes + raisons, ensure_ascii=False), motif, quand, pid))
                completees += 1
            else:
                pid = str(uuid.uuid4())
                cx.execute("INSERT INTO personnes(id, statut, raisons, cree_le, modifie_le) "
                           "VALUES(?, 'a_reviser', ?, ?, ?)",
                           (pid, json.dumps(raisons, ensure_ascii=False), quand, quand))
                creees += 1
            cx.executemany("UPDATE sources SET personne_id = ? WHERE id = ?",
                           [(pid, m) for m in membres])
        return {"personnes_creees": creees, "personnes_completees": completees, "enrichies": 0}

    def _rattacher_enrichissement(self, cx, nouveaux: list[int]) -> dict:
        """LinkedIn : chaque ligne rejoint la personne la plus proche (courriel ou nom très proche)."""
        existants = self._signatures("enrichissement = 0 AND personne_id IS NOT NULL")
        personne_de = self._personne_de()
        interdits = self._interdits()
        enrichies, quand = 0, _iso(maintenant())
        if not nouveaux:
            return {"personnes_creees": 0, "personnes_completees": 0, "enrichies": 0}
        lignes = cx.execute(
            f"SELECT id, donnees FROM sources WHERE id IN ({','.join('?' * len(nouveaux))})",
            tuple(nouveaux)).fetchall()
        for l in lignes:
            sig = doublons.signature(l["id"], json.loads(l["donnees"]))
            meilleur = None
            for e in existants:
                if (min(e.id, sig.id), max(e.id, sig.id)) in interdits:
                    continue
                score, raisons = doublons.comparer(sig, e)
                if score >= 85 and (meilleur is None or score > meilleur[0]):
                    meilleur = (score, personne_de[e.id], e.id, raisons)
            if not meilleur:
                continue
            score, pid, autre, raisons = meilleur
            ligne = cx.execute("SELECT raisons, statut FROM personnes WHERE id = ?", (pid,)).fetchone()
            toutes = json.loads(ligne["raisons"] or "[]") + [
                {"a": autre, "b": l["id"], "score": score, "raisons": raisons}]
            motif = "complément LinkedIn" if ligne["statut"] == "verifie" else None
            cx.execute("UPDATE sources SET personne_id = ? WHERE id = ?", (pid, l["id"]))
            cx.execute("UPDATE personnes SET statut = CASE WHEN statut = 'ecarte' THEN 'ecarte' ELSE 'a_reviser' END, raisons = ?, "
                       "a_revoir = COALESCE(?, a_revoir), modifie_le = ? WHERE id = ?",
                       (json.dumps(toutes, ensure_ascii=False), motif, quand, pid))
            self._completer_par_linkedin(cx, pid, json.loads(l["donnees"]))
            enrichies += 1
        return {"personnes_creees": 0, "personnes_completees": 0, "enrichies": enrichies}

    @staticmethod
    def _completer_par_linkedin(cx, pid: str, linkedin_fiche: dict) -> bool:
        """Un contact déjà travaillé (brouillon ou fiche validée) reçoit d'office ce que LinkedIn
        apporte et qui lui manque : fonction, société, profil, courriel. Rien n'est remplacé ;
        le résultat va dans le brouillon, la fiche validée ne change qu'à la validation."""
        ligne = cx.execute("SELECT fiche, brouillon FROM personnes WHERE id = ?", (pid,)).fetchone()
        texte = ligne["brouillon"] or ligne["fiche"]
        if not texte:
            return False  # pas encore révisé : la proposition reprend déjà LinkedIn
        actuelle = completer(json.loads(texte))
        apport = completer({k: linkedin_fiche.get(k) for k in ("societe", "fonction", "courriels", "sites")
                            if linkedin_fiche.get(k)})
        reunie = fusion.reunir(actuelle, apport)
        if reunie == completer(json.loads(texte)):
            return False
        cx.execute("UPDATE personnes SET brouillon = ? WHERE id = ?", (json.dumps(reunie, ensure_ascii=False), pid))
        return True

    def _rattrapage_linkedin(self) -> None:
        """Une fois : contacts complétés par LinkedIn avant ce correctif (fonction et profil perdus)."""
        if self.base.etat("rattrapage_linkedin_1"):
            return
        with self.base.transaction() as cx:
            for l in cx.execute("SELECT personne_id, donnees FROM sources WHERE source = 'linkedin' "
                                "AND personne_id IS NOT NULL").fetchall():
                self._completer_par_linkedin(cx, l["personne_id"], json.loads(l["donnees"]))
        self.base.ecrire_etat("rattrapage_linkedin_1", True)

    # ================================================================ lecture

    def _sources_de(self, pid: str) -> list[dict]:
        lignes = self.base.lire(
            "SELECT s.id, s.source, s.uid, s.donnees, s.photo IS NOT NULL AS a_photo, s.enrichissement,"
            " i.nom_fichier, i.importe_le FROM sources s JOIN imports i ON i.id = s.import_id"
            " WHERE s.personne_id = ? ORDER BY s.id", (pid,))
        return [{"id": l["id"], "source": l["source"], "libelle": LIBELLES_SOURCES.get(l["source"], l["source"]),
                 "uid": l["uid"], "donnees": nettoyer(completer(json.loads(l["donnees"]))),
                 "a_photo": bool(l["a_photo"]), "enrichissement": bool(l["enrichissement"]),
                 "fichier": l["nom_fichier"], "importe_le": l["importe_le"]} for l in lignes]

    def _personne(self, pid: str):
        ligne = self.base.un("SELECT * FROM personnes WHERE id = ?", (pid,))
        if not ligne:
            raise ErreurCarnet("Ce contact n'existe plus (fusionné ou détaché entre-temps).")
        return ligne

    def _fiche_courante(self, ligne, sources: list[dict]) -> dict:
        """Ce que l'utilisateur voit : brouillon en cours, sinon fiche validée, sinon proposition."""
        for colonne in ("brouillon", "fiche"):
            if ligne[colonne]:
                return regle_proches(completer(json.loads(ligne[colonne])))
        return fusion.proposer(sources)

    def dossier(self, pid: str) -> dict:
        ligne = self._personne(pid)
        sources = self._sources_de(pid)
        courante = self._fiche_courante(ligne, sources)
        # Société déduite des courriels pro (toutes sources), proposée quand la fiche n'en a pas
        tous = completer({"courriels": courante["courriels"]          # ceux retenus d'abord
                          + [c for s in sources for c in s["donnees"]["courriels"]]})
        valeur, origine = self._proposer_societe(tous, self._societes_par_domaine())
        return {
            "id": pid, "statut": ligne["statut"], "a_revoir": ligne["a_revoir"],
            "brouillon": ligne["brouillon"] is not None, "verifie_le": ligne["verifie_le"],
            "fiche": courante,
            "societe_deduite": {"valeur": valeur, "origine": origine} if valeur else None,
            "proposition": fusion.proposer(sources),
            "sources": sources,
            "raisons": json.loads(ligne["raisons"] or "[]"),
        }

    def liste(self) -> list[dict]:
        personnes = self.base.lire("SELECT * FROM personnes")
        sources: dict[str, list[dict]] = {}
        for l in self.base.lire(
                "SELECT id, personne_id, source, donnees, photo IS NOT NULL AS a_photo, enrichissement"
                " FROM sources WHERE personne_id IS NOT NULL ORDER BY id"):
            sources.setdefault(l["personne_id"], []).append(
                {"id": l["id"], "source": l["source"], "donnees": nettoyer(completer(json.loads(l["donnees"]))),
                 "a_photo": bool(l["a_photo"]), "enrichissement": bool(l["enrichissement"])})
        resultat = []
        for p in personnes:
            src = sources.get(p["id"], [])
            fiche = self._fiche_courante(p, src)
            principales = [s for s in src if not s["enrichissement"]]
            resultat.append({
                "id": p["id"], "nom": nom_affiche(fiche), "statut": p["statut"],
                "a_revoir": p["a_revoir"], "brouillon": p["brouillon"] is not None,
                "groupes": fiche["groupes"], "sources": sorted({s["source"] for s in src}),
                "nb_sources": len(principales), "doublon": len(principales) > 1,
                "telephone": (fiche["telephones"][0].get("affichage") if fiche["telephones"] else ""),
                "courriel": (fiche["courriels"][0]["valeur"] if fiche["courriels"] else ""),
                "societe": fiche["societe"],
            })
        return sorted(resultat, key=lambda r: r["nom"].lower())

    def file(self) -> list[dict]:
        """File de révision : doublons d'abord, puis les contacts seuls, par ordre alphabétique."""
        a_faire = [p for p in self.liste() if p["statut"] == "a_reviser"]
        return sorted(a_faire, key=lambda p: (0 if p["doublon"] else 1, p["nom"].lower()))

    def photo(self, source_id: int) -> tuple[bytes, str] | None:
        l = self.base.un("SELECT photo, photo_type FROM sources WHERE id = ?", (source_id,))
        return (l["photo"], l["photo_type"] or "image/jpeg") if l and l["photo"] else None

    # ================================================================ révision

    def enregistrer(self, pid: str, fiche: dict, valider: bool) -> dict:
        """Sans validation, seul le brouillon change : la fiche validée (celle qu'exportent
        l'export propre et le kit) n'est remplacée qu'au moment de « Valider la fiche »."""
        self._personne(pid)
        sources = self._sources_de(pid)
        try:
            propre = normaliser_fiche(fiche, self.cfg.region)
        except ValeurInvalide as exc:
            raise ErreurCarnet(str(exc)) from exc
        if propre["photo"] not in {s["id"] for s in sources if s["a_photo"]}:
            propre["photo"] = None
        texte = json.dumps(propre, ensure_ascii=False)
        quand = _iso(maintenant())
        with self.base.transaction() as cx:
            if GROUPE_MOI in propre["groupes"]:
                self._retirer_moi_ailleurs(cx, pid)
            if valider:
                cx.execute("UPDATE personnes SET fiche = ?, brouillon = NULL, statut = 'verifie', "
                           "a_revoir = NULL, verifie_le = ?, modifie_le = ? WHERE id = ?",
                           (texte, quand, quand, pid))
            else:
                cx.execute("UPDATE personnes SET brouillon = ?, modifie_le = ? WHERE id = ?",
                           (texte, quand, pid))
        return self.dossier(pid)

    def _retirer_moi_ailleurs(self, cx, pid: str) -> None:
        """Le groupe « Moi » ne désigne qu'une fiche : il est retiré des autres."""
        for p in cx.execute("SELECT id, fiche, brouillon FROM personnes WHERE id != ?", (pid,)).fetchall():
            for colonne in ("fiche", "brouillon"):
                if p[colonne] and GROUPE_MOI in (f := json.loads(p[colonne])).get("groupes", []):
                    f["groupes"] = [g for g in f["groupes"] if g != GROUPE_MOI]
                    cx.execute(f"UPDATE personnes SET {colonne} = ? WHERE id = ?",
                               (json.dumps(f, ensure_ascii=False), p["id"]))

    def ecarter(self, pid: str) -> dict:
        """Met un contact de côté : il quitte la file, la Revue, l'export et le kit, et un nouvel
        import ne le ramène pas. Ses fiches restent dans carnet : on peut le restaurer."""
        self._personne(pid)
        with self.base.transaction() as cx:
            cx.execute("UPDATE personnes SET statut = 'ecarte', a_revoir = NULL, modifie_le = ? WHERE id = ?",
                       (_iso(maintenant()), pid))
        return self.dossier(pid)

    def restaurer(self, pid: str) -> dict:
        self._personne(pid)
        with self.base.transaction() as cx:
            cx.execute("UPDATE personnes SET statut = 'a_reviser', a_revoir = 'remis en révision', "
                       "modifie_le = ? WHERE id = ? AND statut = 'ecarte'", (_iso(maintenant()), pid))
        return self.dossier(pid)

    def rouvrir(self, pid: str) -> dict:
        self._personne(pid)
        with self.base.transaction() as cx:
            cx.execute("UPDATE personnes SET statut = 'a_reviser', a_revoir = 'rouvert à la main', "
                       "modifie_le = ? WHERE id = ?", (_iso(maintenant()), pid))
        return self.dossier(pid)

    def repartir(self, pid: str) -> dict:
        """Remplace le brouillon par la proposition automatique (la fiche validée ne change pas)."""
        self._personne(pid)
        proposition = fusion.proposer(self._sources_de(pid))
        with self.base.transaction() as cx:
            cx.execute("UPDATE personnes SET brouillon = ?, modifie_le = ? WHERE id = ?",
                       (json.dumps(proposition, ensure_ascii=False), _iso(maintenant()), pid))
        return self.dossier(pid)

    def detacher(self, pid: str, source_id: int) -> dict:
        """Sépare une fiche source : ce n'est pas la même personne. Ne sera plus rapprochée."""
        self._personne(pid)
        sources = self._sources_de(pid)
        cible = next((s for s in sources if s["id"] == source_id), None)
        if not cible:
            raise ErreurCarnet("Cette fiche ne fait pas partie de ce contact.")
        restantes = [s for s in sources if s["id"] != source_id]
        if not cible["enrichissement"] and not [s for s in restantes if not s["enrichissement"]]:
            raise ErreurCarnet("C'est la seule fiche de ce contact : rien à détacher.")
        quand = _iso(maintenant())
        nouvelle = None
        with self.base.transaction() as cx:
            cx.executemany("INSERT OR IGNORE INTO distinctes(a, b) VALUES(?, ?)",
                           [(min(source_id, s["id"]), max(source_id, s["id"])) for s in restantes])
            if cible["enrichissement"]:
                cx.execute("UPDATE sources SET personne_id = NULL WHERE id = ?", (source_id,))
            else:
                nouvelle = str(uuid.uuid4())
                cx.execute("INSERT INTO personnes(id, statut, raisons, cree_le, modifie_le) "
                           "VALUES(?, 'a_reviser', '[]', ?, ?)", (nouvelle, quand, quand))
                cx.execute("UPDATE sources SET personne_id = ? WHERE id = ?", (nouvelle, source_id))
            ligne = cx.execute("SELECT * FROM personnes WHERE id = ?", (pid,)).fetchone()
            raisons = [r for r in json.loads(ligne["raisons"] or "[]")
                       if source_id not in (r.get("a"), r.get("b"))]
            # Les valeurs apportées uniquement par la fiche détachée quittent ce contact
            courante = fusion.retirer_source(self._fiche_courante(ligne, sources), cible, restantes)
            cx.execute("UPDATE personnes SET raisons = ?, brouillon = ?, statut = 'a_reviser', "
                       "a_revoir = 'fiche détachée', modifie_le = ? WHERE id = ?",
                       (json.dumps(raisons, ensure_ascii=False),
                        json.dumps(courante, ensure_ascii=False), quand, pid))
        return {"dossier": self.dossier(pid), "nouvelle": nouvelle}

    def fusionner(self, pid: str, autre: str) -> dict:
        """Rattache toutes les fiches d'un autre contact à celui-ci (doublon non détecté)."""
        if pid == autre:
            raise ErreurCarnet("Impossible de fusionner un contact avec lui-même.")
        quand = _iso(maintenant())
        # Le travail déjà fait est gardé : la fiche de ce contact, complétée par celle de l'autre
        l1, l2 = self._personne(pid), self._personne(autre)
        f1 = self._fiche_courante(l1, self._sources_de(pid))
        f2 = self._fiche_courante(l2, self._sources_de(autre))
        reunie = fusion.reunir(f1, f2)
        with self.base.transaction() as cx:
            raisons = json.loads(l1["raisons"] or "[]") + json.loads(l2["raisons"] or "[]") + [
                {"a": None, "b": None, "score": 100, "raisons": ["fusion manuelle"]}]
            cx.execute("UPDATE sources SET personne_id = ? WHERE personne_id = ?", (pid, autre))
            cx.execute("DELETE FROM personnes WHERE id = ?", (autre,))
            cx.execute("UPDATE personnes SET raisons = ?, brouillon = ?, statut = 'a_reviser', "
                       "a_revoir = 'fusion manuelle', modifie_le = ? WHERE id = ?",
                       (json.dumps(raisons, ensure_ascii=False), json.dumps(reunie, ensure_ascii=False),
                        quand, pid))
        return self.dossier(pid)

    # ================================================================ groupes

    REGLES = {"proches", "travail"}

    def groupes(self) -> list[dict]:
        """Groupes intégrés (non modifiables) et groupes créés, avec leur nombre de contacts."""
        compte: Counter = Counter()
        for p in self.liste():
            if p["statut"] != "ecarte":
                compte.update(set(p["groupes"]))
        res = [{"nom": g, "fixe": True, "regle": REGLES_GROUPES.get(g), "nb": compte[g]} for g in GROUPES]
        res += [{"nom": g["nom"], "fixe": False, "regle": g.get("regle"), "nb": compte[g["nom"]]}
                for g in GROUPES_PERSO]
        return res

    def _nom_groupe(self, nom: str, sauf: str | None = None) -> str:
        nom = " ".join((nom or "").split())
        if not nom:
            raise ErreurCarnet("Donne un nom au groupe.")
        if len(nom) > 40:
            raise ErreurCarnet("Nom de groupe trop long (40 caractères au plus).")
        if any(c in nom for c in ",;:"):
            raise ErreurCarnet("Le nom d'un groupe ne peut pas contenir , ; ou :")
        pris = {cle_texte(g) for g in groupes_reconnus() + [GROUPE_VERIFIES] if g != sauf}
        if cle_texte(nom) in pris:
            raise ErreurCarnet(f"Le groupe « {nom} » existe déjà.")
        return nom

    def _enregistrer_groupes(self, perso: list[dict]) -> None:
        self.base.ecrire_etat("groupes_perso", perso)
        configurer_groupes(perso)

    def _perso(self, nom: str) -> dict:
        g = next((g for g in GROUPES_PERSO if g["nom"] == nom), None)
        if not g:
            raise ErreurCarnet("Ce groupe est intégré à carnet : il ne peut être ni modifié ni supprimé."
                               if nom in GROUPES else f"Groupe « {nom} » introuvable.")
        return g

    def creer_groupe(self, nom: str, regle: str | None) -> dict:
        if regle not in self.REGLES | {None}:
            raise ErreurCarnet("Règle inconnue.")
        nom = self._nom_groupe(nom)
        self._enregistrer_groupes([dict(g) for g in GROUPES_PERSO] + [{"nom": nom, "regle": regle}])
        return {"nom": nom}

    def modifier_groupe(self, ancien: str, nom: str, regle: str | None) -> dict:
        self._perso(ancien)
        if regle not in self.REGLES | {None}:
            raise ErreurCarnet("Règle inconnue.")
        nom = self._nom_groupe(nom, sauf=ancien)
        perso = [({"nom": nom, "regle": regle} if g["nom"] == ancien else dict(g)) for g in GROUPES_PERSO]
        self._enregistrer_groupes(perso)
        n = self._remplacer_groupe(ancien, nom) if nom != ancien else 0
        return {"nom": nom, "contacts": n}

    def supprimer_groupe(self, nom: str, vers: str | None) -> dict:
        self._perso(nom)
        if vers and (vers == nom or vers not in groupes_reconnus()):
            raise ErreurCarnet("Groupe de destination inconnu.")
        n = self._remplacer_groupe(nom, vers or None)
        self._enregistrer_groupes([dict(g) for g in GROUPES_PERSO if g["nom"] != nom])
        return {"contacts": n}

    def _remplacer_groupe(self, ancien: str, nouveau: str | None) -> int:
        """Remplace (ou retire) un groupe dans toutes les fiches, validées et brouillons.
        Les règles de téléphone du nouveau groupe s'appliquent aussitôt."""
        touches = 0
        with self.base.transaction() as cx:
            for p in cx.execute("SELECT id, fiche, brouillon FROM personnes").fetchall():
                maj = {}
                for colonne in ("fiche", "brouillon"):
                    if not p[colonne]:
                        continue
                    f = json.loads(p[colonne])
                    if ancien not in f.get("groupes", []):
                        continue
                    groupes = [g for g in f["groupes"] if g != ancien]
                    if nouveau and nouveau not in groupes:
                        groupes.append(nouveau)
                    f["groupes"] = sorted(groupes)
                    maj[colonne] = json.dumps(regle_proches(completer(f)), ensure_ascii=False)
                if maj:
                    touches += 1
                    for colonne, texte in maj.items():
                        cx.execute(f"UPDATE personnes SET {colonne} = ?, modifie_le = ? WHERE id = ?",
                                   (texte, _iso(maintenant()), p["id"]))
        return touches

    # ================================================================ revue des contacts vérifiés

    def revue(self) -> dict:
        """Contrôles sur les contacts vérifiés, regroupés par section."""
        personnes = []
        for p in self.base.lire("SELECT * FROM personnes WHERE statut = 'verifie'"):
            sources = self._sources_de(p["id"])
            personnes.append((p["id"], self._fiche_courante(p, sources)))
        par_domaine = self._societes_par_domaine()

        def resume(pid: str, f: dict, **extra) -> dict:
            return {"id": pid, "nom": nom_affiche(f), "groupes": f["groupes"],
                    "telephone": f["telephones"][0].get("affichage") if f["telephones"] else "",
                    "courriel": f["courriels"][0]["valeur"] if f["courriels"] else "", **extra}

        confirmes = set(self.base.etat("telephones_confirmes", []))
        tries = set(self.base.etat("portables_tries", []))
        natures_faites = set(self.base.etat("natures_confirmees", []))
        sections = {k: [] for k in ("anniversaires", "deux_portables", "bureau_travail", "societes",
                                    "travail_a_classer",
                                    "urgence_sans_mobile",
                                    "sans_groupe", "numeros_non_reconnus", "injoignables",
                                    "sites_mal_etiquetes", "emoji_sans_groupe", "numeros_internationaux")}
        for pid, f in sorted(personnes, key=lambda x: nom_affiche(x[1]).lower()):
            groupes = set(f["groupes"])
            if groupes & {"Famille", "Amis"} and not f["anniversaire"]:
                sections["anniversaires"].append(resume(pid, f))
            portables = [t for t in f["telephones"] if nature(t["valeur"]) == "mobile"]
            if groupes & GROUPES_PROCHES and len(portables) >= 2 and pid not in tries:
                sections["deux_portables"].append(resume(pid, f, numeros=[
                    {"valeur": t["valeur"], "affichage": t.get("affichage"), "type": t["type"]} for t in portables]))
            if groupes & set(GROUPES_TRAVAIL + [GROUPE_A_CLASSER]) and not f["societe"]:
                proposition, origine = self._proposer_societe(f, par_domaine)
                sections["societes"].append(resume(pid, f, proposition=proposition, origine=origine))
            for t in f["telephones"]:
                attendu = type_pro_attendu(t)
                if attendu and attendu != t["type"] and f"{pid}|{t['valeur']}" not in confirmes:
                    sections["bureau_travail"].append(resume(pid, f, numero=t["valeur"], affichage=t.get("affichage"),
                                                             type=t["type"], attendu=attendu))
            if GROUPE_A_CLASSER in groupes:
                sections["travail_a_classer"].append(resume(pid, f, societe=f["societe"]))
            if GROUPE_URGENCE in groupes and not any(t.get("mobile") for t in f["telephones"]):
                sections["urgence_sans_mobile"].append(resume(pid, f))
            if not groupes:
                sections["sans_groupe"].append(resume(pid, f))
            invalides = [t["valeur"] for t in f["telephones"] if not t.get("valide")]
            if invalides:
                sections["numeros_non_reconnus"].append(resume(pid, f, numeros=invalides))
            messageries = [s for s in f["sites"] if s.get("type") in MESSAGERIES
                           or reseau_detecte(s["valeur"]) in MESSAGERIES]
            if not f["telephones"] and not f["courriels"] and not messageries:
                sections["injoignables"].append(resume(pid, f))
            # Numéros étrangers : mobile ou fixe ? (détecté quand le pays le permet, à confirmer)
            for t in f["telephones"]:
                if t.get("valide") and not t["valeur"].startswith("+33") \
                        and f"{pid}|{t['valeur']}" not in natures_faites and not t.get("nature_choisie"):
                    sections["numeros_internationaux"].append(resume(
                        pid, f, numero=t["valeur"], affichage=t.get("affichage"), type=t["type"],
                        detectee=nature(t["valeur"])))
            for manque in emojis_sans_groupe(f):
                sections["emoji_sans_groupe"].append(resume(pid, f, **manque))
            # Lien d'un réseau ou d'une messagerie reconnu (t.me, wa.me…) qui n'a pas la bonne étiquette
            a_corriger = {s["valeur"]: reseau_detecte(s["valeur"]) for s in f["sites"]
                          if reseau_detecte(s["valeur"]) and reseau_detecte(s["valeur"]) != s.get("type")}
            if a_corriger:
                sections["sites_mal_etiquetes"].append(resume(pid, f, sites=[
                    {"valeur": v, "type": next(s["type"] for s in f["sites"] if s["valeur"] == v), "attendu": t}
                    for v, t in a_corriger.items()]))
        sections["societes_a_uniformiser"] = self._societes_a_uniformiser(personnes)
        sections["doublons_possibles"] = self._doublons_possibles(personnes)
        ids = {pid for pid, _ in personnes}
        noms = {pid: nom_affiche(f) for pid, f in personnes}
        sections["relations_treemich"] = [
            {"id": pid, "nom": noms[pid], "groupes": [], "treemich": item["treemich"], "contact": item["contact"]}
            for pid, item in sorted(self.base.etat("relations_treemich", {}).items(),
                                    key=lambda x: noms.get(x[0], "").lower()) if pid in ids]
        return sections

    def _doublons_possibles(self, personnes: list[tuple[str, dict]]) -> list[dict]:
        """Contacts vérifiés distincts qui désignent peut-être la même personne : mêmes règles
        que l'import, plus souples (même nom de famille et un mot commun, noms proches…)."""
        ignores = set(self.base.etat("doublons_ignores", []))
        # Fiches déjà déclarées « pas la même personne » (détachées) : pas reproposées
        personne_de = self._personne_de()
        separees = {"|".join(sorted((personne_de[a], personne_de[b])))
                    for a, b in self._interdits() if a in personne_de and b in personne_de}
        sigs = [doublons.signature(i, f) for i, (_, f) in enumerate(personnes)]
        resultat = []
        for x, y, score, raisons in doublons.rapprochements(sigs, seuil=doublons.SEUIL_REVUE):
            (pa, fa), (pb, fb) = personnes[x], personnes[y]
            cle = "|".join(sorted((pa, pb)))
            if cle in ignores or cle in separees:
                continue
            # La fiche d'une personne (prénom ou nom) sert de base, sinon la plus remplie
            def poids(f: dict) -> tuple:
                return (bool(f["prenom"] or f["nom"]),
                        sum(len(f[c]) for c in ("telephones", "courriels", "adresses", "sites")))
            if poids(fb) > poids(fa):
                (pa, fa), (pb, fb) = (pb, fb), (pa, fa)

            def carte(pid: str, f: dict) -> dict:
                return {"id": pid, "nom": nom_affiche(f), "societe": f["societe"], "groupes": f["groupes"],
                        "telephone": f["telephones"][0].get("affichage") if f["telephones"] else "",
                        "courriel": f["courriels"][0]["valeur"] if f["courriels"] else ""}
            resultat.append({"cle": cle, "score": score, "raisons": raisons,
                             "base": carte(pa, fa), "autre": carte(pb, fb)})
        return sorted(resultat, key=lambda d: (-d["score"], d["base"]["nom"].lower()))

    def ignorer_doublon(self, a: str, b: str) -> dict:
        ignores = set(self.base.etat("doublons_ignores", []))
        ignores.add("|".join(sorted((a, b))))
        self.base.ecrire_etat("doublons_ignores", sorted(ignores))
        return {"ok": True}

    def _societes_a_uniformiser(self, personnes: list[tuple[str, dict]]) -> list[dict]:
        """Noms de société qui désignent sans doute la même entreprise : même nom à la casse
        ou aux accents près (bioMérieux / BIOMERIEUX), mots de l'un contenus dans l'autre
        (Sicaf / Sicaf Cosmétiques), ou presque identiques (faute de frappe)."""
        ignores = {frozenset(g) for g in self.base.etat("societes_ignorees", [])}
        compte: dict[str, int] = {}
        for _, f in personnes:
            if f["societe"]:
                compte[f["societe"]] = compte.get(f["societe"], 0) + 1
        noms = sorted(compte)
        parent = {x: x for x in noms}

        def racine(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        mots = {x: set(cle_texte(x).split()) - MOTS_SOCIETE_VIDES for x in noms}
        for i, a in enumerate(noms):
            for b in noms[i + 1:]:
                ka, kb = cle_texte(a), cle_texte(b)
                ma, mb = mots[a], mots[b]
                court = min((ma, mb), key=len)
                inclus = court and len("".join(court)) >= 4 and (ma <= mb or mb <= ma)
                if ka == kb or inclus or fuzz.ratio(ka, kb) >= 92:
                    parent[racine(a)] = racine(b)
        groupes: dict[str, list[str]] = {}
        for x in noms:
            groupes.setdefault(racine(x), []).append(x)
        res = []
        for variantes in groupes.values():
            if len(variantes) < 2 or frozenset(variantes) in ignores:
                continue
            # Proposition : la variante la plus utilisée, puis la plus courte, puis avec majuscules et minuscules
            proposition = sorted(variantes, key=lambda v: (-compte[v], len(v), v.isupper() or v.islower()))[0]
            res.append({"variantes": [{"nom": v, "nb": compte[v]} for v in
                                      sorted(variantes, key=lambda v: -compte[v])],
                        "proposition": proposition})
        return sorted(res, key=lambda g: g["proposition"].lower())

    def uniformiser_societes(self, variantes: list[str], nom: str) -> dict:
        nom = " ".join(nom.split())
        if not nom:
            raise ErreurCarnet("Indique le nom de société à garder.")
        n = 0
        for p in self.base.lire("SELECT id, fiche FROM personnes WHERE statut = 'verifie' AND fiche IS NOT NULL"):
            if completer(json.loads(p["fiche"]))["societe"] in variantes:
                self.retoucher(p["id"], societe=nom)
                n += 1
        return {"modifies": n}

    def ignorer_societes(self, variantes: list[str]) -> dict:
        ignores = self.base.etat("societes_ignorees", [])
        ignores.append(sorted(set(variantes)))
        self.base.ecrire_etat("societes_ignorees", ignores)
        return {"ok": True}

    def _societes_par_domaine(self) -> dict[str, Counter]:
        """Société déjà connue pour un domaine (chez un autre contact) : la meilleure proposition."""
        par_domaine: dict[str, Counter] = {}
        for _, f in self.base_toutes_fiches():
            if f["societe"]:
                for c in f["courriels"]:
                    d = domaine_pro(c["valeur"])
                    if d:
                        par_domaine.setdefault(d, Counter())[f["societe"]] += 1
        return par_domaine

    @staticmethod
    def _proposer_societe(fiche: dict, par_domaine: dict[str, Counter]) -> tuple[str, str]:
        """(société proposée, explication) d'après les courriels professionnels de la fiche."""
        proposition, origine = "", ""
        for c in fiche.get("courriels", []):
            d = domaine_pro(c["valeur"])
            if d and d in par_domaine:
                return par_domaine[d].most_common(1)[0][0], f"déjà utilisée pour @{d}"
            if d and not proposition:
                proposition, origine = societe_depuis_domaine(d), f"déduite de @{d}"
        return proposition, origine

    def base_toutes_fiches(self) -> list[tuple[str, dict]]:
        res = []
        for p in self.base.lire("SELECT * FROM personnes WHERE fiche IS NOT NULL OR brouillon IS NOT NULL"):
            res.append((p["id"], self._fiche_courante(p, [])))
        return res

    def retoucher(self, pid: str, anniversaire: str | None = None, societe: str | None = None,
                  ajouter: list[str] | None = None, retirer: list[str] | None = None,
                  telephone: str | None = None, type_telephone: str | None = None,
                  types: dict[str, str] | None = None, types_sites: dict[str, str] | None = None,
                  natures: dict[str, str] | None = None) -> dict:
        """Correction rapide depuis l'onglet Revue : appliquée à la fiche validée (et au brouillon
        s'il y en a un), sans repasser par la révision."""
        ligne = self._personne(pid)
        if ligne["statut"] != "verifie" or not ligne["fiche"]:
            raise ErreurCarnet("Ce contact n'est pas encore vérifié : complète-le dans la révision.")
        nouvelles = {}
        for colonne in ("fiche", "brouillon"):
            if not ligne[colonne]:
                continue
            f = completer(json.loads(ligne[colonne]))
            if anniversaire is not None:
                f["anniversaire"] = anniversaire
            if societe is not None:
                f["societe"] = societe
            f["groupes"] = [g for g in f["groupes"] if g not in (retirer or [])]
            f["groupes"] += [g for g in (ajouter or []) if g not in f["groupes"]]
            if telephone and type_telephone:
                for t in f["telephones"]:
                    if t["valeur"] == telephone:
                        t["type"] = type_telephone
            for s in f["sites"]:  # étiquettes des liens (telegram, whatsapp…)
                if types_sites and s["valeur"] in types_sites:
                    s["type"] = types_sites[s["valeur"]]
            for t in f["telephones"]:  # nature mobile / fixe confirmée dans la Revue
                choix = (natures or {}).get(t["valeur"])
                if choix in ("mobile", "fixe"):
                    t["nature_choisie"] = choix
                    if choix == "mobile" and t["type"] in ("domicile", "bureau", "principal", "autre"):
                        t["type"] = "mobile"
                    elif choix == "fixe" and t["type"] in ("mobile", "travail"):
                        t["type"] = "domicile"
            for t in f["telephones"]:  # plusieurs numéros d'un coup (portables perso / travail)
                if types and t["valeur"] in types:
                    t["type"] = types[t["valeur"]]
            try:
                propre = normaliser_fiche(f, self.cfg.region)
            except ValeurInvalide as exc:
                raise ErreurCarnet(str(exc)) from exc
            nouvelles[colonne] = json.dumps(propre, ensure_ascii=False)
        with self.base.transaction() as cx:
            if GROUPE_MOI in (ajouter or []):
                self._retirer_moi_ailleurs(cx, pid)
            cx.execute("UPDATE personnes SET fiche = ?, brouillon = ?, modifie_le = ? WHERE id = ?",
                       (nouvelles["fiche"], nouvelles.get("brouillon"), _iso(maintenant()), pid))
        if natures:  # numéros internationaux confirmés : plus redemandés
            faites = self.base.etat("natures_confirmees", [])
            self.base.ecrire_etat("natures_confirmees", sorted(set(faites) | {f"{pid}|{v}" for v in natures}))
        if types:  # portables triés : la question n'est plus posée pour ce contact
            tries = self.base.etat("portables_tries", [])
            self.base.ecrire_etat("portables_tries", sorted(set(tries) | {pid}))
        if telephone and type_telephone:  # ce numéro ne sera plus redemandé dans la Revue
            confirmes = self.base.etat("telephones_confirmes", [])
            confirmes.append(f"{pid}|{telephone}")
            self.base.ecrire_etat("telephones_confirmes", sorted(set(confirmes)))
        return {"ok": True}

    # ================================================================ export et kit

    def _verifiees(self, groupe: str | None = None) -> list[tuple[str, dict, list[dict]]]:
        res = []
        for p in self.base.lire("SELECT * FROM personnes WHERE statut = 'verifie' AND fiche IS NOT NULL"):
            fiche = regle_proches(completer(json.loads(p["fiche"])))
            if groupe and groupe not in fiche["groupes"]:
                continue
            res.append((p["id"], fiche, self._sources_de(p["id"])))
        return sorted(res, key=lambda x: nom_affiche(x[1]).lower())

    def _vcard(self, pid: str, fiche: dict, sources: list[dict]) -> str:
        uid = next((s["uid"] for s in sources if s["source"] == "icloud" and s["uid"]), None)
        return export.vcard(fiche, uid or f"carnet-{pid}",
                            self.photo(fiche["photo"]) if fiche.get("photo") else None, verifie=True)

    def exporter(self) -> dict:
        personnes = self._verifiees()
        if not personnes:
            raise ErreurCarnet("Aucun contact vérifié pour l'instant : rien à exporter.")
        quand = maintenant()
        nom = f"carnet-{quand:%Y-%m-%d_%H%M}.vcf"
        export.ecrire_atomique(self.cfg.export / nom,
                               "".join(self._vcard(pid, f, s) for pid, f, s in personnes))
        restants = self.base.un("SELECT count(*) AS n FROM personnes WHERE statut != 'verifie'")["n"]
        self.base.ecrire_etat("dernier_export", {"le": _iso(quand), "fichier": nom, "nb": len(personnes)})
        return {"fichier": nom, "nb": len(personnes), "non_verifies": restants}

    def exports(self) -> list[dict]:
        return [{"nom": f.name, "taille": f.stat().st_size}
                for f in sorted(self.cfg.export.glob("*.vcf"), reverse=True)]

    def apercu_kit(self) -> dict:
        verifies = self._verifiees(GROUPE_URGENCE)
        a_reviser = [p for p in self.liste()
                     if p["statut"] == "a_reviser" and GROUPE_URGENCE in p["groupes"]]
        return {"verifies": [nom_affiche(f) for _, f, _ in verifies],
                "a_reviser": [p["nom"] for p in a_reviser],
                "dernier_envoi": self.base.etat("dernier_envoi_kit")}

    def envoyer_kit(self) -> dict:
        if not self.cfg.kit_config:
            raise ErreurCarnet("Le dossier du kit n'est pas monté (CARNET_KIT_CONFIG).")
        if not self.cfg.kit_config.is_dir():
            raise ErreurCarnet(f"Dossier du kit introuvable : {self.cfg.kit_config}. "
                               "Vérifie le volume ${KIT_DATA_DIR}/config dans la stack.")
        personnes = self._verifiees(GROUPE_URGENCE)
        if not personnes:
            raise ErreurCarnet("Aucun contact vérifié dans le groupe Urgence.")
        export.ecrire_atomique(self.cfg.kit_config / self.cfg.kit_vcf,
                               "".join(self._vcard(pid, f, s) for pid, f, s in personnes))
        resultat = {"nb": len(personnes), "fichier": self.cfg.kit_vcf, "regeneration": None}
        if self.cfg.kit_token:
            try:
                r = httpx.post(f"{self.cfg.kit_url}/generer", timeout=300,
                               headers={"Authorization": f"Bearer {self.cfg.kit_token}"})
                resultat["regeneration"] = "ok" if r.status_code < 300 else f"erreur HTTP {r.status_code}"
            except httpx.HTTPError as exc:
                resultat["regeneration"] = f"kit injoignable ({exc.__class__.__name__})"
        else:
            resultat["regeneration"] = "non demandée (KIT_API_TOKEN absent) : le kit se régénérera seul"
        self.base.ecrire_etat("dernier_envoi_kit", {"le": _iso(maintenant()), **resultat})
        return resultat

    # ================================================================ iCloud (V2)

    PLAN_VALIDE = 30 * 60   # une simulation plus ancienne doit être refaite avant d'écrire

    def icloud_etat(self) -> dict:
        plan = self._plan
        if plan and time.monotonic() - plan["instant"] > self.PLAN_VALIDE:
            plan = self._plan = None
        utilisateur = self.cfg.icloud_user
        masque = (utilisateur[:2] + "…" + utilisateur[utilisateur.find("@"):]) if "@" in utilisateur else utilisateur
        return {"configure": bool(self.cfg.icloud_user and self.cfg.icloud_password), "compte": masque,
                "tache": dict(self._tache), "plan": plan["resume"] if plan else None,
                "journal": self.base.etat("journal_icloud", []),
                "veille": {"revision": bool(self.base.etat("veille_revision", False)),
                           "journal": self.base.etat("veille_journal", [])[:30]}}

    def _lancer(self, nom: str, travail) -> dict:
        with self._verrou_icloud:
            if self._tache.get("etat") in ("lecture", "ecriture"):
                raise ErreurCarnet("Une opération iCloud est déjà en cours.")
            self._tache = {"etat": "lecture" if nom in ("simulation", "veille") else "ecriture", "operation": nom,
                           "fait": 0, "total": 0, "message": "Connexion à iCloud…"}

        def executer():
            try:
                travail()
            except (ErreurICloud, ErreurCarnet) as exc:
                self._tache.update(etat="erreur", message=str(exc))
            except Exception as exc:  # noqa: BLE001 — affiché, et détaillé dans le journal du conteneur
                log.exception("Opération iCloud %s", nom)
                self._tache.update(etat="erreur", message=f"Erreur inattendue : {exc}")
        threading.Thread(target=executer, daemon=True, name=f"icloud-{nom}").start()
        return {"ok": True}

    def _dav(self) -> CardDAV:
        return CardDAV(self.cfg.icloud_url, self.cfg.icloud_user, self.cfg.icloud_password,
                       transport=self.transport_icloud)

    def icloud_simuler(self) -> dict:
        return self._lancer("simulation", self._simuler)

    def _simuler(self) -> None:
        dav = self._dav()
        try:
            dav.decouvrir()
            self._tache["message"] = "Lecture des contacts iCloud…"
            brutes = dav.lister()
            self._tache["message"] = "Comparaison avec carnet…"
            cartes = [synchro.analyser(b.href, b.etag, b.texte) for b in brutes]
            self._cache_sauvegardes = None
            self._plan = self._preparer(cartes, dav)
        finally:
            dav.fermer()
        n = len(self._plan["actions"])
        self._tache.update(etat="termine", message=f"Simulation terminée : {n} écriture(s) prévue(s), rien n'a été modifié.")

    def _preparer(self, cartes: list[synchro.Carte], dav: CardDAV) -> dict:
        """Calcule ce qu'il faut écrire dans iCloud, sans rien écrire."""
        contacts = {c.uid: c for c in cartes if not c.groupe}
        groupes_icloud = [c for c in cartes if c.groupe]
        suivi = self.base.etat("icloud_suivi", {})
        uids_de: dict[str, list[str]] = defaultdict(list)
        connus = {v["uid"] for v in suivi.values()}
        for l in self.base.lire("SELECT personne_id, uid FROM sources WHERE source = 'icloud' "
                                "AND uid IS NOT NULL ORDER BY id"):
            connus.add(l["uid"])
            if l["personne_id"]:
                uids_de[l["personne_id"]].append(l["uid"])
        # Fiches iCloud dont l'UID n'est pas celui des exports importés (export fait depuis l'iPhone
        # ou le Mac, sans UID ou avec un autre) : reconnues par leur contenu
        orphelines = [c for c in contacts.values() if c.uid not in connus and not c.uid.startswith("carnet-")]
        reconnues = self._reconnaitre(orphelines)
        par_contenu: dict[str, list[str]] = defaultdict(list)
        for u, (pid_r, exacte) in reconnues.items():
            par_contenu[pid_r].append(u)
            connus.add(u)

        actions, essai, cibles = [], None, {}
        membres: dict[str, set[str]] = defaultdict(set)
        a_supprimer: dict[str, dict] = {}
        for pid, fiche, sources in self._verifiees():
            # Fiche d'origine d'abord : une fiche « carnet-… » en double est retirée au profit de l'originale
            candidats = list(dict.fromkeys(uids_de[pid] + par_contenu[pid]
                                           + ([suivi[pid]["uid"]] if pid in suivi else []) + [f"carnet-{pid}"]))
            presents = [u for u in candidats if u in contacts]
            uid = presents[0] if presents else (uids_de[pid][0] if uids_de[pid] else f"carnet-{pid}")
            cibles[pid] = uid
            distante = contacts.get(uid)
            image = self.photo(fiche["photo"]) if fiche.get("photo") else self._photo_icloud(uid, distante, dav)
            if image is None and (synchro.a_une_photo(distante.texte if distante else None)
                                  or synchro.a_une_photo(self._photos_sauvegardees().get(uid))):
                # iCloud a une photo mais ne la fournit pas (X-IMAGEHASH seul) : celle des exports
                # importés est réécrite, sinon iCloud l'effacerait
                avec = sorted((s for s in sources if s["a_photo"]), key=lambda s: s["uid"] != uid)
                image = self.photo(avec[0]["id"]) if avec else None
            nouvelle = export.vcard(fiche, uid, image)
            texte = synchro.assembler(nouvelle, distante.texte if distante else None)
            nom = nom_affiche(fiche)
            base = {"cible": "contact", "pid": pid, "nom": nom, "uid": uid, "texte": texte,
                    "empreinte_carnet": synchro.empreinte(nouvelle) + VERSION_SYNCHRO}
            if distante:
                action = {**base, "action": "modifier", "href": distante.href, "etag": distante.etag}
                s = suivi.get(pid, {})
                inchange = (s.get("etag") == distante.etag and s.get("empreinte_carnet") == base["empreinte_carnet"]) \
                    or synchro.empreinte(texte) == synchro.empreinte(distante.texte)
                if not inchange:
                    actions.append(action)
            else:
                action = {**base, "action": "creer", "href": dav.href_nouveau(uid), "etag": None,
                          "motif": "supprimé d'iCloud depuis l'import" if candidats else "venu de Gmail ou Outlook"}
                actions.append(action)
            if GROUPE_MOI in fiche["groupes"]:
                essai = action
            for u in presents[1:]:
                d = contacts[u]
                a_supprimer[u] = {"cible": "contact", "action": "supprimer", "pid": pid, "uid": u,
                                  "nom": d.nom or nom, "href": d.href, "etag": d.etag,
                                  "motif": "doublon créé par carnet, la fiche d'origine est gardée"
                                  if u.startswith("carnet-") else f"doublon, fusionné dans {nom}"}
            for g in fiche["groupes"]:
                membres[g].add(uid)
        gardes = set(cibles.values())
        for p in self.base.lire("SELECT id FROM personnes WHERE statut = 'ecarte'"):
            exactes = [u for u in par_contenu[p["id"]] if reconnues[u][1]]  # jamais sur une ressemblance
            for u in uids_de[p["id"]] + exactes + ([suivi[p["id"]]["uid"]] if p["id"] in suivi else []):
                if u in contacts and u not in gardes:
                    d = contacts[u]
                    a_supprimer[u] = {"cible": "contact", "action": "supprimer", "pid": p["id"], "uid": u,
                                      "nom": d.nom, "href": d.href, "etag": d.etag, "motif": "mis de côté"}
        supprimes = set(a_supprimer)

        # Groupes : carnet décide pour les contacts qu'il écrit ; les autres membres restent
        geres = gardes | supprimes
        # Un seul groupe iCloud par nom : les autres exemplaires sont des doublons
        par_nom: dict[str, synchro.Carte] = {}
        en_double = []
        for g in sorted(groupes_icloud, key=lambda g: (-len(g.membres), g.uid)):
            if cle_texte(g.nom) in par_nom:
                en_double.append(g)
            else:
                par_nom[cle_texte(g.nom)] = g
        groupes, non_geres = [], []

        def supprimer_groupe(d: synchro.Carte, motif: str) -> None:
            groupes.append({"cible": "groupe", "action": "supprimer", "nom": d.nom or "(sans nom)", "href": d.href,
                            "etag": d.etag, "motif": motif})
        for nom in groupes_reconnus():
            d = par_nom.pop(cle_texte(nom), None)
            voulus = membres.get(nom, set())
            if d:
                cible = voulus | {m for m in d.membres if m not in geres}
                avant = set(d.membres)
                if not cible:
                    supprimer_groupe(d, "remplacé par Collègues et Clients" if nom == GROUPE_A_CLASSER else "vide")
                elif cible != avant:
                    groupes.append({"cible": "groupe", "action": "modifier", "nom": nom, "href": d.href,
                                    "etag": d.etag, "ajoutes": len(cible - avant), "retires": len(avant - cible),
                                    "texte": synchro.carte_groupe(nom, d.uid, sorted(cible), d.texte)})
            elif voulus:
                uid = f"carnet-groupe-{uuid.uuid5(uuid.NAMESPACE_URL, 'carnet:' + nom)}"
                groupes.append({"cible": "groupe", "action": "creer", "nom": nom, "href": dav.href_nouveau(uid),
                                "etag": None, "ajoutes": len(voulus), "retires": 0,
                                "texte": synchro.carte_groupe(nom, uid, sorted(voulus))})
        # Groupes iCloud absents de carnet, et doublons : supprimés (leurs contacts restent)
        for d in par_nom.values():
            supprimer_groupe(d, "vide" if not d.membres else
                             f"absent de carnet, {len(d.membres)} contact(s) gardé(s) hors groupe")
        for d in en_double:
            supprimer_groupe(d, "groupe en double")

        inconnus = sorted((c for c in contacts.values() if c.uid not in connus and not c.uid.startswith("carnet-")),
                          key=lambda c: c.nom.lower())
        actions = (sorted(actions, key=lambda a: a["nom"].lower()) + groupes
                   + sorted(a_supprimer.values(), key=lambda a: a["nom"].lower()))

        def noms(action: str, cible: str = "contact") -> list:
            return [{k: a.get(k) for k in ("nom", "motif", "pid", "ajoutes", "retires")}
                    for a in actions if a["action"] == action and a["cible"] == cible]
        resume = {
            "le": _iso(maintenant()), "icloud": len(contacts), "groupes_icloud": len(groupes_icloud),
            "creer": noms("creer"), "modifier": noms("modifier"), "supprimer": noms("supprimer"),
            "groupes": [{k: a.get(k) for k in ("nom", "action", "ajoutes", "retires", "motif")} for a in groupes],
            "inconnus": [c.nom or "(sans nom)" for c in inconnus], "groupes_non_geres": sorted(non_geres),
            "identiques": len(cibles) - len(noms("creer")) - len(noms("modifier")),
            "essai": essai["nom"] if essai else None,
            "reconnues": len(reconnues),
        }
        nb_creer, nb_verifies = len(resume["creer"]), len(cibles)
        if nb_creer > 10 and nb_creer > nb_verifies // 10:
            resume["alerte"] = (f"{nb_creer} contacts seraient créés dans iCloud. Vérifie qu'ils n'y sont pas déjà : "
                                "s'ils y sont, ils apparaîtraient en double.")
        essai_groupe = next((g for g in groupes if g["nom"] == GROUPE_MOI and g["action"] != "supprimer"), None)
        return {"instant": time.monotonic(), "actions": actions, "essai": essai, "essai_groupe": essai_groupe,
                "inconnus": inconnus,
                "sauvegarde": "".join((c.brut or c.texte) if (c.brut or c.texte).endswith("\n")
                                      else (c.brut or c.texte) + "\r\n" for c in cartes),
                "resume": resume}

    def _reconnaitre(self, cartes: list[synchro.Carte]) -> dict[str, tuple[str, bool]]:
        """UID iCloud → (contact carnet, reconnu à l'identique ?). Contenu identique à une fiche
        importée (hors photo), sinon même mobile, même courriel ou même nom, avec un seul candidat."""
        if not cartes:
            return {}
        par_empreinte: dict[str, set[str]] = defaultdict(set)
        signatures = []
        for l in self.base.lire("SELECT id, personne_id, donnees FROM sources "
                                "WHERE personne_id IS NOT NULL AND enrichissement = 0"):
            d = json.loads(l["donnees"])
            par_empreinte[_empreinte(d, None)].add(l["personne_id"])
            signatures.append((l["personne_id"], doublons.signature(l["id"], d)))
        res: dict[str, tuple[str, bool]] = {}
        for c in cartes:
            try:
                lues, _ = vcard.lire(c.texte, self.cfg.region)
            except Exception:  # noqa: BLE001 — carte illisible : laissée de côté
                continue
            if not lues:
                continue
            fiche = lues[0].fiche
            pids = par_empreinte.get(_empreinte(fiche, None), set())
            if len(pids) == 1:
                res[c.uid] = (next(iter(pids)), True)
                continue
            sig = doublons.signature(0, fiche)
            proches = {pid for pid, s in signatures if doublons.comparer(sig, s)[0] >= 85}
            if len(proches) == 1:
                res[c.uid] = (next(iter(proches)), False)
        return res

    def _photos_sauvegardees(self) -> dict[str, str]:
        """Dernière photo connue de chaque UID dans les sauvegardes iCloud (la plus récente gagne)."""
        if getattr(self, "_cache_sauvegardes", None) is None:
            photos: dict[str, str] = {}
            for f in sorted(self.cfg.archives.glob("*_icloud-sauvegarde.vcf")):
                for bloc in f.read_text(encoding="utf-8", errors="replace").split("END:VCARD"):
                    if "PHOTO" in bloc or "X-IMAGEHASH" in bloc:
                        c = synchro.analyser("", "", bloc + "END:VCARD")
                        if c.uid:
                            photos[c.uid] = bloc
            self._cache_sauvegardes = photos
        return self._cache_sauvegardes

    def _photo_icloud(self, uid: str, distante, dav: CardDAV) -> tuple[bytes, str] | None:
        """Sans photo dans carnet : celle d'iCloud, incluse dans la carte écrite. iCloud ne donne
        parfois qu'un lien : l'image est alors téléchargée, sinon elle disparaîtrait à l'écriture.
        Une photo perdue lors d'une écriture précédente est reprise dans les sauvegardes."""
        for texte in ((distante.texte if distante else None), self._photos_sauvegardees().get(uid)):
            trouvee = synchro.photo(texte) if texte else None
            if not trouvee:
                continue
            if trouvee[0] == "image":
                return trouvee[1]
            donnees = dav.telecharger(trouvee[1])
            if donnees:
                return donnees, synchro.type_image(donnees)
        return None

    def icloud_ecrire(self, essai: bool) -> dict:
        plan = self._plan
        if not plan or time.monotonic() - plan["instant"] > self.PLAN_VALIDE:
            raise ErreurCarnet("Lance d'abord une simulation (elle reste valable 30 minutes).")
        if essai and not plan["essai"]:
            raise ErreurCarnet("Aucune fiche vérifiée dans le groupe Moi : l'essai écrit ta propre fiche.")
        if not essai and not plan["actions"] and not plan["inconnus"]:
            raise ErreurCarnet("iCloud est déjà à jour : rien à écrire.")
        return self._lancer("essai" if essai else "ecriture", lambda: self._ecrire(plan, essai))

    def _ecrire(self, plan: dict, essai: bool) -> None:
        quand = maintenant()
        # Sauvegarde complète d'iCloud tel qu'il a été lu, avant la moindre écriture
        sauvegarde = f"{quand:%Y-%m-%d_%H%M%S}_icloud-sauvegarde.vcf"
        export.ecrire_atomique(self.cfg.archives / sauvegarde, plan["sauvegarde"])
        # L'essai écrit ta fiche et le groupe Moi (pour vérifier aussi les groupes sur l'iPhone)
        actions = [a for a in (plan["essai"], plan["essai_groupe"]) if a] if essai else plan["actions"]
        self._plan = None  # les ETag lus ne valent plus après écriture
        bilan = {"le": _iso(quand), "essai": essai, "sauvegarde": sauvegarde, "crees": 0, "modifies": 0,
                 "supprimes": 0, "groupes": 0, "conflits": [], "erreurs": [], "importes": 0}
        suivi = self.base.etat("icloud_suivi", {})
        self._tache.update(total=len(actions), fait=0, message="Écriture dans iCloud…")
        dav = self._dav()
        try:
            for a in actions:
                try:
                    if a["action"] == "supprimer":
                        dav.supprimer(a["href"], a["etag"])
                        if a["cible"] == "contact":
                            bilan["supprimes"] += 1
                            if suivi.get(a.get("pid"), {}).get("uid") == a["uid"]:
                                suivi.pop(a["pid"], None)
                        else:
                            bilan["groupes"] += 1
                    else:
                        etag = dav.ecrire(a["href"], a["texte"], a["etag"])
                        if a["cible"] == "contact":
                            bilan["crees" if a["action"] == "creer" else "modifies"] += 1
                            suivi[a["pid"]] = {"uid": a["uid"], "href": a["href"], "etag": etag,
                                               "empreinte_carnet": a["empreinte_carnet"]}
                        else:
                            bilan["groupes"] += 1
                except Conflit:
                    bilan["conflits"].append(a["nom"])
                except ErreurICloud as exc:
                    bilan["erreurs"].append(f"{a['nom']} : {exc}")
                    if a.get("texte"):
                        # Carte refusée gardée pour le diagnostic (dossier archives/icloud-refus)
                        refus = self.cfg.archives / "icloud-refus"
                        refus.mkdir(exist_ok=True)
                        nom_f = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in a["nom"])[:60]
                        (refus / f"{quand:%Y-%m-%d_%H%M%S}_{nom_f}.vcf").write_text(a["texte"], encoding="utf-8")
                    if "refuse la connexion" in str(exc):
                        break
                self._tache["fait"] += 1
        finally:
            dav.fermer()
            self.base.ecrire_etat("icloud_suivi", suivi)
        if not essai and plan["inconnus"]:
            # Contacts créés dans iCloud sans carnet : importés pour être révisés
            self._tache["message"] = "Import des contacts ajoutés dans iCloud…"
            nom = f"icloud-nouveaux-{quand:%Y-%m-%d_%H%M%S}.vcf"
            (self.cfg.depot / nom).write_text("".join(
                c.texte if c.texte.endswith("\n") else c.texte + "\r\n" for c in plan["inconnus"]), encoding="utf-8")
            try:
                bilan["importes"] = self.importer(nom, "icloud")["ajoutes"]
            except ErreurCarnet as exc:
                bilan["erreurs"].append(f"Import des nouveaux contacts : {exc}")
        journal = [bilan] + self.base.etat("journal_icloud", [])
        self.base.ecrire_etat("journal_icloud", journal[:50])
        self.base.ecrire_etat("derniere_ecriture_icloud", bilan)
        ecrits = bilan["crees"] + bilan["modifies"] + bilan["supprimes"] + bilan["groupes"]
        etat = "erreur" if bilan["erreurs"] else "termine"
        self._tache.update(etat=etat, message=(f"{'Essai' if essai else 'Écriture'} terminé : {ecrits} écriture(s)"
                                               + (f", {len(bilan['conflits'])} conflit(s)" if bilan["conflits"] else "")
                                               + (f", {len(bilan['erreurs'])} erreur(s)" if bilan["erreurs"] else "")
                                               + "."))

    # ================================================================ LinkedIn par l'API (portabilité des données)

    LINKEDIN_API = "https://api.linkedin.com/rest/memberSnapshotData"
    COLONNES_LINKEDIN = ["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"]

    # Connexion OAuth faite par carnet lui-même (quand l'outil de jeton de LinkedIn échoue).
    # L'adresse de retour n'a pas besoin d'exister : LinkedIn y renvoie le navigateur avec
    # ?code=…&state=… dans la barre d'adresse, et il suffit de coller cette adresse dans carnet.
    def linkedin_autorisation(self) -> dict:
        if not (self.cfg.linkedin_client_id and self.cfg.linkedin_client_secret):
            raise ErreurCarnet("Renseigne CARNET_LINKEDIN_CLIENT_ID et CARNET_LINKEDIN_CLIENT_SECRET "
                               "(onglet Auth de l'app LinkedIn) dans les variables de la stack.")
        etat = secrets.token_urlsafe(24)
        self._etats_linkedin = {k: v for k, v in getattr(self, "_etats_linkedin", {}).items()
                                if v > time.monotonic()}
        self._etats_linkedin[etat] = time.monotonic() + 15 * 60
        parametres = {"response_type": "code", "client_id": self.cfg.linkedin_client_id,
                      "redirect_uri": self.cfg.linkedin_redirect, "state": etat,
                      "scope": "r_dma_portability_self_serve"}
        return {"url": "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(parametres),
                "retour": self.cfg.linkedin_redirect}

    def linkedin_reessayer(self) -> dict:
        if not getattr(self, "_jeton_linkedin", None):
            raise ErreurCarnet("Plus de connexion LinkedIn en mémoire : clique sur « Se connecter à LinkedIn ».")
        return self.linkedin_api(self._jeton_linkedin)

    def linkedin_code(self, adresse: str) -> dict:
        """Adresse de retour collée (…?code=…&state=…) → jeton → import des relations."""
        requete = parse_qs(urlsplit((adresse or "").strip()).query)
        if "error" in requete:
            raise ErreurCarnet("LinkedIn a refusé : " + (requete.get("error_description") or requete["error"])[0])
        code, etat = (requete.get("code") or [""])[0], (requete.get("state") or [""])[0]
        if not code:
            raise ErreurCarnet("Pas de « code= » dans cette adresse : colle l'adresse complète de la page "
                               "sur laquelle LinkedIn t'a renvoyé.")
        if getattr(self, "_etats_linkedin", {}).pop(etat, 0) < time.monotonic():
            raise ErreurCarnet("Lien expiré ou déjà utilisé : clique de nouveau sur « Se connecter à LinkedIn ».")
        try:
            with httpx.Client(timeout=60, transport=getattr(self, "transport_linkedin", None)) as client:
                r = client.post("https://www.linkedin.com/oauth/v2/accessToken", data={
                    "grant_type": "authorization_code", "code": code, "redirect_uri": self.cfg.linkedin_redirect,
                    "client_id": self.cfg.linkedin_client_id, "client_secret": self.cfg.linkedin_client_secret})
        except httpx.HTTPError as exc:
            raise ErreurCarnet(f"LinkedIn injoignable ({exc.__class__.__name__}).") from exc
        if r.status_code >= 400 or "access_token" not in r.text:
            raise ErreurCarnet(f"Échange du code refusé par LinkedIn : {' '.join(r.text.split())[:200]}")
        return self.linkedin_api(r.json()["access_token"])

    def linkedin_api(self, jeton: str) -> dict:
        """Relations LinkedIn lues par l'API de portabilité (membres UE), avec un jeton créé dans
        l'outil OAuth de LinkedIn (portée r_dma_portability_self_serve). Le jeton sert une fois
        et n'est jamais enregistré. Les relations passent ensuite par l'import LinkedIn habituel."""
        jeton = (jeton or "").strip()
        if not jeton:
            raise ErreurCarnet("Colle le jeton d'accès LinkedIn.")
        entetes = {"Authorization": f"Bearer {jeton}", "LinkedIn-Version": "202312",
                   "X-Restli-Protocol-Version": "2.0.0"}
        lignes: list[dict] = []
        with httpx.Client(timeout=60, transport=getattr(self, "transport_linkedin", None)) as client:
            for page in range(500):
                try:
                    r = client.get(self.LINKEDIN_API, headers=entetes,
                                   params={"q": "criteria", "domain": "CONNECTIONS", "start": page})
                except httpx.HTTPError as exc:
                    raise ErreurCarnet(f"LinkedIn injoignable ({exc.__class__.__name__}).") from exc
                if r.status_code in (401, 403):
                    raise ErreurCarnet("LinkedIn refuse le jeton : il a expiré ou n'a pas la portée "
                                       "r_dma_portability_self_serve. Recrée-le dans l'outil OAuth.")
                if r.status_code == 404 or (r.status_code >= 400 and "No data found" in r.text):
                    break  # fin des pages
                if r.status_code >= 400:
                    raise ErreurCarnet(f"LinkedIn a répondu {r.status_code} : {' '.join(r.text.split())[:200]}")
                elements = r.json().get("elements") or []
                if isinstance(elements, dict):
                    elements = [elements]
                donnees = [ligne for e in elements if e.get("snapshotDomain") == "CONNECTIONS"
                           for ligne in (e.get("snapshotData") or [])]
                if not donnees:
                    break
                lignes += donnees
        if not lignes:
            # Après la première autorisation, LinkedIn prépare les données (~20 à 30 min pour CONNECTIONS)
            # et répond « No data found » d'ici là. Le jeton est gardé en mémoire pour réessayer.
            self._jeton_linkedin = jeton
            raise ErreurCarnet("LinkedIn prépare encore tes données : c'est normal juste après la première "
                               "autorisation (environ 30 minutes). Réessaie plus tard avec « Réessayer ».")
        self._jeton_linkedin = None
        tampon = io.StringIO()
        ecrivain = csv.DictWriter(tampon, fieldnames=self.COLONNES_LINKEDIN, extrasaction="ignore")
        ecrivain.writeheader()
        for ligne in lignes:
            ecrivain.writerow({k: str(ligne.get(k, "") or "") for k in self.COLONNES_LINKEDIN})
        nom = f"linkedin-api-{maintenant():%Y-%m-%d_%H%M%S}.csv"
        (self.cfg.depot / nom).write_text(tampon.getvalue(), encoding="utf-8")
        return {"nom": nom, **self.importer(nom, "linkedin")}

    # ================================================================ veille iCloud (V3)

    def veiller(self) -> dict:
        """Relit iCloud et compare aux fiches validées (bouton « Vérifier maintenant » et 3 h)."""
        return self._lancer("veille", self._veiller)

    def veille_mode(self, revision: bool) -> dict:
        self.base.ecrire_etat("veille_revision", bool(revision))
        return {"revision": bool(revision)}

    def _ecarts(self, fiche: dict, texte: str) -> list[dict]:
        """Différences de fond entre la fiche validée et la carte iCloud (la forme est ignorée :
        ordre des lignes, données Siri, photo, types recalculés par les règles de groupe)."""
        try:
            lues, _ = vcard.lire(texte, self.cfg.region)
        except Exception:  # noqa: BLE001 — carte illisible : signalée comme modifiée
            return [{"champ": "carte", "carnet": "", "iphone": "illisible"}]
        if not lues:
            return [{"champ": "carte", "carnet": "", "iphone": "illisible"}]
        iphone = completer(nettoyer(completer(lues[0].fiche)))
        carnet_f = completer(fiche)
        ecarts = []
        for champ in ("prenom", "nom", "surnom", "societe", "fonction", "anniversaire"):
            a, b = (carnet_f[champ] or "").strip(), (iphone[champ] or "").strip()
            if cle_texte(a) != cle_texte(b):
                ecarts.append({"champ": champ, "carnet": a, "iphone": b})
        if " ".join(note(carnet_f["notes"]).split()) != " ".join(note(iphone["notes"]).split()):
            ecarts.append({"champ": "notes", "carnet": carnet_f["notes"][:80], "iphone": iphone["notes"][:80]})
        for champ in CHAMPS_MULTIPLES:
            def valeurs(f: dict) -> dict:
                return {CLES[champ](x): x for x in f[champ] if CLES[champ](x)}
            a, b = valeurs(carnet_f), valeurs(iphone)
            if set(a) != set(b):
                def texte_de(x: dict) -> str:
                    return x.get("affichage") or x.get("valeur") or ", ".join(
                        v for k, v in x.items() if k in ("rue", "cp", "ville") and v)
                ecarts.append({"champ": champ,
                               "carnet": ", ".join(texte_de(a[k]) for k in sorted(set(a) - set(b))),
                               "iphone": ", ".join(texte_de(b[k]) for k in sorted(set(b) - set(a)))})
        return ecarts

    def _veiller(self) -> None:
        quand = maintenant()
        entree = {"le": _iso(quand), "revision": bool(self.base.etat("veille_revision", False)),
                  "lus": 0, "forme": 0, "modifies": [], "nouveaux": [], "supprimes": [], "importes": 0,
                  "erreur": None}
        try:
            dav = self._dav()
            try:
                self._tache["message"] = "Veille : lecture d'iCloud…"
                brutes = dav.lister()
            finally:
                dav.fermer()
            cartes = [synchro.analyser(b.href, b.etag, b.texte) for b in brutes]
            contacts = {c.uid: c for c in cartes if not c.groupe}
            entree["lus"] = len(contacts)
            self._tache["message"] = "Veille : comparaison avec carnet…"
            suivi = self.base.etat("icloud_suivi", {})
            uid_pid: dict[str, str] = {}
            connus: set[str] = set()
            for l in self.base.lire("SELECT personne_id, uid FROM sources WHERE source = 'icloud' AND uid IS NOT NULL"):
                connus.add(l["uid"])
                if l["personne_id"]:
                    uid_pid[l["uid"]] = l["personne_id"]
            for pid, info in suivi.items():
                uid_pid[info["uid"]] = pid
                connus.add(info["uid"])
            orphelines = [c for u, c in contacts.items() if u not in uid_pid and not u.startswith("carnet-")]
            for u, (pid, _exacte) in self._reconnaitre(orphelines).items():
                uid_pid[u] = pid
            verifiees = {pid: fiche for pid, fiche, _ in self._verifiees()}
            a_importer = []
            for u, c in sorted(contacts.items(), key=lambda x: x[1].nom.lower()):
                pid = uid_pid.get(u) or (u[len("carnet-"):] if u.startswith("carnet-") else None)
                if pid is None:
                    entree["nouveaux"].append({"nom": c.nom or "(sans nom)", "uid": u})
                    a_importer.append(c)
                    continue
                fiche = verifiees.get(pid)
                if fiche is None:  # à réviser ou mis de côté : pas surveillé
                    continue
                info = suivi.get(pid)
                if info and info.get("uid") == u and info.get("etag") and info["etag"] == c.etag:
                    continue
                ecarts = self._ecarts(fiche, c.texte)
                if ecarts:
                    entree["modifies"].append({"pid": pid, "nom": nom_affiche(fiche), "ecarts": ecarts})
                    a_importer.append(c)
                else:
                    entree["forme"] += 1
                    if info and info.get("uid") == u:
                        info["etag"] = c.etag  # simple réécriture par iCloud : plus recomparée
            for pid, info in suivi.items():
                if pid in verifiees and info["uid"] not in contacts:
                    entree["supprimes"].append({"pid": pid, "nom": nom_affiche(verifiees[pid])})
            self.base.ecrire_etat("icloud_suivi", suivi)
            if entree["revision"] and a_importer:
                # Mode révision : les cartes changées passent par l'import (remise à réviser)
                nom = f"icloud-veille-{quand:%Y-%m-%d_%H%M%S}.vcf"
                (self.cfg.depot / nom).write_text("".join(
                    c.texte if c.texte.endswith("\n") else c.texte + "\r\n" for c in a_importer), encoding="utf-8")
                try:
                    r = self.importer(nom, "icloud")
                    entree["importes"] = r["ajoutes"] + r["mises_a_jour"]
                except ErreurCarnet as exc:
                    entree["erreur"] = f"Import des changements : {exc}"
        except (ErreurICloud, ErreurCarnet) as exc:
            entree["erreur"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Veille iCloud")
            entree["erreur"] = f"Erreur inattendue : {exc}"
        entree["modifies"] = entree["modifies"][:300]
        journal = [entree] + self.base.etat("veille_journal", [])
        self.base.ecrire_etat("veille_journal", journal[:30])
        if entree["erreur"]:
            self._tache.update(etat="erreur", message=f"Veille : {entree['erreur']}")
        else:
            self._tache.update(etat="termine", message=(
                f"Veille : {len(entree['modifies'])} modifié(s), {len(entree['nouveaux'])} nouveau(x), "
                f"{len(entree['supprimes'])} supprimé(s) sur l'iPhone"
                + (f", {entree['importes']} remis en révision." if entree["revision"] else " (mode journal)."))
            )

    # ================================================================ liaisons Immich et Treemich (V3)

    def _immich(self) -> Immich:
        return Immich(self.cfg.immich_url, self.cfg.immich_cle, transport=getattr(self, "transport_immich", None))

    def _treemich(self) -> Treemich:
        """Session Treemich gardée entre les appels (connexions limitées par Treemich)."""
        cle = (self.cfg.treemich_url, self.cfg.treemich_email, self.cfg.treemich_password,
               id(getattr(self, "transport_treemich", None)))
        if getattr(self, "_session_treemich", (None, None))[0] != cle:
            self._session_treemich = (cle, Treemich(self.cfg.treemich_url, self.cfg.treemich_email,
                                                    self.cfg.treemich_password,
                                                    transport=getattr(self, "transport_treemich", None)))
        return self._session_treemich[1]

    def _donnees_liens(self, rafraichir: bool = False) -> dict:
        """Personnes Immich et Treemich (gardées 10 minutes en mémoire)."""
        cache = getattr(self, "_cache_liens", None)
        if cache and not rafraichir and time.monotonic() - cache["t"] < 600:
            return cache
        d = {"t": time.monotonic(), "immich": [], "treemich": [], "relations": [], "erreurs": []}
        if self.cfg.immich_cle:
            try:
                im = self._immich()
                try:
                    d["immich"] = im.personnes()
                finally:
                    im.fermer()
            except ErreurLien as exc:
                d["erreurs"].append(str(exc))
        if self.cfg.treemich_email:
            try:
                tm = self._treemich()
                try:
                    d["treemich"], d["relations"] = tm.personnes(), tm.relations()
                finally:
                    tm.fermer()
            except ErreurLien as exc:
                d["erreurs"].append(str(exc))
        self._cache_liens = d
        return d

    def liaisons(self, rafraichir: bool = False) -> dict:
        """Contacts vérifiés liés à Immich / Treemich, et propositions à valider."""
        d = self._donnees_liens(rafraichir)
        liens = self.base.etat("liaisons", {})
        refus = set(self.base.etat("liaisons_refusees", []))
        immich_par_id = {p["id"]: p for p in d["immich"]}
        tree_par_id = {p["id"]: p for p in d["treemich"]}
        tree_par_immich = {p["immich"]: p for p in d["treemich"] if p["immich"]}
        pris_immich = {l.get("immich") for l in liens.values() if l.get("immich")}
        pris_tree = {l.get("treemich") for l in liens.values() if l.get("treemich")}

        def index(personnes: list[dict]) -> dict[str, list[dict]]:
            res: dict[str, list[dict]] = defaultdict(list)
            for p in personnes:
                res[cle_texte(p["nom"])].append(p)
            return res
        immich_noms, tree_noms = index(d["immich"]), index(d["treemich"])
        liees, propositions = [], []
        for pid, fiche, _ in self._verifiees():
            nom = nom_affiche(fiche)
            lien = liens.get(pid, {})
            ligne = {"pid": pid, "nom": nom, "groupes": fiche["groupes"], "anniversaire": fiche["anniversaire"]}
            if lien:
                im, tm = immich_par_id.get(lien.get("immich") or ""), tree_par_id.get(lien.get("treemich") or "")
                mots = sorted(cle_texte(f"{fiche['prenom']} {fiche['nom']}").split())
                ecart = any(x and sorted(cle_texte(x["nom"]).split()) != mots for x in (im, tm))
                liees.append({**ligne, "immich": im and {"id": im["id"], "nom": im["nom"]},
                              "treemich": tm and {"id": tm["id"], "nom": tm["nom"]},
                              "ecart_nom": ecart and bool(fiche["prenom"] or fiche["nom"]),
                              "nom_immich_propose": self._nom_pour_immich(fiche)})
                continue
            cles = {cle_texte(f"{fiche['prenom']} {fiche['nom']}"), cle_texte(fiche["surnom"] or "")} - {""}
            candidats = [p for c in cles for p in immich_noms.get(c, [])
                         if p["id"] not in pris_immich and f"{pid}|{p['id']}" not in refus]
            if not candidats:  # nom presque identique (accent, tiret, ordre)
                candidats = [p for p in d["immich"] if p["id"] not in pris_immich and f"{pid}|{p['id']}" not in refus
                             and any(fuzz.token_sort_ratio(c, cle_texte(p["nom"])) >= 92 for c in cles)]
            tree = None
            if len(candidats) == 1 and candidats[0]["id"] in tree_par_immich:
                tree = tree_par_immich[candidats[0]["id"]]
            else:
                t = [p for c in cles for p in tree_noms.get(c, []) if p["id"] not in pris_tree]
                tree = t[0] if len(t) == 1 else None
            if not candidats and not tree:
                continue
            annif = fiche["anniversaire"]
            def date_compatible(p: dict) -> bool:
                return not (annif and p["naissance"] and len(annif) == 10 and p["naissance"][:10] != annif)
            exacte = (len(candidats) == 1 and cle_texte(candidats[0]["nom"]) in cles
                      and date_compatible(candidats[0]))
            propositions.append({**ligne, "exacte": exacte,
                                 "immich": [{"id": p["id"], "nom": p["nom"], "naissance": p["naissance"]}
                                            for p in candidats[:5]],
                                 "treemich": tree and {"id": tree["id"], "nom": tree["nom"]}})
        propositions.sort(key=lambda x: (not x["exacte"], x["nom"].lower()))
        verifiees = {pid: f for pid, f, _ in self._verifiees()}
        return {"immich": bool(self.cfg.immich_cle), "treemich": bool(self.cfg.treemich_email),
                "erreurs": d["erreurs"], "liees": liees, "propositions": propositions,
                "a_formater": self.immich_a_formater(d, liens, verifiees),
                "nb_immich": len(d["immich"]), "nb_treemich": len(d["treemich"]),
                "dernier_passage": self.base.etat("liens_journal", [None])[0]}

    def valider_liaisons(self, liaisons: list[dict]) -> dict:
        liens = self.base.etat("liaisons", {})
        for l in liaisons:
            if l.get("immich") or l.get("treemich"):
                liens[l["pid"]] = {"immich": l.get("immich"), "treemich": l.get("treemich"), "le": _iso(maintenant())}
        self.base.ecrire_etat("liaisons", liens)
        pids = [l["pid"] for l in liaisons]
        return self._lancer("liens", lambda: self._appliquer_liens(pids))

    @staticmethod
    def _nom_pour_immich(fiche: dict) -> str:
        """Même format partout : « Prénom NOM », comme dans carnet."""
        return " ".join(x for x in (fiche["prenom"], fiche["nom"]) if x)

    @staticmethod
    def _format_prenom_nom(nom: str) -> str:
        """Nom Immich sans contact lié : « jean dupont » / « Jean Dupont » → « Jean DUPONT ».
        Un mot déjà en majuscules marque le début du nom de famille, sinon c'est le dernier mot."""
        mots = nom.split()
        if len(mots) < 2:
            return formater_prenom(nom)
        debut = next((i for i, m in enumerate(mots) if i > 0 and m.isupper() and len(m) > 1), len(mots) - 1)
        return f"{formater_prenom(' '.join(mots[:debut]))} {formater_nom(' '.join(mots[debut:]))}"

    def immich_a_formater(self, d: dict, liens: dict, verifiees: dict) -> list[dict]:
        """Personnes Immich dont le nom n'est pas au format « Prénom NOM »."""
        par_immich = {l["immich"]: pid for pid, l in liens.items() if l.get("immich")}
        res = []
        for p in d["immich"]:
            pid = par_immich.get(p["id"])
            propose = self._nom_pour_immich(verifiees[pid]) if pid in verifiees else self._format_prenom_nom(p["nom"])
            if propose and propose != p["nom"]:
                res.append({"id": p["id"], "nom": p["nom"], "propose": propose, "lie": pid in verifiees})
        return sorted(res, key=lambda x: (not x["lie"], x["nom"].lower()))

    def renommer_immich(self, immich_id: str, nom: str) -> dict:
        """Renomme une personne Immich (et la personne Treemich qui lui correspond)."""
        nom = " ".join((nom or "").split())
        if not nom:
            raise ErreurCarnet("Nom vide.")
        immich = self._immich()
        try:
            immich.renommer(immich_id, nom)
        finally:
            immich.fermer()
        d = self._donnees_liens()
        liens = self.base.etat("liaisons", {})
        tid = next((l.get("treemich") for l in liens.values() if l.get("immich") == immich_id and l.get("treemich")),
                   None) or next((p["id"] for p in d["treemich"] if p["immich"] == immich_id), None)
        if tid and self.cfg.treemich_email:
            mots = nom.split()
            debut = next((i for i, m in enumerate(mots) if i > 0 and m.isupper() and len(m) > 1), len(mots) - 1)
            tm = self._treemich()
            try:
                tm.renommer(tid, " ".join(mots[:debut]), " ".join(mots[debut:]))
            finally:
                tm.fermer()
        self._cache_liens = None
        return {"nom": nom}

    def corriger_nom(self, pid: str, garder: str) -> dict:
        """Écart d'orthographe entre carnet et Immich / Treemich : on garde l'une des deux."""
        lien = self.base.etat("liaisons", {}).get(pid)
        if not lien:
            raise ErreurCarnet("Ce contact n'est pas lié.")
        fiche = completer(json.loads(self._personne(pid)["fiche"] or "{}"))
        d = self._donnees_liens(rafraichir=True)
        im = next((p for p in d["immich"] if p["id"] == lien.get("immich")), None)
        if garder == "immich":
            if not im:
                raise ErreurCarnet("Personne Immich introuvable.")
            mots = im["nom"].split()
            n = max(1, min(len(fiche["prenom"].split()) or 1, len(mots) - 1))  # Immich écrit « Prénom Nom »
            fiche["prenom"], fiche["nom"] = formater_prenom(" ".join(mots[:n])), formater_nom(" ".join(mots[n:]))
            self._remplacer_fiche_validee(pid, fiche)
            prenom, nom = fiche["prenom"], fiche["nom"]
        elif garder == "carnet":
            prenom, nom = fiche["prenom"], fiche["nom"]
            if im:
                immich = self._immich()
                try:
                    immich.renommer(im["id"], " ".join(x for x in (prenom, nom) if x))
                finally:
                    immich.fermer()
        else:
            raise ErreurCarnet("Choix inconnu.")
        if lien.get("treemich") and self.cfg.treemich_email:  # Treemich prend l'orthographe retenue
            tm = self._treemich()
            try:
                tm.renommer(lien["treemich"], prenom, nom)
            finally:
                tm.fermer()
        self._cache_liens = None
        return {"nom": " ".join(x for x in (prenom, nom) if x)}

    def refuser_liaison(self, pid: str, immich: str) -> dict:
        refus = set(self.base.etat("liaisons_refusees", []))
        refus.add(f"{pid}|{immich}")
        self.base.ecrire_etat("liaisons_refusees", sorted(refus))
        return {"ok": True}

    def delier(self, pid: str) -> dict:
        liens = self.base.etat("liaisons", {})
        liens.pop(pid, None)
        self.base.ecrire_etat("liaisons", liens)
        return {"ok": True}

    def actualiser_liens(self) -> dict:
        return self._lancer("liens", lambda: self._appliquer_liens(None))

    def _source_immich(self, cx, pid: str, immich_id: str, image: tuple[bytes, str]) -> int:
        """Visage Immich rangé comme une fiche source « Immich » (complément) du contact."""
        imp = cx.execute("SELECT id FROM imports WHERE source = 'immich'").fetchone()
        if imp:
            import_id = imp["id"]
        else:
            quand = maintenant()
            import_id = cx.execute(
                "INSERT INTO imports(source, nom_fichier, sha256, archive, importe_le, expire_le, nb_lus) "
                "VALUES('immich', 'Immich', 'immich', NULL, ?, '9999-12-31T00:00:00+00:00', 0)",
                (_iso(quand),)).lastrowid
        existante = cx.execute("SELECT id FROM sources WHERE source = 'immich' AND personne_id = ?", (pid,)).fetchone()
        emp = hashlib.sha256(image[0]).hexdigest()
        if existante:
            cx.execute("UPDATE sources SET uid = ?, empreinte = ?, photo = ?, photo_type = ? WHERE id = ?",
                       (immich_id, emp, image[0], image[1], existante["id"]))
            return existante["id"]
        return cx.execute(
            "INSERT INTO sources(import_id, source, uid, empreinte, donnees, photo, photo_type, enrichissement, personne_id) "
            "VALUES(?, 'immich', ?, ?, ?, ?, ?, 1, ?)",
            (import_id, immich_id, emp, json.dumps(fiche_vide()), image[0], image[1], pid)).lastrowid

    def _appliquer_liens(self, pids: list[str] | None) -> None:
        """Photos depuis Immich, relations depuis Treemich, pour les contacts liés.
        Les ajouts sans conflit vont directement dans la fiche validée (iCloud suivra à la
        prochaine écriture) ; une relation qui contredit un nom associé saisi va dans la Revue."""
        d = self._donnees_liens(rafraichir=True)
        liens = self.base.etat("liaisons", {})
        cibles = {p: l for p, l in liens.items() if pids is None or p in pids}
        bilan = {"le": _iso(maintenant()), "photos": 0, "relations": 0, "a_revoir": 0, "erreurs": list(d["erreurs"])}
        self._tache.update(total=len(cibles), fait=0, message="Liaisons : photos et relations…")
        verifiees = {pid: f for pid, f, _ in self._verifiees()}
        tid_vers_pid = {l["treemich"]: p for p, l in liens.items() if l.get("treemich")}
        genres = {p["id"]: p["genre"] for p in d["treemich"]}
        noms_tree = {p["id"]: p["nom"] for p in d["treemich"]}
        a_revoir = self.base.etat("relations_treemich", {})
        gardees = self.base.etat("relations_gardees", {})   # « Garder le contact » : pas redemandé
        portraits_hd = {p for p, x in self.base.etat("photos_hd", {}).items() if x.get("immich") == (liens.get(p) or {}).get("immich")}
        immich = None
        try:
            if self.cfg.immich_cle and any(l.get("immich") for l in cibles.values()):
                immich = self._immich()
            for pid, lien in cibles.items():
                self._tache["fait"] += 1
                fiche = verifiees.get(pid)
                if fiche is None:
                    continue
                maj = False
                if immich and lien.get("immich") and pid not in portraits_hd:   # un portrait HD n'est pas remplacé par la vignette
                    try:
                        image = immich.visage(lien["immich"])
                    except ErreurLien as exc:
                        bilan["erreurs"].append(str(exc))
                        image = None
                    if image:
                        with self.base.transaction() as cx:
                            sid = self._source_immich(cx, pid, lien["immich"], image)
                        ancienne = self.photo(fiche["photo"]) if fiche.get("photo") else None
                        if fiche.get("photo") != sid or not ancienne or ancienne[0] != image[0]:
                            fiche["photo"] = sid
                            maj = True
                            bilan["photos"] += 1
                if lien.get("treemich") and d["treemich"]:
                    voulues = [{"valeur": nom_affiche(verifiees[tid_vers_pid[t]]) if tid_vers_pid.get(t) in verifiees
                                else noms_tree.get(t, ""), "type": typ}
                               for t, typ in relations_de(lien["treemich"], d["relations"], genres) if noms_tree.get(t)]
                    existantes = fiche["noms_associes"]
                    noms_existants = {cle_texte(x["valeur"]) for x in existantes}
                    ajouts = [v for v in voulues if cle_texte(v["valeur"]) not in noms_existants]
                    if ajouts:
                        fiche["noms_associes"] = existantes + ajouts
                        maj = True
                        bilan["relations"] += len(ajouts)
                    cles_voulues = {(cle_texte(v["valeur"]), v["type"]) for v in voulues}
                    noms_voulus = {cle_texte(v["valeur"]) for v in voulues}
                    contradictions = [x for x in existantes if x.get("type") in TYPES_FAMILLE and (
                        cle_texte(x["valeur"]) not in noms_voulus
                        or (cle_texte(x["valeur"]), x["type"]) not in cles_voulues)]
                    signature = hashlib.sha256(json.dumps(sorted(cles_voulues), ensure_ascii=False).encode()).hexdigest()
                    if contradictions and gardees.get(pid) != signature:
                        a_revoir[pid] = {"treemich": voulues, "contact": contradictions, "signature": signature}
                        bilan["a_revoir"] += 1
                    else:
                        a_revoir.pop(pid, None)
                if maj:
                    self._remplacer_fiche_validee(pid, fiche)
        finally:
            if immich:
                immich.fermer()
        self.base.ecrire_etat("relations_treemich", a_revoir)
        journal = [bilan] + self.base.etat("liens_journal", [])
        self.base.ecrire_etat("liens_journal", journal[:30])
        self._tache.update(etat="erreur" if bilan["erreurs"] else "termine", message=(
            f"Liaisons : {bilan['photos']} photo(s), {bilan['relations']} relation(s) ajoutée(s)"
            + (f", {bilan['a_revoir']} à revoir dans la Revue" if bilan["a_revoir"] else "")
            + (f" ; {bilan['erreurs'][0]}" if bilan["erreurs"] else "") + "."))

    def _remplacer_fiche_validee(self, pid: str, fiche: dict) -> None:
        """Met à jour la fiche validée (et le brouillon en cours, s'il existe) sans la rouvrir."""
        propre = normaliser_fiche(fiche, self.cfg.region)
        with self.base.transaction() as cx:
            ligne = cx.execute("SELECT brouillon FROM personnes WHERE id = ?", (pid,)).fetchone()
            cx.execute("UPDATE personnes SET fiche = ?, modifie_le = ? WHERE id = ?",
                       (json.dumps(propre, ensure_ascii=False), _iso(maintenant()), pid))
            if ligne and ligne["brouillon"]:
                b = completer(json.loads(ligne["brouillon"]))
                b["photo"] = propre["photo"]
                b["noms_associes"] = b["noms_associes"] + [x for x in propre["noms_associes"]
                                                           if cle_texte(x["valeur"]) not in
                                                           {cle_texte(y["valeur"]) for y in b["noms_associes"]}]
                cx.execute("UPDATE personnes SET brouillon = ? WHERE id = ?", (json.dumps(b, ensure_ascii=False), pid))

    def trancher_relations(self, pid: str, choix: str) -> dict:
        """Revue « relations Treemich » : prendre l'arbre, ou garder le contact tel quel."""
        a_revoir = self.base.etat("relations_treemich", {})
        item = a_revoir.pop(pid, None)
        if not item:
            raise ErreurCarnet("Plus de différence à trancher pour ce contact.")
        if choix != "treemich":  # tant que l'arbre ne change pas, la question n'est plus posée
            gardees = self.base.etat("relations_gardees", {})
            gardees[pid] = item.get("signature")
            self.base.ecrire_etat("relations_gardees", gardees)
        if choix == "treemich":
            ligne = self._personne(pid)
            fiche = completer(json.loads(ligne["fiche"]))
            fiche["noms_associes"] = [x for x in fiche["noms_associes"] if x.get("type") not in TYPES_FAMILLE] \
                + item["treemich"]
            self._remplacer_fiche_validee(pid, fiche)
        self.base.ecrire_etat("relations_treemich", a_revoir)
        return {"ok": True}

    def visage_immich(self, immich_id: str) -> tuple[bytes, str] | None:
        im = self._immich()
        try:
            return im.visage(immich_id)
        finally:
            im.fermer()

    # ================================================================ portraits HD depuis Immich

    PORTRAITS_PAR_PERSONNE = 120   # photos les plus récentes examinées par personne (1er passage)
    PORTRAITS_A_MESURER = 8        # meilleurs visages (par taille) dont la netteté est mesurée
    PORTRAITS_GARDES = 6           # choix proposés par contact
    PORTRAITS_JOURS = 30           # recherche automatique une fois par mois (pendant la tâche de nuit)

    def _source_immich_id(self, pid: str) -> int | None:
        l = self.base.un("SELECT id FROM sources WHERE source = 'immich' AND personne_id = ?", (pid,))
        return l["id"] if l else None

    def _portrait_eligible(self, pid: str, fiche: dict) -> bool:
        """Contact sans photo, ou dont la photo vient d'Immich (vignette ou portrait HD) :
        une photo d'iCloud, de Gmail ou choisie à la main dans la révision est gardée."""
        return not fiche.get("photo") or fiche["photo"] == self._source_immich_id(pid)

    def photos_hd(self) -> dict:
        liens = self.base.etat("liaisons", {})
        hd = self.base.etat("photos_hd", {})
        candidats = self.base.etat("photos_hd_candidats", {})
        journal = self.base.etat("photos_hd_journal", [])
        lignes = []
        for pid, fiche, _ in self._verifiees():
            immich = (liens.get(pid) or {}).get("immich")
            if not immich or not self._portrait_eligible(pid, fiche):
                continue
            h = hd.get(pid) if (hd.get(pid) or {}).get("immich") == immich else None
            lignes.append({"pid": pid, "nom": nom_affiche(fiche), "photo": fiche.get("photo"),
                           "hd": h and {k: h[k] for k in ("asset", "taille", "nettete", "manuel", "le")},
                           "candidats": [{k: c[k] for k in ("asset", "taille", "nettete", "le")}
                                         for c in candidats.get(pid, [])]})
        lignes.sort(key=lambda x: (x["hd"] is not None, x["nom"].lower()))
        prochaine = None
        if journal:
            prochaine = _iso(datetime.fromisoformat(journal[0]["le"]) + timedelta(days=self.PORTRAITS_JOURS))
        return {"immich": bool(self.cfg.immich_cle), "lignes": lignes, "journal": journal[:10],
                "prochaine": prochaine}

    def chercher_portraits(self) -> dict:
        return self._lancer("portraits", lambda: self._chercher_portraits(None))

    def _portraits_dus(self) -> bool:
        journal = self.base.etat("photos_hd_journal", [])
        if not journal or not self.cfg.immich_cle:
            return False   # le premier passage se lance d'un clic
        return maintenant() - datetime.fromisoformat(journal[0]["le"]) >= timedelta(days=self.PORTRAITS_JOURS)

    def _chercher_portraits(self, pids: list[str] | None) -> None:
        """Pour chaque contact lié : meilleurs visages Immich (entiers, grands, nets) ; le meilleur
        devient la photo du contact (sauf choix manuel) et la photo de la personne dans Immich."""
        quand = maintenant()
        liens = self.base.etat("liaisons", {})
        hd = self.base.etat("photos_hd", {})
        tous_candidats = self.base.etat("photos_hd_candidats", {})
        journal = self.base.etat("photos_hd_journal", [])
        depuis = journal[0]["le"] if journal else None
        cibles = [(pid, fiche, liens[pid]["immich"]) for pid, fiche, _ in self._verifiees()
                  if (pids is None or pid in pids) and (liens.get(pid) or {}).get("immich")
                  and self._portrait_eligible(pid, fiche)]
        bilan = {"le": _iso(quand), "contacts": len(cibles), "changees": 0, "sans_photo_hd": 0, "erreurs": []}
        self._tache.update(total=len(cibles), fait=0, message="Portraits : lecture des photos Immich…")
        immich = self._immich()
        try:
            for pid, fiche, immich_id in cibles:
                self._tache["fait"] += 1
                self._tache["message"] = f"Portraits : {nom_affiche(fiche)}…"
                actuel = hd.get(pid) if (hd.get(pid) or {}).get("immich") == immich_id else None
                anciens = tous_candidats.get(pid, []) if actuel or pid in tous_candidats else []
                try:
                    trouves = self._candidats_portrait(immich, immich_id, depuis if anciens else None, anciens)
                except ErreurLien as exc:
                    bilan["erreurs"].append(str(exc))
                    if "droits" in str(exc):
                        break   # clé sans les droits nécessaires : inutile d'insister
                    continue
                tous_candidats[pid] = trouves
                if not trouves:
                    bilan["sans_photo_hd"] += 1
                    continue
                if actuel and actuel.get("manuel"):
                    continue
                meilleur = trouves[0]
                if actuel and (actuel["asset"] == meilleur["asset"] or meilleur["score"] < actuel.get("score", 0) * 1.1):
                    continue
                try:
                    hd[pid] = self._poser_portrait(immich, pid, fiche, immich_id, meilleur, manuel=False)
                    bilan["changees"] += 1
                except ErreurLien as exc:
                    bilan["erreurs"].append(f"{nom_affiche(fiche)} : {exc}")
        finally:
            immich.fermer()
            self.base.ecrire_etat("photos_hd", hd)
            self.base.ecrire_etat("photos_hd_candidats", tous_candidats)
        bilan["erreurs"] = bilan["erreurs"][:20]
        self.base.ecrire_etat("photos_hd_journal", ([bilan] + journal)[:24])
        self._tache.update(etat="erreur" if bilan["erreurs"] and not bilan["changees"] else "termine", message=(
            f"Portraits : {bilan['changees']} photo(s) HD posée(s) sur {bilan['contacts']} contact(s)"
            + (f", {bilan['sans_photo_hd']} sans visage assez grand" if bilan["sans_photo_hd"] else "")
            + (f" ; {bilan['erreurs'][0]}" if bilan["erreurs"] else "")
            + (". Elles partiront dans iCloud à la prochaine écriture." if bilan["changees"] else ".")))

    def _candidats_portrait(self, immich: Immich, immich_id: str, depuis: str | None, anciens: list[dict]) -> list[dict]:
        """Visages entiers et assez grands de la personne, classés par taille et netteté.
        Après le premier passage, seules les photos arrivées depuis sont examinées."""
        connus = {c["asset"]: c for c in anciens}
        for photo in immich.photos_de(immich_id, self.PORTRAITS_PAR_PERSONNE, depuis):
            if photo["id"] in connus:
                continue
            visage = next((v for v in immich.visages_photo(photo["id"])
                           if (v.get("person") or {}).get("id") == immich_id), None)
            boite = portraits.boite_relative(visage) if visage else None
            if not boite or not portraits.entier(boite):
                continue
            taille = portraits.taille_reelle(boite, photo["largeur"], photo["hauteur"], visage)
            if taille < portraits.VISAGE_MIN:
                continue
            connus[photo["id"]] = {"asset": photo["id"], "boite": list(boite), "taille": taille, "nettete": None,
                                   "type": photo["type"], "le": (photo["le"] or "")[:10]}
        liste = sorted(connus.values(), key=lambda c: -c["taille"])
        for c in liste[:self.PORTRAITS_A_MESURER]:
            if c["nettete"] is None:
                apercu = immich.image(c["asset"], "preview")
                try:
                    c["nettete"] = round(portraits.nettete(apercu, c["boite"]), 1) if apercu else None
                except Exception:  # noqa: BLE001 — aperçu illisible : netteté inconnue
                    c["nettete"] = None
        for c in liste:
            c["score"] = round(portraits.score(c["taille"], c["nettete"]), 1)
        nets = [c for c in liste if c["nettete"] is None or c["nettete"] >= portraits.NETTETE_MIN]
        liste = sorted(nets or liste, key=lambda c: -c["score"])
        return liste[:self.PORTRAITS_GARDES]

    def _poser_portrait(self, immich: Immich, pid: str, fiche: dict, immich_id: str, cand: dict, manuel: bool) -> dict:
        """Découpe le portrait dans la meilleure version de la photo, puis l'installe partout."""
        contenu = None
        if cand.get("type", "").lower() in ("image/jpeg", "image/png", "image/webp", "image/tiff"):
            contenu = immich.image(cand["asset"], "original")
            if contenu and not portraits.lisible(contenu):
                contenu = None
        for taille in ("fullsize", "preview"):   # HEIC, RAW… : versions JPEG générées par Immich
            if contenu:
                break
            contenu = immich.image(cand["asset"], taille)
        if not contenu:
            raise ErreurLien("photo introuvable dans Immich.")
        image = portraits.portrait(contenu, cand["boite"])
        with self.base.transaction() as cx:
            sid = self._source_immich(cx, pid, immich_id, image)
        fiche = dict(fiche, photo=sid)
        self._remplacer_fiche_validee(pid, fiche)
        try:
            immich.definir_couverture(immich_id, cand["asset"])
        except ErreurLien as exc:  # la photo du contact est posée quand même
            log.warning("Photo de la personne Immich %s : %s", immich_id, exc)
        return {"immich": immich_id, "asset": cand["asset"], "taille": cand["taille"], "nettete": cand["nettete"],
                "score": cand.get("score", 0), "manuel": manuel, "le": _iso(maintenant())}

    def choisir_portrait(self, pid: str, asset: str) -> dict:
        """Choix manuel parmi les candidats : gardé lors des recherches suivantes."""
        lien = self.base.etat("liaisons", {}).get(pid) or {}
        cand = next((c for c in self.base.etat("photos_hd_candidats", {}).get(pid, []) if c["asset"] == asset), None)
        if not lien.get("immich") or not cand:
            raise ErreurCarnet("Cette photo n'est plus proposée : relance la recherche.")
        ligne = self._personne(pid)
        fiche = completer(json.loads(ligne["fiche"] or "{}"))
        immich = self._immich()
        try:
            entree = self._poser_portrait(immich, pid, fiche, lien["immich"], cand, manuel=True)
        finally:
            immich.fermer()
        hd = self.base.etat("photos_hd", {})
        hd[pid] = entree
        self.base.ecrire_etat("photos_hd", hd)
        return {"ok": True}

    def portrait_auto(self, pid: str) -> dict:
        """Annule un choix manuel : la prochaine recherche choisira de nouveau la meilleure."""
        hd = self.base.etat("photos_hd", {})
        if pid in hd:
            hd[pid]["manuel"] = False
            hd[pid]["score"] = 0
            self.base.ecrire_etat("photos_hd", hd)
        return {"ok": True}

    def apercu_portrait(self, pid: str, asset: str) -> tuple[bytes, str] | None:
        """Petit aperçu d'un candidat, cadré comme le portrait final (gardé en mémoire)."""
        cache = self.__dict__.setdefault("_cache_apercus", {})
        if (pid, asset) in cache:
            return cache[(pid, asset)]
        cand = next((c for c in self.base.etat("photos_hd_candidats", {}).get(pid, []) if c["asset"] == asset), None)
        if not cand:
            return None
        immich = self._immich()
        try:
            contenu = immich.image(asset, "preview")
        finally:
            immich.fermer()
        if not contenu:
            return None
        image = portraits.portrait(contenu, cand["boite"], taille=320)
        if len(cache) > 400:
            cache.clear()
        cache[(pid, asset)] = image
        return image

    # ================================================================ Home Assistant : réservations et journal de naissance

    def _personnes_ha(self) -> list[dict]:
        """Contacts vérifiés liés à Immich, et proches (règle « proches »), avec le nom tel que la
        réservation doit l'écrire : le nom Immich quand le contact est lié, sinon le nom carnet."""
        d = self._donnees_liens()
        noms_immich = {p["id"]: p["nom"] for p in d["immich"]}
        liens = self.base.etat("liaisons", {})
        res = []
        for pid, fiche, _ in self._verifiees():
            lien = liens.get(pid, {})
            immich = lien.get("immich")
            if not immich and not set(fiche["groupes"]) & GROUPES_PROCHES:
                continue
            res.append({"pid": pid, "nom": noms_immich.get(immich) or nom_affiche(fiche), "nom_carnet": nom_affiche(fiche),
                        "immich_id": immich, "treemich_id": lien.get("treemich"), "fiche": fiche})
        return res

    def ha_personnes(self) -> dict:
        personnes = sorted(self._personnes_ha(), key=lambda p: p["nom"].lower())
        return {"personnes": [{"nom": p["nom"], "immich": bool(p["immich_id"])} for p in personnes]}

    def ha_invite(self, nom: str) -> dict:
        """Nom (ou identifiant Immich, ou adresse de sa fiche) → date de naissance. 404 si inconnu,
        409 si plusieurs personnes portent ce nom (pas de devinette pour un journal imprimé)."""
        brut = (nom or "").strip()
        brut = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\s*(?:→|->)\s*\d{4}-\d{2}-\d{2}\)\s*$", "", brut)  # « Nom (dates) »
        personnes = self._personnes_ha()
        uuid_ = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", brut.lower())
        if uuid_:
            trouves = [p for p in personnes if p["immich_id"] == uuid_.group(0)]
        else:
            cle = cle_texte(brut)
            trouves = [p for p in personnes if cle in (cle_texte(p["nom"]), cle_texte(p["nom_carnet"]))]
        if not trouves:
            raise HTTPException(404, f"« {brut} » n'est ni un proche ni un contact lié à Immich dans carnet.")
        if len(trouves) > 1:
            raise HTTPException(409, f"Plusieurs personnes s'appellent « {brut} » : mets l'identifiant Immich dans le champ.")
        p = trouves[0]
        annif = p["fiche"]["anniversaire"] or ""
        return {"nom": p["nom"], "prenom": p["fiche"]["prenom"], "naissance": annif or None,
                "annee_connue": len(annif) == 10, "immich_id": p["immich_id"], "treemich_id": p["treemich_id"],
                "groupes": p["fiche"]["groupes"]}

    # ================================================================ dates de naissance → Immich et Treemich (V3, étape 5)

    def naissances_simuler(self) -> dict:
        return self._lancer("naissances", self._simuler_naissances)

    def _simuler_naissances(self) -> None:
        """Compare la date de naissance de carnet à celle d'Immich et de Treemich, sans rien écrire."""
        d = self._donnees_liens(rafraichir=True)
        if d["erreurs"]:
            raise ErreurCarnet(d["erreurs"][0])
        naissance_immich = {p["id"]: (p["naissance"] or "")[:10] for p in d["immich"]}
        liens = self.base.etat("liaisons", {})
        verifiees = {pid: f for pid, f, _ in self._verifiees()}
        lignes = []
        tm = self._treemich() if self.cfg.treemich_email and any(l.get("treemich") for l in liens.values()) else None
        cibles = [(pid, l) for pid, l in liens.items() if pid in verifiees]
        self._tache.update(total=len(cibles), fait=0, message="Dates de naissance : lecture d'Immich et Treemich…")
        for pid, lien in sorted(cibles, key=lambda x: nom_affiche(verifiees[x[0]]).lower()):
            self._tache["fait"] += 1
            fiche = verifiees[pid]
            date = fiche["anniversaire"] or ""
            ligne = {"pid": pid, "nom": nom_affiche(fiche), "carnet": date, "complete": len(date) == 10}
            for cible, ident in (("immich", lien.get("immich")), ("treemich", lien.get("treemich"))):
                if not ident or (cible == "treemich" and not tm):
                    continue
                actuelle = naissance_immich.get(ident, "") if cible == "immich" else tm.naissance(ident)
                if not date:
                    etat = "rien_dans_carnet"
                elif len(date) != 10:
                    etat = "annee_inconnue"
                elif actuelle == date:
                    etat = "identique"
                elif not actuelle:
                    etat = "ajouter"
                else:
                    etat = "differente"
                ligne[cible] = {"id": ident, "actuelle": actuelle, "etat": etat}
            lignes.append(ligne)
        self._plan_naissances = {"instant": time.monotonic(), "lignes": lignes, "le": _iso(maintenant())}
        n = sum(1 for l in lignes for c in ("immich", "treemich") if l.get(c, {}).get("etat") in ("ajouter", "differente"))
        self._tache.update(etat="termine", message=f"Simulation : {n} date(s) à écrire, rien n'a été modifié.")

    def naissances_plan(self) -> dict | None:
        plan = getattr(self, "_plan_naissances", None)
        if not plan or time.monotonic() - plan["instant"] > self.PLAN_VALIDE:
            return {"plan": None, "journal": self.base.etat("naissances_journal", [])[:20]}
        resume = {c: {e: sum(1 for l in plan["lignes"] if l.get(c, {}).get("etat") == e)
                      for e in ("ajouter", "differente", "identique", "annee_inconnue", "rien_dans_carnet")}
                  for c in ("immich", "treemich")}
        return {"plan": {"le": plan["le"], "lignes": plan["lignes"], "resume": resume},
                "journal": self.base.etat("naissances_journal", [])[:20]}

    def naissances_ecrire(self, cible: str, remplacer: bool, essai: str | None, confirme: bool) -> dict:
        plan = getattr(self, "_plan_naissances", None)
        if not plan or time.monotonic() - plan["instant"] > self.PLAN_VALIDE:
            raise ErreurCarnet("Lance d'abord une simulation (valable 30 minutes).")
        if cible not in ("immich", "treemich"):
            raise ErreurCarnet("Cible inconnue.")
        if not essai and not confirme:
            raise ErreurCarnet("Coche la confirmation avant d'écrire.")
        etats = {"ajouter", "differente"} if remplacer else {"ajouter"}
        a_faire = [l for l in plan["lignes"] if l.get(cible, {}).get("etat") in etats and (not essai or l["pid"] == essai)]
        if essai and not a_faire:
            raise ErreurCarnet("Rien à écrire pour cette personne (date identique, absente ou année inconnue).")
        if not a_faire:
            raise ErreurCarnet("Rien à écrire.")
        return self._lancer("naissances", lambda: self._ecrire_naissances(cible, a_faire, bool(essai)))

    def _ecrire_naissances(self, cible: str, lignes: list[dict], essai: bool) -> None:
        quand = maintenant()
        bilan = {"le": _iso(quand), "cible": cible, "essai": essai, "ecrites": [], "erreurs": [], "sauvegarde": None}
        client = self._immich() if cible == "immich" else self._treemich()
        try:
            if cible == "treemich":  # export complet de l'arbre avant la première écriture
                nom = f"{quand:%Y-%m-%d_%H%M%S}_treemich-avant-dates.ged"
                (self.cfg.archives / nom).write_bytes(client.exporter_gedcom())
                bilan["sauvegarde"] = nom
            self._tache.update(total=len(lignes), fait=0, message=f"Dates de naissance → {cible.capitalize()}…")
            for l in lignes:
                info = l[cible]
                try:
                    client.maj_naissance(info["id"], l["carnet"])
                    # ancienne valeur gardée : de quoi revenir en arrière à la main si besoin
                    bilan["ecrites"].append({"nom": l["nom"], "avant": info["actuelle"], "apres": l["carnet"]})
                except ErreurLien as exc:
                    bilan["erreurs"].append(f"{l['nom']} : {exc}")
                self._tache["fait"] += 1
        finally:
            client.fermer()
        self._plan_naissances = None  # les valeurs lues ne valent plus
        self.base.ecrire_etat("naissances_journal", ([bilan] + self.base.etat("naissances_journal", []))[:50])
        self._tache.update(etat="erreur" if bilan["erreurs"] else "termine", message=(
            f"{'Essai' if essai else 'Écriture'} {cible.capitalize()} : {len(bilan['ecrites'])} date(s) écrite(s)"
            + (f", {len(bilan['erreurs'])} erreur(s)" if bilan["erreurs"] else "") + "."))

    # ================================================================ sauvegarde de nuit (V3)

    SEUIL_COUPE_CIRCUIT = 0.05   # au-delà de 5 % de fiches supprimées ou changées d'un coup : arrêt

    def nuit(self) -> dict:
        """Tâche de 3 h : veille iCloud, puis sauvegarde (export daté + copie Synology)."""
        def travail():
            if self.cfg.icloud_user and self.cfg.icloud_password:
                self._veiller()
            if self.base.etat("liaisons", {}) and (self.cfg.immich_cle or self.cfg.treemich_email):
                try:
                    self._appliquer_liens(None)
                except Exception:  # noqa: BLE001 — la sauvegarde passe quand même
                    log.exception("Liaisons de nuit")
            if self._portraits_dus():   # une fois par mois, pour ménager le NAS
                try:
                    self._chercher_portraits(None)
                except Exception:  # noqa: BLE001
                    log.exception("Portraits de nuit")
            self._sauvegarder()
        return self._lancer("veille", travail)

    def sauvegarder(self) -> dict:
        return self._lancer("sauvegarde", self._sauvegarder)

    def _sauvegarder(self) -> None:
        quand = maintenant()
        entree = {"le": _iso(quand), "vcf": None, "contacts": 0, "synology": None, "erreur": None}
        try:
            personnes = self._verifiees()
            entree["contacts"] = len(personnes)
            # 1. Export daté, sans photos (léger) ; gardé CARNET_SAUVEGARDE_JOURS jours
            dossier = self.cfg.archives / "sauvegardes"
            dossier.mkdir(exist_ok=True)
            nom = f"carnet-{quand:%Y-%m-%d}.vcf"
            export.ecrire_atomique(dossier / nom, "".join(
                export.vcard(f, f"carnet-{pid}", None) for pid, f, _ in personnes))
            entree["vcf"] = nom
            limite = (quand - timedelta(days=self.cfg.sauvegarde_jours)).timestamp()
            for f in dossier.glob("carnet-*.vcf"):
                if f.stat().st_mtime < limite:
                    f.unlink(missing_ok=True)
            # 2. Copie dans Synology Contacts
            if self.cfg.synology_url:
                self._tache["message"] = "Sauvegarde : copie dans Synology Contacts…"
                entree["synology"] = self._copier_synology(personnes)
        except (ErreurICloud, ErreurCarnet) as exc:
            entree["erreur"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Sauvegarde de nuit")
            entree["erreur"] = f"Erreur inattendue : {exc}"
        journal = [entree] + self.base.etat("sauvegarde_journal", [])
        self.base.ecrire_etat("sauvegarde_journal", journal[:30])
        syno = entree["synology"] or {}
        if entree["erreur"]:
            self._tache.update(etat="erreur", message=f"Sauvegarde : {entree['erreur']}")
        else:
            self._tache.update(etat="termine", message=(
                f"Sauvegarde : {entree['contacts']} contacts dans {entree['vcf']}"
                + (f" ; Synology : {syno['crees']} créé(s), {syno['modifies']} mis à jour, {syno['supprimes']} supprimé(s)."
                   if syno else ".")))

    def _copier_synology(self, personnes: list) -> dict:
        """Synology Contacts à l'identique des fiches vérifiées et de leurs groupes. Arrêt sans
        rien écrire si plus de 5 % des fiches déjà copiées seraient supprimées ou modifiées."""
        dav = CardDAV(self.cfg.synology_url, self.cfg.synology_user, self.cfg.synology_password,
                      transport=getattr(self, "transport_synology", None), nom_carnet=self.cfg.synology_carnet,
                      verifier_tls=self.cfg.synology_verifier_tls, service="Synology")
        bilan = {"crees": 0, "modifies": 0, "supprimes": 0, "groupes": 0, "erreurs": []}
        try:
            distantes = {c.uid: c for c in (synchro.analyser(b.href, b.etag, b.texte) for b in dav.lister())}
            voulues: dict[str, tuple[str, str]] = {}   # uid → (nom, texte)
            membres: dict[str, list[str]] = defaultdict(list)
            for pid, fiche, _ in personnes:
                uid = f"carnet-{pid}"
                image = self.photo(fiche["photo"]) if fiche.get("photo") else None
                voulues[uid] = (nom_affiche(fiche), export.vcard(fiche, uid, image))
                for g in fiche["groupes"]:
                    membres[g].append(uid)
            for g, uids in membres.items():
                uid = f"carnet-groupe-{uuid.uuid5(uuid.NAMESPACE_URL, 'carnet:' + g)}"
                voulues[uid] = (g, synchro.carte_groupe(g, uid, uids))
            suivi = self.base.etat("synology_suivi", {})
            actions = []
            for uid, (nom, texte) in voulues.items():
                d = distantes.get(uid)
                emp = synchro.empreinte(texte)
                if d is None:
                    actions.append(("creer", uid, nom, texte, None, dav.href_nouveau(uid)))
                elif not (suivi.get(uid, {}).get("etag") == d.etag and suivi[uid].get("empreinte") == emp) \
                        and synchro.empreinte(d.texte) != emp:
                    actions.append(("modifier", uid, nom, texte, d.etag, d.href))
            for uid, d in distantes.items():
                if uid not in voulues:
                    actions.append(("supprimer", uid, d.nom, None, d.etag, d.href))
            touches = sum(1 for a in actions if a[0] != "creer")
            if distantes and touches > max(5, self.SEUIL_COUPE_CIRCUIT * len(distantes)):
                raise ErreurCarnet(f"copie Synology bloquée : {touches} fiches sur {len(distantes)} seraient "
                                   "modifiées ou supprimées d'un coup (plus de 5 %). Vérifie carnet, puis lance "
                                   "« Forcer la copie » si c'est voulu.")
            self._ecrire_synology(dav, actions, suivi, bilan)
        finally:
            dav.fermer()
        return bilan

    def forcer_synology(self) -> dict:
        """Copie Synology sans coupe-circuit (après vérification par l'utilisateur)."""
        def travail():
            ancien, self.SEUIL_COUPE_CIRCUIT = self.SEUIL_COUPE_CIRCUIT, 10**9
            try:
                self._sauvegarder()
            finally:
                self.SEUIL_COUPE_CIRCUIT = ancien
        return self._lancer("sauvegarde", travail)

    def _ecrire_synology(self, dav: CardDAV, actions: list, suivi: dict, bilan: dict) -> None:
        self._tache.update(total=len(actions), fait=0)
        for action, uid, nom, texte, etag, href in actions:
            try:
                if action == "supprimer":
                    dav.supprimer(href, etag)
                    suivi.pop(uid, None)
                    bilan["supprimes"] += 1
                else:
                    nouvel_etag = dav.ecrire(href, texte, etag)
                    suivi[uid] = {"etag": nouvel_etag, "empreinte": synchro.empreinte(texte)}
                    if uid.startswith("carnet-groupe-"):
                        bilan["groupes"] += 1
                    else:
                        bilan["crees" if action == "creer" else "modifies"] += 1
            except ErreurICloud as exc:
                bilan["erreurs"].append(f"{nom} : {exc}")
                if "refuse la connexion" in str(exc):
                    break
            self._tache["fait"] = self._tache.get("fait", 0) + 1
        self.base.ecrire_etat("synology_suivi", suivi)

    def sauvegardes(self) -> dict:
        dossier = self.cfg.archives / "sauvegardes"
        fichiers = sorted(dossier.glob("carnet-*.vcf"), reverse=True) if dossier.is_dir() else []
        return {"synology": bool(self.cfg.synology_url), "jours": self.cfg.sauvegarde_jours,
                "fichiers": [{"nom": f.name, "taille": f.stat().st_size} for f in fichiers],
                "journal": self.base.etat("sauvegarde_journal", [])[:30]}

    def _resume_sauvegarde(self) -> dict | None:
        journal = self.base.etat("sauvegarde_journal", [])
        if not journal:
            return None
        s = journal[0]
        syno = s.get("synology") or {}
        return {"le": s["le"], "ok": not s["erreur"] and not syno.get("erreurs"), "erreur": s["erreur"],
                "contacts": s["contacts"], "synology": bool(syno)}

    # ================================================================ archives

    def archives(self) -> list[dict]:
        aujourdhui = maintenant()
        res = []
        for imp in self.base.lire("SELECT * FROM imports WHERE source != 'immich' ORDER BY importe_le DESC"):
            expire = datetime.fromisoformat(imp["expire_le"])
            jours = (expire - aujourdhui).days
            noms = sorted({nom_affiche(completer(json.loads(l["donnees"]))) for l in self.base.lire(
                "SELECT donnees FROM sources WHERE import_id = ?", (imp["id"],))}, key=str.lower)
            res.append({
                "id": imp["id"], "source": imp["source"],
                "libelle": LIBELLES_SOURCES.get(imp["source"], imp["source"]),
                "fichier": imp["nom_fichier"], "importe_le": imp["importe_le"],
                "expire_le": imp["expire_le"], "jours_restants": max(jours, 0),
                "bientot": imp["purge_le"] is None and jours <= self.cfg.alerte_jours,
                "purge_le": imp["purge_le"], "lus": imp["nb_lus"], "ajoutes": imp["nb_ajoutes"],
                "identiques": imp["nb_identiques"], "contacts": noms,
            })
        return res

    def purger(self) -> int:
        """Supprime les archives arrivées à échéance et le texte d'origine des fiches."""
        quand = maintenant()
        echues = self.base.lire("SELECT id, archive FROM imports WHERE purge_le IS NULL AND expire_le <= ?",
                                (_iso(quand),))
        for imp in echues:
            if imp["archive"]:
                (self.cfg.archives / imp["archive"]).unlink(missing_ok=True)
            with self.base.transaction() as cx:
                cx.execute("UPDATE imports SET archive = NULL, purge_le = ? WHERE id = ?",
                           (_iso(quand), imp["id"]))
                cx.execute("UPDATE sources SET brut = NULL WHERE import_id = ?", (imp["id"],))
            log.info("Archive %s supprimée (durée de conservation atteinte)", imp["archive"])
        limite = (quand - timedelta(days=self.cfg.archive_jours)).timestamp()
        for f in self.cfg.archives.glob("*_icloud-sauvegarde.vcf"):
            if f.stat().st_mtime < limite:
                f.unlink(missing_ok=True)
                log.info("Sauvegarde iCloud %s supprimée (durée de conservation atteinte)", f.name)
        return len(echues)

    # ================================================================ état (Home Assistant)

    def _resume_veille(self) -> dict | None:
        """Dernière veille, pour Home Assistant : compteurs et erreur éventuelle (aucun nom)."""
        journal = self.base.etat("veille_journal", [])
        if not journal:
            return None
        v = journal[0]
        return {"le": v["le"], "ok": not v["erreur"], "erreur": v["erreur"], "revision": v["revision"],
                "modifies": len(v["modifies"]), "nouveaux": len(v["nouveaux"]), "supprimes": len(v["supprimes"])}

    def statut(self) -> dict:
        compte = {l["statut"]: l["n"] for l in
                  self.base.lire("SELECT statut, count(*) AS n FROM personnes GROUP BY statut")}
        liste = self.liste()
        archives = [a for a in self.archives() if a["bientot"]]
        prochaine = min((a["expire_le"] for a in self.archives() if a["purge_le"] is None), default=None)
        return {
            "total": sum(n for st, n in compte.items() if st != "ecarte"),
            "ecartes": compte.get("ecarte", 0),
            "verifies": compte.get("verifie", 0),
            "a_reviser": compte.get("a_reviser", 0),
            "doublons_a_reviser": sum(1 for p in liste if p["statut"] == "a_reviser" and p["doublon"]),
            "a_revoir": sum(1 for p in liste if p["statut"] == "a_reviser" and p["a_revoir"]),
            "linkedin_sans_contact": self.base.un(
                "SELECT count(*) AS n FROM sources WHERE enrichissement = 1 AND personne_id IS NULL")["n"],
            "archives_bientot": len(archives),
            "contacts_archives_bientot": sum(len(a["contacts"]) for a in archives),
            "prochaine_suppression": prochaine,
            "dernier_export": self.base.etat("dernier_export"),
            "dernier_envoi_kit": self.base.etat("dernier_envoi_kit"),
            "veille": self._resume_veille(),
            "sauvegarde": self._resume_sauvegarde(),
            "derniere_ecriture_icloud": {k: v for k, v in (self.base.etat("derniere_ecriture_icloud") or {}).items()
                                         if k in ("le", "essai", "crees", "modifies", "supprimes", "groupes")} or None,
        }
