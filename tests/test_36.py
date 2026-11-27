"""3.6 : l'arbre de famille pour Sillage (GET /sillage/arbre), la case « jamais aux invités », les propositions des
invités (POST /sillage/propositions) et leur traitement dans « À traiter ». Personnes d'essai inventées."""
from __future__ import annotations

import pytest

from app import actions, arbre, liaisons, traiter
from app.carnet import ErreurCarnet

from .test_228 import c  # noqa: F401 — fixture réutilisée
from .test_carnet import services  # noqa: F401

PAUL, CLAIRE = "DDDD-4444", "AAAA-1111"
COMMUN = {"Authorization": "Bearer jeton-commun-essai"}


def _client(c, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    main.ETAT["carnet"] = c
    monkeypatch.setenv("MAISON_JETON", "jeton-commun-essai")
    return TestClient(main.app)


def _famille(tm):
    """Claire et Paul (couple, reliés à leurs fiches), leur fille Lou, la mère de Claire (sans fiche), un ex de Paul."""
    tm.autres = [{"id": "t-lou", "name": "Lou MARTIN", "gender": "FEMALE", "immich": "im-lou"},
                 {"id": "t-rose", "name": "Rose DURAND", "gender": "FEMALE"},
                 {"id": "t-ex", "name": "Anne BLANC", "gender": "FEMALE"},
                 {"id": "t-seul", "name": "Isolé SANSLIEN"}]
    tm.autres_liens = [{"fromPersonId": "t-claire", "toPersonId": "t-lou", "type": "PARENT_OF"},
                       {"fromPersonId": "t-lou", "toPersonId": "t-paul", "type": "CHILD_OF"},
                       {"fromPersonId": "t-rose", "toPersonId": "t-claire", "type": "PARENT_OF"},
                       {"fromPersonId": "t-claire", "toPersonId": "t-rose", "type": "CHILD_OF"},     # doublon inversé
                       {"fromPersonId": "t-paul", "toPersonId": "t-ex", "type": "SPOUSE_OF",
                        "divorceDate": "2001-05-02"}]


def _relier(c):
    liaisons.lier(c, CLAIRE, "treemich", "t-claire")
    liaisons.lier(c, PAUL, "treemich", "t-paul")
    liaisons.donnees(c, rafraichir=True)


# ================================================================ l'arbre

def test_36_graphe_complet_liens_normalises(c, services):  # noqa: F811
    tm = services["treemich"]
    _famille(tm)
    tm.divorces[("t-ex", "t-paul")] = "2001-05-02"
    _relier(c)
    g = arbre.graphe(c)
    assert g["contrat"] == 1 and g["ok"] is True
    par = {p["id"]: p for p in g["personnes"]}
    assert set(par) == {"t-claire", "t-paul", "t-lou", "t-rose", "t-ex", "t-seul"}
    # Personnes reliées : fiche, identifiant maison, date ; personne de l'arbre seule : rien de daté
    assert par["t-claire"]["fiche"] is True and par["t-claire"]["personne_id"].startswith("p-")
    assert par["t-claire"]["naissance"] and par["t-claire"]["genre"] == "femme"
    assert par["t-rose"]["fiche"] is False and par["t-rose"]["naissance"] == "" and par["t-rose"]["personne_id"] is None
    assert par["t-lou"]["immich"] == "im-lou" and par["t-rose"]["immich"] is None
    liens = {(l["type"], l["de"], l["vers"]) for l in g["liens"]}
    assert ("parent", "t-claire", "t-lou") in liens and ("parent", "t-paul", "t-lou") in liens
    assert ("parent", "t-rose", "t-claire") in liens
    assert sum(1 for l in g["liens"] if l["type"] == "parent" and l["vers"] == "t-claire") == 1    # doublon retiré
    assert ("conjoint", "t-claire", "t-paul") in liens
    ex = next(l for l in g["liens"] if l["type"] == "conjoint" and "t-ex" in (l["de"], l["vers"]))
    assert ex["divorce"] is True
    assert next(l for l in g["liens"] if l["type"] == "conjoint" and "t-claire" in (l["de"], l["vers"]))["divorce"] is False


def test_36_route_jeton_commun_et_masque(c, services, monkeypatch):  # noqa: F811
    _famille(services["treemich"])
    _relier(c)
    client = _client(c, monkeypatch)
    assert client.get("/sillage/arbre").status_code == 401
    assert client.get("/sillage/arbre", headers={"Authorization": "Bearer faux"}).status_code == 401
    r = client.get("/sillage/arbre", headers=COMMUN)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert not any(p["masque_invites"] for p in r.json()["personnes"])
    # Case « jamais aux invités » (visible ensuite dans l'arbre)
    arbre.masquer(c, "t-rose", True)
    arbre.masquer(c, "t-claire", True)
    par = {p["id"]: p for p in client.get("/sillage/arbre", headers=COMMUN).json()["personnes"]}
    assert par["t-rose"]["masque_invites"] and par["t-claire"]["masque_invites"] and not par["t-paul"]["masque_invites"]
    arbre.masquer(c, "t-claire", False)
    assert arbre.masques(c) == {"t-rose"}


def test_36_deces_de_la_fiche_et_date_sans_annee(c, services):  # noqa: F811
    _famille(services["treemich"])
    _relier(c)
    c.base.executer("INSERT INTO deces(uid, date, origine, le) VALUES (?, ?, 'main', '2026-01-01')", (PAUL, ""))
    c.oublier()
    par = {p["id"]: p for p in arbre.graphe(c)["personnes"]}
    assert par["t-paul"]["decede"] is True and par["t-paul"]["deces"] == "inconnue"
    assert arbre._date_fiche("--03-14") == "" and arbre._date_fiche("1985-03-14") == "1985-03-14"


# ================================================================ propositions

def _prop(**kw):
    base = {"id": "prop-0001-abcd", "personne": "t-rose", "nom": "Rose DURAND", "type": "date", "champ": "naissance",
            "valeur": "1931-07-02", "invites": ["Marc", "Léa"], "sejour": {"du": "2026-12-01", "au": "2026-12-03"}}
    return {**base, **kw}


def test_36_proposition_recue_idempotente_et_controlee(c, services, monkeypatch):  # noqa: F811
    _famille(services["treemich"])
    _relier(c)
    client = _client(c, monkeypatch)
    assert client.post("/sillage/propositions", json=_prop()).status_code == 401
    r = client.post("/sillage/propositions", json=_prop(), headers=COMMUN)
    assert r.status_code == 200 and r.json() == {"ok": True, "deja": False}
    assert client.post("/sillage/propositions", json=_prop(), headers=COMMUN).json()["deja"] is True
    p = [x for x in traiter.liste(c) if x["motif"] == "proposition_invite"]
    assert len(p) == 1 and p[0]["tuile"] == "propositions" and p[0]["nom"] == "Rose DURAND" and p[0]["uid"] is None
    assert p[0]["donnees"]["invites"] == ["Marc", "Léa"]
    assert next(t for t in traiter.tuiles(c) if t["cle"] == "propositions")["nombre"] == 1
    # Une proposition sur une personne reliée porte la fiche
    client.post("/sillage/propositions", json=_prop(id="prop-0002-abcd", personne="t-claire", nom="Claire"), headers=COMMUN)
    assert any(x["uid"] == CLAIRE for x in traiter.liste(c) if x["motif"] == "proposition_invite")
    # Refus : type, date mal écrite, lien sans mot, identifiant manquant
    for mauvais in (_prop(id="prop-0003-abcd", type="autre"), _prop(id="prop-0004-abcd", valeur="2 juillet"),
                    _prop(id="prop-0005-abcd", type="lien", lien="parent", valeur="", mot=""), _prop(id="x")):
        assert client.post("/sillage/propositions", json=mauvais, headers=COMMUN).status_code == 400
    assert client.post("/sillage/propositions", content=b"pas du json", headers=COMMUN).status_code == 400


def test_36_plafond_des_propositions(c, services, monkeypatch):  # noqa: F811
    monkeypatch.setattr(arbre, "EN_ATTENTE_MAX", 2)
    arbre.recevoir(c, _prop(id="prop-a-00001"))
    arbre.recevoir(c, _prop(id="prop-a-00002"))
    with pytest.raises(arbre.PropositionRefusee, match="Trop de propositions"):
        arbre.recevoir(c, _prop(id="prop-a-00003"))


def test_36_accepter_une_date_ecrit_dans_treemich_et_relit(c, services):  # noqa: F811
    tm = services["treemich"]
    _famille(tm)
    _relier(c)
    arbre.recevoir(c, _prop())
    p = next(x for x in traiter.liste(c) if x["motif"] == "proposition_invite")
    res = actions.repondre(c, p["id"], "accepter", "1931-07-04")      # corrigée par Julien
    assert res["ok"] and "Treemich" in res["message"]
    assert ("/people/t-rose", {"birthDate": "1931-07-04"}) in tm.ecrits
    assert not [x for x in traiter.liste(c) if x["motif"] == "proposition_invite"]


def test_36_date_oubliee_par_treemich_le_point_reste(c, services):  # noqa: F811
    tm = services["treemich"]
    _famille(tm)
    _relier(c)
    tm.oublie = True
    arbre.recevoir(c, _prop())
    p = next(x for x in traiter.liste(c) if x["motif"] == "proposition_invite")
    with pytest.raises(ErreurCarnet, match="pas gardé"):
        actions.repondre(c, p["id"], "accepter", None)
    assert [x for x in traiter.liste(c) if x["motif"] == "proposition_invite"]


def test_36_mariage_seulement_sur_un_couple_existant(c, services):  # noqa: F811
    tm = services["treemich"]
    _famille(tm)
    _relier(c)
    arbre.recevoir(c, _prop(id="prop-m-00001", personne="t-claire", champ="mariage", valeur="2010-06-12",
                             autre="t-paul", autre_nom="Paul MARTIN"))
    arbre.recevoir(c, _prop(id="prop-m-00002", personne="t-rose", champ="mariage", valeur="1950-01-01", autre="t-lou"))
    pts = {x["cle"]: x for x in traiter.liste(c) if x["motif"] == "proposition_invite"}
    actions.repondre(c, pts["prop-m-00001"]["id"], "accepter", None)
    assert tm.mariages[("t-claire", "t-paul")] == "2010-06-12"
    with pytest.raises(ErreurCarnet, match="couple n'existe pas"):
        actions.repondre(c, pts["prop-m-00002"]["id"], "accepter", None)


def test_36_nom_ecrit_avec_prenom_et_nom_explicites(c, services):  # noqa: F811
    tm = services["treemich"]
    _famille(tm)
    _relier(c)
    arbre.recevoir(c, _prop(id="prop-n-00001", type="nom", champ="prenom", valeur="Rosa"))
    p = next(x for x in traiter.liste(c) if x["motif"] == "proposition_invite")
    with pytest.raises(ErreurCarnet, match="prénom et le nom"):
        actions.repondre(c, p["id"], "accepter", {})
    actions.repondre(c, p["id"], "accepter", {"prenom": "Rosa", "nom": "DURAND"})
    assert tm.noms["t-rose"]["givenName"] == "Rosa" and tm.noms["t-rose"]["surname"] == "DURAND"


def test_36_lien_et_personne_jamais_ecrits(c, services):  # noqa: F811
    tm = services["treemich"]
    _famille(tm)
    _relier(c)
    arbre.recevoir(c, _prop(id="prop-l-00001", type="lien", lien="enfant", valeur="", mot="Il manque Hugo, son fils"))
    arbre.recevoir(c, _prop(id="prop-p-00001", type="personne", valeur="Hugo", mot="né en 1960"))
    pts = [x for x in traiter.liste(c) if x["motif"] == "proposition_invite"]
    avant = list(tm.ecrits)
    for p in pts:
        with pytest.raises(ErreurCarnet, match="se crée dans Treemich"):
            actions.repondre(c, p["id"], "accepter", None)
        actions.repondre(c, p["id"], "fait", None)
    assert tm.ecrits == avant
    assert not [x for x in traiter.liste(c) if x["motif"] == "proposition_invite"]


def test_36_lecture_seule_rien_n_est_ecrit(c, services):  # noqa: F811
    tm = services["treemich"]
    _famille(tm)
    _relier(c)
    import dataclasses
    c.cfg = dataclasses.replace(c.cfg, lecture_seule=True)
    arbre.recevoir(c, _prop())
    p = next(x for x in traiter.liste(c) if x["motif"] == "proposition_invite")
    with pytest.raises(ErreurCarnet):
        actions.repondre(c, p["id"], "accepter", None)
    assert not any("birthDate" in (corps or {}) for _, corps in tm.ecrits)


def test_36_rejeter_ne_repropose_pas(c, services):  # noqa: F811
    arbre.recevoir(c, _prop())
    p = next(x for x in traiter.liste(c) if x["motif"] == "proposition_invite")
    actions.repondre(c, p["id"], "ignorer", None)
    assert not [x for x in traiter.liste(c) if x["motif"] == "proposition_invite"]
    assert arbre.recevoir(c, _prop())["ok"]           # même identifiant : déjà écarté, pas remis
    assert not [x for x in traiter.liste(c) if x["motif"] == "proposition_invite"]
