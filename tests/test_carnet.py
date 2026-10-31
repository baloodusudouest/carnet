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
    assert {(g["nom"], g["action"]) for g in plan["groupes"]} == {("Famille", "creer"), ("Moi", "creer"), ("Boulot", "supprimer")}
    assert plan["inconnus"] == ["Nadia Neuf"] and plan["groupes_non_geres"] == []
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
    assert serveur.texte("GGGG-0002") is None                       # groupe absent de carnet : supprimé
    assert serveur.texte("DDDD-4444") is not None                   # … mais pas ses contacts
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
    brute = c.get(f"/api/icloud/brute/{dubois['id']}")                 # diagnostic : la carte telle qu'iCloud la renvoie
    assert brute.status_code == 200 and "BBBB-2222" in brute.text and "attachment" in brute.headers["content-disposition"]

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


def test_icloud_cartes_abimees():
    """iCloud colle des propriétés et renvoie du JSON sur plusieurs lignes : la carte est remise
    en forme (UID propre, données Siri retirées) avant d'être réécrite."""
    from app import synchro
    brut = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Aurore\r\n"
            "UID:17A05E05-5B40-4C87-A7D9-8C5E72723A57X-ADDRESSBOOKSERVER-PHONEME-DATA:{\r\n"
            '  "nameChecksum" : 1816191416,\r\n"ttsData" : "o R O \r\n R"\r\n}\r\n],\r\n}\r\n'
            "item2.X-ADDRESSING-GRAMMAR:abc\r\n"
            "X-SOCIALPROFILE;x-user=+1:x-apple:+1X-SHARED-PHOTO-DISPLAY-PREF:ALWAYS_ASK\r\nEND:VCARD\r\n")
    c = synchro.analyser("h", "e", brut)
    assert c.uid == "17A05E05-5B40-4C87-A7D9-8C5E72723A57" and c.brut == brut
    ecrite = synchro.assembler("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Aurore G\r\nUID:17A05E05-5B40-4C87-A7D9-8C5E72723A57\r\nEND:VCARD\r\n", c.texte)
    assert "PHONEME" not in ecrite and "ttsData" not in ecrite and "}" not in ecrite
    assert "item1.X-ADDRESSING-GRAMMAR:abc" in ecrite and "X-SHARED-PHOTO-DISPLAY-PREF:ALWAYS_ASK" in ecrite
    groupe = synchro.carte_groupe("Amis", "g1", [c.uid])
    assert "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:17A05E05-5B40-4C87-A7D9-8C5E72723A57\r\n" in groupe


def test_groupes_personnalises(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    assert c.post("/api/groupes", json={"nom": "Famille"}).status_code == 400          # déjà pris
    assert c.post("/api/groupes/modifier", json={"ancien": "Amis", "nom": "Potes"}).status_code == 400  # intégré
    assert c.post("/api/groupes", json={"nom": "Rugby", "regle": "proches"}).status_code == 200
    assert "Rugby" in c.get("/api/config").json()["groupes"]
    assert c.get("/api/config").json()["regles"]["Rugby"] == "proches"
    claire = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    f["groupes"] = ["Rugby"]
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    fiche = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    assert [t["type"] for t in fiche["telephones"] if t["nature"] == "mobile"] == ["mobile"]   # règle proches
    # Renommer : les fiches suivent
    assert c.post("/api/groupes/modifier", json={"ancien": "Rugby", "nom": "Rugby club", "regle": "travail"}).json()["contacts"] == 1
    fiche = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    assert fiche["groupes"] == ["Rugby club"]
    assert [t["type"] for t in fiche["telephones"] if t["nature"] == "mobile"] == ["travail"]  # règle travail
    nb = {g["nom"]: g["nb"] for g in c.get("/api/groupes").json()}
    assert nb["Rugby club"] == 1
    # Supprimer en déplaçant les contacts vers Amis
    assert c.post("/api/groupes/supprimer", json={"nom": "Rugby club", "vers": "Amis"}).json()["contacts"] == 1
    assert c.get(f"/api/personnes/{claire['id']}").json()["fiche"]["groupes"] == ["Amis"]
    assert "Rugby club" not in c.get("/api/config").json()["groupes"]
    assert c.post("/api/groupes/supprimer", json={"nom": "Urgence"}).status_code == 400


def test_veille_icloud(client, monkeypatch):
    """Veille : après une écriture, rien ne bouge ; puis modification, ajout et suppression sur
    l'iPhone sont repérés. En mode journal rien n'est remis en révision, en mode révision si."""
    from app.main import etat
    from tests.faux_icloud import FauxICloud
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    serveur = FauxICloud((DONNEES / "icloud.vcf").read_text())
    cn = etat["carnet"]
    monkeypatch.setattr(cn, "transport_icloud", serveur.transport())
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "icloud_user": "moi@icloud.com",
                                                        "icloud_password": "abcd-efgh-ijkl-mnop"}))
    for debut in ("Claire", "Jean-Pierre", "Plomberie"):
        p = _personne(c, debut)
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        f["groupes"] = ["Amis"]
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post("/api/icloud/simulation")
    _attendre(c)
    c.post("/api/icloud/ecriture", json={"confirme": True})
    _attendre(c)

    # Juste après l'écriture : aucune différence, même si iCloud réécrit la carte (forme)
    serveur.modifier_sur_iphone("CCCC-3333", serveur.texte("CCCC-3333").replace("END:VCARD", "X-ADDRESSBOOKSERVER-PHONEME-DATA:{}\r\nEND:VCARD"))
    c.post("/api/icloud/veille")
    v = _attendre(c)["veille"]["journal"][0]
    assert (len(v["modifies"]), len(v["nouveaux"]), len(v["supprimes"]), v["forme"]) == (0, 0, 0, 1), v

    # Sur l'iPhone : un numéro changé, un contact ajouté, un contact supprimé
    serveur.modifier_sur_iphone("AAAA-1111", serveur.texte("AAAA-1111").replace("+33 6 12 34 56 78", "+33 6 99 99 99 99"))
    serveur.modifier_sur_iphone("NEUF-1", "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Neuf;Nina;;;\r\nFN:Nina Neuf\r\nUID:NEUF-1\r\nEND:VCARD\r\n")
    del serveur.cartes["/1234/carddavhome/card/BBBB-2222.vcf"]
    c.post("/api/icloud/veille")
    v = _attendre(c)["veille"]["journal"][0]
    assert [m["nom"] for m in v["modifies"]] == ["Claire MARTIN"]
    assert v["modifies"][0]["ecarts"][0]["champ"] == "telephones"
    assert [n["nom"] for n in v["nouveaux"]] == ["Nina Neuf"]
    assert [s["nom"] for s in v["supprimes"]] == ["Jean-Pierre DUBOIS"]
    assert _personne(c, "Claire")["statut"] == "verifie"                      # mode journal : rien ne bouge
    assert c.get("/status").json()["veille"]["modifies"] == 1

    # Mode révision : Claire repasse à réviser, Nina est importée
    c.post("/api/icloud/veille/mode", json={"revision": True})
    c.post("/api/icloud/veille")
    v = _attendre(c)["veille"]["journal"][0]
    assert v["importes"] == 2
    assert _personne(c, "Claire")["statut"] == "a_reviser" and _personne(c, "Nina")["statut"] == "a_reviser"


