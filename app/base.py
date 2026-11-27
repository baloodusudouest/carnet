"""Base SQLite de carnet 2 (fichier carnet2.db dans /state, hors partage).

Une table par sujet, schéma versionné (PRAGMA user_version). Une seule connexion protégée par
un verrou : carnet n'a qu'un utilisateur et des accès courts. Chaque écriture incrémente un
compteur de génération, qui sert à invalider les calculs gardés en mémoire.

2.28 : la base peut être chiffrée par SQLCipher (clé `CARNET_DB_KEY`). Avec une clé, une base encore
en clair est chiffrée au démarrage (copie en clair gardée 14 jours pour un retour arrière, puis
effacée) ; sans clé, une base chiffrée refuse de s'ouvrir plutôt que d'en créer une vide.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("carnet")

VERSION = 12  # 2 : validations, personnes_externes (2.1) ; 3 : attentes, exceptions, unions, décès (2.8) ; 4 : genres (2.22) ;
              # 5 : personnes, alimentation (2.28) ; 6 : journaux (2.29) ; 7 : journaux_parus (2.30) ; 8 : livre_or (2.31) ;
              # 9 : journaux_pepites (2.33) ; 10 : evenements, evenements_personnes, compteurs (3.1) ;
              # 11 : alimentation.note, alimentation_operations (3.5) ; 12 : arbre_masques (3.6)
ENTETE_CLAIR = b"SQLite format 3\x00"
GARDE_CLAIR = timedelta(days=14)     # copie en clair d'avant le chiffrement, pour revenir à la 2.27 : effacée ensuite

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
-- 2.12 : photo ou affiche choisie dans Photos depuis la dernière recherche (la ligne est alors repliée)
CREATE TABLE IF NOT EXISTS choisis (
    uid        TEXT NOT NULL,
    sorte      TEXT NOT NULL,        -- « photo » ou « affiche »
    le         TEXT NOT NULL,
    PRIMARY KEY (uid, sorte)
);

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
-- ---- 2.8 (schéma 3) : uniquement des ajouts, la 2.7 rouvre la base sans rien perdre ----
-- Une ligne par case cochée du tableau « quelles informations chaque groupe doit avoir »
CREATE TABLE IF NOT EXISTS attentes (
    groupe TEXT NOT NULL,
    info   TEXT NOT NULL,
    PRIMARY KEY (groupe, info)
);
-- « Normal pour ce contact » : un manque précis qu'on ne signale plus
CREATE TABLE IF NOT EXISTS exceptions (
    uid  TEXT NOT NULL,
    info TEXT NOT NULL,
    le   TEXT NOT NULL,
    PRIMARY KEY (uid, info)
);
-- Couples de Treemich (a < b) : dernier état lu, et la réponse « pas de mariage ni PACS »
CREATE TABLE IF NOT EXISTS unions (
    a         TEXT NOT NULL,
    b         TEXT NOT NULL,
    mariage   TEXT,
    divorce   TEXT,
    sans      INTEGER NOT NULL DEFAULT 0,
    ignoree   TEXT,              -- dates différentes déjà écartées (« Ignorer »)
    lu_le     TEXT,
    PRIMARY KEY (a, b)
);
-- Décès connus de carnet : date si elle existe, origine icloud / treemich / main
CREATE TABLE IF NOT EXISTS deces (
    uid     TEXT PRIMARY KEY,
    date    TEXT,
    origine TEXT NOT NULL,
    le      TEXT NOT NULL
);
-- Dernière recherche de logo par fiche (pour ne pas rechercher sans fin)
CREATE TABLE IF NOT EXISTS logos_cherches (
    uid      TEXT PRIMARY KEY,
    le       TEXT NOT NULL,
    trouves  INTEGER NOT NULL DEFAULT 0
);
-- Logo retenu pour une société : posé sur toutes ses fiches sans photo, reproposé aux suivantes
CREATE TABLE IF NOT EXISTS logos_societes (
    cle     TEXT PRIMARY KEY,    -- nom de la société, sans accents ni casse
    nom     TEXT NOT NULL,
    image   BLOB NOT NULL,
    le      TEXT NOT NULL
);
-- Écritures faites par carnet tout seul (fête, mariage, décès), avec la valeur d'avant
CREATE TABLE IF NOT EXISTS automatiques (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    le       TEXT NOT NULL,
    service  TEXT NOT NULL,      -- icloud / treemich
    sujet    TEXT NOT NULL,      -- fete / mariage / deces
    cible    TEXT NOT NULL,      -- uid de la fiche, ou « a|b » pour un couple, ou id Treemich
    avant    TEXT,
    apres    TEXT,
    defaite  TEXT
);
CREATE INDEX IF NOT EXISTS idx_automatiques_le ON automatiques(le);
-- ---- 2.22 (schéma 4) : un ajout, la 2.21 rouvre la base sans rien perdre ----
-- Genre d'une personne : choisi dans carnet (origine « main ») ou lu dans Treemich
CREATE TABLE IF NOT EXISTS genres (
    uid     TEXT PRIMARY KEY,
    genre   TEXT NOT NULL,       -- femme / homme / autre
    origine TEXT NOT NULL,       -- main / treemich
    le      TEXT NOT NULL
);
-- ---- 2.28 (schéma 5) : deux ajouts, la 2.27 rouvre une base en clair sans rien perdre ----
-- Identifiant maison stable d'une personne. L'UID iCloud n'est qu'un attribut : il change quand une
-- carte est fusionnée, supprimée puis recréée ; l'identifiant, lui, reste. Une fiche retirée garde son
-- identifiant (uid vide, ancien_uid gardé) ; une fiche absorbée par une fusion pointe vers celle gardée.
CREATE TABLE IF NOT EXISTS personnes (
    id            TEXT PRIMARY KEY,          -- « p- » + 10 caractères hexadécimaux
    uid           TEXT UNIQUE,               -- fiche iCloud actuelle ; vide si retirée ou fusionnée
    ancien_uid    TEXT,
    remplacee_par TEXT,                      -- identifiant gardé après une fusion
    cree_le       TEXT NOT NULL,
    retiree_le    TEXT
);
-- Alimentation d'une personne (par identifiant maison, jamais écrite dans iCloud) : allergies,
-- intolérances, « aucune connue », date de vérification, aliments non aimés, plaisirs coupables.
CREATE TABLE IF NOT EXISTS alimentation (
    personne      TEXT PRIMARY KEY,
    allergies     TEXT NOT NULL DEFAULT '[]',
    intolerances  TEXT NOT NULL DEFAULT '[]',
    aucune        INTEGER NOT NULL DEFAULT 0,  -- « aucune allergie ni intolérance connue », dit par Julien
    verifiee_le   TEXT,
    non_aimes     TEXT NOT NULL DEFAULT '[]',
    plaisirs      TEXT NOT NULL DEFAULT '[]',
    le            TEXT NOT NULL
);
-- ---- 2.29 (schéma 6) : un ajout, la 2.28 rouvre la base sans rien perdre ----
-- « Pour les journaux » : ce que Julien sait d'une personne, pour les rumeurs de Gazette (jamais dans iCloud)
CREATE TABLE IF NOT EXISTS journaux (
    personne TEXT PRIMARY KEY,
    texte    TEXT NOT NULL,
    le       TEXT NOT NULL,
    par      TEXT NOT NULL           -- carnet / gazette
);
-- 2.30 : « Journaux parus » — un numéro approuvé dans Gazette (La Récidive) : date du séjour, N°, événement, indices,
-- descriptions des photos et textes imprimés, pour que les numéros suivants ne se répètent pas (jamais dans iCloud)
CREATE TABLE IF NOT EXISTS journaux_parus (
    personne TEXT NOT NULL,
    cle      TEXT NOT NULL,          -- « recidive-AAAA-MM-JJ » : un numéro par séjour, remplacé s'il est réapprouvé
    le       TEXT NOT NULL,          -- date du séjour (AAAA-MM-JJ)
    donnees  TEXT NOT NULL,          -- JSON
    maj      TEXT NOT NULL,
    PRIMARY KEY (personne, cle)
);
-- 2.31 : livre d'or de la maison — les mots que les invités laissent depuis leur chambre (carte Home Assistant),
-- envoyés par Home Assistant à chaque signature ; rattachés à la fiche de chaque signataire reconnu (personne vide :
-- pas encore rattaché, à rattacher depuis une fiche). Jamais dans iCloud.
CREATE TABLE IF NOT EXISTS livre_or (
    id       INTEGER PRIMARY KEY,
    cle      TEXT NOT NULL UNIQUE,   -- un même mot renvoyé n'entre pas deux fois
    personne TEXT NOT NULL DEFAULT '',
    nom      TEXT NOT NULL,          -- le nom tel que Home Assistant l'a envoyé
    message  TEXT NOT NULL,
    chambre  TEXT NOT NULL DEFAULT '',
    le       TEXT NOT NULL,          -- début du séjour (AAAA-MM-JJ)
    recu     TEXT NOT NULL
);
-- ---- 2.33 (schéma 9) : un ajout, la 2.32 rouvre la base sans rien perdre ----
-- « Fiche complète » pour les journaux (Gazette, La Récidive) : une ligne par pépite (un détail court sur une
-- personne, rangé dans une rubrique). Écrite pépite par pépite par carnet ou Gazette, avec contrôle de `le`.
-- `interdit` = 1 : « Sujets interdits » (jamais envoyés à l'IA). Jamais dans iCloud.
CREATE TABLE IF NOT EXISTS journaux_pepites (
    id       TEXT PRIMARY KEY,       -- « pp- » + 12 caractères hexadécimaux
    personne TEXT NOT NULL,          -- identifiant maison
    rubrique TEXT NOT NULL,          -- clé de app/rubriques_journaux.json, ou « interdits »
    texte    TEXT NOT NULL,          -- 200 caractères au plus
    interdit INTEGER NOT NULL DEFAULT 0,
    source   TEXT NOT NULL,          -- julien / carnet / recidive / sillage
    parue_le TEXT,                   -- date du numéro approuvé où elle a servi (AAAA-MM-JJ), vide sinon
    le       TEXT NOT NULL,          -- dernière modification (contrôle des écritures concurrentes)
    par      TEXT NOT NULL           -- carnet / gazette / migration
);
CREATE INDEX IF NOT EXISTS idx_journaux_pepites_personne ON journaux_pepites(personne);
-- ---- 3.1 (schéma 10) : événements envoyés par les applis (adresse commune), voir app/evenements.py ----
CREATE TABLE IF NOT EXISTS evenements (
    appli   TEXT NOT NULL,
    cle     TEXT NOT NULL,
    type    TEXT NOT NULL,           -- sejour, gazette, recidive, douze_points, livre_or, autre
    date    TEXT NOT NULL,           -- AAAA-MM-JJ
    titre   TEXT NOT NULL DEFAULT '',
    resume  TEXT NOT NULL DEFAULT '',
    lien    TEXT NOT NULL DEFAULT '',   -- page de l'événement dans l'appli
    maj     TEXT NOT NULL,
    PRIMARY KEY (appli, cle)
);
CREATE TABLE IF NOT EXISTS evenements_personnes (
    id       INTEGER PRIMARY KEY,
    appli    TEXT NOT NULL,
    cle      TEXT NOT NULL,
    personne TEXT NOT NULL DEFAULT '',  -- identifiant maison ; vide : pas reconnue (À traiter)
    nom      TEXT NOT NULL DEFAULT '',
    immich   TEXT NOT NULL DEFAULT '',
    role     TEXT NOT NULL DEFAULT '',
    donnees  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_evt_personnes_personne ON evenements_personnes(personne);
CREATE INDEX IF NOT EXISTS idx_evt_personnes_evt ON evenements_personnes(appli, cle);
-- compteurs par personne envoyés par une appli (ex. Gazette : photos_scandale)
-- ---- 3.5 (schéma 11) : modifications d'alimentation venues de Home Assistant, gardées pour qu'un renvoi
-- (file d'attente de Home Assistant) ne s'applique pas deux fois. La colonne alimentation.note est ajoutée au démarrage.
CREATE TABLE IF NOT EXISTS alimentation_operations (
    id       TEXT PRIMARY KEY,       -- identifiant donné par Home Assistant
    personne TEXT NOT NULL,
    le       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS compteurs (
    personne TEXT NOT NULL,
    appli    TEXT NOT NULL,
    nom      TEXT NOT NULL,
    valeur   INTEGER NOT NULL,
    maj      TEXT NOT NULL,
    PRIMARY KEY (personne, appli, nom)
);
-- ---- 3.6 (schéma 12) : personnes de l'arbre (identifiant Treemich) jamais montrées aux invités dans l'arbre de Sillage
CREATE TABLE IF NOT EXISTS arbre_masques (
    treemich TEXT PRIMARY KEY,
    le       TEXT NOT NULL
);
"""


