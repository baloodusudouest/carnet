"""2.26 : réglages d'usage dans l'appli (reprise une fois depuis la stack), sauvegarde pour l'Anneau, restauration."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main, maison, nuit, reglages
from app.carnet import Carnet
from app.temps import ZONE
from tests.test_carnet import _config

ANCIENNES = ("CARNET_VEILLE_HEURE", "CARNET_EMOJI_GROUPES", "CARNET_SYNOLOGY_CARNET", "CARNET_SYNOLOGY_VERIFIER_TLS")


@pytest.fixture(autouse=True)
def environnement(monkeypatch):
    for v in (*ANCIENNES, "MAISON_JETON", "MAISON_JETON_ANCIEN", "CARNET_LECTURE_SEULE", "MAISON_LECTURE_SEULE"):
        monkeypatch.delenv(v, raising=False)
    yield
    main.LIRE_ANNEAU = None


def journal(c) -> list[str]:
    return [j["message"] for j in c.base.journal("reglages", limite=100)]


def test_reprise_des_anciennes_variables_une_seule_fois(tmp_path, monkeypatch):
    monkeypatch.setenv("CARNET_VEILLE_HEURE", "4:15")
    monkeypatch.setenv("CARNET_EMOJI_GROUPES", "🍕:Amis")
    monkeypatch.setenv("CARNET_SYNOLOGY_CARNET", "Contacts du NAS")
    monkeypatch.setenv("CARNET_SYNOLOGY_VERIFIER_TLS", "non")
    c = Carnet(_config(tmp_path))
    r = reglages.tout(c)
    assert r["veille_heure"] == "04:15" and r["emoji_groupes"] == "🍕:Amis"
    assert r["synology_carnet"] == "Contacts du NAS" and r["synology_verifier_tls"] is False
    assert c.cfg.veille_heure == "04:15" and c.cfg.synology_verifier_tls is False and c.cfg.nuit_active
    assert c.synology().nom_carnet == "Contacts du NAS"
    from app import normalisation
    assert normalisation.EMOJI_GROUPES == {"🍕": "Amis"}
    lignes = journal(c)
    assert len(lignes) == 4 and all("repris de la variable" in l for l in lignes)
    assert json.loads((tmp_path / "state" / "reglages.json").read_text())["veille_heure"] == "04:15"
    # Second démarrage : les variables (même changées) ne sont plus lues
    monkeypatch.setenv("CARNET_VEILLE_HEURE", "05:00")
    monkeypatch.setenv("CARNET_SYNOLOGY_VERIFIER_TLS", "oui")
    c2 = Carnet(_config(tmp_path))
    assert c2.cfg.veille_heure == "04:15" and c2.cfg.synology_verifier_tls is False
    assert len(journal(c2)) == 4                                        # aucune nouvelle reprise


def test_defauts_sans_variable_et_reprise_impossible(tmp_path, monkeypatch):
    for sous in "abc":
        (tmp_path / sous).mkdir()
    c = Carnet(_config(tmp_path / "a"))
    r = reglages.tout(c)
    assert r["veille_heure"] == "03:00" and r["synology_verifier_tls"] is True
    assert r["synology_carnet"] == "My Contacts|Mes contacts"
    assert not journal(c)
    assert set(r) == {"emoji_groupes", "veille_heure", "synology_carnet", "synology_verifier_tls",
                      "auto_fetes", "auto_famille", "nuit_immich", "nuit_synology", "nuit_kit", "nuit_contacts"}
    monkeypatch.setenv("CARNET_VEILLE_HEURE", "25:00")                  # heure impossible : défaut, et c'est dit
    c = Carnet(_config(tmp_path / "b"))
    assert c.cfg.veille_heure == "03:00"
    assert any("Heure de la nuit" in l for l in journal(c))
    monkeypatch.setenv("CARNET_VEILLE_HEURE", "off")                    # « off » : nuit désactivée, gardée
    c = Carnet(_config(tmp_path / "c"))
    assert c.cfg.veille_heure == "off" and not c.cfg.nuit_active


def connecte(c) -> TestClient:
    main.ETAT["carnet"] = c
    client = TestClient(main.app)
    client.__enter__()
    assert client.post("/api/connexion", json={"mot_de_passe": "secret"}).status_code == 200
    return client


def test_api_reglages_changer_et_mauvais_types(tmp_path):
    c = Carnet(_config(tmp_path))
    main.ETAT["carnet"] = c
    with TestClient(main.app) as anonyme:
        assert anonyme.get("/api/reglages").status_code == 401
        assert anonyme.put("/api/reglages", json={"veille_heure": "04:00"}).status_code == 401
    client = connecte(c)
    try:
        d = client.get("/api/reglages").json()
        assert d["reglages"]["veille_heure"] == "03:00" and d["lecture_seule"] is False
        c.reveil.clear()
        r = client.put("/api/reglages", json={"veille_heure": "04:30", "synology_verifier_tls": False,
                                              "emoji_groupes": "🔧:Artisans et services;🍕:Amis", "nuit_kit": False})
        assert r.status_code == 200, r.text
        assert r.json()["reglages"]["veille_heure"] == "04:30" and r.json()["reglages"]["nuit_kit"] is False
        assert c.cfg.veille_heure == "04:30" and c.cfg.synology_verifier_tls is False
        assert c.reveil.is_set()                                         # la nuit recalcule son heure
        assert any("veille_heure" in l for l in journal(c))
        assert c.base.lire("nuit_kit") is False
        # mauvais types et valeurs : 400, message clair, rien n'est changé
        for corps, mot in (({"synology_verifier_tls": "peut-être"}, "oui ou non"),
                           ({"veille_heure": 4}, "texte attendu"),
                           ({"veille_heure": "27:99"}, "HH:MM"),
                           ({"emoji_groupes": "🍕Amis"}, "émoji:groupe"),
                           ({"nuit_immich": "oui"}, "oui ou non"),
                           ({"inconnu": 1}, "inconnu"),
                           ({"veille_heure": "05:00", "synology_carnet": ["liste"]}, "texte attendu")):
            r = client.put("/api/reglages", json=corps)
            assert r.status_code == 400 and mot in r.json()["detail"], (corps, r.text)
        assert c.cfg.veille_heure == "04:30"
        r = client.put("/api/reglages", json={"reglages": {"veille_heure": "off"}})     # forme {"reglages": {...}}
        assert r.status_code == 200 and not c.cfg.nuit_active
    finally:
        client.__exit__(None, None, None)


def test_la_nuit_suit_l_heure_sans_redemarrer(tmp_path, monkeypatch):
    c = Carnet(_config(tmp_path))
    reglages.changer(c, {"veille_heure": "off"})
    passages = []
    vu = threading.Event()

    def faux_passer(cn, origine="nuit"):
        passages.append(cn.cfg.veille_heure)
        vu.set()
        reglages.changer(cn, {"veille_heure": "off"})                 # une seule fois
    monkeypatch.setattr(nuit, "passer", faux_passer)
    monkeypatch.setattr(nuit, "prochaine", lambda heure, apres: datetime.now(ZONE) + timedelta(seconds=0.2))
    nuit.demarrer(c)
    time.sleep(0.3)
    assert not passages                                                  # nuit désactivée : rien
    reglages.changer(c, {"veille_heure": "02:10"})                        # réglée : la boucle se réveille
    assert vu.wait(5) and passages == ["02:10"]


def test_externe_sauvegarde(tmp_path, monkeypatch):
    c = Carnet(_config(tmp_path))
    main.ETAT["carnet"] = c
    with TestClient(main.app) as client:
        h = {"Authorization": "Bearer jeton-commun"}
        assert client.get("/externe/sauvegarde", headers=h).status_code == 404        # MAISON_JETON vide : fermée
        monkeypatch.setenv("MAISON_JETON", "jeton-commun")
        monkeypatch.setenv("CARNET_JETON_SILLAGE", "ancien-jeton")
        assert client.get("/externe/sauvegarde").status_code == 404
        assert client.get("/externe/sauvegarde", headers={"Authorization": "Bearer ancien-jeton"}).status_code == 404
        assert client.get("/externe/sauvegarde", headers={"Authorization": "Bearer jeton-ha"}).status_code == 404
        r = client.get("/externe/sauvegarde", headers=h)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        d = r.json()
        assert d["contrat"] == 1 == maison.CONTRAT_SAUVEGARDE and d["appli"] == "carnet"
        assert d["version"] == main.__version__
        assert set(d["reglages"]) == set(reglages.tout(c))
        texte = r.text
        for interdit in ("secret", "abcd-efgh", "moi@icloud", "jeton", "nas:4001", "tm\"", str(tmp_path)):
            assert interdit not in texte, interdit
        assert client.get("/externe/sauvegarde", headers={"X-Maison-Jeton": "jeton-commun"}).status_code == 200
        # une clé exclue ou un nom de secret ne sort jamais, même s'il entrait dans les réglages
        vrai_tout = reglages.tout
        monkeypatch.setattr(reglages, "tout", lambda cn: {**vrai_tout(cn), "synology_url": "https://nas.exemple",
                                                         "icloud_password": "x", "lecture_seule": True})
        d = client.get("/externe/sauvegarde", headers=h).json()
        assert not {"synology_url", "icloud_password", "lecture_seule"} & set(d["reglages"])
        assert set(reglages.EXCLUS) >= {"synology_url", "lecture_seule"}
        assert client.get("/health").json() == {"ok": True, "version": main.__version__}


def faux_anneau(sauvegardes: dict, appels: list | None = None):
    def lire(adresse, jeton):
        if appels is not None:
            appels.append((adresse, jeton))
        if "?le=" not in adresse:
            return {"dates": sorted(sauvegardes, reverse=True)}
        le = adresse.rsplit("=", 1)[1]
        if le not in sauvegardes:
            raise urllib.error.HTTPError(adresse, 404, "Not Found", {}, None)
        return {"le": le, "version": "2.26.0", "reglages": sauvegardes[le]}
    return lire


def test_restaurer(tmp_path, monkeypatch):
    monkeypatch.setenv("MAISON_JETON", "jeton-commun")
    monkeypatch.setenv("CARNET_LECTURE_SEULE", "oui")                  # restaurer reste permis en lecture seule
    c = Carnet(_config(tmp_path, lecture_seule=True))
    appels = []
    main.LIRE_ANNEAU = faux_anneau({
        "2026-11-15": {"veille_heure": "05:45", "synology_verifier_tls": False, "nuit_kit": False,
                       "emoji_groupes": "🔧:Artisans et services", "cle_disparue": "x", "un_jeton": "y"},
        "2026-11-14": {"veille_heure": "03:00"},
    }, appels)
    client = connecte(c)
    try:
        assert client.get("/api/restaurer").json() == {"dates": ["2026-11-15", "2026-11-14"]}
        assert appels[0] == ("http://anneau:8094/externe/sauvegardes/carnet", "jeton-commun")
        d = client.get("/api/restaurer", params={"le": "2026-11-15"}).json()
        assert d["le"] == "2026-11-15" and d["version"] == "2.26.0"
        assert {x["cle"]: (x["actuel"], x["sauve"]) for x in d["differences"]} == {
            "veille_heure": ("03:00", "05:45"), "synology_verifier_tls": (True, False), "nuit_kit": (True, False)}
        r = client.post("/api/restaurer", json={"le": "2026-11-15"})
        assert r.status_code == 200, r.text
        assert r.json()["reglages"]["veille_heure"] == "05:45" and r.json()["changes"] == ["nuit_kit", "synology_verifier_tls", "veille_heure"]
        assert c.cfg.veille_heure == "05:45" and c.cfg.synology_verifier_tls is False and c.base.lire("nuit_kit") is False
        assert any("restaurés depuis la sauvegarde du 2026-11-15" in l for l in journal(c))
        assert client.get("/api/restaurer", params={"le": "2026-11-15"}).json()["differences"] == []
        # date inconnue : 404 clair ; sans date : 400
        r = client.get("/api/restaurer", params={"le": "2026-01-01"})
        assert r.status_code == 404 and "pas de sauvegarde" in r.json()["detail"]
        assert client.post("/api/restaurer", json={}).status_code == 400
        # Anneau injoignable : 503 et message, rien de cassé
        def injoignable(adresse, jeton):
            raise urllib.error.URLError("refused")
        main.LIRE_ANNEAU = injoignable
        for r in (client.get("/api/restaurer"), client.post("/api/restaurer", json={"le": "2026-11-15"})):
            assert r.status_code == 503 and "Anneau injoignable" in r.json()["detail"]
        # sans MAISON_JETON et sans faux Anneau : message clair
        main.LIRE_ANNEAU = None
        monkeypatch.delenv("MAISON_JETON")
        r = client.get("/api/restaurer")
        assert r.status_code == 503 and "MAISON_JETON" in r.json()["detail"]
    finally:
        client.__exit__(None, None, None)


def test_lire_sauvegarde_du_module_avec_faux_anneau():
    """Le faux Anneau passe aussi par l'argument lire= du module commun (sans réseau)."""
    r = maison.lire_sauvegarde("carnet", "2026-11-15", url="http://anneau:8094", jeton="j",
                               lire=faux_anneau({"2026-11-15": {"veille_heure": "01:00"}}))
    assert r["reglages"] == {"veille_heure": "01:00"}