def test_linkedin_par_api(client, monkeypatch):
    import httpx
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    vus = []

    def repondre(r):
        vus.append(r)
        assert r.headers["authorization"] == "Bearer abc" and r.headers["linkedin-version"] == "202312"
        start = int(r.url.params["start"])
        if start == 0:
            return httpx.Response(200, json={"paging": {"start": 0}, "elements": [{"snapshotDomain": "CONNECTIONS",
                "snapshotData": [{"First Name": "Claire", "Last Name": "Martin", "URL": "https://www.linkedin.com/in/claire-martin",
                                  "Email Address": "", "Company": "Boulangerie du Port", "Position": "Gérante",
                                  "Connected On": "12 Mar 2020"}]}]})
        return httpx.Response(404, text='{"message":"No data found for this memberId"}')
    monkeypatch.setattr(etat["carnet"], "transport_linkedin", httpx.MockTransport(repondre), raising=False)
    pid = _personne(c, "Claire")["id"]
    f = c.get(f"/api/personnes/{pid}").json()["fiche"]
    c.put(f"/api/personnes/{pid}", json={"fiche": f, "valider": True})      # déjà révisée
    r = c.post("/api/linkedin", json={"jeton": "abc"})
    assert r.status_code == 200, r.text
    assert r.json()["enrichies"] == 1 and len(vus) == 2
    claire = c.get(f"/api/personnes/{pid}").json()
    assert any(s["source"] == "linkedin" for s in claire["sources"])
    # La fiche en cours reçoit d'office la fonction et le profil LinkedIn qui lui manquaient
    assert claire["fiche"]["fonction"] == "Gérante"
    assert any(s["type"] == "linkedin" for s in claire["fiche"]["sites"])
    assert claire["fiche"]["societe"] == "Boulangerie du Port"


def test_linkedin_oauth_par_carnet(client, monkeypatch):
    import httpx
    from urllib.parse import parse_qs, urlsplit
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    assert c.post("/api/linkedin/autorisation").status_code == 400          # pas encore configuré
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "linkedin_client_id": "id1",
                                                        "linkedin_client_secret": "s3cr3t"}))

    def repondre(r):
        if r.url.path == "/oauth/v2/accessToken":
            corps = parse_qs(r.content.decode())
            assert corps["code"] == ["CODE1"] and corps["client_secret"] == ["s3cr3t"]
            assert corps["redirect_uri"] == ["https://localhost/carnet-linkedin"]
            return httpx.Response(200, json={"access_token": "abc", "expires_in": 5184000})
        if int(r.url.params["start"]) == 0:
            return httpx.Response(200, json={"elements": [{"snapshotDomain": "CONNECTIONS", "snapshotData": [
                {"First Name": "Claire", "Last Name": "Martin", "Company": "Boulangerie du Port", "Position": "Gérante"}]}]})
        return httpx.Response(404, text="No data found for this memberId")
    monkeypatch.setattr(cn, "transport_linkedin", httpx.MockTransport(repondre), raising=False)
    url = c.post("/api/linkedin/autorisation").json()["url"]
    q = parse_qs(urlsplit(url).query)
    assert q["scope"] == ["r_dma_portability_self_serve"] and q["client_id"] == ["id1"]
    retour = f"https://localhost/carnet-linkedin?code=CODE1&state={q['state'][0]}"
    r = c.post("/api/linkedin/code", json={"adresse": retour})
    assert r.status_code == 200, r.text
    assert r.json()["enrichies"] == 1
    assert c.post("/api/linkedin/code", json={"adresse": retour}).status_code == 400   # usage unique