class CleInvalide(RuntimeError):
    """Base chiffrée sans clé, clé fausse, ou clé posée sans SQLCipher : carnet ne démarre pas."""


def _sqlcipher():
    try:
        import sqlcipher3
    except ImportError as exc:   # pragma: no cover — l'image contient toujours SQLCipher
        raise CleInvalide("CARNET_DB_KEY est posée mais SQLCipher n'est pas installé dans l'image.") from exc
    return sqlcipher3


def _pragma_cle(cle: str) -> str:
    return "PRAGMA key = '" + cle.replace("'", "''") + "'"


def est_en_clair(chemin: Path) -> bool:
    """Vrai si le fichier existe et commence par l'entête d'une base SQLite non chiffrée."""
    if not chemin.is_file() or chemin.stat().st_size == 0:
        return False
    with chemin.open("rb") as f:
        return f.read(16) == ENTETE_CLAIR


def connecter(chemin: Path, cle: str = "", **kw):
    """Connexion à une base carnet, chiffrée ou non. Aussi utilisée par les sondes (copie de la base).
    Lève CleInvalide si la clé ne correspond pas, ou si la base est chiffrée et qu'aucune clé n'est donnée."""
    if not cle:
        if chemin.is_file() and chemin.stat().st_size and not est_en_clair(chemin):
            raise CleInvalide("La base carnet2.db est chiffrée mais CARNET_DB_KEY est absente de la stack : "
                              "carnet ne démarre pas (rien n'est créé ni effacé).")
        return sqlite3.connect(str(chemin), **kw)
    cx = _sqlcipher().connect(str(chemin), **kw)
    cx.execute(_pragma_cle(cle))
    try:
        cx.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception as exc:   # noqa: BLE001 — « file is not a database » : clé fausse
        cx.close()
        raise CleInvalide("CARNET_DB_KEY ne correspond pas à la base carnet2.db : carnet ne démarre pas "
                          "(vérifie la valeur rangée dans le gestionnaire de mots de passe).") from exc
    return cx


