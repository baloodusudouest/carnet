"""3.1 : adresse commune des événements envoyés par les applis, compteurs, et dossier complet d'une personne dans le
coffre Contacts (fiches liées Allergies, Pépites, Récidives, Gazette, Livre d'or, Douze points, Séjours, Sillage,
Arbre ; rangement unique des notes de la 3.0). Personnes et données inventées."""
from __future__ import annotations

import os
import tarfile

import pytest

from app import alimentation, coffre, evenements as E, liaisons, personnes, traiter
from app.carnet import ErreurCarnet

from .test_228 import c, note  # noqa: F401 — fixture réutilisée
from .test_carnet import services  # noqa: F401

PAUL, CLAIRE = "DDDD-4444", "AAAA-1111"


def _client(c, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    main.ETAT["carnet"] = c
    monkeypatch.setenv("MAISON_JETON", "jeton-commun-essai")
    return TestClient(main.app)


COMMUN = {"Authorization": "Bearer jeton-commun-essai"}


def _sejour(paul_id):
    return {"type": "sejour", "date": "2026-08-14", "titre": "Séjour — Chambre d'Ami", "resume": "Trois nuits",
            "lien": "https://gazette.exemple/#/livret/12",
            "personnes": [{"personne_id": paul_id, "role": "invité"}, {"nom": "Claire MARTIN", "role": "invitée"},
                          {"nom": "Inconnu TOTAL"}]}


# ================================================================ réception

def test_31_evenement_recu_reconnu_partiel_et_jeton(c, monkeypatch):  # noqa: F811
    paul = personnes.de(c, PAUL)
    with _client(c, monkeypatch) as client:
        assert client.put("/evenements/gazette/sejour-12", json=_sejour(paul)).status_code == 401
        r = client.put("/evenements/gazette/sejour-12", headers=COMMUN, json=_sejour(paul))
        assert r.status_code == 200 and r.json()["reconnues"] == 2 and r.json()["a_rattacher"] == ["Inconnu TOTAL"]
        assert client.put("/evenements/Gazette/x", headers=COMMUN, json=_sejour(paul)).status_code == 400
        assert client.put("/evenements/gazette/sejour-12", headers=COMMUN,
                          json={**_sejour(paul), "type": "fête"}).status_code == 400
        assert client.put("/evenements/gazette/sejour-12", headers=COMMUN,
                          json={**_sejour(paul), "lien": "javascript:alert(1)"}).status_code == 400
    assert [e["cle"] for e in E.de_personne(c, paul)] == ["sejour-12"]
    assert E.de_personne(c, personnes.de(c, CLAIRE))[0]["role"] == "invitée"
    # la personne inconnue est dans À traiter, comptée dans le chiffre de l'onglet
    tuile = next(t for t in traiter.tuiles(c) if t["cle"] == "evenements")
    assert tuile["nombre"] == 1 and tuile["compte"] and traiter.compte(c)["evenements"] == 1


def test_31_immich_puis_rattachement_garde_au_renvoi(c, monkeypatch):  # noqa: F811
    liaisons.lier(c, PAUL, "immich", "im-paul")
    corps = {"type": "douze_points", "date": "2026-05-16", "titre": "Soirée Eurovision 2026",
             "personnes": [{"immich_id": "im-paul", "donnees": {"moyenne": 7.5, "classement": 2, "top3": ["Suède", "Italie", "France"]}},
                           {"nom": "Tata Josette", "donnees": {"moyenne": 6}}]}
    r = E.recevoir(c, "douze-points", "soiree-3", corps)
    assert r["reconnues"] == 1 and r["a_rattacher"] == ["Tata Josette"]
    ligne = E.a_rattacher(c)[0]
    E.rattacher(c, ligne["id"], CLAIRE)
    assert E.a_rattacher(c) == []
    E.recevoir(c, "douze-points", "soiree-3", corps)                      # renvoyé : le rattachement à la main reste
    assert E.a_rattacher(c) == [] and len(E.de_personne(c, personnes.de(c, CLAIRE))) == 1
    assert E.retirer(c, "douze-points", "soiree-3") == {"retire": True}
    assert E.de_personne(c, personnes.de(c, PAUL)) == []
    E.recevoir(c, "douze-points", "soiree-4", {**corps, "personnes": [{"nom": "Quelqu'un"}]})
    E.ecarter(c, E.a_rattacher(c)[0]["id"])
    assert E.a_rattacher(c) == []
    with pytest.raises(ErreurCarnet):
        E.recevoir(c, "douze-points", "soiree-5", {**corps, "personnes": [{"role": "sans nom"}]})


def test_31_compteurs_photos_scandale(c, monkeypatch):  # noqa: F811
    paul, claire = personnes.de(c, PAUL), personnes.de(c, CLAIRE)
    with _client(c, monkeypatch) as client:
        r = client.put("/compteurs/gazette/photos_scandale", headers=COMMUN,
                       json={"personnes": [{"personne_id": paul, "valeur": 7}, {"nom": "Claire MARTIN", "valeur": 0},
                                           {"nom": "Personne INCONNUE", "valeur": 3}], "complet": True})
        assert r.json() == {"enregistres": 2, "inconnues": 1}
        assert client.put("/compteurs/gazette/photos_scandale", json={"personnes": []}).status_code == 401
        fiche = client.get(f"/api/contacts/{PAUL}", cookies={})
    assert E.compteur(c, paul, "gazette", "photos_scandale") == 7
    E.recevoir_compteur(c, "gazette", "photos_scandale", {"personnes": [{"personne_id": claire, "valeur": 2}], "complet": True})
    assert E.compteur(c, paul, "gazette", "photos_scandale") is None and E.compteur(c, claire, "gazette", "photos_scandale") == 2
    assert fiche.status_code == 401                                      # la fiche demande une session


def test_31_ha_personnes_donne_les_identifiants(c):  # noqa: F811
    from app import sorties
    liaisons.lier(c, PAUL, "immich", "im-paul")
    p = sorties.ha_personnes(c)["personnes"]
    assert p == [{"nom": "Paul MARTIN", "immich": True, "personne_id": personnes.de(c, PAUL), "immich_id": "im-paul"}]


# ================================================================ coffre : dossier complet

def test_31_coffre_sejours_douze_points_gazette(c):  # noqa: F811
    paul = personnes.de(c, PAUL)
    E.recevoir(c, "gazette", "sejour-12", _sejour(paul))
    E.recevoir(c, "douze-points", "soiree-3", {"type": "douze_points", "date": "2026-05-16", "titre": "Soirée Eurovision 2026",
                                                "lien": "https://douze.exemple/#/soiree/3",
                                                "personnes": [{"personne_id": paul, "donnees": {"moyenne": 7.5, "classement": 2}}]})
    E.recevoir_compteur(c, "gazette", "photos_scandale", {"personnes": [{"personne_id": paul, "valeur": 7}]})
    b = coffre.synchroniser(c)
    racine = c.cfg.contacts
    sejour = (racine / "Événements" / "Séjours" / "2026-08-14 — Séjour — Chambre d'Ami.md").read_text(encoding="utf-8")
    assert "[Ouvrir dans Gazette](https://gazette.exemple/#/livret/12)" in sejour and "Trois nuits" in sejour
    assert "[[Paul MARTIN]]" in sejour and "[[Claire MARTIN]]" in sejour and "Inconnu" not in sejour
    soiree = (racine / "Événements" / "Douze points" / "2026-05-16 — Soirée Eurovision 2026.md").read_text(encoding="utf-8")
    assert "Note moyenne : 7.5" in soiree and "Classement : 2" in soiree
    dossier = racine / "Personnes" / "Paul MARTIN"
    idx = (dossier / "Paul MARTIN — Douze points.md").read_text(encoding="utf-8")
    assert "[[2026-05-16 — Soirée Eurovision 2026]] — note 7.5, classement 2" in idx
    assert "[[2026-08-14 — Séjour — Chambre d'Ami]]" in (dossier / "Paul MARTIN — Séjours.md").read_text(encoding="utf-8")
    assert "**Photos scandale** : 7" in (dossier / "Paul MARTIN — Gazette.md").read_text(encoding="utf-8")
    contact = note(c, "Paul MARTIN")
    for titre in ("Séjours", "Douze points", "Gazette"):
        assert f"[[Paul MARTIN — {titre}|{titre}]]" in contact
    assert "Paul MARTIN — Pépites" not in contact                       # seulement s'il y a du contenu
    assert b["evenements"] == 2
    assert coffre.synchroniser(c)["mises_a_jour"] == 0                  # rien de changé : rien de réécrit


def test_31_rangement_unique_des_notes_30(c):  # noqa: F811
    from app import journaux as J
    paul = personnes.de(c, PAUL)
    coffre.synchroniser(c)                                              # notes Contact de la 3.0 déjà là
    J.ajouter(c, paul, {"rubrique": "animaux", "texte": "Un chat nommé Pompon"}, "carnet")
    J.ecrire_paru(c, paul, "recidive-2026-11-19", {"journal": "recidive", "numero": 3, "le": "2026-11-19"})
    racine = c.cfg.contacts
    dossier = racine / "Personnes" / "Paul MARTIN"
    (dossier / "Paul MARTIN — Pour les journaux.md").write_text(
        f"---\nindex_de: {paul}\ntype: index\nindex_type: journaux\n---\n{coffre.DEBUT}\nvieux\n{coffre.FIN}\n\n## Mes notes\n\nÀ garder.\n",
        encoding="utf-8")
    vieux_evt = racine / "Événements" / "La Récidive" / "2026-11-19 — La Récidive N° 3.md"
    vieux_evt.parent.mkdir(parents=True)
    vieux_evt.write_text(f"---\nevenement_id: paru-recidive-2026-11-19\n---\n{coffre.DEBUT}\nx\n{coffre.FIN}\n\nSoirée mémorable.\n",
                         encoding="utf-8")
    b = coffre.synchroniser(c)
    pepites = dossier / "Paul MARTIN — Pépites.md"
    assert b["rangees"] == 2 and pepites.exists() and not (dossier / "Paul MARTIN — Pour les journaux.md").exists()
    texte = pepites.read_text(encoding="utf-8")
    assert "À garder." in texte and "index_type: pepites" in texte and "vieux" not in texte
    nouvel_evt = racine / "Événements" / "Récidives" / vieux_evt.name
    assert nouvel_evt.exists() and "Soirée mémorable." in nouvel_evt.read_text(encoding="utf-8")
    assert not vieux_evt.parent.exists()                                # ancien dossier vide retiré
    assert coffre.synchroniser(c)["rangees"] == 0                       # une seule fois


def test_31_sillage_lu_une_fois_jamais_vide(c, monkeypatch):  # noqa: F811
    liaisons.lier(c, PAUL, "immich", "im-paul")
    appels = []
    reponse = {"valeur": None}

    def faux(_c, imm):
        appels.append(imm)
        return reponse["valeur"]
    monkeypatch.setattr(coffre, "LIRE_SILLAGE", faux)
    coffre.synchroniser(c)                                              # Sillage injoignable : rien créé
    dossier = c.cfg.contacts / "Personnes" / "Paul MARTIN"
    assert not (dossier / "Paul MARTIN — Sillage.md").exists()
    reponse["valeur"] = [{"nom": "Naissance à Agen", "annee": 1985}, {"nom": "Mariage", "annee": 2012}]
    coffre.synchroniser(c)
    texte = (dossier / "Paul MARTIN — Sillage.md").read_text(encoding="utf-8")
    assert "- 1985 — Naissance à Agen" in texte and "- 2012 — Mariage" in texte
    n = len(appels)
    reponse["valeur"] = None
    coffre.synchroniser(c)                                              # gardé 24 h : pas relu, pas vidé
    assert len(appels) == n and "Mariage" in (dossier / "Paul MARTIN — Sillage.md").read_text(encoding="utf-8")


def test_31_arbre_sans_treemich_lu_note_non_touchee(c):  # noqa: F811
    assert coffre.arbre(c) is None or isinstance(coffre.arbre(c), dict)
    c.oublier("liens")
    liaisons.lier(c, PAUL, "treemich", "t-paul")
    coffre.synchroniser(c)
    assert not (c.cfg.contacts / "Personnes" / "Paul MARTIN" / "Paul MARTIN — Arbre.md").exists()


def test_31_allergies_fiche_liee_et_copie_avant_nuit(c):  # noqa: F811
    alimentation.definir(c, PAUL, {"allergies": ["arachide"], "non_aimes": ["coriandre"]})
    coffre.synchroniser(c)
    copie = coffre.copier_avant_nuit(c)
    assert copie and copie.exists()
    with tarfile.open(copie) as tar:
        noms = tar.getnames()
    assert "Personnes/Paul MARTIN/Paul MARTIN — Allergies.md" in noms and not any(n.startswith(".") for n in noms)
    vieux = copie.with_name("2020-01-01.tar.gz")
    vieux.write_bytes(b"")
    coffre.copier_avant_nuit(c)
    assert not vieux.exists() and copie.exists()
    assert not [p for p in c.cfg.contacts.rglob("*.md") if "." in p.stem]
    assert not any(p.name.startswith(".carnet-") for p in c.cfg.contacts.rglob("*"))
    assert os.path.isdir(c.cfg.state)