def test_sauvegarde_synology(client, monkeypatch, tmp_path):
    """Sauvegarde de nuit : export daté + copie Synology à l'identique, bloquée si trop de
    fiches disparaîtraient d'un coup."""
    from app.main import etat
    from tests.faux_icloud import FauxICloud
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    syno = FauxICloud("", utilisateur="carnet", mot_de_passe="pw")
    syno.autres_carnets = [("Contacts de l'équipe", "/1234/carddavhome/equipe/")]   # jamais choisi
    cn = etat["carnet"]
    monkeypatch.setattr(cn, "transport_synology", syno.transport(), raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "synology_url": "http://nas:5000/carddav/carnet/",
                                                        "synology_user": "carnet", "synology_password": "pw"}))
    ids = []
    for debut in ("Claire", "Jean-Pierre", "Plomberie"):
        p = _personne(c, debut)
        ids.append(p["id"])
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        f["groupes"] = ["Amis"]
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post("/api/sauvegardes")
    _attendre(c)
    s = c.get("/api/sauvegardes").json()
    assert s["journal"][0]["erreur"] is None and s["journal"][0]["synology"]["crees"] == 3
    assert s["journal"][0]["synology"]["groupes"] == 1
    assert len(s["fichiers"]) == 1 and c.get(f"/api/sauvegardes/{s['fichiers'][0]['nom']}").text.count("BEGIN:VCARD") == 3
    assert len(syno.cartes) == 4 and c.get("/status").json()["sauvegarde"]["ok"]
    assert all(h.startswith("/1234/carddavhome/card/") for _, h in syno.ecritures)

    # Rien n'a changé : aucune écriture
    avant = len(syno.ecritures)
    c.post("/api/sauvegardes")
    _attendre(c)
    assert len(syno.ecritures) == avant

    # Un seul contact mis de côté : supprimé de Synology (sous le seuil de 5 fiches)
    c.post(f"/api/personnes/{ids[2]}/ecarter")
    c.post("/api/sauvegardes")
    _attendre(c)
    assert c.get("/api/sauvegardes").json()["journal"][0]["synology"]["supprimes"] == 1

    # Base vidée par erreur (simulée) avec beaucoup de fiches en face : copie bloquée
    for i in range(20):
        syno.modifier_sur_iphone(f"carnet-x{i}", f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:X{i}\r\nUID:carnet-x{i}\r\nEND:VCARD\r\n")
    c.post("/api/sauvegardes")
    t = _attendre(c)
    assert t["tache"]["etat"] == "erreur" and "bloquée" in t["tache"]["message"]
    assert syno.texte("carnet-x0") is not None
    c.post("/api/sauvegardes/forcer")
    _attendre(c)
    assert syno.texte("carnet-x0") is None


def _faux_immich_treemich(ecrits=None):
    import httpx, json as _json
    ecrits = ecrits if ecrits is not None else []
    visages = {"im-claire": b"\xff\xd8\xff\xe0visage-claire", "im-paul": b"\xff\xd8\xff\xe0visage-paul"}

    def immich(r):
        assert r.headers["x-api-key"] == "cle"
        if r.method == "PUT":
            ecrits.append(("immich", r.url.path, _json.loads(r.content)))
            return httpx.Response(200, json={})
        if r.url.path == "/api/people":
            return httpx.Response(200, json={"people": [
                {"id": "im-claire", "name": "Claire Martin", "birthDate": None, "isHidden": False},
                {"id": "im-jp", "name": "Jean-Pierre Duboiss", "birthDate": "1970-07-02", "isHidden": False},
                {"id": "im-paul", "name": "Paul Martin", "birthDate": None, "isHidden": False},
                {"id": "im-x", "name": "", "isHidden": False}], "total": 4, "hasNextPage": False})
        pid = r.url.path.split("/")[3]
        return httpx.Response(200, content=visages[pid], headers={"content-type": "image/jpeg"}) if pid in visages \
            else httpx.Response(404)

    def treemich(r):
        if r.url.path == "/auth/login":
            assert _json.loads(r.content) == {"email": "moi@x.fr", "password": "tm"}
            return httpx.Response(200, json={"user": {}}, headers={"set-cookie": "treemich_session=s1; Path=/"})
        assert "treemich_session=s1" in r.headers.get("cookie", "")
        if r.method == "PATCH":
            ecrits.append(("treemich", r.url.path, _json.loads(r.content)))
            return httpx.Response(200, json={})
        if r.url.path == "/people":
            return httpx.Response(200, json={"people": [
                {"id": "t-claire", "name": "Claire Martin", "profile": {"gender": "FEMALE"},
                 "externalIdentities": [{"provider": "IMMICH", "providerPersonId": "im-claire"}]},
                {"id": "t-paul", "name": "Paul Martin", "profile": {"gender": "MALE"}, "externalIdentities": []},
                {"id": "t-lea", "name": "Léa Martin", "profile": {"gender": "FEMALE"}, "externalIdentities": []}]})
        if r.url.path == "/people/t-claire/life-events":
            return httpx.Response(200, json={"lifeEvents": [{"eventType": "BIRTH", "year": 1984, "month": 3, "day": 14}]})
        if r.url.path.endswith("/life-events"):
            return httpx.Response(200, json={"lifeEvents": []})
        if r.url.path == "/export/gedcom":
            return httpx.Response(200, content=b"0 HEAD\n1 SOUR Treemich\n0 TRLR\n")
        if r.url.path == "/relationships":
            return httpx.Response(200, json={"relationships": [
                {"fromPersonId": "t-claire", "toPersonId": "t-paul", "type": "SPOUSE_OF"},
                {"fromPersonId": "t-claire", "toPersonId": "t-lea", "type": "PARENT_OF"}], "nextCursor": None})
        return httpx.Response(404)
    return httpx.MockTransport(immich), httpx.MockTransport(treemich)


def test_liaisons_immich_treemich(client, monkeypatch):
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    t_im, t_tm = _faux_immich_treemich()
    monkeypatch.setattr(cn, "transport_immich", t_im, raising=False)
    monkeypatch.setattr(cn, "transport_treemich", t_tm, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "immich_cle": "cle",
                                                        "treemich_email": "moi@x.fr", "treemich_password": "tm"}))
    for debut in ("Claire", "Jean-Pierre"):
        p = _personne(c, debut)
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    l = c.get("/api/liaisons?rafraichir=true").json()
    assert l["erreurs"] == [] and l["nb_immich"] == 3
    props = {p["nom"]: p for p in l["propositions"]}
    claire = props["Claire MARTIN"]
    assert claire["exacte"] and claire["immich"][0]["id"] == "im-claire" and claire["treemich"]["id"] == "t-claire"
    jp = props["Jean-Pierre DUBOIS"]                 # nom presque identique : proposé, pas exact
    assert not jp["exacte"] and jp["immich"][0]["id"] == "im-jp"
    # Claire avait « Paul Martin » en conjoint (saisi) : Treemich confirme et ajoute sa fille
    c.post("/api/liaisons/valider", json={"liaisons": [{"pid": claire["pid"], "immich": "im-claire", "treemich": "t-claire"}]})
    t = _attendre(c)
    assert t["tache"]["etat"] == "termine", t["tache"]
    f = c.get(f"/api/personnes/{claire['pid']}").json()
    assert f["statut"] == "verifie"
    assert {(n["valeur"], n["type"]) for n in f["fiche"]["noms_associes"]} >= {("Paul Martin", "conjoint"), ("Léa Martin", "enfant")}
    assert any(s["source"] == "immich" for s in f["sources"])
    assert c.get(f"/api/photos/{f['fiche']['photo']}").content.endswith(b"visage-claire")
    assert c.get("/api/revue").json()["relations_treemich"] == []
    assert [x["pid"] for x in c.get("/api/liaisons").json()["liees"]] == [claire["pid"]]
    assert "immich" not in [a["source"] for a in c.get("/api/archives").json()]
    # Refus d'une proposition : plus reproposée
    c.post("/api/liaisons/refuser", json={"pid": jp["pid"], "immich": "im-jp"})
    assert "Jean-Pierre DUBOIS" not in {p["nom"] for p in c.get("/api/liaisons").json()["propositions"]}


def test_relations_treemich_contradiction(client, monkeypatch):
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    t_im, t_tm = _faux_immich_treemich()
    monkeypatch.setattr(cn, "transport_treemich", t_tm, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "treemich_email": "moi@x.fr", "treemich_password": "tm"}))
    p = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
    f["noms_associes"] = [{"valeur": "Paul Martin", "type": "frère"}, {"valeur": "Marc Martin", "type": "enfant"}]
    c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post("/api/liaisons/valider", json={"liaisons": [{"pid": p["id"], "treemich": "t-claire"}]})
    _attendre(c)
    revue = c.get("/api/revue").json()["relations_treemich"]
    assert len(revue) == 1 and {x["valeur"] for x in revue[0]["contact"]} == {"Paul Martin", "Marc Martin"}
    c.post(f"/api/personnes/{p['id']}/relations", json={"choix": "contact"})       # garder : plus redemandé
    c.post("/api/liaisons/actualiser")
    _attendre(c)
    assert c.get("/api/revue").json()["relations_treemich"] == []
    etat["carnet"].base.ecrire_etat("relations_gardees", {})                        # oublié : redemandé
    c.post("/api/liaisons/actualiser")
    _attendre(c)
    assert len(c.get("/api/revue").json()["relations_treemich"]) == 1
    c.post(f"/api/personnes/{p['id']}/relations", json={"choix": "treemich"})
    noms = {(n["valeur"], n["type"]) for n in c.get(f"/api/personnes/{p['id']}").json()["fiche"]["noms_associes"]}
    assert noms == {("Paul Martin", "conjoint"), ("Léa Martin", "enfant")}
    assert c.get("/api/revue").json()["relations_treemich"] == []


