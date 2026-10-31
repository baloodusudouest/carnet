"""Base SQLite chiffrée (SQLCipher). Une seule connexion, protégée par un verrou :
carnet n'a qu'un utilisateur, les accès concurrents sont rares et courts."""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import sqlcipher3

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,              -- icloud | gmail | outlook | linkedin
    nom_fichier TEXT NOT NULL,
    sha256      TEXT NOT NULL UNIQUE,
    archive     TEXT,                       -- chemin relatif dans archives/ (NULL une fois purgée)
    importe_le  TEXT NOT NULL,
    expire_le   TEXT NOT NULL,
    nb_lus      INTEGER NOT NULL DEFAULT 0,
    nb_ajoutes  INTEGER NOT NULL DEFAULT 0,
    nb_identiques INTEGER NOT NULL DEFAULT 0,
    purge_le    TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    import_id   INTEGER NOT NULL REFERENCES imports(id),
    source      TEXT NOT NULL,
    uid         TEXT,                       -- UID d'origine (iCloud) s'il existe
    empreinte   TEXT NOT NULL,              -- empreinte des données normalisées
    donnees     TEXT NOT NULL,              -- fiche normalisée (JSON)
    photo       BLOB,
    photo_type  TEXT,
    brut        TEXT,                       -- texte d'origine (effacé avec l'archive)
    personne_id TEXT REFERENCES personnes(id),
    enrichissement INTEGER NOT NULL DEFAULT 0  -- 1 = LinkedIn : enrichit, ne crée pas de contact
);
CREATE INDEX IF NOT EXISTS idx_sources_personne ON sources(personne_id);
CREATE INDEX IF NOT EXISTS idx_sources_empreinte ON sources(source, empreinte);
CREATE TABLE IF NOT EXISTS personnes (
    id          TEXT PRIMARY KEY,
    statut      TEXT NOT NULL DEFAULT 'a_reviser',  -- a_reviser | verifie
    fiche       TEXT,                       -- dernière fiche validée (JSON) : seule exportée
    brouillon   TEXT,                       -- modifications en cours, pas encore validées (JSON)
    raisons     TEXT,                       -- pourquoi ces fiches ont été rapprochées (JSON)
    a_revoir    TEXT,                       -- motif d'un retour en révision
    cree_le     TEXT NOT NULL,
    modifie_le  TEXT NOT NULL,
    verifie_le  TEXT
);
CREATE TABLE IF NOT EXISTS distinctes (
    a INTEGER NOT NULL, b INTEGER NOT NULL,     -- deux fiches source à ne jamais rapprocher
    PRIMARY KEY (a, b)
);
CREATE TABLE IF NOT EXISTS etat (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);
"""


class Base:
    def __init__(self, chemin: Path, cle: str):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.RLock()
        self._cx = sqlcipher3.connect(str(chemin), check_same_thread=False, isolation_level=None)
        # La clé est passée en paramètre lié impossible avec PRAGMA : on échappe les apostrophes.
        self._cx.execute("PRAGMA key = '" + cle.replace("'", "''") + "'")
        self._cle = cle   # en mémoire seulement : sert à chiffrer les copies de sauvegarde
        try:
            self._cx.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlcipher3.DatabaseError as exc:  # mauvaise clé ou fichier abîmé
            raise RuntimeError("Impossible d'ouvrir la base : CARNET_DB_KEY ne correspond pas.") from exc
        self._cx.row_factory = sqlcipher3.Row
        self._cx.execute("PRAGMA foreign_keys = ON")
        self._cx.execute("PRAGMA journal_mode = WAL")
        self._cx.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlcipher3.Connection]:
        with self._verrou:
            self._cx.execute("BEGIN IMMEDIATE")
            try:
                yield self._cx
            except BaseException:
                self._cx.execute("ROLLBACK")
                raise
            self._cx.execute("COMMIT")

    def lire(self, sql: str, params: tuple | dict = ()) -> list[sqlcipher3.Row]:
        with self._verrou:
            return self._cx.execute(sql, params).fetchall()

    def un(self, sql: str, params: tuple | dict = ()) -> sqlcipher3.Row | None:
        with self._verrou:
            return self._cx.execute(sql, params).fetchone()

    def etat(self, cle: str, defaut: Any = None) -> Any:
        ligne = self.un("SELECT valeur FROM etat WHERE cle = ?", (cle,))
        return json.loads(ligne["valeur"]) if ligne else defaut

    def ecrire_etat(self, cle: str, valeur: Any) -> None:
        with self.transaction() as cx:
            cx.execute(
                "INSERT INTO etat(cle, valeur) VALUES(?, ?) "
                "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                (cle, json.dumps(valeur, ensure_ascii=False)),
            )

    def copier(self, destination: Path) -> None:
        """Copie complète et cohérente de la base, chiffrée avec la même clé (sqlcipher_export).
        Écrite à côté puis renommée : une copie interrompue ne remplace jamais la précédente."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        cle = self._cle.replace("'", "''")
        with self._verrou:
            self._cx.execute("ATTACH DATABASE ? AS copie KEY '" + cle + "'", (str(tmp),))
            try:
                self._cx.execute("SELECT sqlcipher_export('copie')").fetchone()
            finally:
                self._cx.execute("DETACH DATABASE copie")
        tmp.replace(destination)

    @staticmethod
    def verifier(chemin: Path, cle: str) -> dict:
        """Ouvre une copie avec une clé donnée et la contrôle (sans rien modifier)."""
        cx = sqlcipher3.connect(f"file:{chemin}?mode=ro", uri=True)
        try:
            cx.execute("PRAGMA key = '" + cle.replace("'", "''") + "'")
            try:
                cx.execute("SELECT count(*) FROM sqlite_master").fetchone()
            except sqlcipher3.DatabaseError:
                return {"ok": False, "motif": "cette clé n'ouvre pas la sauvegarde"}
            integrite = cx.execute("PRAGMA integrity_check").fetchone()[0]
            compte = {t: cx.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                      for t in ("personnes", "sources", "imports", "etat")}
            compte["verifies"] = cx.execute("SELECT count(*) FROM personnes WHERE statut = 'verifie'").fetchone()[0]
            compte["photos"] = cx.execute("SELECT count(*) FROM sources WHERE photo IS NOT NULL").fetchone()[0]
            return {"ok": integrite == "ok", "motif": None if integrite == "ok" else f"base abîmée : {integrite}",
                    "comptes": compte}
        finally:
            cx.close()

    def fermer(self) -> None:
        with self._verrou:
            self._cx.close()
