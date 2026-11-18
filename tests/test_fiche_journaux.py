"""2.33 : « Fiche complète » pour les journaux — pépites rangées par rubriques, migration du texte libre (une seule
fois), écritures pépite par pépite avec contrôle de `le` (409), routes Gazette au jeton commun, export du coffre
Contacts, schéma 9 sur une base chiffrée. Données inventées."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import base as base_, coffre, journaux as J, main, personnes
from app.base import Base

from .test_carnet import c, services  # noqa: F401 — fixtures réutilisées

PAUL = "DDDD-4444"
JETON = "jeton-commun-essai"
COMMUN = {"Authorization": f"Bearer {JETON}"}


@pytest.fixture
def client(c, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MAISON_JETON", JETON)
    main.ETAT["carnet"] = c
    try:
        with TestClient(main.app) as cl:
            assert cl.post("/api/connexion", json={"mot_de_passe": "secret"}).status_code == 200
            yield cl
    finally:
        main.ETAT.clear()


def _ident(c):  # noqa: F811
    return personnes.de(c, PAUL)


# ================================================================ rubriques partagées avec Gazette

def test_rubriques_identiques_au_contrat_et_valides():
    ici = Path(J.__file__).with_name("rubriques_journaux.json")
    d = json.loads(ici.read_text(encoding="utf-8"))
    cles = [r["cle"] for f in d["familles"] for r in f["rubriques"]]
    assert len(cles) == len(set(cles)) and "autre" in cles and d["interdits"]["cle"] == "interdits"
    assert {"metier", "conjoint", "enfants", "animaux", "plats-aimes", "ton", "si-c-etait"} <= set(cles)
    contrat = Path("/home/claude/consignes/rubriques_journaux.json")
    if contrat.exists():                                     # sur la machine de travail : copie à l'identique
        assert contrat.read_bytes() == ici.read_bytes()


def test_rangement_du_vrac_par_mots_cles():
    assert J.ranger("Son chien s'appelle Biscotte") == "animaux"
    assert J.ranger("Fan absolu de l'Eurovision") == "fetes"
    assert J.ranger("Ronfle comme un tracteur pendant la sieste") == "sommeil"
    assert J.ranger("Joue au rugby le dimanche") == "sports"
    assert J.ranger("xyz") == "autre"


# ================================================================ migration du texte libre

def test_migration_du_texte_libre_une_seule_fois(c):  # noqa: F811
    ident = _ident(c)
    long = "Première phrase assez longue pour remplir. " * 6 + "Fin."
    J.ecrire(c, ident, "fan de pétanque\n\n- collectionne les cuillères\n" + long, "gazette")
    liste = J.pepites(c, ident)
    assert [p["texte"] for p in liste][:2] == ["fan de pétanque", "collectionne les cuillères"]
    assert all(p["rubrique"] == "autre" and p["source"] == "carnet" and len(p["texte"]) <= 200 for p in liste)
    assert len(liste) > 3                                    # ligne trop longue : coupée en phrases
    n = len(liste)
    assert J.migrer(c, ident) == 0 and len(J.pepites(c, ident)) == n           # une seule fois
    # la colonne reste en base, intacte ; elle n'est plus écrite : une ligne nouvelle devient une pépite
    avant = c.base.un("SELECT texte FROM journaux WHERE personne = ?", (ident,))["texte"]
    r = J.ecrire(c, ident, "fan de pétanque\nnouvelle manie", "gazette")
    assert r["pepites"] == 1
    assert c.base.un("SELECT texte FROM journaux WHERE personne = ?", (ident,))["texte"] == avant
    assert len(J.pepites(c, ident)) == n + 1
    # une personne sans texte est marquée aussi : rien de créé, rien de recréé ensuite
    autre = personnes.de(c, "AAAA-1111")
    assert J.migre(c, autre) is False
    assert J.pepites(c, autre) == [] and J.migre(c, autre) is True
    J.ecrire(c, autre, "aime le jazz", "carnet")             # écrit après la migration : une pépite, pas de texte
    assert [p["texte"] for p in J.pepites(c, autre)] == ["aime le jazz"]
    assert c.base.un("SELECT texte FROM journaux WHERE personne = ?", (autre,)) is None


def test_lecture_deja_migree_ne_fait_pas_oublier_les_calculs(c):  # noqa: F811
    ident = _ident(c)
    J.pepites(c, ident)
    g = c.base.generation
    J.pepites(c, ident)
    J.fiche_complete(c, ident)
    assert c.base.generation == g


# ================================================================ CRUD avec contrôle de `le`

def test_crud_carnet_avec_409(client, c):  # noqa: F811
    base = f"/api/contacts/{PAUL}/fiche-journaux"
    vide = client.get(base).json()
    assert vide["pepites"] == [] and vide["jauge"] == {"nombre": 0, "palier": "", "prochain": 5}
    assert vide["rubriques"]["familles"][0]["cle"] == "vie" and vide["personne_id"] == _ident(c)
    assert set(vide["connu"]) == {"metier", "conjoint", "enfants", "animaux", "alimentation", "immich_id"}
    p = client.post(f"{base}/pepites", json={"rubrique": "sports", "texte": "  Joue  à la pétanque  "}).json()
    assert p["texte"] == "Joue à la pétanque" and p["source"] == "julien" and p["par"] == "carnet" and p["parue_le"] is None
    assert set(p) >= {"id", "rubrique", "texte", "le", "source", "parue_le", "interdit"}
    # vrac : rangée par mots-clés ; « autre » sinon
    assert client.post(f"{base}/pepites", json={"texte": "A peur des araignées"}).json()["rubrique"] == "peurs"
    assert client.post(f"{base}/pepites", json={"rubrique": "vrac", "texte": "qwerty"}).json()["rubrique"] == "autre"
    # doublon : pas deux fois
    assert client.post(f"{base}/pepites", json={"rubrique": "sports", "texte": "joue à la pétanque"}).json()["deja"] is True
    # garde-fous
    assert client.post(f"{base}/pepites", json={"rubrique": "sports", "texte": "x" * 201}).status_code == 400
    assert client.post(f"{base}/pepites", json={"rubrique": "inconnue", "texte": "x"}).status_code == 400
    assert client.post(f"{base}/pepites", json={"texte": "x", "source": "ia"}).status_code == 400
    # modifier avec le bon `le`
    r = client.put(f"{base}/pepites/{p['id']}", json={"le": p["le"], "texte": "Champion de pétanque"})
    assert r.status_code == 200
    p2 = r.json()
    assert p2["texte"] == "Champion de pétanque" and p2["le"] != p["le"]
    # ancien `le` : 409, rien ne change
    r = client.put(f"{base}/pepites/{p['id']}", json={"le": p["le"], "texte": "écrasé"})
    assert r.status_code == 409 and "changé" in r.json()["detail"]
    assert client.put(f"{base}/pepites/{p['id']}", json={"texte": "sans le"}).status_code == 400
    # déplacer dans les sujets interdits, puis en sortir
    p3 = client.put(f"{base}/pepites/{p['id']}", json={"le": p2["le"], "interdit": True}).json()
    assert p3["rubrique"] == "interdits" and p3["interdit"] is True
    p4 = client.put(f"{base}/pepites/{p['id']}", json={"le": p3["le"], "rubrique": "sports"}).json()
    assert p4["rubrique"] == "sports" and p4["interdit"] is False
    # effacer : `le` exigé, ancien `le` → 409, bon `le` → effacée, ensuite 404
    assert client.request("DELETE", f"{base}/pepites/{p['id']}", json={"le": p["le"]}).status_code == 409
    assert client.request("DELETE", f"{base}/pepites/{p['id']}").status_code == 400
    assert client.request("DELETE", f"{base}/pepites/{p['id']}", json={"le": p4["le"]}).json() == {"ok": True, "id": p["id"]}
    assert client.request("DELETE", f"{base}/pepites/{p['id']}", json={"le": p4["le"]}).status_code == 404
    assert client.put(f"{base}/pepites/pp-inconnue", json={"le": "x", "texte": "y"}).status_code == 404
    # session exigée
    client.cookies.clear()
    assert client.get(base).status_code == 401


def test_jauge_et_paliers():
    def n(k, interdits=0):
        return [{"interdit": False}] * k + [{"interdit": True}] * interdits
    assert J.jauge(n(4, 3)) == {"nombre": 4, "palier": "", "prochain": 5}
    assert J.jauge(n(5))["palier"] == "de quoi rire"
    assert J.jauge(n(15)) == {"nombre": 15, "palier": "bien fournie", "prochain": 30}
    assert J.jauge(n(31)) == {"nombre": 31, "palier": "inépuisable", "prochain": None}


# ================================================================ routes Gazette (jeton commun)

def test_routes_gazette_avec_jeton(client, c):  # noqa: F811
    from app import liaisons
    ident = _ident(c)
    base = f"/gazette/personnes/{ident}/fiche"
    assert client.get(base, headers=COMMUN).json()["connu"]["immich_id"] == ""       # pas encore liée à Immich
    liaisons.lier(c, PAUL, "immich", "im-paul")
    assert client.get(base).status_code == 401                        # session seule : pas assez
    assert client.get(base, headers={"Authorization": "Bearer faux"}).status_code == 401
    assert client.get("/gazette/personnes/p-inconnue00/fiche", headers=COMMUN).status_code == 404
    f = client.get(base, headers=COMMUN).json()
    assert f["connu"]["immich_id"] == "im-paul" and f["pepites"] == []
    p = client.post(f"{base}/pepites", headers=COMMUN, json={"rubrique": "ton", "texte": "taquin", "source": "julien"}).json()
    assert p["par"] == "gazette"
    i = client.post(f"{base}/pepites", headers=COMMUN, json={"rubrique": "interdits", "texte": "son divorce"}).json()
    assert i["interdit"] is True
    assert client.post(f"{base}/pepites", json={"texte": "x"}).status_code == 401
    r = client.put(f"{base}/pepites/{p['id']}", headers=COMMUN, json={"le": p["le"], "texte": "taquin mais tendre"})
    assert r.status_code == 200
    # écriture concurrente : carnet a modifié entre-temps, Gazette reçoit 409
    assert client.put(f"{base}/pepites/{p['id']}", headers=COMMUN, json={"le": p["le"], "texte": "absurde"}).status_code == 409
    # numéro approuvé : parue_le posé, `le` inchangé
    le = r.json()["le"]
    m = client.post(f"{base}/parues", headers=COMMUN, json={"ids": [p["id"], "pp-inconnue"], "date": "2026-11-19"}).json()
    assert m == {"ok": True, "marquees": 1, "ignorees": 1}
    lue = next(x for x in client.get(base, headers=COMMUN).json()["pepites"] if x["id"] == p["id"])
    assert lue["parue_le"] == "2026-11-19" and lue["le"] == le
    assert client.post(f"{base}/parues", headers=COMMUN, json={"ids": [p["id"]], "date": "19/11"}).status_code == 400
    assert client.post(f"{base}/parues", json={"ids": [p["id"]], "date": "2026-11-19"}).status_code == 401
    # même fiche dans carnet
    assert {x["id"] for x in client.get(f"/api/contacts/{PAUL}/fiche-journaux").json()["pepites"]} == {p["id"], i["id"]}
    # ancien champ `journaux` de /gazette/personnes (anciennes Gazette) : pépites sans les sujets interdits
    gz = client.get("/gazette/personnes", headers=COMMUN).json()["personnes"]
    assert next(x for x in gz if x["carnet_id"] == PAUL)["journaux"] == "taquin mais tendre"
    d = client.request("DELETE", f"{base}/pepites/{i['id']}", params={"le": i["le"]}, headers=COMMUN)   # `le` en ?le=
    assert d.status_code == 200


def test_suggestions_et_connu_depuis_carnet(client, c):  # noqa: F811
    from app import alimentation
    alimentation.definir(c, PAUL, {"plaisirs": ["frites"], "non_aimes": ["endives"], "allergies": ["noix"]})
    ident = _ident(c)
    J.ecrire_paru(c, ident, "recidive-2026-08-15", {"numero": 1, "evenement": "soirée déguisée",
                                                     "indices": "a perdu ses clés. chante faux"})
    f = client.get(f"/gazette/personnes/{ident}/fiche", headers=COMMUN).json()
    assert f["connu"]["alimentation"]["allergies"] == ["noix"]
    s = {(x["rubrique"], x["texte"], x["source"]) for x in f["suggestions"]}
    assert ("plats-aimes", "frites", "carnet") in s and ("plats-detestes", "endives", "carnet") in s
    assert ("sejours", "soirée déguisée (15/08/2026)", "recidive") in s
    assert any(t == "a perdu ses clés." and src == "recidive" for _, t, src in s)
    assert not any(t == "noix" for _, t, _ in s)                       # allergies : lues, jamais proposées
    # rien n'est recopié tant que Julien n'a pas touché « Ajouter »
    assert f["pepites"] == []
    client.post(f"/api/contacts/{PAUL}/fiche-journaux/pepites", json={"rubrique": "plats-aimes", "texte": "frites", "source": "carnet"})
    f = client.get(f"/api/contacts/{PAUL}/fiche-journaux").json()
    assert not any(x["texte"] == "frites" for x in f["suggestions"])


# ================================================================ export du coffre Contacts

def test_export_coffre_fiche_complete(c):  # noqa: F811
    ident = _ident(c)
    J.ajouter(c, ident, {"rubrique": "sports", "texte": "Champion de pétanque"}, "carnet")
    J.ajouter(c, ident, {"rubrique": "animaux", "texte": "Un chat nommé Pompon", "source": "sillage"}, "gazette")
    J.ajouter(c, ident, {"rubrique": "interdits", "texte": "son ancien patron"}, "carnet")
    bloc = coffre.bloc(c, PAUL, c.fiche(PAUL), ident, {})
    assert "## Pour les journaux (Gazette)" in bloc
    assert "### Goûts et passions" in bloc and "- **Sports**" in bloc and "  - Champion de pétanque" in bloc
    assert "Un chat nommé Pompon (sillage)" in bloc
    assert "### Sujets interdits\n- son ancien patron" in bloc
    assert bloc.index("### Sujets interdits") > bloc.index("### Goûts et passions")
    assert "2 pépites" in bloc                                         # jauge sans les sujets interdits


def test_export_coffre_sans_pepite_pas_de_section(c):  # noqa: F811
    assert "Pour les journaux" not in coffre.bloc(c, PAUL, c.fiche(PAUL), _ident(c), {})


# ================================================================ schéma 9 sur une base chiffrée existante

def test_schema_9_ajoute_sans_rien_perdre_sur_base_chiffree(tmp_path):
    chemin = tmp_path / "carnet2.db"
    b = Base(chemin, "clé d'essai")
    b.executer("DROP TABLE journaux_pepites")                          # base telle que la 2.32 la laisse
    b.cx.execute("PRAGMA user_version = 8")
    b.executer("INSERT INTO journaux(personne, texte, le, par) VALUES ('p-0123456789', 'aime le jazz', 'x', 'carnet')")
    b.fermer()
    b = Base(chemin, "clé d'essai")
    assert b.un("PRAGMA user_version")[0] == base_.VERSION == 9
    assert b.un("SELECT texte FROM journaux")["texte"] == "aime le jazz"
    colonnes = [l[1] for l in b.tous("PRAGMA table_info(journaux_pepites)")]
    assert colonnes == ["id", "personne", "rubrique", "texte", "interdit", "source", "parue_le", "le", "par"]
    b.fermer()
