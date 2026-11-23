"""3.5 : conjoint et couple dans Treemich, raison d'un blocage sur la fiche, point « Conjoint manquant dans Treemich » ;
alimentation vers et depuis Home Assistant (listes, note d'hôte, ajouts et retraits, renvoi sans doublon) ; séjours
envoyés par Home Assistant ; suppression d'un mot du livre d'or. Fiches d'essai inventées (Claire et Paul MARTIN)."""
from __future__ import annotations

import pytest

from app import actions, alimentation, coffre, famille, journaux, liaisons, personnes, traiter
from app.carnet import ErreurCarnet

from .test_228 import c  # noqa: F401 — fixture réutilisée (coffre Contacts compris)
from .test_carnet import _ecrire_champ, services  # noqa: F401


H = {"Authorization": "Bearer jeton-ha"}


def _client(c):
    from fastapi.testclient import TestClient
    from app import main
    main.ETAT["carnet"] = c
    return TestClient(main.app)


# ================================================================ conjoint, couple, raisons

def test_conjoint_nomme_et_raison_sans_conjoint(c, services):  # noqa: F811
    tm = services["treemich"]
    tm.couple = False
    liaisons.lier(c, "AAAA-1111", "treemich", "t-claire")
    _ecrire_champ(c, "AAAA-1111", mariage="12/06/2010", noms_associes=[])     # la fiche d'essai nomme Paul : retiré
    liaisons.donnees(c, rafraichir=True)
    assert famille.conjoint_nomme(c, "AAAA-1111") is None
    raisons = famille.raisons_de(c, "AAAA-1111")
    assert any("aucun conjoint n'est choisi" in r for r in raisons)
    # Le point « Conjoint manquant dans Treemich » existe, sans création possible
    p = [x for x in traiter.liste(c) if x["motif"] == "conjoint_treemich"]
    assert len(p) == 1 and p[0]["tuile"] == "treemich" and p[0]["donnees"]["possible"] is False
    # Conjoint nommé sur la fiche, mais pas relié à l'arbre
    _ecrire_champ(c, "AAAA-1111", noms_associes=[{"valeur": "Paul MARTIN", "type": "conjoint"}])
    assert famille.conjoint_nomme(c, "AAAA-1111") == "DDDD-4444"
    assert any("n'est pas relié" in r for r in famille.raisons_de(c, "AAAA-1111"))
    # Relié : le point propose de créer le couple
    liaisons.lier(c, "DDDD-4444", "treemich", "t-paul")
    liaisons.donnees(c, rafraichir=True)
    p = [x for x in traiter.liste(c) if x["motif"] == "conjoint_treemich"]
    assert len(p) == 1 and p[0]["donnees"]["possible"] is True and p[0]["donnees"]["conjoint_uid"] == "DDDD-4444"
    assert any("Créer le couple" in r for r in famille.raisons_de(c, "AAAA-1111"))


def test_creer_couple_depuis_a_traiter_puis_date_accordee(c, services):  # noqa: F811
    tm = services["treemich"]
    tm.couple = False
    liaisons.lier(c, "AAAA-1111", "treemich", "t-claire")
    liaisons.lier(c, "DDDD-4444", "treemich", "t-paul")
    f = c.fiche("AAAA-1111")
    _ecrire_champ(c, "AAAA-1111", mariage="12/06/2010",
                  noms_associes=(f.get("noms_associes") or []) + [{"valeur": "Paul MARTIN", "type": "conjoint"}])
    liaisons.donnees(c, rafraichir=True)
    p = next(x for x in traiter.liste(c) if x["motif"] == "conjoint_treemich")
    res = actions.repondre(c, p["id"], "creer", None)
    assert res["cree"] is True and "créé dans Treemich" in res["message"]
    assert tm.couple is True and tm.mariages == {("t-claire", "t-paul"): "2010-06-12"}
    assert any(chemin.endswith("/relationships") and corps.get("type") == "SPOUSE_OF" for chemin, corps in tm.ecrits)
    # La carte de Paul reçoit la date (iCloud) ; le point a disparu
    assert c.fiche("DDDD-4444")["mariage"] == "2010-06-12"
    assert not [x for x in traiter.liste(c) if x["motif"] == "conjoint_treemich"]
    # Deuxième fois : le couple existe déjà, rien n'est recréé
    assert famille.creer_couple(c, "AAAA-1111", "DDDD-4444")["cree"] is False