def test_corriger_orthographe(client, monkeypatch):
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    ecrits = []
    t_im, t_tm = _faux_immich_treemich(ecrits)
    monkeypatch.setattr(cn, "transport_immich", t_im, raising=False)
    monkeypatch.setattr(cn, "transport_treemich", t_tm, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "immich_cle": "cle",
                                                        "treemich_email": "moi@x.fr", "treemich_password": "tm"}))
    jp, claire = _personne(c, "Jean-Pierre"), _personne(c, "Claire")
    for p in (jp, claire):
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post("/api/liaisons/valider", json={"liaisons": [{"pid": jp["id"], "immich": "im-jp"},
                                                         {"pid": claire["id"], "immich": "im-claire", "treemich": "t-claire"}]})
    _attendre(c)
    liees = {x["nom"]: x for x in c.get("/api/liaisons").json()["liees"]}
    assert liees["Jean-Pierre DUBOIS"]["ecart_nom"] and not liees["Claire MARTIN"]["ecart_nom"]
    # Garder carnet : Immich prend « Jean-Pierre Dubois »
    assert c.post("/api/liaisons/nom", json={"pid": jp["id"], "garder": "carnet"}).json()["nom"] == "Jean-Pierre DUBOIS"
    assert ecrits == [("immich", "/api/people/im-jp", {"name": "Jean-Pierre DUBOIS"})]
    # Garder Immich : carnet prend « Jean-Pierre DUBOISS »
    c.post("/api/liaisons/nom", json={"pid": jp["id"], "garder": "immich"})
    f = c.get(f"/api/personnes/{jp['id']}").json()["fiche"]
    assert (f["prenom"], f["nom"]) == ("Jean-Pierre", "DUBOISS")
    # Treemich suit l'orthographe retenue
    c.post("/api/liaisons/nom", json={"pid": claire["id"], "garder": "carnet"})
    assert ecrits[-2:] == [("immich", "/api/people/im-claire", {"name": "Claire MARTIN"}),
                           ("treemich", "/people/t-claire", {"givenName": "Claire", "surname": "MARTIN",
                                                             "displayNameOverride": "Claire MARTIN"})]
    # Revue des noms Immich : format « Prénom NOM » proposé, liés d'après carnet
    a_formater = {x["id"]: x for x in c.get("/api/liaisons?rafraichir=true").json()["a_formater"]}
    assert a_formater["im-paul"]["propose"] == "Paul MARTIN" and not a_formater["im-paul"]["lie"]
    c.post("/api/immich/renommer", json={"id": "im-paul", "nom": "Paul MARTIN"})
    assert ecrits[-1] == ("immich", "/api/people/im-paul", {"name": "Paul MARTIN"})


def test_home_assistant_reservations(client, monkeypatch):
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    t_im, t_tm = _faux_immich_treemich()
    monkeypatch.setattr(cn, "transport_immich", t_im, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "immich_cle": "cle"}))
    assert c.get("/ha/personnes").status_code == 503                           # pas de jeton défini
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "ha_token": "jeton-ha"}))
    monkeypatch.setitem(etat, "cfg", cn.cfg)
    assert c.get("/ha/personnes").status_code == 401
    h = {"Authorization": "Bearer jeton-ha"}
    claire, jp = _personne(c, "Claire"), _personne(c, "Jean-Pierre")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})
    f = c.get(f"/api/personnes/{jp['id']}").json()["fiche"]
    f["groupes"] = ["Famille"]
    c.put(f"/api/personnes/{jp['id']}", json={"fiche": f, "valider": True})
    c.post("/api/liaisons/valider", json={"liaisons": [{"pid": claire["id"], "immich": "im-claire"}]})
    _attendre(c)
    noms = c.get("/ha/personnes", headers=h).json()["personnes"]
    assert noms == [{"nom": "Claire Martin", "immich": True}, {"nom": "Jean-Pierre DUBOIS", "immich": False}]
    r = c.get("/ha/invite", params={"nom": "Claire Martin (2026-08-16 → 2026-08-23)"}, headers=h).json()
    assert r["naissance"] == "1985-03-14" and r["annee_connue"] and r["immich_id"] == "im-claire"
    assert c.get("/ha/invite", params={"nom": "im-claire"}, headers=h).status_code == 404
    assert c.get("/ha/invite", params={"nom": "https://photos/people/" + "0" * 8 + "-0000-0000-0000-" + "0" * 12},
                 headers=h).status_code == 404
    r = c.get("/ha/invite", params={"nom": "jean-pierre dubois"}, headers=h).json()
    assert r["naissance"] == "--07-02" and not r["annee_connue"]
    assert c.get("/ha/invite", params={"nom": "Inconnu Total"}, headers=h).status_code == 404

    # Calendrier « Anniversaires » : tous les vérifiés ayant une date, même nom que /ha/personnes
    assert c.get("/ha/anniversaires").status_code == 401
    assert c.get("/ha/anniversaires", headers={"Authorization": "Bearer faux"}).status_code == 401
    r = c.get("/ha/anniversaires", headers=h)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    a = r.json()
    assert a["nombre"] == 2 and a["genere_le"]
    assert a["anniversaires"] == [
        {"nom": "Claire Martin", "jour": 14, "mois": 3, "annee": 1985, "immich": True},
        {"nom": "Jean-Pierre DUBOIS", "jour": 2, "mois": 7, "annee": None, "immich": False}]
    assert {x["nom"] for x in a["anniversaires"]} <= {x["nom"] for x in noms}


