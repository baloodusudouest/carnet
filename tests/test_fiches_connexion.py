"""Fiches « Connexion » communes (contrat 3, socle 0.11.0) : forme de /api/maison/services, accès par session ou
ANNEAU_CLE seulement (jamais MAISON_JETON), « Vérifier » d'un service pas relié n'essaie rien, copies non retouchées
du module commun et de l'interface commune."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main, maison
from app.reglages import ID_APPLI as APPLI

from .test_carnet import _config, c, services  # noqa: F401 — fixtures réutilisées

RACINE = Path(__file__).resolve().parent.parent
CLE = "cle-anneau-de-test-1234567890"
IDS = ['icloud', 'immich', 'treemich', 'synology-contacts', 'home-assistant', 'kit-urgence', 'millesime', 'coffre-contacts']


@pytest.fixture
def client(c):
    """carnet de test (faux iCloud, Immich, Treemich, Synology) servi par l'appli, sans session."""
    main.ETAT["carnet"] = c
    try:
        with TestClient(main.app) as cl:
            yield cl
    finally:
        main.ETAT.clear()


def connecter(client):
    assert client.post("/api/connexion", json={"mot_de_passe": "secret"}).status_code == 200


CHAMPS = {"id", "nom", "genre", "cible", "etat", "lit", "ecrit", "reglage", "detail", "verifie_le", "guide",
          "derniere_ecriture", "gestes"}


def test_forme_du_contrat_3(client):
    connecter(client)
    r = client.get("/api/maison/services")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    corps = r.json()
    assert corps["contrat"] == 3 and corps["appli"] == APPLI and corps["simule"] is False
    assert [s["id"] for s in corps["services"]] == IDS
    for s in corps["services"]:
        assert set(s) == CHAMPS and s["lit"] and s["ecrit"] and s["etat"] in maison.ETATS_SERVICE
        assert len(s["gestes"]) <= 1
        if s["etat"] == "pas_relie":
            assert s["reglage"]


def test_acces_session_ou_cle_anneau(client, monkeypatch):
    assert client.get("/api/maison/services").status_code == 401
    monkeypatch.setenv("MAISON_JETON", "jeton-commun-de-test-12345")
    entete = {"Authorization": "Bearer jeton-commun-de-test-12345"}
    assert client.get("/api/maison/services", headers=entete).status_code == 401
    monkeypatch.setenv("ANNEAU_CLE", CLE)
    assert client.get("/api/maison/services", headers={"Authorization": f"Bearer {CLE}"}).status_code == 200
    assert client.get("/api/maison/services", headers={"Authorization": "Bearer mauvaise"}).status_code == 401


def test_verifier_inconnu_et_pas_relie(client):
    connecter(client)
    assert client.post("/api/maison/services/inconnu/verifier").status_code == 404
    for s in client.get("/api/maison/services").json()["services"]:
        if s["etat"] == "pas_relie":
            apres = client.post(f"/api/maison/services/{s['id']}/verifier").json()
            assert apres["etat"] == "pas_relie" and apres["verifie_le"] is None


def test_copies_communes_non_retouchees():
    assert maison.CONTRAT == 3 and maison.VERSION_SOCLE == "0.11.1"
    assert maison.empreinte_calculee() == maison.empreinte_ecrite()
    for nom in maison.FICHIERS_INTERFACE:
        ecrite, calculee = maison.empreinte_interface(RACINE / "frontend" / "src" / "lib" / "services" / nom)
        assert ecrite and ecrite == calculee, nom


def test_propre_a_carnet_gestes_et_essais_legers(client, services):
    """carnet : un geste par service qui écrit (Synchroniser d'iCloud…), aucun pour Home Assistant ni Millésime ;
    « Vérifier » d'iCloud et de Synology ne lit aucune carte et n'écrit rien ; un service sans réglage est « pas relié »."""
    connecter(client)
    fiches = {s["id"]: s for s in client.get("/api/maison/services").json()["services"]}
    assert fiches["icloud"]["gestes"] == [{"id": "synchroniser", "nom": "Synchroniser"}]
    assert fiches["synology-contacts"]["gestes"] == [{"id": "copier", "nom": "Copier maintenant"}]
    assert fiches["kit-urgence"]["gestes"][0]["nom"] == "Envoyer au kit"
    assert not fiches["home-assistant"]["gestes"] and not fiches["millesime"]["gestes"]
    assert fiches["kit-urgence"]["genre"] == "maison" and fiches["kit-urgence"]["cible"] == "kit-urgence"
    assert fiches["millesime"]["etat"] == "pas_relie" and fiches["millesime"]["reglage"] == "MAISON_JETON"
    assert fiches["coffre-contacts"]["etat"] == "pas_relie"
    assert fiches["icloud"]["etat"] == "relie" and fiches["icloud"]["verifie_le"] is None
    avant = (list(services["icloud"].ecritures), list(services["synology"].ecritures))
    for sid in ("icloud", "synology-contacts", "immich", "treemich"):
        apres = client.post(f"/api/maison/services/{sid}/verifier").json()
        assert apres["verifie_le"] and apres["etat"] in ("repond", "ne_repond_pas"), apres
    assert client.post("/api/maison/services/icloud/verifier").json()["etat"] == "repond"
    assert (services["icloud"].ecritures, services["synology"].ecritures) == avant
    ha = client.post("/api/maison/services/home-assistant/verifier").json()
    assert ha["etat"] == "relie" and ha["verifie_le"] is None              # carnet n'appelle pas Home Assistant


def test_un_geste_reussi_sert_d_essai(client, monkeypatch):
    connecter(client)
    from app import connexion
    monkeypatch.setattr(connexion, "synchroniser", lambda c, s: {"message": "Copie Synology : 0 créée(s)."})
    assert client.post("/api/connexion/synology/synchroniser").status_code == 200
    import time
    for _ in range(50):
        if main.carnet().tache.get("etat") != "en_cours":
            break
        time.sleep(0.05)
    fiche = next(s for s in client.get("/api/maison/services").json()["services"] if s["id"] == "synology-contacts")
    assert fiche["etat"] == "repond" and fiche["detail"].startswith("Copie Synology")