def test_creer_couple_refuse_ou_oublie_par_treemich(c, services):  # noqa: F811
    tm = services["treemich"]
    tm.couple = False
    liaisons.lier(c, "AAAA-1111", "treemich", "t-claire")
    liaisons.lier(c, "DDDD-4444", "treemich", "t-paul")
    tm.refuse_couple = True
    with pytest.raises(ErreurCarnet, match="refusé de créer le couple"):
        famille.creer_couple(c, "AAAA-1111", "DDDD-4444")
    tm.refuse_couple, tm.oublie = False, True
    with pytest.raises(ErreurCarnet, match="n'a pas gardé le couple"):
        famille.creer_couple(c, "AAAA-1111", "DDDD-4444")
    # Une fiche non reliée : jamais de personne créée dans Treemich
    tm.oublie = False
    liaisons.delier(c, "DDDD-4444", "treemich")
    nb = len(tm.ecrits)
    with pytest.raises(ErreurCarnet, match="carnet n'y crée jamais de personne"):
        famille.creer_couple(c, "AAAA-1111", "DDDD-4444")
    assert len(tm.ecrits) == nb


def test_lier_conjoint_ecrit_les_deux_cartes(c, services):  # noqa: F811
    tm = services["treemich"]
    tm.couple = False
    _ecrire_champ(c, "AAAA-1111", mariage="12/06/2010", noms_associes=[])
    res = famille.lier_conjoint(c, "AAAA-1111", "DDDD-4444")
    noms = lambda u: [(n["valeur"].casefold(), n["type"]) for n in c.fiche(u).get("noms_associes") or []]  # noqa: E731
    assert ("paul martin", "conjoint") in noms("AAAA-1111") and ("claire martin", "conjoint") in noms("DDDD-4444")
    assert "Rien dans Treemich" in res["message"] and not tm.ecrits
    # Une deuxième fois : rien n'est réécrit
    assert "carte(s) iCloud" not in famille.lier_conjoint(c, "AAAA-1111", "DDDD-4444")["message"]


def test_api_fiche_dit_la_raison_et_le_conjoint(c, services):  # noqa: F811
    services["treemich"].couple = False
    liaisons.lier(c, "AAAA-1111", "treemich", "t-claire")
    _ecrire_champ(c, "AAAA-1111", noms_associes=[])
    liaisons.donnees(c, rafraichir=True)
    with _client(c) as client:
        from app import main
        main.ETAT["sessions"].connecte = lambda cookies: True
        f = client.get("/api/contacts/AAAA-1111").json()
        assert f["famille"] == {"raisons": [], "conjoint": None}
        f["fiche"]["mariage"] = "12/06/2010"
        apercu = client.post("/api/contacts/AAAA-1111/apercu", json={"fiche": f["fiche"]}).json()
        r = client.put("/api/contacts/AAAA-1111", json={"fiche": apercu["fiche"], "etag": f["etag"]}).json()
        assert any("aucun conjoint" in x for x in r["raisons"])
        assert any("aucun conjoint" in x for x in client.get("/api/contacts/AAAA-1111").json()["famille"]["raisons"])


# ================================================================ alimentation et Home Assistant

def test_note_d_hote_et_annuaire(c):  # noqa: F811
    a = alimentation.definir(c, "DDDD-4444", {"allergies": "arachide", "plaisirs": ["chocolat noir"],
                                              "note": "  arrive toujours en avance  "})
    assert a["note"] == "arrive toujours en avance" and a["statut"] == "a_connaitre"
    # Une modification sans « note » ne l'efface pas
    assert alimentation.definir(c, "DDDD-4444", {"allergies": "arachide"})["note"] == "arrive toujours en avance"
    with pytest.raises(ErreurCarnet):
        alimentation.definir(c, "DDDD-4444", {"note": "x" * 501})
    ann = alimentation.annuaire(c)
    assert [p["nom"] for p in ann] == ["Paul MARTIN"] and ann[0]["note"] == "arrive toujours en avance"
    # Note seule : la ligne est gardée (statut inconnu)
    alimentation.definir(c, "AAAA-1111", {"note": "dort tard"})
    assert alimentation.fiche(c, "AAAA-1111")["statut"] == "inconnu"
    assert len(alimentation.annuaire(c)) == 2