def test_naissances_vers_immich_et_treemich(client, monkeypatch):
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    ecrits = []
    t_im, t_tm = _faux_immich_treemich(ecrits)
    monkeypatch.setattr(cn, "transport_immich", t_im, raising=False)
    monkeypatch.setattr(cn, "transport_treemich", t_tm, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "immich_cle": "cle",
                                                        "treemich_email": "moi@x.fr", "treemich_password": "tm"}))
    claire, jp = _personne(c, "Claire"), _personne(c, "Jean-Pierre")
    for p in (claire, jp):
        f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
        c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post("/api/liaisons/valider", json={"liaisons": [
        {"pid": claire["id"], "immich": "im-claire", "treemich": "t-claire"},
        {"pid": jp["id"], "immich": "im-jp", "treemich": "t-paul"}]})
    _attendre(c)
    ecrits.clear()
    assert c.post("/api/naissances/ecriture", json={"cible": "immich", "confirme": True}).status_code == 400   # pas de simulation
    c.post("/api/naissances/simulation")
    assert _attendre(c)["tache"]["etat"] == "termine"
    plan = c.get("/api/naissances").json()["plan"]
    lignes = {l["nom"]: l for l in plan["lignes"]}
    assert lignes["Claire MARTIN"]["immich"]["etat"] == "ajouter"           # vide dans Immich
    assert lignes["Claire MARTIN"]["treemich"]["etat"] == "differente"      # 1984 dans l'arbre, 1985 dans carnet
    assert lignes["Jean-Pierre DUBOIS"]["immich"]["etat"] == "annee_inconnue"
    assert ecrits == []                                                       # la simulation n'écrit rien
    # Essai sur une personne, puis Treemich sans remplacer les dates différentes : rien à écrire
    c.post("/api/naissances/ecriture", json={"cible": "immich", "essai": claire["id"]})
    _attendre(c)
    assert ecrits == [("immich", "/api/people/im-claire", {"birthDate": "1985-03-14"})]
    c.post("/api/naissances/simulation")
    _attendre(c)
    assert c.post("/api/naissances/ecriture", json={"cible": "treemich", "confirme": True}).status_code == 400
    c.post("/api/naissances/ecriture", json={"cible": "treemich", "confirme": True, "remplacer": True})
    _attendre(c)
    assert ecrits[-1] == ("treemich", "/people/t-claire", {"birthDate": "1985-03-14"})
    j = c.get("/api/naissances").json()["journal"][0]
    assert j["ecrites"] == [{"nom": "Claire MARTIN", "avant": "1984-03-14", "apres": "1985-03-14"}]
    assert (etat["cfg"].archives / j["sauvegarde"]).read_bytes().startswith(b"0 HEAD")


def test_treemich_patiente_sur_429():
    import httpx
    from app.liens import Treemich
    appels = {"n": 0}

    def repondre(r):
        if r.url.path == "/auth/login":
            return httpx.Response(200)
        appels["n"] += 1
        if appels["n"] <= 2:
            return httpx.Response(429, headers={"retry-after": "5"})
        return httpx.Response(200, json={})
    tm = Treemich("http://tm:4000", "a@b.c", "x", transport=httpx.MockTransport(repondre))
    tm.maj_naissance("t1", "1985-03-14")          # deux refus, puis accepté
    assert appels["n"] == 3


def _jpeg(largeur, hauteur, boite, net=True):
    """Photo de test : fond uni et, à l'emplacement du visage, une texture aléatoire (pas de trame
    régulière, comme un vrai visage) nette ou floue."""
    import io as _io
    import numpy as _np
    from PIL import Image, ImageFilter
    img = Image.new("RGB", (largeur, hauteur), (90, 110, 130))
    x1, y1, x2, y2 = (int(boite[0] * largeur), int(boite[1] * hauteur), int(boite[2] * largeur), int(boite[3] * hauteur))
    alea = _np.random.default_rng(7).integers(0, 255, (y2 - y1, x2 - x1, 3), dtype=_np.uint8)
    texture = Image.fromarray(alea).filter(ImageFilter.GaussianBlur(2 if net else 14))
    img.paste(texture, (x1, y1))
    sortie = _io.BytesIO()
    img.save(sortie, "JPEG", quality=92)
    return sortie.getvalue()


def test_portraits_hd(client, monkeypatch):
    import httpx, json as _json
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    ecrits = []
    t_im, t_tm = _faux_immich_treemich(ecrits)
    # a1 : visage net, assez grand ; a2 : plus grand mais flou ; a3 : coupé au bord ; a4 : trop petit
    photos = {
        "a1": ((0.40, 0.30, 0.60, 0.56), True, 4000, 3000),
        "a2": ((0.30, 0.20, 0.62, 0.62), False, 4000, 3000),
        "a3": ((0.00, 0.30, 0.25, 0.60), True, 4000, 3000),
        "a4": ((0.45, 0.45, 0.48, 0.49), True, 4000, 3000),
    }
    images = {a: _jpeg(1200, 900, b, net) for a, (b, net, _, _) in photos.items()}
    lus = {"faces": 0}

    def immich(r):
        chemin = r.url.path
        if chemin == "/api/search/metadata":
            corps = _json.loads(r.content)
            assert corps["personIds"] == ["im-claire"] and corps["type"] == "IMAGE"
            nouvelles = [] if corps.get("createdAfter") else list(photos)
            return httpx.Response(200, json={"albums": {}, "assets": {"items": [
                {"id": a, "width": photos[a][2], "height": photos[a][3], "originalMimeType": "image/jpeg",
                 "fileCreatedAt": "2025-06-01T10:00:00Z"} for a in nouvelles], "nextCursor": None, "nextPage": None}})
        if chemin == "/api/faces":
            lus["faces"] += 1
            a = r.url.params["id"]
            b = photos[a][0]
            return httpx.Response(200, json=[
                {"id": "f-autre", "boundingBoxX1": 10, "boundingBoxY1": 10, "boundingBoxX2": 600, "boundingBoxY2": 600,
                 "imageWidth": 1440, "imageHeight": 1080, "person": {"id": "im-paul"}},
                {"id": f"f-{a}", "boundingBoxX1": int(b[0] * 1440), "boundingBoxY1": int(b[1] * 1080),
                 "boundingBoxX2": int(b[2] * 1440), "boundingBoxY2": int(b[3] * 1080),
                 "imageWidth": 1440, "imageHeight": 1080, "person": {"id": "im-claire"}}])
        if chemin.startswith("/api/assets/"):
            return httpx.Response(200, content=images[chemin.split("/")[3]], headers={"content-type": "image/jpeg"})
        return t_im.handler(r)

    monkeypatch.setattr(cn, "transport_immich", httpx.MockTransport(immich), raising=False)
    monkeypatch.setattr(cn, "transport_treemich", t_tm, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "immich_cle": "cle",
                                                        "treemich_email": "moi@x.fr", "treemich_password": "tm"}))
    p = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
    c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post("/api/liaisons/valider", json={"liaisons": [{"pid": p["id"], "immich": "im-claire", "treemich": "t-claire"}]})
    _attendre(c)
    l = c.get("/api/portraits").json()
    assert [x["pid"] for x in l["lignes"]] == [p["id"]] and l["lignes"][0]["hd"] is None and l["prochaine"] is None

    c.post("/api/portraits/recherche")
    t = _attendre(c)
    assert t["tache"]["etat"] == "termine", t["tache"]
    ligne = c.get("/api/portraits").json()["lignes"][0]
    assert ligne["hd"]["asset"] == "a1" and not ligne["hd"]["manuel"]       # le flou, le coupé et le petit sont écartés
    assert {x["asset"] for x in ligne["candidats"]} == {"a1"}
    from PIL import Image
    import io as _io
    fiche = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
    img = Image.open(_io.BytesIO(c.get(f"/api/photos/{fiche['photo']}").content))
    assert img.format == "JPEG" and img.width == img.height and img.width > 500
    assert ("immich", "/api/people/im-claire", {"featureFaceAssetId": "a1"}) in ecrits
    assert c.get(f"/api/portraits/apercu/{p['id']}/a1").headers["content-type"] == "image/jpeg"

    # La mise à jour des liaisons ne remet pas la vignette à la place du portrait
    c.post("/api/liaisons/actualiser")
    _attendre(c)
    assert not c.get(f"/api/photos/{fiche['photo']}").content.endswith(b"visage-claire")

    # Recherche suivante : seules les nouvelles photos sont lues ; un choix manuel est gardé
    c.post("/api/portraits/choix", json={"pid": p["id"], "asset": "a1"})
    assert c.get("/api/portraits").json()["lignes"][0]["hd"]["manuel"]
    avant = lus["faces"]
    c.post("/api/portraits/recherche")
    _attendre(c)
    assert lus["faces"] == avant
    assert c.get("/api/portraits").json()["lignes"][0]["hd"]["manuel"]
    assert c.post("/api/portraits/choix", json={"pid": p["id"], "asset": "zz"}).status_code == 400

    # Une fois par mois pendant la nuit
    assert not cn._portraits_dus()
    j = cn.base.etat("photos_hd_journal", [])
    j[0]["le"] = "2020-01-01T00:00:00+01:00"
    cn.base.ecrire_etat("photos_hd_journal", j)
    assert cn._portraits_dus()


