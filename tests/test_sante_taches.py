"""Santé des tâches de fond (2.32, socle 0.9.0) : /health porte version_socle, taches et copie_base ;
les messages d'erreur n'y sont qu'avec le jeton commun ; une nuit ratée fait passer la tâche « nuit » en retard."""
from __future__ import annotations

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app import main, maison, nuit
from app.carnet import Carnet

from .test_carnet import _config, c, services  # noqa: F401 — fixtures réutilisées


@pytest.fixture
def registre(monkeypatch):
    """Registre neuf pour chaque test (le registre du module vit le temps du processus)."""
    neuf = maison.Taches()
    monkeypatch.setattr(maison, "TACHES", neuf)
    return neuf


def test_health_porte_taches_et_copie(c, registre, monkeypatch):
    monkeypatch.setenv("MAISON_JETON", "jeton-commun-essai")
    main.ETAT["carnet"] = c
    try:
        with TestClient(main.app) as client:
            d = client.get("/health").json()
            assert d["ok"] is True and d["version"] == main.__version__
            assert d["version_socle"] == maison.VERSION_SOCLE == "0.11.1"
            noms = {t["nom"]: t for t in d["taches"]}
            assert {"nuit", "copie-des-bases", *main.TACHES_DEMANDE} <= set(noms)
            assert noms["nuit"]["type"] == "reguliere" and noms["nuit"]["periode_s"] == 86400
            assert noms["copie-des-bases"]["periode_s"] == 86400
            assert noms["import"]["type"] == "demande" and noms["import"]["etat"] == "jamais"
            assert all("message" not in t for t in d["taches"])          # sans jeton : pas de message
            assert d["copie_base"]["bases"] == ["carnet2.db"] and d["copie_base"]["le"] is None
            avec = client.get("/health", headers={"Authorization": "Bearer jeton-commun-essai"}).json()
            assert all("message" in t for t in avec["taches"])
            faux = client.get("/health", headers={"Authorization": "Bearer faux"}).json()
            assert all("message" not in t for t in faux["taches"])
    finally:
        main.ETAT.clear()


def test_nuit_ratee_passe_en_retard_sans_changer_le_bilan(c, registre, monkeypatch):
    nuit.declarer(c)
    monkeypatch.setattr(nuit, "passer", lambda c, origine="nuit": {"erreur": "iCloud injoignable (essai)"})
    bilan = nuit.passer_suivie(c)
    assert bilan == {"erreur": "iCloud injoignable (essai)"}            # l'appelant voit le même bilan qu'avant
    t = {x["nom"]: x for x in registre.etat(avec_messages=True)}["nuit"]
    assert t["etat"] == "en_retard" and t["derniere_erreur"] and "iCloud injoignable" in t["message"]
    monkeypatch.setattr(nuit, "passer", lambda c, origine="nuit": {"erreur": None})
    nuit.passer_suivie(c)
    assert {x["nom"]: x for x in registre.etat()}["nuit"]["etat"] == "ok"


def test_nuit_desactivee_devient_a_la_demande(tmp_path, registre):
    cn = Carnet(_config(tmp_path, veille_heure="off"))
    nuit.declarer(cn)
    assert {x["nom"]: x for x in registre.etat()}["nuit"]["type"] == "demande"


def test_operation_a_la_main_ratee_passe_en_erreur(c, registre):
    main.ETAT["carnet"] = c
    try:
        main.declarer_taches(c)

        def casse():
            raise RuntimeError("Immich répond 500 (essai)")
        main._fond("liens", casse)
        import time
        for _ in range(100):
            if c.tache.get("etat") != "en_cours":
                break
            time.sleep(0.02)
        t = {x["nom"]: x for x in registre.etat()}["liens"]
        assert t["etat"] == "erreur" and c.tache["etat"] == "erreur"   # carnet le dit comme avant
    finally:
        main.ETAT.clear()


def test_base_chiffree_copiee_avec_sa_cle(tmp_path):
    """Socle 0.9.1 : la copie de nuit d'une base chiffrée (SQLCipher) s'ouvre avec la même clé et reste chiffrée."""
    from app.base import connecter, est_en_clair
    base = tmp_path / "carnet2.db"
    cx = connecter(base, "cle-d-essai-pour-copie")
    cx.execute("CREATE TABLE t(x)"); cx.execute("INSERT INTO t VALUES (42)"); cx.commit(); cx.close()
    ouvrir = lambda chemin, lecture_seule=False: connecter(Path(chemin), "cle-d-essai-pour-copie", timeout=30)
    r = maison.copier_bases([base], tmp_path / "copies", ouvrir)
    copie = tmp_path / "copies" / "carnet2-derniere.db"
    assert r["ok"] is True and not est_en_clair(copie)
    assert connecter(copie, "cle-d-essai-pour-copie").execute("SELECT x FROM t").fetchall() == [(42,)]
