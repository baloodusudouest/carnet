"""Tests de bout en bout sur des contacts fictifs (tests/donnees/)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import normalisation as n
from app.export import vcard
from app.sources import vcard as lecteur_vcf

DONNEES = Path(__file__).parent / "donnees"


# ------------------------------------------------------------------ unitaires

def test_telephone_e164_et_affichage():
    t = n.telephone("06 12 34 56 78", "mobile")
    assert t["valeur"] == "+33612345678"
    assert t["affichage"] == "+33 6 12 34 56 78"
    assert t["mobile"] and t["valide"]
    assert n.telephone("0033 5 53 11 22 33", "domicile")["valeur"] == "+33553112233"
    belge = n.telephone("+32 470 12 34 56", "mobile")
    assert belge["affichage"].startswith("+32 ")
    bizarre = n.telephone("12", "autre")
    assert not bizarre["valide"] and bizarre["valeur"] == "12"


def test_noms():
    assert n.formater_prenom("jean-pierre") == "Jean-Pierre"
    assert n.formater_prenom("JEAN PIERRE") == "Jean Pierre"
    assert n.formater_prenom("McKenzie") == "McKenzie"
    assert n.formater_nom("le Goff") == "LE GOFF"
    assert n.formater_nom("lefèvre") == "LEFÈVRE"
    assert n.separer_nom_complet("Claire MARTIN") == ("Claire", "MARTIN")


def test_anniversaires():
    assert n.anniversaire("1985-03-14") == "1985-03-14"
    assert n.anniversaire("19850314") == "1985-03-14"
    assert n.anniversaire("--07-02") == "--07-02"
    assert n.anniversaire("1604-07-02", sans_annee=True) == "--07-02"
    assert n.anniversaire("3/25/1990") == "1990-03-25"     # Outlook (américain)
    assert n.anniversaire("25/3/1990") == "1990-03-25"     # jour > 12 : forcément J/M
    assert n.anniversaire("31/02/1990") == ""


def test_lecture_icloud():
    fiches, avert = lecteur_vcf.lire((DONNEES / "icloud.vcf").read_text())
    assert len(fiches) == 3
    claire = fiches[0].fiche
    assert (claire["prenom"], claire["nom"]) == ("Claire", "MARTIN")
    assert claire["groupes"] == ["Urgence"]                # carte de groupe iCloud
    assert {t["type"] for t in claire["telephones"]} == {"mobile", "bureau"}
    assert claire["noms_associes"] == [{"valeur": "Paul Martin", "type": "conjoint"}]
    assert claire["notes"] == "Cliente fidèle, aime les croissants"
    assert fiches[0].uid == "AAAA-1111"
    jp = fiches[1].fiche
    assert (jp["prenom"], jp["nom"], jp["anniversaire"]) == ("Jean-Pierre", "DUBOIS", "--07-02")
    plombier = fiches[2].fiche
    assert (plombier["prenom"], plombier["nom"], plombier["societe"]) == ("", "", "Plomberie Garonne")


def test_vcard_aller_retour():
    fiches, _ = lecteur_vcf.lire((DONNEES / "icloud.vcf").read_text())
    texte = vcard(fiches[0].fiche, "AAAA-1111", verifie=True)
    relue, _ = lecteur_vcf.lire(texte)
    f = relue[0].fiche
    origine = fiches[0].fiche
    for champ in ("prenom", "nom", "societe", "anniversaire", "notes", "courriels", "adresses",
                  "noms_associes"):
        assert f[champ] == origine[champ], champ
    assert [t["valeur"] for t in f["telephones"]] == [t["valeur"] for t in origine["telephones"]]
    assert "+33 6 12 34 56 78" in texte
    assert "CATEGORIES:Urgence,✓ Vérifiés" in texte
    assert all(len(l.encode()) <= 75 for l in texte.split("\r\n"))
    sans_annee = vcard(fiches[1].fiche, "B")
    assert "BDAY;X-APPLE-OMIT-YEAR=1604;VALUE=date:1604-07-02" in sans_annee


# ------------------------------------------------------------------ bout en bout (API)

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CARNET_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CARNET_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("CARNET_PASSWORD", "secret-de-test")
    monkeypatch.setenv("CARNET_DB_KEY", "cle-de-test")
    monkeypatch.setenv("CARNET_KIT_CONFIG", str(tmp_path / "kit-config"))
    monkeypatch.setenv("KIT_API_TOKEN", "")
    (tmp_path / "kit-config").mkdir()
    from app.main import app
    with TestClient(app, headers={"X-Carnet": "1"}) as c:
        yield c


def _connecter(c):
    assert c.get("/api/contacts").status_code == 401
    assert c.post("/api/connexion", json={"mot_de_passe": "faux"}).status_code == 401
    assert c.post("/api/connexion", json={"mot_de_passe": "secret-de-test"}).status_code == 200


def _importer(c, fichier, source):
    with open(DONNEES / fichier, "rb") as f:
        r = c.post("/api/depot", files=[("fichiers", (fichier, f.read()))])
    assert r.status_code == 200, r.text
    r = c.post("/api/importer", json={"nom": fichier, "source": source})
    assert r.status_code == 200, r.text
    return r.json()


def test_parcours_complet(client, tmp_path):
    c = client
    _connecter(c)
    r = _importer(c, "icloud.vcf", "icloud")
    assert r["ajoutes"] == 3 and r["personnes_creees"] == 3
    r = _importer(c, "gmail.vcf", "gmail")
    assert r["personnes_completees"] == 2      # Claire (mobile), Jean-Pierre (nom)
    assert r["personnes_creees"] == 1          # Sophie
    r = _importer(c, "outlook.csv", "outlook")
    assert r["personnes_completees"] == 1      # Sophie (courriel)
    assert r["personnes_creees"] == 1          # Marc
    r = _importer(c, "Connections.csv", "linkedin")
    assert r["enrichies"] == 1                 # Sophie ; « Inconnu Total » ne crée rien
    assert c.post("/api/importer", json={"nom": "icloud.vcf", "source": "icloud"}).status_code == 400

    statut = c.get("/status").json()
    assert statut["total"] == 5 and statut["linkedin_sans_contact"] == 1

    file = c.get("/api/file").json()
    assert [p["doublon"] for p in file] == [True, True, True, False, False]  # doublons d'abord

    claire = next(p for p in file if p["nom"] == "Claire MARTIN")
    d = c.get(f"/api/personnes/{claire['id']}").json()
    assert len(d["sources"]) == 2
    f = d["fiche"]
    assert len(f["telephones"]) == 2 and len(f["courriels"]) == 2
    assert set(f["groupes"]) == {"Amis", "Urgence"}
    assert f["photo"] == next(s["id"] for s in d["sources"] if s["source"] == "icloud")
    f["courriels"] = [x for x in f["courriels"] if "boulangerie" not in x["valeur"]]
    d = c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True}).json()
    assert d["statut"] == "verifie" and len(d["fiche"]["courriels"]) == 1

    # Jean-Pierre : on détache la fiche Gmail (en fait une autre personne)
    jp = next(p for p in file if p["nom"].startswith("Jean"))
    d = c.get(f"/api/personnes/{jp['id']}").json()
    gmail = next(s for s in d["sources"] if s["source"] == "gmail")
    r = c.post(f"/api/personnes/{jp['id']}/detacher", json={"source_id": gmail["id"]}).json()
    assert len(r["dossier"]["sources"]) == 1 and r["nouvelle"]
    # … puis on s'aperçoit que c'était bien lui : fusion manuelle
    d = c.post(f"/api/personnes/{jp['id']}/fusionner", json={"autre": r["nouvelle"]}).json()
    assert len(d["sources"]) == 2
    assert c.get("/status").json()["total"] == 5

    # Export complet et kit
    r = c.post("/api/export").json()
    assert r["nb"] == 1 and r["non_verifies"] == 4
    assert c.get(f"/api/exports/{r['fichier']}").text.count("BEGIN:VCARD") == 1
    kit = c.post("/api/kit").json()
    assert kit["nb"] == 1
    texte = (tmp_path / "kit-config" / "contacts-urgence.vcf").read_text()
    assert "UID:AAAA-1111" in texte and "Claire" in texte

    archives = c.get("/api/archives").json()
    assert len(archives) == 4 and archives[0]["jours_restants"] >= 364
    assert not list((tmp_path / "data" / "depot").iterdir())   # tout est passé en archives


def test_base_chiffree(client, tmp_path):
    _connecter(client)
    _importer(client, "icloud.vcf", "icloud")
    contenu = (tmp_path / "state" / "carnet.db").read_bytes()
    assert b"SQLite format 3" not in contenu[:16]
    assert b"Claire" not in contenu


# ------------------------------------------------------------------ régressions (relecture)

def test_valeurs_jamais_supprimees_en_silence():
    f = n.normaliser_fiche({"noms_associes": [{"valeur": "Мария Иванова", "type": "mère"}],
                            "adresses": [{"region": "Bretagne", "pays": "France"}]})
    assert f["noms_associes"][0]["valeur"] == "Мария Иванова"
    assert f["adresses"][0]["region"] == "Bretagne"


def test_sites_et_extensions():
    assert n.site("https://www.dropbox.com/s/abc")["type"] == "site"
    assert n.site("https://x.com/exemple")["type"] == "x"
    assert n.site("https://fr.linkedin.com/in/exemple")["type"] == "linkedin"
    t = n.telephone("+33 1 23 45 67 89 ext. 12", "travail")
    assert t["valeur"] == "+33123456789;ext=12" and t["affichage"] == "+33 1 23 45 67 89;12"
    assert n.normaliser_fiche({"telephones": [t]})["telephones"][0]["valeur"] == "+33123456789;ext=12"
    assert n.telephone("05 53 11 22 33", None)["type"] == "autre"


def test_anniversaires_saisis():
    assert n.anniversaire("05/03/1985") == "1985-03-05"          # saisie : J/M
    assert n.anniversaire("05/03/1985", ordre="mj") == "1985-05-03"
    assert n.anniversaire("15 mars 1985") == "1985-03-15"
    assert n.anniversaire("1er août") == "--08-01"
    assert n.anniversaire("15.03.1985") == "1985-03-15"
    assert n.anniversaire("1985-3-5") == "1985-03-05"
    with pytest.raises(n.ValeurInvalide):
        n.normaliser_fiche({"anniversaire": "bientôt"})


def _personne(c, debut):
    return next(p for p in c.get("/api/contacts").json() if p["nom"].startswith(debut))


def test_brouillon_ne_touche_pas_la_fiche_validee(client, tmp_path):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    f2 = dict(f, telephones=[])
    d = c.put(f"/api/personnes/{claire['id']}", json={"fiche": f2, "valider": False}).json()
    assert d["statut"] == "verifie" and d["brouillon"] and d["fiche"]["telephones"] == []
    c.post("/api/kit")
    texte = (tmp_path / "kit-config" / "contacts-urgence.vcf").read_text()
    assert "+33 6 12 34 56 78" in texte                       # l'export garde la version validée
    r = c.put(f"/api/personnes/{claire['id']}", json={"fiche": dict(f, anniversaire="n'importe quoi"),
                                                      "valider": False})
    assert r.status_code == 400 and "non reconnu" in r.json()["detail"]


def test_fusion_garde_le_travail(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire, plombier = _personne(c, "Claire"), _personne(c, "Plomberie")
    f = c.get(f"/api/personnes/{plombier['id']}").json()["fiche"]
    f["groupes"] = ["Artisans et services"]
    f["notes"] = "Vient le mardi"
    c.put(f"/api/personnes/{plombier['id']}", json={"fiche": f, "valider": True})
    d = c.post(f"/api/personnes/{claire['id']}/fusionner", json={"autre": plombier["id"]}).json()
    assert set(d["fiche"]["groupes"]) == {"Urgence", "Artisans et services"}
    assert "Vient le mardi" in d["fiche"]["notes"] and "croissants" in d["fiche"]["notes"]


def test_detacher_retire_les_valeurs(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    _importer(c, "gmail.vcf", "gmail")
    claire = _personne(c, "Claire")
    d = c.get(f"/api/personnes/{claire['id']}").json()
    gmail = next(s for s in d["sources"] if s["source"] == "gmail")
    r = c.post(f"/api/personnes/{claire['id']}/detacher", json={"source_id": gmail["id"]}).json()
    courriels = [x["valeur"] for x in r["dossier"]["fiche"]["courriels"]]
    assert courriels == ["claire.martin@exemple.fr"]


def test_linkedin_avant_les_autres(client):
    c = client
    _connecter(c)
    _importer(c, "Connections.csv", "linkedin")
    assert c.get("/status").json()["linkedin_sans_contact"] == 2
    r = _importer(c, "gmail.vcf", "gmail")
    assert r["enrichies"] == 1
    assert c.get("/status").json()["linkedin_sans_contact"] == 1


def test_reimport_meme_uid(client, tmp_path):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    nouveau = (DONNEES / "icloud.vcf").read_text().replace("06 12 34 56 78", "06 99 99 99 99")
    r = c.post("/api/depot", files=[("fichiers", ("icloud-2.vcf", nouveau.encode()))]).json()
    r = c.post("/api/importer", json={"nom": r[0]["nom"], "source": "icloud"}).json()
    assert r["mises_a_jour"] == 1 and r["identiques"] == 2 and r["personnes_creees"] == 0
    d = c.get(f"/api/personnes/{_personne(c, 'Claire')['id']}").json()
    assert len(d["sources"]) == 1 and d["a_revoir"].startswith("fiche mise à jour")
    assert [t["valeur"] for t in d["proposition"]["telephones"]][0] == "+33699999999"


def test_depot_sans_ecrasement_et_securite(client):
    c = client
    _connecter(c)
    r1 = c.post("/api/depot", files=[("fichiers", ("a.vcf", b"x"))]).json()
    r2 = c.post("/api/depot", files=[("fichiers", ("a.vcf", b"y"))]).json()
    assert (r1[0]["nom"], r2[0]["nom"]) == ("a.vcf", "a (2).vcf")
    assert c.post("/api/export", headers={"X-Carnet": ""}).status_code == 403
    c.post("/api/deconnexion")
    assert c.get("/api/contacts").status_code == 401


def test_notes_sans_texte():
    assert n.note("***** ***** *****") == ""
    assert n.note(" --- ") == ""
    assert n.note("Code portail : 1234") == "Code portail : 1234"
    from app.fusion import proposer
    f = proposer([{"id": 1, "source": "icloud", "a_photo": False, "donnees": {"notes": "*****"}},
                  {"id": 2, "source": "gmail", "a_photo": False, "donnees": {"notes": "Voisine"}}])
    assert f["notes"] == "Voisine"


def test_parasites_outlook():
    texte = ("Ce contact est en lecture seule. Pour y apporter des modifications, appuyez sur le lien "
             "ci-dessus pour le modifier dans Outlook.")
    assert n.note(texte) == ""
    assert n.note(texte + "\nCode portail 1234") == "Code portail 1234"
    assert n.site("ms-outlook://people/v3/3/LgAAAA?a=4a41") is None
    assert n.site("x-apple:abc") is None
    assert n.site("exemple.fr")["valeur"] == "exemple.fr"
    f = n.nettoyer({"notes": texte, "sites": [{"valeur": "ms-outlook://people/x", "type": "site"},
                                              {"valeur": "https://exemple.fr", "type": "site"}]})
    assert f["notes"] == "" and [s["valeur"] for s in f["sites"]] == ["https://exemple.fr"]


def test_courriels_pro_proposes():
    f = n.nettoyer({"courriels": [{"valeur": "b.martin@sicaf-cosmetiques.fr", "type": "domicile"},
                                  {"valeur": "claire@gmail.com", "type": "domicile"},
                                  {"valeur": "x@hotmail.fr", "type": "autre"},
                                  {"valeur": "y@wanadoo.fr", "type": "domicile"}]})
    assert [c["type"] for c in f["courriels"]] == ["travail", "domicile", "autre", "domicile"]


def test_note_outlook_tronquee():
    assert n.note("Ce contact est en lecture seule. Pour y apporter des modifications, a") == ""
    assert n.note("Ce contact est en lecture seule. Pour y apporter\nCode 1234") == "Code 1234"


def test_societe_depuis_domaine():
    assert n.societe_depuis_domaine("sicaf-cosmetiques.fr") == "Sicaf Cosmetiques"
    assert n.societe_depuis_domaine("edf.fr") == "EDF"
    assert n.societe_depuis_domaine("sncf.com") == "SNCF"
    assert n.societe_depuis_domaine("mail.groupe-exemple.com") == "Groupe Exemple"
    assert n.domaine_pro("a@gmail.com") is None


def test_revue(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    _importer(c, "gmail.vcf", "gmail")
    claire, jp = _personne(c, "Claire"), _personne(c, "Jean")
    # Claire : cliente, société vidée, courriel pro ; Jean-Pierre : Famille sans anniversaire, ancien « Travail »
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f.update(societe="", groupes=["Clients", "Urgence"])
    f["courriels"] = [x for x in f["courriels"] if "boulangerie" in x["valeur"]]
    f["telephones"] = [t for t in f["telephones"] if not t["mobile"]]
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    g = c.get(f"/api/personnes/{jp['id']}").json()["fiche"]
    g.update(anniversaire="", groupes=["Famille", "Travail"])
    c.put(f"/api/personnes/{jp['id']}", json={"fiche": g, "valider": True})

    r = c.get("/api/revue").json()
    assert [x["nom"] for x in r["anniversaires"]] == ["Jean-Pierre DUBOIS"]
    soc = {x["nom"]: x for x in r["societes"]}
    assert soc["Claire MARTIN"]["proposition"] == "Boulangerie Port"
    d = c.get(f"/api/personnes/{claire['id']}").json()
    assert d["societe_deduite"] == {"valeur": "Boulangerie Port", "origine": "déduite de @boulangerie-port.fr"}
    assert [x["nom"] for x in r["travail_a_classer"]] == ["Jean-Pierre DUBOIS"]
    assert [x["nom"] for x in r["urgence_sans_mobile"]] == ["Claire MARTIN"]

    c.post(f"/api/personnes/{jp['id']}/retoucher", json={"anniversaire": "2/7/1960", "ajouter": ["Collègues"],
                                                        "retirer": ["Travail"]})
    c.post(f"/api/personnes/{claire['id']}/retoucher", json={"societe": "Boulangerie du Port"})
    r = c.get("/api/revue").json()
    assert not r["anniversaires"] and not r["travail_a_classer"]
    assert "Jean-Pierre DUBOIS" in [x["nom"] for x in r["societes"]]   # collègue sans société
    d = c.get(f"/api/personnes/{jp['id']}").json()
    assert d["statut"] == "verifie" and d["fiche"]["anniversaire"] == "1960-07-02"
    assert c.post(f"/api/personnes/{jp['id']}/retoucher", json={"anniversaire": "bof"}).status_code == 400


def test_telegram():
    assert n.site("https://t.me/@id1234")["type"] == "telegram"
    assert n.courriel("https://t.me/@id1234", "domicile") is None
    f = n.nettoyer({"courriels": [{"valeur": "https://t.me/@id1234", "type": "domicile"},
                                  {"valeur": "a@gmail.com", "type": "domicile"}]})
    assert [c["valeur"] for c in f["courriels"]] == ["a@gmail.com"]
    assert f["sites"] == [{"valeur": "https://t.me/@id1234", "type": "telegram"}]
    from app.export import vcard
    assert "X-SOCIALPROFILE;type=telegram:https://t.me/@id1234" in vcard(f, "u")


def test_emoji_vers_groupe():
    n.configurer_emojis("🍕:Amis;🔧:Artisans et services")
    try:
        f = n.nettoyer({"prenom": "Léa 🍕", "groupes": []})
        assert f["groupes"] == ["Amis"]
        assert n.normaliser_fiche({"notes": "plombier 🔧"})["groupes"] == ["Artisans et services"]
        assert n.nettoyer({"prenom": "Léa"}).get("groupes", []) == []
    finally:
        n.configurer_emojis("")


def test_telegram_deja_importe():
    f = n.nettoyer({"sites": [{"valeur": "https://t.me/@id99", "type": "site"}]})
    assert f["sites"][0]["type"] == "telegram"


def test_societes_a_uniformiser(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    _importer(c, "gmail.vcf", "gmail")
    _importer(c, "outlook.csv", "outlook")
    noms = ["bioMérieux", "BIOMERIEUX", "Pierre Fabre", "Pierre Fabre Dermo-Cosmétique", "Total SA"]
    for p, soc in zip(c.get("/api/contacts").json(), noms):
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        f["societe"] = soc
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    groupes = c.get("/api/revue").json()["societes_a_uniformiser"]
    assert sorted(sorted(v["nom"] for v in g["variantes"]) for g in groupes) == [
        ["BIOMERIEUX", "bioMérieux"], ["Pierre Fabre", "Pierre Fabre Dermo-Cosmétique"]]
    bio = next(g for g in groupes if "bioMérieux" in [v["nom"] for v in g["variantes"]])
    assert bio["proposition"] == "bioMérieux"
    r = c.post("/api/societes/uniformiser", json={"variantes": ["bioMérieux", "BIOMERIEUX"], "nom": "bioMérieux"})
    assert r.json()["modifies"] == 2
    c.post("/api/societes/ignorer", json={"variantes": ["Pierre Fabre", "Pierre Fabre Dermo-Cosmétique"]})
    assert c.get("/api/revue").json()["societes_a_uniformiser"] == []


def test_portables_en_mobile():
    f = n.nettoyer({"telephones": [n.telephone("06 12 34 56 78", "domicile"), n.telephone("07 81 23 45 67", "autre"),
                                   n.telephone("06 98 76 54 32", "travail"), n.telephone("05 53 11 22 33", "domicile")]})
    assert [t["type"] for t in f["telephones"]] == ["mobile", "mobile", "travail", "domicile"]


def test_portables_des_proches_en_mobile(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f["groupes"] = ["Jardin secret"]
    f["telephones"][0]["type"] = "travail"            # +33 6 noté travail
    d = c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True}).json()
    types = {t["valeur"]: t["type"] for t in d["fiche"]["telephones"]}
    assert types["+33612345678"] == "mobile" and types["+33553000001"] == "bureau"
    assert "portables_proches" not in c.get("/api/revue").json()


def test_bureau_ou_travail():
    f = n.nettoyer({"telephones": [n.telephone("06 12 34 56 78", "bureau"), n.telephone("05 53 11 22 33", "travail"),
                                   n.telephone("06 98 76 54 32", "travail"), n.telephone("01 23 45 67 89", "bureau")]})
    assert [t["type"] for t in f["telephones"]] == ["travail", "bureau", "travail", "bureau"]
    assert n.type_pro_attendu(n.telephone("+32 2 123 45 67", "bureau")) is None   # étranger : pas de règle


def test_revue_bureau_travail(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    for t in f["telephones"]:
        t["type"] = "bureau" if t["mobile"] else "travail"     # l'inverse de la règle
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    r = c.get("/api/revue").json()["bureau_travail"]
    assert sorted((x["numero"], x["attendu"]) for x in r) == [("+33553000001", "bureau"), ("+33612345678", "travail")]
    c.post(f"/api/personnes/{claire['id']}/retoucher", json={"telephone": "+33612345678", "type_telephone": "travail"})
    c.post(f"/api/personnes/{claire['id']}/retoucher", json={"telephone": "+33553000001", "type_telephone": "travail"})
    assert c.get("/api/revue").json()["bureau_travail"] == []   # le second est gardé tel quel


def test_deux_portables_des_proches(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f["groupes"] = ["Amis"]
    f["telephones"].append({"valeur": "07 81 23 45 67", "type": "autre"})
    d = c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True}).json()
    r = c.get("/api/revue").json()["deux_portables"]
    assert [sorted(x["valeur"] for x in g["numeros"]) for g in r] == [["+33612345678", "+33781234567"]]
    c.post(f"/api/personnes/{claire['id']}/retoucher",
           json={"types": {"+33612345678": "mobile", "+33781234567": "travail"}})
    assert c.get("/api/revue").json()["deux_portables"] == []
    types = {t["valeur"]: t["type"] for t in c.get(f"/api/personnes/{claire['id']}").json()["fiche"]["telephones"]}
    assert types["+33781234567"] == "travail" and types["+33612345678"] == "mobile"


def test_mettre_de_cote(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    plombier = _personne(c, "Plomberie")
    d = c.post(f"/api/personnes/{plombier['id']}/ecarter").json()
    assert d["statut"] == "ecarte"
    assert plombier["id"] not in [p["id"] for p in c.get("/api/file").json()]
    st = c.get("/status").json()
    assert st["total"] == 2 and st["ecartes"] == 1
    # un nouvel export contenant la même fiche ne le ramène pas
    nouveau = (DONNEES / "icloud.vcf").read_text().replace("0553445566", "05 53 44 55 67")
    r = c.post("/api/depot", files=[("fichiers", ("icloud-2.vcf", nouveau.encode()))]).json()
    c.post("/api/importer", json={"nom": r[0]["nom"], "source": "icloud"})
    assert c.get(f"/api/personnes/{plombier['id']}").json()["statut"] == "ecarte"
    d = c.post(f"/api/personnes/{plombier['id']}/restaurer").json()
    assert d["statut"] == "a_reviser"


def test_messageries_dans_la_revue(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    _importer(c, "outlook.csv", "outlook")
    marc = _personne(c, "Marc")                       # ni téléphone ni courriel
    f = c.get(f"/api/personnes/{marc['id']}").json()["fiche"]
    c.put(f"/api/personnes/{marc['id']}", json={"fiche": f, "valider": True})
    assert [x["nom"] for x in c.get("/api/revue").json()["injoignables"]] == ["Marc PETIT"]
    f["sites"] = [{"valeur": "https://t.me/marc", "type": "telegram"}]
    c.put(f"/api/personnes/{marc['id']}", json={"fiche": f, "valider": True})
    assert c.get("/api/revue").json()["injoignables"] == []
    # une étiquette fausse, mise à la main dans une fiche validée
    claire = _personne(c, "Claire")
    g = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    g["sites"] = [{"valeur": "https://wa.me/33612345678", "type": "linkedin"}]
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": g, "valider": True})
    r = c.get("/api/revue").json()["sites_mal_etiquetes"]
    assert r[0]["sites"] == [{"valeur": "https://wa.me/33612345678", "type": "linkedin", "attendu": "whatsapp"}]
    c.post(f"/api/personnes/{claire['id']}/retoucher", json={"types_sites": {"https://wa.me/33612345678": "whatsapp"}})
    assert c.get("/api/revue").json()["sites_mal_etiquetes"] == []


def test_revue_emoji_sans_groupe(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f["surnom"] = "Clairette 🍕"
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})   # aucune règle encore
    n.configurer_emojis("🍕:Amis")
    try:
        r = c.get("/api/revue").json()["emoji_sans_groupe"]
        assert [(x["nom"], x["groupe"], x["champs"]) for x in r] == [("Claire MARTIN", "Amis", ["surnom"])]
        c.post(f"/api/personnes/{claire['id']}/retoucher", json={"ajouter": ["Amis"]})
        assert c.get("/api/revue").json()["emoji_sans_groupe"] == []
    finally:
        n.configurer_emojis("")


def test_artisans_travail_bureau():
    f = n.normaliser_fiche({"groupes": ["Artisans et services"],
                            "telephones": [{"valeur": "06 12 34 56 78", "type": "mobile"},
                                           {"valeur": "05 53 11 22 33", "type": "domicile"},
                                           {"valeur": "+32 470 12 34 56", "type": "mobile"}]})
    assert [t["type"] for t in f["telephones"]] == ["travail", "bureau", "travail"]   # +32 4… : mobile belge


def test_fiche_entreprise_principal():
    f = n.normaliser_fiche({"societe": "Plomberie Garonne", "groupes": ["Artisans et services"],
                            "telephones": [{"valeur": "05 53 44 55 66", "type": "bureau"},
                                           {"valeur": "06 12 34 56 78", "type": "mobile"}]})
    assert [t["type"] for t in f["telephones"]] == ["principal", "travail"]
    g = n.normaliser_fiche({"prenom": "Paul", "societe": "Plomberie Garonne", "groupes": ["Clients"],
                            "telephones": [{"valeur": "05 53 44 55 66", "type": "bureau"}]})
    assert g["telephones"][0]["type"] == "bureau"        # une personne : la règle ne s'applique pas


def test_numeros_de_poste():
    for saisie in ("05 53 00 00 00 poste 123", "05 53 00 00 00 p123", "05 53 00 00 00 #123",
                   "05 53 00 00 00,123", "05 53 00 00 00;123", "+33 5 53 00 00 00 ext. 123"):
        t = n.telephone(saisie, "principal")
        assert (t["valeur"], t["affichage"]) == ("+33553000000;ext=123", "+33 5 53 00 00 00;123"), saisie
    from app.export import vcard
    assert "TEL;type=MAIN;type=pref:+33 5 53 00 00 00;123" in vcard(
        {"telephones": [n.telephone("05 53 00 00 00 poste 123", "principal")]}, "u")


def test_poste_relu_depuis_vcard():
    from app.export import vcard
    texte = vcard({"telephones": [n.telephone("05 53 00 00 00 poste 123", "principal")]}, "u")
    relu, _ = lecteur_vcf.lire(texte)
    assert relu[0].fiche["telephones"][0]["valeur"] == "+33553000000;ext=123"


def test_adresse_client_en_travail():
    f = n.normaliser_fiche({"prenom": "Paul", "groupes": ["Clients"],
                            "adresses": [{"rue": "1 rue A", "ville": "Agen", "type": "domicile"}]})
    assert f["adresses"][0]["type"] == "travail"


def test_groupe_moi_unique(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire, jp = _personne(c, "Claire"), _personne(c, "Jean")
    for p in (claire, jp):
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        f["groupes"] = ["Moi"]
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    assert "Moi" not in c.get(f"/api/personnes/{claire['id']}").json()["fiche"]["groupes"]
    assert c.get(f"/api/personnes/{jp['id']}").json()["fiche"]["groupes"] == ["Moi"]
    assert jp["id"] not in [x["id"] for x in c.get("/api/revue").json()["sans_groupe"]]


def test_collegues_et_clients_travail_bureau():
    for groupe in ("Collègues", "Clients"):
        f = n.normaliser_fiche({"prenom": "Paul", "groupes": [groupe],
                                "telephones": [{"valeur": "06 12 34 56 78", "type": "mobile"},
                                               {"valeur": "05 53 11 22 33", "type": "domicile"}]})
        assert [t["type"] for t in f["telephones"]] == ["travail", "bureau"], groupe


def test_regles_tous_pays():
    assert n.nature("+32479123456") == "mobile" and n.nature("+3222345678") == "fixe"
    assert n.nature("+12025550123") is None            # États-Unis : impossible de trancher
    f = n.normaliser_fiche({"prenom": "Jan", "groupes": ["Collègues"],
                            "telephones": [{"valeur": "+32 479 12 34 56", "type": "mobile"},
                                           {"valeur": "+32 2 234 56 78", "type": "domicile"},
                                           {"valeur": "+1 202 555 0123", "type": "domicile"}]})
    assert [t["type"] for t in f["telephones"]] == ["travail", "bureau", "domicile"]
    g = n.normaliser_fiche({"prenom": "Lies", "groupes": ["Amis"],
                            "telephones": [{"valeur": "+32 479 12 34 56", "type": "travail"}]})
    assert g["telephones"][0]["type"] == "mobile"


def test_revue_numeros_internationaux(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f["groupes"] = ["Collègues"]
    f["telephones"] += [{"valeur": "+1 202 555 0123", "type": "autre"}, {"valeur": "+32 479 12 34 56", "type": "autre"}]
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    r = {x["numero"]: x["detectee"] for x in c.get("/api/revue").json()["numeros_internationaux"]}
    assert r == {"+12025550123": None, "+32479123456": "mobile"}
    c.post(f"/api/personnes/{claire['id']}/retoucher", json={"natures": {"+12025550123": "mobile", "+32479123456": "mobile"}})
    assert c.get("/api/revue").json()["numeros_internationaux"] == []
    types = {t["valeur"]: t["type"] for t in c.get(f"/api/personnes/{claire['id']}").json()["fiche"]["telephones"]}
    assert types["+12025550123"] == "travail"          # collègue + mobile confirmé → travail


def test_meme_nom_de_famille_et_structure():
    from app import doublons as d
    cabinet = d.signature(1, {"societe": "Docteur Chossat PSV Villeneuve"})
    isabelle = d.signature(2, {"prenom": "Isabelle", "nom": "CHOSSAT", "societe": "PSV Villeneuve Sur Lot Prep"})
    pierre = d.signature(3, {"prenom": "Pierre", "nom": "Chossat", "societe": "PSV Villeneuve"})
    structure = d.signature(4, {"societe": "PSV Villeneuve"})
    assert d.comparer(cabinet, isabelle)[0] == d.SCORE_FAMILLE
    assert d.comparer(isabelle, pierre)[0] == 0           # prénoms différents
    assert d.comparer(isabelle, structure)[0] == 0        # la structure seule ne suffit pas
    assert d.SCORE_FAMILLE < d.SEUIL                      # jamais réunis seuls à l'import
    assert [p[:2] for p in d.rapprochements([cabinet, isabelle, pierre, structure], seuil=d.SEUIL_REVUE)] == [(1, 2), (1, 3)]


def test_revue_doublons_possibles(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire, plombier = _personne(c, "Claire"), _personne(c, "Plomberie")
    for p, modif in ((claire, {"societe": "Cabinet Garonne Agen"}),
                     (plombier, {"prenom": "", "nom": "", "societe": "Docteur Martin Garonne"})):
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        f.update(modif)
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    doublons = c.get("/api/revue").json()["doublons_possibles"]
    assert len(doublons) == 1 and doublons[0]["base"]["id"] == claire["id"]
    assert c.post("/api/doublons/ignorer", json={"a": claire["id"], "b": plombier["id"]}).status_code == 200
    assert c.get("/api/revue").json()["doublons_possibles"] == []


# ------------------------------------------------------------------ V2 : écriture iCloud

def _attendre(c):
    import time
    for _ in range(400):
        t = c.get("/api/icloud").json()
        if t["tache"]["etat"] in ("termine", "erreur"):
            return t
        time.sleep(0.025)
    raise AssertionError("tâche iCloud jamais terminée")


def test_synchro_icloud(client, monkeypatch):
    from app.main import etat
    from tests.faux_icloud import FauxICloud
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    # iCloud aujourd'hui : les fiches importées + un champ que carnet ignore, un contact ajouté
    # sur l'iPhone depuis, et un groupe que carnet ne connaît pas
    origine = (DONNEES / "icloud.vcf").read_text()
    origine = origine.replace("UID:AAAA-1111", "item9.X-ABDATE:2010-06-12\r\nitem9.X-ABLabel:_$!<Anniversary>!$_\r\nUID:AAAA-1111")
    origine += ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:Neuf;Nadia;;;\r\nFN:Nadia Neuf\r\nTEL;type=CELL:06 99 88 77 66\r\n"
                "UID:DDDD-4444\r\nEND:VCARD\r\n"
                "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Boulot\r\nX-ADDRESSBOOKSERVER-KIND:group\r\n"
                "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:CCCC-3333\r\nX-ADDRESSBOOKSERVER-MEMBER:urn:uuid:DDDD-4444\r\n"
                "UID:GGGG-0002\r\nEND:VCARD\r\n")
    serveur = FauxICloud(origine)
    cn = etat["carnet"]
    monkeypatch.setattr(cn, "transport_icloud", serveur.transport())
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "icloud_user": "moi@icloud.com",
                                                        "icloud_password": "abcd-efgh-ijkl-mnop"}))

    claire, dubois, plombier = _personne(c, "Claire"), _personne(c, "Jean-Pierre"), _personne(c, "Plomberie")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f["groupes"] = ["Moi", "Urgence", "Famille"]
    f["fonction"] = "Boulangère"
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    f = c.get(f"/api/personnes/{dubois['id']}").json()["fiche"]
    c.put(f"/api/personnes/{dubois['id']}", json={"fiche": f, "valider": True})
    c.post(f"/api/personnes/{plombier['id']}/ecarter")

    # Écrire sans simulation : refusé
    assert c.post("/api/icloud/ecriture", json={"confirme": True}).status_code == 400
    c.post("/api/icloud/simulation")
    t = _attendre(c)
    assert t["tache"]["etat"] == "termine", t["tache"]
    plan = t["plan"]
    assert serveur.ecritures == []                                  # la simulation n'écrit rien
    assert {x["nom"] for x in plan["modifier"]} == {"Claire MARTIN", "Jean-Pierre DUBOIS"}
    assert [(x["nom"], x["motif"]) for x in plan["supprimer"]] == [("Plomberie Garonne", "mis de côté")]
    assert {(g["nom"], g["action"]) for g in plan["groupes"]} == {("Famille", "creer"), ("Moi", "creer"), ("Boulot", "modifier")}
    assert plan["inconnus"] == ["Nadia Neuf"] and plan["groupes_non_geres"] == ["Boulot"]
    assert plan["essai"] == "Claire MARTIN"

    # Essai : seule la fiche « Moi » est écrite
    assert c.post("/api/icloud/ecriture", json={"essai": True}).status_code == 200
    t = _attendre(c)
    assert t["tache"]["etat"] == "termine" and serveur.ecritures[0] == ("PUT", "/1234/carddavhome/card/AAAA-1111.vcf")
    assert len(serveur.ecritures) == 2 and "FN:Moi" in serveur.cartes[serveur.ecritures[1][1]][1]   # + groupe Moi
    carte = serveur.texte("AAAA-1111")
    assert "TITLE:Boulangère" in carte and "X-ABDATE:2010-06-12" in carte      # champ inconnu gardé
    assert "CATEGORIES" not in carte and carte.count("BEGIN:VCARD") == 1
    assert (Path(etat["cfg"].archives).glob("*_icloud-sauvegarde.vcf").__next__().read_text().count("BEGIN:VCARD") == 6)

    # Écriture complète, avec un contact modifié sur l'iPhone entre-temps : conflit, pas écrasé
    c.post("/api/icloud/simulation")
    plan = _attendre(c)["plan"]
    assert {x["nom"] for x in plan["modifier"]} == {"Jean-Pierre DUBOIS"}         # Claire est déjà à jour
    assert c.post("/api/icloud/ecriture", json={}).status_code == 400              # confirmation obligatoire
    iphone = serveur.texte("BBBB-2222").replace("FN:jean-pierre DUBOIS", "FN:JP")
    serveur.modifier_sur_iphone("BBBB-2222", iphone)
    c.post("/api/icloud/ecriture", json={"confirme": True})
    t = _attendre(c)
    bilan = t["journal"][0]
    assert bilan["conflits"] == ["Jean-Pierre DUBOIS"] and serveur.texte("BBBB-2222") == iphone
    assert serveur.texte("CCCC-3333") is None and bilan["supprimes"] == 1
    assert bilan["groupes"] == 2 and bilan["importes"] == 1         # Famille et Boulot (Moi : fait à l'essai)
    famille = next(t for t in serveur.cartes.values() if "FN:Famille" in t[1])[1]
    assert "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:AAAA-1111" in famille
    boulot = serveur.texte("GGGG-0002")
    assert "CCCC-3333" not in boulot and "DDDD-4444" in boulot
    nadia = _personne(c, "Nadia")
    assert nadia["statut"] == "a_reviser"

    # Nouvelle simulation : seul le conflit reste à écrire, Nadia n'est plus inconnue
    c.post("/api/icloud/simulation")
    plan = _attendre(c)["plan"]
    assert [x["nom"] for x in plan["modifier"]] == ["Jean-Pierre DUBOIS"]
    assert plan["creer"] == plan["supprimer"] == plan["groupes"] == plan["inconnus"] == []


def test_icloud_mauvais_mot_de_passe(client, monkeypatch):
    from app.main import etat
    from tests.faux_icloud import FauxICloud
    c = client
    _connecter(c)
    cn = etat["carnet"]
    monkeypatch.setattr(cn, "transport_icloud", FauxICloud("").transport())
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "icloud_user": "moi@icloud.com",
                                                        "icloud_password": "faux"}))
    c.post("/api/icloud/simulation")
    t = _attendre(c)
    assert t["tache"]["etat"] == "erreur" and "mot de passe d'application" in t["tache"]["message"]


def test_icloud_photo_par_lien(client, monkeypatch):
    """iCloud ne donne parfois qu'un lien vers la photo : elle est téléchargée et gardée."""
    import base64
    from app.main import etat
    from tests.faux_icloud import FauxICloud
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    image = b"\xff\xd8\xff\xe0" + b"photo-de-jp" * 20
    origine = (DONNEES / "icloud.vcf").read_text().replace(
        "UID:BBBB-2222", "PHOTO;X-ABCROP-RECTANGLE=ABClipRect_1&0&0&10&10;VALUE=uri:https://p42-contacts.icloud.com/photos/jp\r\nUID:BBBB-2222")
    serveur = FauxICloud(origine)
    serveur.photos["/photos/jp"] = image
    cn = etat["carnet"]
    monkeypatch.setattr(cn, "transport_icloud", serveur.transport())
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "icloud_user": "moi@icloud.com",
                                                        "icloud_password": "abcd-efgh-ijkl-mnop"}))
    dubois = _personne(c, "Jean-Pierre")
    f = c.get(f"/api/personnes/{dubois['id']}").json()["fiche"]
    f["groupes"] = ["Moi"]
    c.put(f"/api/personnes/{dubois['id']}", json={"fiche": f, "valider": True})
    c.post("/api/icloud/simulation")
    _attendre(c)
    c.post("/api/icloud/ecriture", json={"essai": True})
    _attendre(c)
    assert any("FN:Moi" in t for _, t in serveur.cartes.values())     # l'essai crée aussi le groupe Moi
    carte = serveur.texte("BBBB-2222").replace("\r\n ", "")
    assert "VALUE=uri" not in carte and base64.b64encode(image).decode() in carte

    # Photo disparue d'iCloud lors d'une écriture précédente : reprise dans la sauvegarde
    serveur.modifier_sur_iphone("BBBB-2222", "\r\n".join(
        l for l in serveur.texte("BBBB-2222").replace("\r\n ", "").split("\r\n") if not l.startswith("PHOTO")))
    c.post("/api/icloud/simulation")
    assert [x["nom"] for x in _attendre(c)["plan"]["modifier"]] == ["Jean-Pierre DUBOIS"]
    c.post("/api/icloud/ecriture", json={"essai": True})
    _attendre(c)
    assert base64.b64encode(image).decode() in serveur.texte("BBBB-2222").replace("\r\n ", "")