def test_modifier_par_ha_ajouts_retraits_confirmation_et_doublon(c):  # noqa: F811
    ident = personnes.de(c, "DDDD-4444")
    alimentation.definir(c, "DDDD-4444", {"allergies": "arachide", "non_aimes": "olives", "aucune": False})
    op = {"operation": "ha-0001-aaaa", "personne_id": ident, "ajouts": {"allergies": ["Sésame"], "plaisirs": ["Crêpes"]},
          "retraits": {"non_aimes": ["OLIVES"]}, "note": "végétarien le soir"}
    r = alimentation.modifier_par_ha(c, op)
    assert r["deja"] is False and r["allergies"] == ["arachide", "Sésame"] and r["non_aimes"] == [] and r["plaisirs"] == ["Crêpes"]
    assert r["note"] == "végétarien le soir"
    # Renvoi de la file d'attente : pas appliqué deux fois
    op2 = {**op, "ajouts": {"allergies": ["Kiwi"]}}
    assert alimentation.modifier_par_ha(c, op2)["deja"] is True
    assert alimentation.de_personne(c, ident)["allergies"] == ["arachide", "Sésame"]
    # Retirer une allergie : refusé sans confirmation, accepté avec
    with pytest.raises(ErreurCarnet, match="confirmation"):
        alimentation.modifier_par_ha(c, {"operation": "ha-0002-bbbb", "personne_id": ident, "retraits": {"allergies": ["arachide"]}})
    r = alimentation.modifier_par_ha(c, {"operation": "ha-0003-cccc", "personne_id": ident,
                                         "retraits": {"allergies": ["arachide"]}, "confirme": True})
    assert r["allergies"] == ["Sésame"]
    # « Aucune connue » ne tient pas face à une allergie ; identifiant inconnu : LookupError
    r = alimentation.modifier_par_ha(c, {"operation": "ha-0004-dddd", "personne_id": ident, "aucune": True})
    assert r["aucune"] is False and r["statut"] == "a_connaitre"
    with pytest.raises(LookupError):
        alimentation.modifier_par_ha(c, {"operation": "ha-0005-eeee", "personne_id": "p-0000000000"})
    with pytest.raises(ErreurCarnet):
        alimentation.modifier_par_ha(c, {"operation": "x", "personne_id": ident})
    with pytest.raises(ErreurCarnet, match="Liste inconnue"):
        alimentation.modifier_par_ha(c, {"operation": "ha-0006-ffff", "personne_id": ident, "ajouts": {"vin": ["rouge"]}})
    # Le journal ne porte jamais le contenu
    assert "Sésame" not in str([dict(l) for l in c.base.tous("SELECT * FROM journal")])


def test_api_ha_aliments_lecture_ecriture_annuaire(c):  # noqa: F811
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    alimentation.definir(c, "DDDD-4444", {"intolerances": "lactose", "note": "café serré"})
    with _client(c) as client:
        assert client.get("/ha/aliments?nom=Paul MARTIN").status_code == 401
        r = client.get("/ha/aliments", params={"nom": "Paul MARTIN (2026-11-20 → 2026-11-22)"}, headers=H).json()
        assert r["intolerances"] == ["lactose"] and r["note"] == "café serré" and r["statut"] == "a_connaitre"
        ident = r["personne_id"]
        assert client.get("/ha/aliments", params={"personne_id": ident}, headers=H).json()["nom"] == "Paul MARTIN"
        assert client.get("/ha/aliments", params={"nom": "Personne Inconnue"}, headers=H).status_code == 404
        assert client.get("/ha/aliments", params={"personne_id": "p-0000000000"}, headers=H).status_code == 404
        assert client.get("/ha/aliments", headers=H).status_code == 400
        m = client.post("/ha/aliments/modifier", headers=H,
                        json={"operation": "ha-1111-aaaa", "personne_id": ident, "ajouts": {"allergies": ["kiwi"]}})
        assert m.status_code == 200 and m.json()["allergies"] == ["kiwi"]
        assert client.post("/ha/aliments/modifier", headers=H,
                           json={"operation": "ha-1112-aaaa", "personne_id": ident,
                                 "retraits": {"allergies": ["kiwi"]}}).status_code == 400
        assert client.post("/ha/aliments/modifier", headers=H,
                           json={"operation": "ha-1113-aaaa", "personne_id": "p-0000000000"}).status_code == 404
        ann = client.get("/ha/aliments/annuaire", headers=H).json()
        assert [p["nom"] for p in ann["personnes"]] == ["Paul MARTIN"]