def test_portrait_de_face_prefere():
    from app import portraits
    # visage un peu plus grand mais de profil < visage de face, même netteté
    assert portraits.score(450, 150, 0.1) < portraits.score(380, 150, 0.9)
    assert portraits.score(450, 150, None) > portraits.score(380, 150, None)
    # photo sans visage repérable par YuNet : orientation 0 (pénalisée, pas écartée)
    assert portraits.de_face(_jpeg(800, 600, (0.4, 0.3, 0.6, 0.56)), (0.4, 0.3, 0.6, 0.56)) == 0.0


def test_portrait_photo_ecran_reperee():
    import io as _io
    import numpy as _np
    from PIL import Image
    from app import portraits
    boite = (0.25, 0.25, 0.75, 0.75)
    net, ecran = portraits.qualite(_jpeg(800, 800, boite), boite)
    assert ecran < portraits.ECRAN_MAX and net >= portraits.NETTETE_MIN
    # trame régulière (pixels d'un écran photographié) : repérée, malgré beaucoup de « détail » fin
    yy, xx = _np.mgrid[0:800, 0:800]
    trame = 128 + 60 * _np.sin(xx * 2 * _np.pi / 5.3) * _np.sin(yy * 2 * _np.pi / 5.1)
    sortie = _io.BytesIO()
    Image.fromarray(_np.stack([trame] * 3, -1).astype("uint8")).save(sortie, "JPEG", quality=92)
    assert portraits.qualite(sortie.getvalue(), boite)[1] >= portraits.ECRAN_MAX


def test_photo_allegee_pour_icloud():
    import io as _io
    import numpy as _np
    from PIL import Image
    from app import export, portraits
    sortie = _io.BytesIO()
    Image.fromarray(_np.random.default_rng(1).integers(0, 255, (1400, 1400, 3), dtype=_np.uint8)).save(sortie, "JPEG", quality=95)
    lourde = sortie.getvalue()
    assert len(lourde) > 500_000
    carte = export.vcard({"prenom": "A", "nom": "B"}, "u1", (lourde, "image/jpeg"))
    assert len(carte.encode()) < 200_000          # iCloud refuse au-delà de ~256 Ko
    petite = (b"\xff\xd8\xff" + b"x" * 1000, "image/jpeg")
    assert portraits.alleger(petite) == petite    # une photo légère n'est pas retouchée