def test_icloud_photo_signalee_par_hash(client, monkeypatch):
    """iCloud signale parfois la photo sans la fournir (X-IMAGEHASH) : carnet réécrit celle des
    exports importés au lieu de la laisser disparaître, et retire les anciens repères."""
    from app.main import etat
    from tests.faux_icloud import FauxICloud
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    texte = (DONNEES / "icloud.vcf").read_text()
    debut = texte.index("PHOTO;")
    texte = texte[:debut] + "X-IMAGETYPE:PHOTO\r\nX-IMAGEHASH:04Wgk79BgmezunyrbGM64g==\r\n" + texte[texte.index("UID:AAAA-1111"):]
    serveur = FauxICloud(texte)
    cn = etat["carnet"]
    monkeypatch.setattr(cn, "transport_icloud", serveur.transport())
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "icloud_user": "moi@icloud.com",
                                                        "icloud_password": "abcd-efgh-ijkl-mnop"}))
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f["groupes"], f["photo"] = ["Moi"], None          # pas de photo retenue dans carnet
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    c.post("/api/icloud/simulation")
    _attendre(c)
    c.post("/api/icloud/ecriture", json={"essai": True})
    _attendre(c)
    carte = serveur.texte("AAAA-1111")
    assert "PHOTO;ENCODING=b" in carte and "X-IMAGEHASH" not in carte and "X-IMAGETYPE" not in carte


