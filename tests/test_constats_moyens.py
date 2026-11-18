"""Constats moyens de l'audit du 17/11/2026 (M12 à M15) : écriture des dates vers Treemich une par une,
routes async qui ne bloquent plus la boucle, /status réduit sans session, plafond de pixels des images reçues."""
from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from app import famille, galerie
from app.carnet import ErreurCarnet

from .test_carnet import _relier_le_couple, c, services  # noqa: F401 — fixtures réutilisées


# ================================================================ M12 : une date, une relecture

def _deces(*cibles: str) -> list[dict]:
    return [{"service": "treemich", "sujet": "deces", "cible": t, "uid": "", "avant": "", "apres": "2024-02-03",
             "nom": f"Personne {t}", "texte": f"décès de {t}"} for t in cibles]


def test_m12_treemich_qui_ne_garde_pas_arrete_a_la_premiere_date(c, services, monkeypatch):
    tm = services["treemich"]
    d = _relier_le_couple(c)
    famille.regler(c, "famille", True)
    monkeypatch.setattr(famille, "examiner", lambda c, d: {"actions": _deces("t-un", "t-deux", "t-trois")})
    tm.oublie = True
    bilan = {"ecrites": 0, "reportees": 0, "details": [], "treemich": 0}
    famille.appliquer(c, d, bilan, 20, fetes_aussi=False)
    envois = [e for e in tm.ecrits if "deathDate" in (e[1] or {})]
    assert len(envois) == 1                                   # avant : les trois dates partaient avant la relecture
    assert not famille.actif(c, "famille") and any("coupé" in x for x in bilan["details"])


def test_m12_plafond_par_passage(c, services, monkeypatch):
    tm = services["treemich"]
    d = _relier_le_couple(c)
    famille.regler(c, "famille", True)
    monkeypatch.setattr(famille, "examiner", lambda c, d: {"actions": _deces("t-un", "t-deux", "t-trois")})
    bilan = {"ecrites": 0, "reportees": 0, "details": [], "treemich": 0}
    famille.appliquer(c, d, bilan, 2, fetes_aussi=False)
    assert bilan["treemich"] == 2 and bilan["reportees"] == 1
    assert set(tm.deces) == {"t-un", "t-deux"} and famille.actif(c, "famille")


# ================================================================ M13 : rien de bloquant dans la boucle

def _dans_la_boucle() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def test_m13_logo_et_import_hors_de_la_boucle(c, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    vu: dict[str, bool] = {}

    def logo(c, uid, contenu=None, url=None):
        vu["logo"] = _dans_la_boucle()
        return {"n": 0}

    def lire(contenu, region):
        vu["import"] = _dans_la_boucle()
        return [], []

    monkeypatch.setattr(main.galerie, "deposer_logo", logo)
    monkeypatch.setattr(main.vcard, "lire", lire)
    main.ETAT["carnet"] = c
    try:
        with TestClient(main.app) as client:
            assert client.post("/api/connexion", json={"mot_de_passe": "secret"}).status_code == 200
            assert client.post("/api/contacts/AAAA-1111/logo-depose", content=b"\x89PNG...").status_code == 200
            r = client.post("/api/import", params={"nom": "a.vcf"}, content=b"BEGIN:VCARD\r\nEND:VCARD\r\n")
            assert r.status_code == 200
    finally:
        main.ETAT.clear()
    assert vu == {"logo": False, "import": False}


# ================================================================ M14 : /status réduit sans session

def test_m14_status_sans_session_sans_messages_d_erreur(c):
    from fastapi.testclient import TestClient
    from app import main
    secret_syno = "Synology a refusé l'utilisateur carnet-essai"
    secret_icloud = "iCloud : mot de passe d'application refusé pour essai@exemple.invalid"
    c.base.ecrire("synology", {"erreur": secret_syno, "crees": 0, "modifies": 0, "supprimes": 0})
    c.base.ecrire("nuit", {"le": "2026-11-18T03:00:00", "erreur": secret_icloud, "erreur_lecture": secret_icloud})
    main.ETAT["carnet"] = c
    try:
        with TestClient(main.app) as client:
            c.tache = {"nom": "essai", "etat": "erreur", "message": secret_icloud}
            reduit = client.get("/status").json()
            texte = str(reduit)
            assert secret_syno not in texte and secret_icloud not in texte
            # mêmes champs pour le paquet Home Assistant, erreur toujours signalée
            assert reduit["sauvegarde"]["ok"] is False and reduit["sauvegarde"]["erreur"]
            assert reduit["veille"]["ok"] is False and reduit["veille"]["erreur"]
            assert "a_reviser" in reduit and reduit["tache"] == {"nom": "essai", "etat": "erreur"}
            # jeton de Home Assistant : tout le détail
            ha = {"authorization": "Bearer " + c.cfg.ha_token}
            complet = client.get("/status", headers=ha).json()
            assert complet["sauvegarde"]["erreur"] == secret_syno and complet["veille"]["erreur"] == secret_icloud
            assert client.get("/status", headers={"authorization": "Bearer faux"}).json()["sauvegarde"]["erreur"] != secret_syno
            # session ouverte : tout le détail
            assert client.post("/api/connexion", json={"mot_de_passe": "secret"}).status_code == 200
            assert client.get("/status").json()["tache"]["message"] == secret_icloud
    finally:
        main.ETAT.clear()


# ================================================================ M15 : plafond de pixels

def test_m15_image_trop_grande_refusee_avant_decodage(c):
    sortie = io.BytesIO()
    Image.new("1", (6000, 6000)).save(sortie, "PNG")          # 36 millions de pixels, quelques dizaines de Ko
    assert len(sortie.getvalue()) < galerie.POIDS_MAX
    with pytest.raises(ErreurCarnet, match="trop grande"):
        galerie.deposer_logo(c, "AAAA-1111", contenu=sortie.getvalue())
