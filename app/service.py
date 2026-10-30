"""Opérations de carnet : import, rapprochement, révision, export, kit, archives."""
from __future__ import annotations

import hashlib
from collections import Counter
import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from rapidfuzz import fuzz

from . import doublons, export, fusion
from .config import Config
from .db import Base
from .modele import (GROUPE_A_CLASSER, GROUPE_URGENCE, GROUPES_TRAVAIL, LIBELLES_SOURCES,
                     completer, nom_affiche)
from .normalisation import (ValeurInvalide, cle_texte, domaine_pro, nettoyer, normaliser_fiche,
                            societe_depuis_domaine)
from .sources import detecter_source, lire_texte, linkedin, outlook, vcard

log = logging.getLogger("carnet")
LECTEURS = {"icloud": vcard.lire, "gmail": vcard.lire, "outlook": outlook.lire,
            "linkedin": linkedin.lire}
EXTENSIONS = {".vcf", ".vcard", ".csv"}


# Mots qui ne distinguent pas une société (formes juridiques, articles)
MOTS_SOCIETE_VIDES = {"sa", "sas", "sasu", "sarl", "eurl", "sci", "scop", "gmbh", "ltd", "inc", "llc",
                      "group", "groupe", "la", "le", "les", "de", "des", "du", "et", "the", "and", "france"}


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
                cx.execute("UPDATE personnes SET statut = 'a_reviser', a_revoir = 'fiche mise à jour "
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
                cx.execute("UPDATE personnes SET statut = 'a_reviser', raisons = ?, "
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
            cx.execute("UPDATE personnes SET statut = 'a_reviser', raisons = ?, "
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
                return completer(json.loads(ligne[colonne]))
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
            if valider:
                cx.execute("UPDATE personnes SET fiche = ?, brouillon = NULL, statut = 'verifie', "
                           "a_revoir = NULL, verifie_le = ?, modifie_le = ? WHERE id = ?",
                           (texte, quand, quand, pid))
            else:
                cx.execute("UPDATE personnes SET brouillon = ?, modifie_le = ? WHERE id = ?",
                           (texte, quand, pid))
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
        sections = {k: [] for k in ("anniversaires", "portables_proches", "societes", "travail_a_classer",
                                    "urgence_sans_mobile",
                                    "sans_groupe", "numeros_non_reconnus", "injoignables")}
        for pid, f in sorted(personnes, key=lambda x: nom_affiche(x[1]).lower()):
            groupes = set(f["groupes"])
            if groupes & {"Famille", "Amis"} and not f["anniversaire"]:
                sections["anniversaires"].append(resume(pid, f))
            if groupes & {"Famille", "Amis"}:
                # Portables (+33 6 / +33 7) d'un proche : son mobile perso ou celui du travail ?
                for t in f["telephones"]:
                    if t["valeur"].startswith(("+336", "+337")) and f"{pid}|{t['valeur']}" not in confirmes:
                        sections["portables_proches"].append(
                            resume(pid, f, numero=t["valeur"], affichage=t.get("affichage"), type=t["type"]))
            if groupes & set(GROUPES_TRAVAIL + [GROUPE_A_CLASSER]) and not f["societe"]:
                proposition, origine = self._proposer_societe(f, par_domaine)
                sections["societes"].append(resume(pid, f, proposition=proposition, origine=origine))
            if GROUPE_A_CLASSER in groupes:
                sections["travail_a_classer"].append(resume(pid, f, societe=f["societe"]))
            if GROUPE_URGENCE in groupes and not any(t.get("mobile") for t in f["telephones"]):
                sections["urgence_sans_mobile"].append(resume(pid, f))
            if not groupes:
                sections["sans_groupe"].append(resume(pid, f))
            invalides = [t["valeur"] for t in f["telephones"] if not t.get("valide")]
            if invalides:
                sections["numeros_non_reconnus"].append(resume(pid, f, numeros=invalides))
            if not f["telephones"] and not f["courriels"]:
                sections["injoignables"].append(resume(pid, f))
        sections["societes_a_uniformiser"] = self._societes_a_uniformiser(personnes)
        return sections

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
                  telephone: str | None = None, type_telephone: str | None = None) -> dict:
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
            try:
                propre = normaliser_fiche(f, self.cfg.region)
            except ValeurInvalide as exc:
                raise ErreurCarnet(str(exc)) from exc
            nouvelles[colonne] = json.dumps(propre, ensure_ascii=False)
        with self.base.transaction() as cx:
            cx.execute("UPDATE personnes SET fiche = ?, brouillon = ?, modifie_le = ? WHERE id = ?",
                       (nouvelles["fiche"], nouvelles.get("brouillon"), _iso(maintenant()), pid))
        if telephone and type_telephone:  # ce numéro ne sera plus redemandé dans la Revue
            confirmes = self.base.etat("telephones_confirmes", [])
            confirmes.append(f"{pid}|{telephone}")
            self.base.ecrire_etat("telephones_confirmes", sorted(set(confirmes)))
        return {"ok": True}

    # ================================================================ export et kit

    def _verifiees(self, groupe: str | None = None) -> list[tuple[str, dict, list[dict]]]:
        res = []
        for p in self.base.lire("SELECT * FROM personnes WHERE statut = 'verifie' AND fiche IS NOT NULL"):
            fiche = completer(json.loads(p["fiche"]))
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
                     if p["statut"] != "verifie" and GROUPE_URGENCE in p["groupes"]]
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
        return len(echues)

    # ================================================================ état (Home Assistant)

    def statut(self) -> dict:
        compte = {l["statut"]: l["n"] for l in
                  self.base.lire("SELECT statut, count(*) AS n FROM personnes GROUP BY statut")}
        liste = self.liste()
        archives = [a for a in self.archives() if a["bientot"]]
        prochaine = min((a["expire_le"] for a in self.archives() if a["purge_le"] is None), default=None)
        return {
            "total": sum(compte.values()),
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
        }