def test_affiches_iphone(client, monkeypatch):
    import httpx, json as _json
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    t_im, t_tm = _faux_immich_treemich()
    # b1 : visage serré au bord du cadre vertical possible ; b2 : visage plus petit mais avec de la place autour
    photos = {"b1": (0.30, 0.10, 0.70, 0.75), "b2": (0.44, 0.25, 0.56, 0.41)}
    images = {a: _jpeg(1500, 2000, b) for a, b in photos.items()}
    envoyes, albums, supprimes = [], {}, []

    def immich(r):
        chemin = r.url.path
        if chemin == "/api/search/metadata":
            return httpx.Response(200, json={"albums": {}, "assets": {"items": [
                {"id": a, "width": 3000, "height": 4000, "originalMimeType": "image/jpeg", "fileCreatedAt": "2025-01-01"}
                for a in photos], "nextCursor": None, "nextPage": None}})
        if chemin == "/api/faces":
            b = photos[r.url.params["id"]]
            return httpx.Response(200, json=[{"id": "f", "boundingBoxX1": int(b[0] * 1440), "boundingBoxY1": int(b[1] * 1920),
                                              "boundingBoxX2": int(b[2] * 1440), "boundingBoxY2": int(b[3] * 1920),
                                              "imageWidth": 1440, "imageHeight": 1920, "person": {"id": "im-claire"}}])
        if chemin == "/api/assets" and r.method == "POST":
            assert b"archive" in r.content and b"affiche-Claire-MARTIN.jpg" in r.content
            envoyes.append(r.content)
            return httpx.Response(201, json={"id": f"up{len(envoyes)}", "status": "created"})
        if chemin == "/api/assets" and r.method == "DELETE":
            supprimes.extend(_json.loads(r.content)["ids"])
            return httpx.Response(204)
        if chemin == "/api/albums" and r.method == "GET":
            return httpx.Response(200, json=[{"id": i, "albumName": n} for i, n in albums.items()])
        if chemin == "/api/albums" and r.method == "POST":
            albums["al1"] = _json.loads(r.content)["albumName"]
            return httpx.Response(201, json={"id": "al1"})
        if chemin.startswith("/api/albums/al1"):
            return httpx.Response(200, json={"id": "al1"})
        if chemin.startswith("/api/assets/up"):
            return httpx.Response(200, content=b"\xff\xd8\xffaffiche", headers={"content-type": "image/jpeg"})
        if chemin.startswith("/api/assets/"):
            return httpx.Response(200, content=images[chemin.split("/")[3]], headers={"content-type": "image/jpeg"})
        return t_im.handler(r)

    monkeypatch.setattr(cn, "transport_immich", httpx.MockTransport(immich), raising=False)
    monkeypatch.setattr(cn, "transport_treemich", t_tm, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "immich_cle": "cle",
                                                        "treemich_email": "moi@x.fr", "treemich_password": "tm"}))
    p = _personne(c, "Claire")
    f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
    f["groupes"] = ["Famille"]
    c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    c.post("/api/liaisons/valider", json={"liaisons": [{"pid": p["id"], "immich": "im-claire"}]})
    _attendre(c)
    assert c.post("/api/affiches/preparation").status_code == 400          # aucun groupe coché
    a = c.post("/api/affiches/groupes", json={"groupes": ["Famille", "Inconnu"]}).json()
    assert a["groupes"] == ["Famille"] and [l["pid"] for l in a["lignes"]] == [p["id"]]
    c.post("/api/affiches/preparation")
    t = _attendre(c)
    assert t["tache"]["etat"] == "termine", t["tache"]
    ligne = c.get("/api/affiches").json()["lignes"][0]
    assert [x["asset"] for x in ligne["propositions"]] == ["b2"]          # b1 : visage trop serré
    assert ligne["choisie"] is None and envoyes == []                     # rien n'est envoyé sans choix
    assert c.get(f"/api/affiches/proposition/{p['id']}/b2").headers["content-type"] == "image/jpeg"
    assert c.post("/api/affiches/choix", json={"pid": p["id"], "asset": "b1"}).status_code == 400
    c.post("/api/affiches/choix", json={"pid": p["id"], "asset": "b2"})
    assert albums == {"al1": "Affiches de contacts"} and len(envoyes) == 1
    ligne = c.get("/api/affiches").json()["lignes"][0]
    assert ligne["choisie"] == "b2" and ligne["manuel"]
    from PIL import Image
    import io as _io
    corps = envoyes[0]
    img = Image.open(_io.BytesIO(corps[corps.index(b"\xff\xd8\xff"):]))
    assert img.height > img.width * 2                                    # format écran d'iPhone
    # Nouvelle recherche : le choix est gardé ; retirer ; contact sorti du groupe
    c.post("/api/affiches/preparation")
    _attendre(c)
    assert len(envoyes) == 1 and c.get("/api/affiches").json()["lignes"][0]["choisie"] == "b2"
    c.post("/api/affiches/choix", json={"pid": p["id"], "asset": None})
    assert supprimes == ["up1"] and cn.base.etat("affiches") == {}
    c.post("/api/affiches/choix", json={"pid": p["id"], "asset": "b2"})
    c.post("/api/affiches/groupes", json={"groupes": ["Amis"]})
    c.post("/api/affiches/preparation")
    _attendre(c)
    assert supprimes == ["up1", "up2"] and cn.base.etat("affiches") == {}


def test_liaisons_lisent_la_derniere_lecture(client, monkeypatch):
    import httpx
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    t_im, t_tm = _faux_immich_treemich()
    appels = {"immich": 0}

    def compte(r):
        if r.url.path == "/api/people":
            appels["immich"] += 1
        return t_im.handler(r)
    monkeypatch.setattr(cn, "transport_immich", httpx.MockTransport(compte), raising=False)
    monkeypatch.setattr(cn, "transport_treemich", t_tm, raising=False)
    monkeypatch.setattr(cn, "cfg", cn.cfg.__class__(**{**cn.cfg.__dict__, "immich_cle": "cle",
                                                        "treemich_email": "moi@x.fr", "treemich_password": "tm"}))
    l = c.get("/api/liaisons").json()                     # rien en base : lu une fois
    assert appels["immich"] == 1 and l["nb_immich"] == 3 and l["lu_le"]
    cn._cache_liens = None                                # comme après un redémarrage du conteneur
    c.get("/api/liaisons")
    assert appels["immich"] == 1                          # servi depuis la base, Immich non sollicité
    c.get("/api/liaisons?rafraichir=true")
    assert appels["immich"] == 2                          # « Relire » : nouvelle lecture
    vieux = cn.base.etat("liens_cache")
    vieux["le"] = "2020-01-01T00:00:00+01:00"
    cn.base.ecrire_etat("liens_cache", vieux)
    cn._cache_liens = None
    c.get("/api/liaisons")
    assert appels["immich"] == 3                          # plus de 26 h : relu


