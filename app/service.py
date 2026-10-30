"""Opérations de carnet : import, rapprochement, révision, export, kit, archives."""
from __future__ import annotations

import hashlib
from collections import Counter
import json
import logging
import shutil
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from rapidfuzz import fuzz

from . import doublons, export, fusion, synchro
from .carddav import CardDAV, Conflit, ErreurICloud
from .config import Config
from .db import Base
from .modele import (GROUPE_A_CLASSER, GROUPE_MOI, GROUPE_URGENCE, GROUPES_RECONNUS, GROUPES_TRAVAIL,
                     LIBELLES_SOURCES, completer, nom_affiche)
from .normalisation import (MESSAGERIES, ValeurInvalide, cle_texte, domaine_pro, regle_proches,
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
            enrichies += 1
        return {"personnes_creees": 0, "personnes_completees": 0, "enrichies": enrichies}

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
            if groupes & {"Famille", "Amis", "Jardin secret"} and len(portables) >= 2 and pid not in tries:
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
                "journal": self.base.etat("journal_icloud", [])}

    def _lancer(self, nom: str, travail) -> dict:
        with self._verrou_icloud:
            if self._tache.get("etat") in ("lecture", "ecriture"):
                raise ErreurCarnet("Une opération iCloud est déjà en cours.")
            self._tache = {"etat": "lecture" if nom == "simulation" else "ecriture", "operation": nom,
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
        for nom in GROUPES_RECONNUS:
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

    # ================================================================ archives

    def archives(self) -> list[dict]:
        aujourdhui = maintenant()
        res = []
        for imp in self.base.lire("SELECT * FROM imports ORDER BY importe_le DESC"):
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
            "derniere_ecriture_icloud": {k: v for k, v in (self.base.etat("derniere_ecriture_icloud") or {}).items()
                                         if k in ("le", "essai", "crees", "modifies", "supprimes", "groupes")} or None,
        }