def test_api_ha_sejour_puis_annulation(c):  # noqa: F811
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    ident = personnes.de(c, "DDDD-4444")
    corps = {"date": "2026-12-20", "titre": "Séjour — Chambre d'Ami", "resume": "Du 20/12/2026 au 27/12/2026",
             "personnes": [{"personne_id": ident, "role": "invité"}]}
    with _client(c) as client:
        assert client.put("/ha/evenements/sejour-ami-2026-12-20-paul_martin", json=corps).status_code == 401
        r = client.put("/ha/evenements/sejour-ami-2026-12-20-paul_martin", headers=H, json=corps)
        assert r.status_code == 200 and r.json()["reconnues"] == 1
        assert client.put("/ha/evenements/x-1", headers=H, json={**corps, "type": "gazette"}).status_code == 400
        from app import evenements
        assert [e["type"] for e in evenements.de_personne(c, ident)] == ["sejour"]
        assert client.delete("/ha/evenements/sejour-ami-2026-12-20-paul_martin", headers=H).status_code == 200
        assert evenements.de_personne(c, ident) == []


# ================================================================ livre d'or

def test_supprimer_un_mot_du_livre_d_or(c):  # noqa: F811
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    mot = {"invites": "Paul MARTIN", "message": "Mot d'essai", "chambre": "Chambre d'Ami", "le": "2026-11-20"}
    assert journaux.recevoir_livre(c, mot)["nouveaux"] == 1
    coffre.synchroniser(c)
    evts = list((c.cfg.contacts / "Événements").rglob("*.md"))
    assert any("Mot d'essai" in p.read_text(encoding="utf-8") for p in evts)
    ident = personnes.de(c, "DDDD-4444")
    m = journaux.livre_or(c, ident)[0]
    res = journaux.supprimer_livre(c, m["id"])
    assert res["ok"] and journaux.livre_or(c, ident) == []
    # Un renvoi de Home Assistant ne le fait pas revenir
    assert journaux.recevoir_livre(c, mot)["nouveaux"] == 0 and journaux.livre_or(c, ident) == []
    with pytest.raises(ErreurCarnet):
        journaux.supprimer_livre(c, m["id"])
    # Coffre : la note d'événement dit qu'il a été retiré, le texte du mot n'y est plus
    coffre.synchroniser(c)
    textes = [p.read_text(encoding="utf-8") for p in (c.cfg.contacts / "Événements").rglob("*.md")]
    assert not any("Mot d'essai" in t for t in textes) and any("n'est plus dans carnet" in t for t in textes)
    # Un autre mot, non supprimé, revient normalement
    assert journaux.recevoir_livre(c, {**mot, "message": "Vrai mot"})["nouveaux"] == 1


def test_api_supprimer_mot(c):  # noqa: F811
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    journaux.recevoir_livre(c, {"invites": "Paul MARTIN", "message": "Essai", "le": "2026-11-20"})
    m = journaux.livre_or(c, personnes.de(c, "DDDD-4444"))[0]
    with _client(c) as client:
        assert client.delete(f"/api/livre-or/{m['id']}").status_code == 401
        from app import main
        main.ETAT["sessions"].connecte = lambda cookies: True
        assert client.delete(f"/api/livre-or/{m['id']}").status_code == 200
        assert client.delete(f"/api/livre-or/{m['id']}").status_code == 400