def test_vignettes_et_compression(client):
    import io as _io
    from PIL import Image
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    sortie = _io.BytesIO()
    Image.new("RGB", (800, 600), (200, 100, 50)).save(sortie, "JPEG")
    with cn.base.transaction() as cx:
        sid = cx.execute("SELECT id FROM sources LIMIT 1").fetchone()["id"]
        cx.execute("UPDATE sources SET photo = ?, photo_type = 'image/jpeg' WHERE id = ?", (sortie.getvalue(), sid))
    r = c.get(f"/api/photos/{sid}?taille=88")
    assert r.headers["content-type"] == "image/webp" and Image.open(_io.BytesIO(r.content)).size == (88, 88)
    assert c.get(f"/api/photos/{sid}?taille=88", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert c.get(f"/api/photos/{sid}").headers["content-type"] == "image/jpeg"     # sans taille : l'original
    assert c.get("/api/contacts", headers={"Accept-Encoding": "gzip"}).status_code == 200


def test_copie_et_restauration_de_la_base(client):
    from app.main import etat
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    cn = etat["carnet"]
    assert c.post("/api/sauvegardes/restauration", json={}).status_code == 400      # pas encore de copie
    c.post("/api/sauvegardes")
    _attendre(c)
    s = c.get("/api/sauvegardes").json()
    assert len(s["bases"]) == 1 and s["bases"][0]["nom"].endswith(".db")
    assert s["journal"][0]["base"]["nom"] == s["bases"][0]["nom"]
    copie = (cn.cfg.archives / "sauvegardes" / s["bases"][0]["nom"]).read_bytes()
    assert not copie.startswith(b"SQLite format 3")                               # chiffrée
    r = c.post("/api/sauvegardes/restauration", json={"cle": "mauvaise"}).json()
    assert not r["ok"] and "clé" in r["motif"]
    r = c.post("/api/sauvegardes/restauration", json={"cle": cn.cfg.db_key}).json()
    assert r["ok"] and r["cle"] == "Enpass" and r["comptes"]["personnes"] > 0 and r["vcf"] is not None
    journal = c.get("/api/sauvegardes").json()["restaurations"]
    assert len(journal) == 2 and cn.cfg.db_key not in str(journal)                # la clé n'est jamais notée


def test_fusion_manuelle_de_plusieurs_fiches_avec_linkedin(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    _importer(c, "Connections.csv", "linkedin")
    tous = c.get("/api/contacts?tout=true").json()
    orphelines = [p for p in tous if p["statut"] == "linkedin"]
    assert orphelines and all(p["id"].startswith("li-") for p in orphelines)
    assert not any(p["statut"] == "linkedin" for p in c.get("/api/contacts").json())   # liste habituelle inchangée
    li = orphelines[0]
    a, b = [p for p in tous if p["statut"] != "linkedin"][:2]
    assert c.post("/api/contacts/fusion", json={"ids": [li["id"]]}).status_code == 400              # une seule fiche
    assert c.post("/api/contacts/fusion", json={"ids": [li["id"], li["id"]]}).status_code == 400
    r = c.post("/api/contacts/fusion", json={"ids": [a["id"], b["id"], li["id"]]})
    assert r.status_code == 200, r.text
    cible = r.json()["id"]
    d = c.get(f"/api/personnes/{cible}").json()
    assert d["statut"] == "a_reviser" and d["a_revoir"] == "fusion manuelle"
    sources = {s["source"] for s in d["sources"]}
    assert "linkedin" in sources and any(s["source"] == "linkedin" and not s["enrichissement"] for s in d["sources"])
    restants = {p["id"] for p in c.get("/api/contacts?tout=true").json()}
    assert li["id"] not in restants and len({a["id"], b["id"]} & restants) == 1


def test_bilan_de_l_accueil(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    b = c.get("/api/bilan").json()
    assert b["statut"]["a_reviser"] > 0 and b["revue"] is not None and b["restauration"] is None
    assert b["liaisons"] is None and b["photos"] == {"hd": 0, "affiches": 0}


def test_ajouter_le_profil_linkedin(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    p = _personne(c, "Jean-Pierre")
    f = c.get(f"/api/personnes/{p['id']}").json()["fiche"]
    c.put(f"/api/personnes/{p['id']}", json={"fiche": f, "valider": True})
    assert c.post(f"/api/personnes/{p['id']}/linkedin", json={"url": "https://exemple.fr/jp"}).status_code == 400
    r = c.post(f"/api/personnes/{p['id']}/linkedin", json={"url": "www.linkedin.com/in/jp-dubois/?trk=x"}).json()
    assert r["linkedin"] == "https://www.linkedin.com/in/jp-dubois"
    d = c.get(f"/api/personnes/{p['id']}").json()
    assert d["statut"] == "verifie" and any(s["type"] == "linkedin" for s in d["fiche"]["sites"])
    ligne = next(x for x in c.get("/api/contacts").json() if x["id"] == p["id"])
    assert ligne["linkedin"] == "https://www.linkedin.com/in/jp-dubois"


@pytest.mark.parametrize("brut, sans_annee, attendu", [
    ("1985-03-04", False, (4, 3, 1985)),
    ("19850304", False, (4, 3, 1985)),
    ("1985-03-04T00:00:00Z", False, (4, 3, 1985)),          # date seule, pas de décalage de fuseau
    ("1985-03-04T23:30:00-05:00", False, (4, 3, 1985)),
    ("--0304", False, (4, 3, None)),
    ("--03-04", False, (4, 3, None)),
    ("1604-07-02", True, (2, 7, None)),                     # X-APPLE-OMIT-YEAR=1604
    ("1604-07-02", False, (2, 7, None)),                    # 1604 seul : année inconnue chez Apple
    ("1850-07-02", True, (2, 7, None)),                     # année < 1900 avec OMIT-YEAR
    ("1950-07-02", True, (2, 7, 1950)),                     # année plausible gardée
    ("--02-29", False, (29, 2, None)),                      # 29 février sans année : valable
    ("1985-02-29", False, None),                            # 1985 n'est pas bissextile
    ("1985-13-01", False, None),
    ("--13-40", False, None),
    ("pas une date", False, None),
    ("", False, None),
    (None, False, None),
])
def test_analyse_des_anniversaires(brut, sans_annee, attendu):
    from app.anniversaires import analyser
    assert analyser(brut, sans_annee=sans_annee) == attendu


def test_anniversaires_tri_et_doublons():
    from app.anniversaires import assembler
    e = [{"nom": "Zoé B", "jour": 1, "mois": 12, "annee": None, "immich": False},
         {"nom": "Adam M", "jour": 29, "mois": 2, "annee": None, "immich": False},
         {"nom": "Adeline F", "jour": 4, "mois": 3, "annee": 1985, "immich": True},
         {"nom": "Adeline F", "jour": 4, "mois": 3, "annee": 1985, "immich": True},
         {"nom": "Bruno C", "jour": 29, "mois": 2, "annee": 1990, "immich": False}]
    r = assembler(e)
    assert [x["nom"] for x in r] == ["Adam M", "Bruno C", "Adeline F", "Zoé B"]


def test_ajouter_plusieurs_contacts_a_un_groupe(client):
    c = client
    _connecter(c)
    _importer(c, "icloud.vcf", "icloud")
    claire, jp = _personne(c, "Claire"), _personne(c, "Jean-Pierre")
    f = c.get(f"/api/personnes/{claire['id']}").json()["fiche"]
    c.put(f"/api/personnes/{claire['id']}", json={"fiche": f, "valider": True})          # vérifiée ; JP à relire
    assert c.post("/api/contacts/groupe", json={"ids": [claire["id"]], "groupe": "Inconnu"}).status_code == 400
    r = c.post("/api/contacts/groupe", json={"ids": [claire["id"], jp["id"], "li-1"], "groupe": "Clients"}).json()
    assert r["modifies"] == 2
    d = c.get(f"/api/personnes/{claire['id']}").json()
    assert d["statut"] == "verifie" and "Clients" in d["fiche"]["groupes"]
    assert "Clients" in c.get(f"/api/personnes/{jp['id']}").json()["fiche"]["groupes"]
    assert c.post("/api/contacts/groupe", json={"ids": [claire["id"]], "groupe": "Clients"}).json()["modifies"] == 0
    c.post("/api/contacts/groupe", json={"ids": [claire["id"]], "groupe": "Clients", "retirer": True})
    assert "Clients" not in c.get(f"/api/personnes/{claire['id']}").json()["fiche"]["groupes"]