def chiffrer_si_besoin(chemin: Path, cle: str) -> dict | None:
    """Base en clair + clé : copie chiffrée vérifiée (mêmes tables, mêmes nombres de lignes), puis bascule.
    La base en clair est gardée à côté (carnet2.db.clair-AAAAMMJJ) pour un retour à la 2.27, et effacée
    après GARDE_CLAIR. Renvoie le bilan, ou None s'il n'y avait rien à faire."""
    _effacer_copies_claires(chemin)
    if not cle or not est_en_clair(chemin):
        return None
    sq = _sqlcipher()
    neuve = chemin.with_name(chemin.name + ".chiffrement")
    for f in (neuve, Path(str(neuve) + "-wal"), Path(str(neuve) + "-shm")):
        f.unlink(missing_ok=True)
    source = sq.connect(str(chemin))
    try:
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        tables = [r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                               "AND name NOT LIKE 'sqlite_%'")]
        comptes = {t: source.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        version = source.execute("PRAGMA user_version").fetchone()[0]
        source.execute(f"ATTACH DATABASE '{str(neuve).replace(chr(39), chr(39) * 2)}' AS chiffree "
                       f"KEY '{cle.replace(chr(39), chr(39) * 2)}'")
        source.execute("SELECT sqlcipher_export('chiffree')")
        source.execute(f"PRAGMA chiffree.user_version = {int(version)}")
        source.execute("DETACH DATABASE chiffree")
    finally:
        source.close()
    verif = connecter(neuve, cle)
    try:
        for t, n in comptes.items():
            if verif.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] != n:
                raise CleInvalide(f"Chiffrement de la base : la table {t} n'a pas le même nombre de lignes. "
                                  "Rien n'a été basculé, la base en clair est intacte.")
    finally:
        verif.close()
    claire = chemin.with_name(f"{chemin.name}.clair-{datetime.now().strftime('%Y%m%d')}")
    os.replace(chemin, claire)
    for suffixe in ("-wal", "-shm"):
        Path(str(chemin) + suffixe).unlink(missing_ok=True)
    os.replace(neuve, chemin)
    log.info("Base chiffrée par SQLCipher (%d tables) ; copie en clair gardée %d jours : %s",
             len(comptes), GARDE_CLAIR.days, claire.name)
    return {"tables": len(comptes), "lignes": sum(comptes.values()), "copie_claire": claire.name}


