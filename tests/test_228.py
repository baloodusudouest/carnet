"""2.28 : identifiant maison stable, alimentation, indicateur pour Home Assistant, base chiffrée
(SQLCipher) et notes du coffre Obsidian « Contacts »."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app import actions, alimentation, base as base_, coffre, connexion, icloud, liaisons, nuit, personnes, temps
from app.base import Base, CleInvalide, est_en_clair
from app.carnet import Carnet, ErreurCarnet

from .test_carnet import _config, carte_simple, services  # noqa: F401 — fixture réutilisée


@pytest.fixture
def c(tmp_path, services):  # noqa: F811
    (tmp_path / "coffre" / "Personnes").mkdir(parents=True)
    transports = {k: v.transport() for k, v in services.items()}
    cn = Carnet(_config(tmp_path, contacts=tmp_path / "coffre"), transports)
    cn.treemich().facteur_attente = 0
    with cn.ecriture():
        icloud.relire(cn, "test")
    return cn


def note(c, nom):
    return (c.cfg.contacts / "Personnes" / f"{nom}.md").read_text(encoding="utf-8")


# ================================================================ identifiant maison

def test_identifiant_cree_une_fois_et_stable(c, services):
    ids = personnes.ids(c)
    assert set(ids) == set(c.fiches()) and all(i.startswith("p-") and len(i) == 12 for i in ids.values())
    assert len(set(ids.values())) == len(ids)
    with c.ecriture():
        icloud.relire(c, "test")
    assert personnes.ids(c) == ids
    assert personnes.uid_de(c, ids["DDDD-4444"]) == "DDDD-4444"


def test_suppression_garde_identifiant_et_alimentation_annuler_rattache(c):
    ident = personnes.de(c, "DDDD-4444")
    alimentation.definir(c, "DDDD-4444", {"allergies": "arachide"})
    etag = c.base.un("SELECT etag FROM fiches WHERE uid = ?", ("DDDD-4444",))["etag"]
    res = actions.supprimer(c, "DDDD-4444", etag, True)
    assert personnes.uid_de(c, ident) is None
    assert alimentation.de_personne(c, ident)["allergies"] == ["arachide"]
    assert [p["id"] for p in personnes.sans_fiche(c)] == [ident]
    actions.annuler(c, res["jeton"])
    assert personnes.de(c, "DDDD-4444") == ident
    assert alimentation.fiche(c, "DDDD-4444")["statut"] == "a_connaitre"


def test_fusion_identifiant_garde_et_alimentation_suit(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("EEEE-5555", carte_simple("EEEE-5555", "Paul Martin", "TEL;type=CELL:+33 6 98 76 54 32\r\n"))
    with c.ecriture():
        icloud.relire(c)
    garde, absorbe = personnes.de(c, "DDDD-4444"), personnes.de(c, "EEEE-5555")
    alimentation.definir(c, "EEEE-5555", {"intolerances": ["lactose"], "verifiee_le": "2026-11-01"})
    prop = actions.proposition_fusion(c, "DDDD-4444", "EEEE-5555")
    actions.fusionner(c, "DDDD-4444", "EEEE-5555", prop["proposee"])
    assert personnes.de(c, "DDDD-4444") == garde
    assert personnes.uid_de(c, absorbe) == "DDDD-4444"                 # l'ancien identifiant suit la fusion
    a = alimentation.fiche(c, "DDDD-4444")
    assert a["intolerances"] == ["lactose"] and a["verifiee_le"] == "2026-11-01"


def test_rattacher_un_identifiant_a_une_carte_recreee(c, services):
    ident = personnes.de(c, "DDDD-4444")
    alimentation.definir(c, "DDDD-4444", {"aucune": True})
    etag = c.base.un("SELECT etag FROM fiches WHERE uid = ?", ("DDDD-4444",))["etag"]
    actions.supprimer(c, "DDDD-4444", etag, True)
    services["icloud"].modifier_sur_iphone("FFFF-6666", carte_simple("FFFF-6666", "Paul Martin"))
    with c.ecriture():
        icloud.relire(c)
    provisoire = personnes.de(c, "FFFF-6666")
    assert provisoire != ident
    personnes.rattacher(c, ident, "FFFF-6666")
    assert personnes.de(c, "FFFF-6666") == ident
    assert alimentation.fiche(c, "FFFF-6666")["statut"] == "aucune"
    with pytest.raises(ErreurCarnet):
        personnes.rattacher(c, ident, "AAAA-1111")                       # a déjà une fiche


# ================================================================ alimentation

def test_alimentation_saisie_statuts_et_garde_fous(c):
    a = alimentation.fiche(c, "AAAA-1111")
    assert a["statut"] == "inconnu" and a["allergies"] == []          # rien de dit : inconnu, jamais « rien »
    a = alimentation.definir(c, "AAAA-1111", {"allergies": "Arachide, noix ; arachide", "non_aimes": ["coriandre"],
                                              "plaisirs": "chocolat noir", "verifiee": True})
    assert a["allergies"] == ["Arachide", "noix"] and a["statut"] == "a_connaitre"
    assert a["non_aimes"] == ["coriandre"] and a["plaisirs"] == ["chocolat noir"]
    assert a["verifiee_le"] == temps.iso(temps.maintenant())[:10]          # heure de Paris (le CI tourne en UTC)
    with pytest.raises(ErreurCarnet):
        alimentation.definir(c, "AAAA-1111", {"allergies": ["noix"], "aucune": True})
    with pytest.raises(ErreurCarnet):
        alimentation.definir(c, "AAAA-1111", {"verifiee_le": "17/11/2026", "aucune": True})
    a = alimentation.definir(c, "AAAA-1111", {"aucune": True})
    assert a["statut"] == "aucune" and a["verifiee_le"] == temps.iso(temps.maintenant())[:10]   # date gardée
    assert alimentation.definir(c, "AAAA-1111", {})["statut"] == "inconnu"   # tout vidé : retour à inconnu
    assert not c.base.tous("SELECT 1 FROM alimentation")
    journal = " ".join(str(l) for l in c.base.journal("alimentation"))
    assert "Arachide" not in journal and "noix" not in journal and "chocolat" not in journal


def test_alimentation_jamais_dans_icloud(c, services):
    alimentation.definir(c, "DDDD-4444", {"allergies": ["sésame"]})
    assert "sésame" not in services["icloud"].texte("DDDD-4444")


def test_api_alimentation_et_home_assistant(c):
    from fastapi.testclient import TestClient
    from app import main
    main.ETAT["carnet"] = c
    with TestClient(main.app) as client:
        assert client.put("/api/contacts/DDDD-4444/alimentation", json={"allergies": ["kiwi"]}).status_code == 401
        main.ETAT["sessions"].connecte = lambda cookies: True
        r = client.put("/api/contacts/DDDD-4444/alimentation", json={"allergies": ["kiwi"], "verifiee_le": "2026-11-02"})
        assert r.status_code == 200 and r.json()["statut"] == "a_connaitre"
        fiche = client.get("/api/contacts/DDDD-4444").json()
        assert fiche["alimentation"]["allergies"] == ["kiwi"] and fiche["personne_id"].startswith("p-")
        h = {"Authorization": "Bearer jeton-ha"}
        assert client.get("/ha/allergies?nom=Paul MARTIN").status_code == 401
        liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
        inv = client.get("/ha/invite", params={"nom": "Paul MARTIN (2026-11-20 → 2026-11-22)"}, headers=h).json()
        assert inv["allergies"] == "a_connaitre" and inv["allergies_verifiees_le"] == "2026-11-02"
        assert inv["personne_id"] == fiche["personne_id"] and "kiwi" not in str(inv)
        par_id = client.get("/ha/allergies", params={"personne_id": fiche["personne_id"]}, headers=h).json()
        assert par_id == {"personne_id": fiche["personne_id"], "connue": True, "allergies": "a_connaitre",
                          "allergies_verifiees_le": "2026-11-02"}
        inconnu = client.get("/ha/allergies", params={"personne_id": "p-0000000000"}, headers=h).json()
        assert inconnu["allergies"] == "inconnu" and inconnu["connue"] is False
        assert client.get("/ha/allergies", params={"nom": "Personne Inconnue"}, headers=h).status_code == 404
        assert client.get("/ha/allergies", headers=h).status_code == 400
        assert all(x["personne_id"].startswith("p-") for x in client.get("/ha/contacts", headers=h).json()["contacts"])


# ================================================================ base chiffrée

def test_base_en_clair_chiffree_avec_la_cle_puis_illisible_sans(tmp_path):
    chemin = tmp_path / "carnet2.db"
    b = Base(chemin)
    b.ecrire("temoin", "valeur")
    b.executer("INSERT INTO personnes(id, uid, cree_le) VALUES ('p-0123456789', 'U1', 'x')")
    b.fermer()
    assert est_en_clair(chemin)
    b = Base(chemin, "une clé ' assez longue")
    assert b.chiffrement and b.chiffrement["tables"] > 10
    assert b.lire("temoin") == "valeur" and b.un("SELECT uid FROM personnes")["uid"] == "U1"
    assert dict(b.un("SELECT id, uid FROM personnes")) == {"id": "p-0123456789", "uid": "U1"}
    b.fermer()
    assert not est_en_clair(chemin)
    assert list(tmp_path.glob("carnet2.db.clair-*"))                   # copie pour revenir à la 2.27
    with pytest.raises(CleInvalide):
        Base(chemin)                                                   # chiffrée sans clé : refus, rien de créé
    with pytest.raises(CleInvalide):
        Base(chemin, "mauvaise clé")
    b = Base(chemin, "une clé ' assez longue")
    assert b.chiffrement is None and b.lire("temoin") == "valeur"
    b.fermer()


def test_copie_en_clair_effacee_apres_quatorze_jours(tmp_path):
    chemin = tmp_path / "carnet2.db"
    Base(chemin, "cle").fermer()
    vieille = tmp_path / f"carnet2.db.clair-{(datetime.now() - timedelta(days=15)):%Y%m%d}"
    recente = tmp_path / f"carnet2.db.clair-{(datetime.now() - timedelta(days=3)):%Y%m%d}"
    vieille.write_bytes(b"x")
    recente.write_bytes(b"x")
    Base(chemin, "cle").fermer()
    assert not vieille.exists() and recente.exists()


def test_carnet_complet_sur_base_chiffree(tmp_path, services):  # noqa: F811
    transports = {k: v.transport() for k, v in services.items()}
    cn = Carnet(_config(tmp_path, db_key="clé de test"), transports)
    with cn.ecriture():
        icloud.relire(cn, "test")
    alimentation.definir(cn, "AAAA-1111", {"allergies": ["noix"]})
    cn.base.fermer()
    assert not est_en_clair(tmp_path / "state" / "carnet2.db")
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(str(tmp_path / "state" / "carnet2.db")).execute("SELECT * FROM fiches").fetchall()
    cn2 = Carnet(_config(tmp_path, db_key="clé de test"), transports)
    assert alimentation.fiche(cn2, "AAAA-1111")["allergies"] == ["noix"]


def test_sonde_lit_une_copie_chiffree(tmp_path, monkeypatch):
    chemin = tmp_path / "carnet2.db"
    b = Base(chemin, "cle-sonde")
    b.executer("INSERT INTO fiches(uid, href, etag, texte, fiche, lu_le) VALUES ('U', 'h', 'e', 'BEGIN:VCARD', '{}', 'x')")
    b.fermer()
    from app import sonde_champs
    monkeypatch.setenv("CARNET_DB_KEY", "cle-sonde")
    assert sonde_champs.lire_cartes(chemin) == ["BEGIN:VCARD"]


# ================================================================ coffre Contacts

def test_coffre_garde_fou_dossier_non_monte(c, tmp_path):
    vide = tmp_path / "pas-monte"
    vide.mkdir()
    c.cfg = replace(c.cfg, contacts=vide)
    with pytest.raises(coffre.CoffreAbsent):
        coffre.synchroniser(c)
    assert not any(vide.iterdir())                                     # rien écrit dans un dossier vide
    assert coffre.sante(c)["etat"] == "erreur"


def test_coffre_cree_les_notes_des_personnes_seulement(c):
    alimentation.definir(c, "DDDD-4444", {"allergies": ["arachide"], "plaisirs": ["chocolat"], "verifiee_le": "2026-11-03"})
    b = coffre.synchroniser(c)
    noms = sorted(p.stem for p in (c.cfg.contacts / "Personnes").glob("*.md"))
    assert "Plomberie Garonne" not in noms and b["crees"] == len(noms) == 3
    paul = note(c, "Paul MARTIN")
    assert paul.startswith("---\npersonne_id: p-") and "carnet: présente" in paul
    assert "Allergies ou intolérances à connaître" in paul and "**Allergies** : arachide" in paul
    assert "**Vérifiée le** : 03/11/2026" in paul and "**Plaisirs coupables** : chocolat" in paul
    assert coffre.DEBUT in paul and coffre.FIN in paul and paul.rstrip().endswith("## Mes notes")
    claire = note(c, "Claire MARTIN")
    assert "[[Paul MARTIN|Paul Martin]]" in claire                     # lien vers la note du proche
    assert "Inconnu : à demander" in claire
    assert coffre.synchroniser(c)["inchangees"] == 3                   # rien de changé : rien de réécrit


def test_coffre_zone_libre_et_entete_a_la_main_gardees(c):
    coffre.synchroniser(c)
    chemin = c.cfg.contacts / "Personnes" / "Paul MARTIN.md"
    texte = chemin.read_text(encoding="utf-8")
    texte = texte.replace("---\n" + coffre.DEBUT, "tags:\n  - cousin\n---\nAvant le bloc, à moi.\n" + coffre.DEBUT, 1)
    texte += "Il préfère le thé. Secret de famille.\n"
    chemin.write_text(texte, encoding="utf-8")
    alimentation.definir(c, "DDDD-4444", {"intolerances": ["gluten"]})
    b = coffre.synchroniser(c)
    assert b["mises_a_jour"] == 1
    nouveau = chemin.read_text(encoding="utf-8")
    assert "**Intolérances** : gluten" in nouveau
    assert "Il préfère le thé. Secret de famille." in nouveau and "Avant le bloc, à moi." in nouveau
    assert "tags:\n  - cousin" in nouveau and nouveau.count("personne_id:") == 1


def test_coffre_note_deplacee_retrouvee_note_sans_bloc_respectee(c):
    coffre.synchroniser(c)
    racine = c.cfg.contacts
    (racine / "Famille").mkdir()
    os.replace(racine / "Personnes" / "Paul MARTIN.md", racine / "Famille" / "Paulo.md")
    claire = racine / "Personnes" / "Claire MARTIN.md"
    t = claire.read_text(encoding="utf-8")
    debut, fin = t.index(coffre.DEBUT), t.index(coffre.FIN) + len(coffre.FIN)
    claire.write_text(t[:debut] + "Tout réécrit à la main." + t[fin:], encoding="utf-8")
    alimentation.definir(c, "DDDD-4444", {"aucune": True})
    alimentation.definir(c, "AAAA-1111", {"aucune": True})
    b = coffre.synchroniser(c)
    assert b["crees"] == 0 and b["sans_bloc"] == 1 and b["mises_a_jour"] == 1
    assert "Aucune allergie ni intolérance connue" in (racine / "Famille" / "Paulo.md").read_text(encoding="utf-8")
    assert not (racine / "Personnes" / "Paul MARTIN.md").exists()
    assert "Tout réécrit à la main." in claire.read_text(encoding="utf-8")


def test_coffre_fiche_retiree_marquee_jamais_effacee(c):
    coffre.synchroniser(c)
    etag = c.base.un("SELECT etag FROM fiches WHERE uid = ?", ("DDDD-4444",))["etag"]
    actions.supprimer(c, "DDDD-4444", etag, True)
    b = coffre.synchroniser(c)
    assert b["retirees"] == 1
    paul = note(c, "Paul MARTIN")
    assert "carnet: retirée" in paul and "carnet: présente" not in paul and coffre.DEBUT in paul


def test_coffre_lecture_seule_et_connexion(c):
    c.cfg = replace(c.cfg, lecture_seule=True)
    with pytest.raises(ErreurCarnet):
        coffre.synchroniser(c)
    assert not list((c.cfg.contacts / "Personnes").glob("*.md"))
    c.cfg = replace(c.cfg, lecture_seule=False)
    res = connexion.synchroniser(c, "contacts")
    assert "3 note(s) créée(s)" in res["message"]
    ligne = next(s for s in connexion.etat(c, {}, {}) if s["cle"] == "contacts")
    assert ligne["synchronisable"] and ligne["nuit"]["actif"] is True


def test_nuit_ecrit_le_coffre_et_interrupteur(c, services):
    nuit.passer(c, "test")
    assert len(list((c.cfg.contacts / "Personnes").glob("*.md"))) == 3
    connexion.regler_nuit(c, "contacts", False)
    alimentation.definir(c, "DDDD-4444", {"allergies": ["moutarde"]})
    nuit.passer(c, "test")
    assert "moutarde" not in note(c, "Paul MARTIN")
