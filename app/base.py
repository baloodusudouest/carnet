"""Base SQLite de carnet 2 (fichier carnet2.db dans /state, hors partage).

Une table par sujet, schéma versionné (PRAGMA user_version). Une seule connexion protégée par
un verrou : carnet n'a qu'un utilisateur et des accès courts. Chaque écriture incrémente un
compteur de génération, qui sert à invalider les calculs gardés en mémoire.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

VERSION = 2   # 2 : validations, personnes_externes (carnet 2.1)

SCHEMA = """
-- Cartes contact lues dans iCloud : la source maître. `fiche` est la forme lisible (JSON),
-- `texte` la carte telle qu'iCloud la donne (gardée pour réécrire sans rien perdre).
CREATE TABLE IF NOT EXISTS fiches (
    uid      TEXT PRIMARY KEY,
    href     TEXT NOT NULL,
    etag     TEXT NOT NULL,
    texte    TEXT NOT NULL,
    fiche    TEXT NOT NULL,
    photo    INTEGER NOT NULL DEFAULT 0,
    lu_le    TEXT NOT NULL
);
-- Cartes de groupe iCloud (X-ADDRESSBOOKSERVER-KIND:group)
CREATE TABLE IF NOT EXISTS groupes (
    uid      TEXT PRIMARY KEY,
    href     TEXT NOT NULL,
    etag     TEXT NOT NULL,
    nom      TEXT NOT NULL,
    texte    TEXT NOT NULL,
    membres  TEXT NOT NULL
);
-- Boîte « À traiter » : un point par (motif, clé), jamais en double
CREATE TABLE IF NOT EXISTS a_traiter (
    id       INTEGER PRIMARY KEY,
    uid      TEXT,
    motif    TEXT NOT NULL,
    cle      TEXT NOT NULL,
    donnees  TEXT NOT NULL,
    cree_le  TEXT NOT NULL,
    UNIQUE (motif, cle)
);
-- Propositions écartées (« Ignorer », « Pas lui », « Pas la même personne ») : plus reproposées
CREATE TABLE IF NOT EXISTS ignores (
    motif TEXT NOT NULL,
    cle   TEXT NOT NULL,
    le    TEXT NOT NULL,
    PRIMARY KEY (motif, cle)
);
-- Liaisons contact ↔ Immich / Treemich ; une personne n'est liée qu'à un contact
CREATE TABLE IF NOT EXISTS liaisons (
    uid      TEXT NOT NULL,
    service  TEXT NOT NULL,          -- immich | treemich
    ext_id   TEXT NOT NULL,
    statut   TEXT NOT NULL,          -- auto | confirmee
    le       TEXT NOT NULL,
    PRIMARY KEY (uid, service),
    UNIQUE (service, ext_id)
);
CREATE TABLE IF NOT EXISTS refus (
    uid      TEXT NOT NULL,
    service  TEXT NOT NULL,
    ext_id   TEXT NOT NULL,
    PRIMARY KEY (uid, service, ext_id)
);
-- Portraits HD : candidats Immich et choix
CREATE TABLE IF NOT EXISTS portraits (
    uid        TEXT PRIMARY KEY,
    candidats  TEXT NOT NULL DEFAULT '[]',
    asset      TEXT,
    manuel     INTEGER NOT NULL DEFAULT 0,
    le         TEXT NOT NULL
);
-- Affiches plein écran (album Immich) et leur pose sur l'iPhone
CREATE TABLE IF NOT EXISTS affiches (
    uid        TEXT PRIMARY KEY,
    source     TEXT,                 -- asset Immich d'origine, ou « logo »
    immich     TEXT,                 -- asset de l'affiche dans l'album
    posee      TEXT,
    le         TEXT NOT NULL
);
-- Relations LinkedIn, reconnues par l'adresse de leur profil
CREATE TABLE IF NOT EXISTS linkedin (
    url        TEXT PRIMARY KEY,
    uid        TEXT,
    detachee   INTEGER NOT NULL DEFAULT 0,
    donnees    TEXT NOT NULL,
    le         TEXT NOT NULL
);
-- Écritures sûres en attente pour la nuit (LinkedIn quand la fiche portait l'ancienne valeur)
CREATE TABLE IF NOT EXISTS en_attente (
    uid      TEXT NOT NULL,
    motif    TEXT NOT NULL,
    donnees  TEXT NOT NULL,
    PRIMARY KEY (uid, motif)
);
-- Fiches validées : empreinte des champs audités au moment de la validation (carnet 2.1)
CREATE TABLE IF NOT EXISTS validations (
    uid       TEXT PRIMARY KEY,
    empreinte TEXT NOT NULL,
    le        TEXT NOT NULL
);
-- Personnes lues dans Telegram ou un export Instagram, en attente de rattachement (purgées à 90 jours)
CREATE TABLE IF NOT EXISTS personnes_externes (
    service  TEXT NOT NULL,
    ext_id   TEXT NOT NULL,
    nom      TEXT NOT NULL,
    donnees  TEXT NOT NULL,
    vu_le    TEXT NOT NULL,
    PRIMARY KEY (service, ext_id)
);
CREATE TABLE IF NOT EXISTS journal (
    id       INTEGER PRIMARY KEY,
    le       TEXT NOT NULL,
    type     TEXT NOT NULL,
    message  TEXT NOT NULL,
    details  TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_type ON journal(type, id);
-- Quelques valeurs isolées : référence iCloud, dernier passage de nuit, session…
CREATE TABLE IF NOT EXISTS kv (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);
"""


class Base:
    def __init__(self, chemin: Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin = chemin
        self.cx = sqlite3.connect(str(chemin), check_same_thread=False, isolation_level=None)
        self.cx.row_factory = sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.execute("PRAGMA foreign_keys=ON")
        self._verrou = threading.RLock()
        self.generation = 0
        with self._verrou:
            self.cx.executescript(SCHEMA)
            self.cx.execute(f"PRAGMA user_version = {VERSION}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._verrou:
            self.cx.execute("BEGIN IMMEDIATE")
            try:
                yield self.cx
            except BaseException:
                self.cx.execute("ROLLBACK")
                raise
            self.cx.execute("COMMIT")
            self.generation += 1

    def tous(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._verrou:
            return self.cx.execute(sql, params).fetchall()

    def un(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._verrou:
            return self.cx.execute(sql, params).fetchone()

    def executer(self, sql: str, params: tuple = ()) -> None:
        with self.transaction() as cx:
            cx.execute(sql, params)

    # ------------------------------------------------------------ valeurs isolées

    def lire(self, cle: str, defaut: Any = None) -> Any:
        ligne = self.un("SELECT valeur FROM kv WHERE cle = ?", (cle,))
        return json.loads(ligne["valeur"]) if ligne and ligne["valeur"] is not None else defaut

    def ecrire(self, cle: str, valeur: Any) -> None:
        self.executer("INSERT INTO kv(cle, valeur) VALUES (?, ?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                      (cle, json.dumps(valeur, ensure_ascii=False)))

    def noter(self, type_: str, message: str, details: Any = None, le: str | None = None) -> None:
        """Ligne de journal. Les journaux /ha/… n'y mettent jamais de nom ni de date."""
        from .temps import iso, maintenant
        self.executer("INSERT INTO journal(le, type, message, details) VALUES (?, ?, ?, ?)",
                      (le or iso(maintenant()), type_, message,
                       json.dumps(details, ensure_ascii=False) if details is not None else None))
        self.executer("DELETE FROM journal WHERE id NOT IN (SELECT id FROM journal ORDER BY id DESC LIMIT 2000)")

    def journal(self, type_: str | None = None, limite: int = 50) -> list[dict]:
        if type_:
            lignes = self.tous("SELECT * FROM journal WHERE type = ? ORDER BY id DESC LIMIT ?", (type_, limite))
        else:
            lignes = self.tous("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limite,))
        return [{"le": l["le"], "type": l["type"], "message": l["message"],
                 "details": json.loads(l["details"]) if l["details"] else None} for l in lignes]

    def fermer(self) -> None:
        with self._verrou:
            self.cx.close()