def _effacer_copies_claires(chemin: Path) -> None:
    """Efface les copies en clair d'avant le chiffrement une fois GARDE_CLAIR passé."""
    limite = datetime.now() - GARDE_CLAIR
    for f in chemin.parent.glob(chemin.name + ".clair-*"):
        try:
            if datetime.strptime(f.name.rsplit("-", 1)[1], "%Y%m%d") < limite:
                f.unlink()
                log.info("Copie en clair d'avant le chiffrement effacée : %s", f.name)
        except (ValueError, OSError):
            continue


class Base:
    def __init__(self, chemin: Path, cle: str = ""):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin = chemin
        self.chiffree = bool(cle)
        self.chiffrement = chiffrer_si_besoin(chemin, cle)    # 2.28 : base en clair + clé → chiffrée
        self.cx = connecter(chemin, cle, check_same_thread=False, isolation_level=None)
        self.cx.row_factory = _sqlcipher().Row if cle else sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.execute("PRAGMA foreign_keys=ON")
        self._verrou = threading.RLock()
        self.generation = 0
        with self._verrou:
            self.cx.executescript(SCHEMA)
            self._completer_colonnes()
            self.cx.execute(f"PRAGMA user_version = {VERSION}")

    # Colonnes ajoutées après coup à une table existante (une base d'une version précédente les reçoit vides)
    COLONNES = {("alimentation", "note"): "TEXT NOT NULL DEFAULT ''"}     # 3.5 : note d'hôte

    def _completer_colonnes(self) -> None:
        for (table, colonne), definition in self.COLONNES.items():
            presentes = {r[1] for r in self.cx.execute(f'PRAGMA table_info("{table}")').fetchall()}
            if colonne not in presentes:
                self.cx.execute(f'ALTER TABLE "{table}" ADD COLUMN "{colonne}" {definition}')
                log.info("Base : colonne %s.%s ajoutée", table, colonne)

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