def test_icloud_uid_differents(client, monkeypatch, tmp_path):
    """Exports faits depuis l'iPhone : pas d'UID, ou pas celui d'iCloud. Les fiches iCloud sont
    reconnues par leur contenu ; un doublon « carnet-… » créé à tort est supprimé, l'original gardé."""
    from app.main import etat
    from tests.faux_icloud import FauxICloud
    c = client
    _connecter(c)
    import re as _re
    sans_uid = _re.sub(r"^UID:(AAAA|BBBB|CCCC).*\r?\n", "", (DONNEES / "icloud.vcf").read_text(), flags=_re.M)
    r = c.post("/api/depot", files=[("fichiers", ("iphone.vcf", sans_uid.encode()))])
    assert c.post("/api/importer", json={"nom": r.json()[0]["nom"], "source": "icloud"}).status_code == 200
    claire, dubois, plombier = _personne(c, "Claire"), _personne(c, "Jean-Pierre"), _personne(c, "Plomberie")
    for p in (claire, dubois):
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post(f"/api/personnes/{plombier['id']}/ecarter")

    distant = (DONNEES / "icloud.vcf").read_text().replace("TEL;type=HOME;type=VOICE:+33 5 53 11 22 33",
                                                           "TEL;type=HOME;type=VOICE:+33 5 53 11 22 33\r\nNOTE:vu à Agen")
    distant += f"BEGIN:VCARD\r\nVERSION:3.0\r\nN:MARTIN;Claire;;;\r\nFN:Claire MARTIN\r\nUID:carnet-{claire['id']}\r\nEND:VCARD\r\n"
    serveur = FauxICloud(distant)
    cn = etat["carnet"]
    monkeypatch.setattr(cn, "transport_icloud", serveur.transport())
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "icloud_user": "moi@icloud.com",
                                                        "icloud_password": "abcd-efgh-ijkl-mnop"}))
    c.post("/api/icloud/simulation")
    plan = _attendre(c)["plan"]
    assert plan["creer"] == [] and plan["inconnus"] == [] and "alerte" not in plan
    assert {x["nom"] for x in plan["modifier"]} == {"Claire MARTIN", "Jean-Pierre DUBOIS"}
    assert sorted(x["motif"] for x in plan["supprimer"]) == ["doublon créé par carnet, la fiche d'origine est gardée", "mis de côté"]
    c.post("/api/icloud/ecriture", json={"confirme": True})
    _attendre(c)
    assert serveur.texte(f"carnet-{claire['id']}") is None and serveur.texte("CCCC-3333") is None
    assert "NOTE:vu à Agen" not in serveur.texte("BBBB-2222")      # mise à jour de l'original
