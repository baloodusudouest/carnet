"""Tests de carnet 2 : d'abord tous les scénarios de perte de données, puis les modules."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from app import actions, icloud, liaisons, linkedin, nuit, photos, reprise, sorties, traiter
from app.carnet import Carnet, ErreurCarnet, Occupe
from app.config import Config
from tests.faux_icloud import CARNET, FauxICloud
from tests.faux_services import FauxImmich, FauxTreemich

DONNEES = Path(__file__).parent / "donnees"

PAUL = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:MARTIN;Paul;;;\r\nFN:Paul MARTIN\r\n"
        "TEL;type=CELL;type=VOICE:+33 6 98 76 54 32\r\nBDAY;value=date:1983-01-09\r\nX-PERSO:garder\r\n"
        "UID:DDDD-4444\r\nEND:VCARD\r\n")


def carte_simple(uid: str, nom: str, extra: str = "") -> str:
    prenom, _, famille = nom.partition(" ")
    return (f"BEGIN:VCARD\r\nVERSION:3.0\r\nN:{famille};{prenom};;;\r\nFN:{nom}\r\n{extra}"
            f"UID:{uid}\r\nEND:VCARD\r\n")


@pytest.fixture
def services():
    vcf = (DONNEES / "icloud.vcf").read_text(encoding="utf-8") + PAUL
    return {"icloud": FauxICloud(vcf), "immich": FauxImmich(), "treemich": FauxTreemich(),
            "synology": FauxICloud("", utilisateur="carnet", mot_de_passe="syno")}


def _config(tmp_path: Path, **kw) -> Config:
    (tmp_path / "kit").mkdir(exist_ok=True)
    base = dict(data=tmp_path / "data", state=tmp_path / "state", password="secret", static=tmp_path / "static",
                icloud_user="moi@icloud.com", icloud_password="abcd-efgh-ijkl-mnop", immich_cle="cle",
                immich_url="http://immich:2283", treemich_email="moi@x.fr", treemich_password="tm",
                treemich_url="http://treemich:4000", synology_url="https://nas:4001/carddav/carnet/",
                synology_password="syno", ha_token="jeton-ha", kit_config=tmp_path / "kit",
                emoji_groupes="🔧:Artisans et services")
    base.update(kw)
    return Config(**base)


@pytest.fixture
def c(tmp_path, services) -> Carnet:
    transports = {k: v.transport() for k, v in services.items()}
    cn = Carnet(_config(tmp_path), transports)
    cn.treemich().facteur_attente = 0
    with cn.ecriture():
        icloud.relire(cn, "test")   # première lecture : la référence
    return cn


def points(c, motif=None):
    return [p for p in traiter.liste(c) if motif is None or p["motif"] == motif]


# ================================================================ référence et veille

def test_premiere_lecture_sert_de_reference(c, services):
    assert c.base.lire("reference")["contacts"] == 4
    assert not points(c, "iphone_nouvelle") and not points(c, "iphone_modifiee")
    assert services["icloud"].ecritures == []          # rien n'est écrit en lisant
    f = c.fiches()["AAAA-1111"]
    assert f["prenom"] == "Claire" and f["nom"] == "MARTIN" and f["groupes"] == ["Urgence"] and f["a_photo"]


def test_modification_iphone_va_dans_a_traiter_puis_garder(c, services):
    ic = services["icloud"]
    texte = ic.texte("DDDD-4444").replace("+33 6 98 76 54 32", "+33 6 11 11 11 11")
    ic.modifier_sur_iphone("DDDD-4444", texte)
    with c.ecriture():
        bilan = icloud.relire(c)
    assert bilan["modifies"] == 1
    [p] = points(c, "iphone_modifiee")
    assert [d["champ"] for d in p["donnees"]["champs"]] == ["telephones"]
    assert c.fiches()["DDDD-4444"]["telephones"][0]["valeur"] == "+33611111111"   # iCloud est maître
    actions.repondre(c, p["id"], "garder")
    assert not points(c, "iphone_modifiee")
    assert ic.ecritures == []


def test_modification_iphone_revenir_remet_la_carte_exacte(c, services):
    ic = services["icloud"]
    avant = ic.texte("DDDD-4444")
    ic.modifier_sur_iphone("DDDD-4444", avant.replace("Paul", "Pol"))
    with c.ecriture():
        icloud.relire(c)
    [p] = points(c, "iphone_modifiee")
    actions.repondre(c, p["id"], "revenir")
    assert ic.texte("DDDD-4444") == avant
    assert c.fiches()["DDDD-4444"]["prenom"] == "Paul"
    with c.ecriture():
        assert icloud.relire(c)["modifies"] == 0          # notre propre écriture n'est pas signalée


def test_nouvelle_fiche_iphone(c, services):
    services["icloud"].modifier_sur_iphone("EEEE-5555", carte_simple("EEEE-5555", "Léa Martin"))
    with c.ecriture():
        icloud.relire(c)
    [p] = points(c, "iphone_nouvelle")
    assert p["uid"] == "EEEE-5555" and p["nom"] == "Léa MARTIN"


def test_suppression_iphone_jamais_recreee_seule(c, services):
    ic = services["icloud"]
    del ic.cartes[f"{CARNET}BBBB-2222.vcf"]
    with c.ecriture():
        icloud.relire(c)
    [p] = points(c, "iphone_supprimee")
    assert "BBBB-2222" not in c.fiches()
    nuit.passer(c, "test")
    assert ic.texte("BBBB-2222") is None                 # la nuit ne recrée rien
    actions.repondre(c, p["id"], "recreer")
    assert ic.texte("BBBB-2222") is not None and "BBBB-2222" in c.fiches()
    assert not points(c, "iphone_supprimee")


def test_suppression_confirmee_oublie_les_liaisons(c, services):
    liaisons.lier(c, "BBBB-2222", "immich", "im-jp")
    del services["icloud"].cartes[f"{CARNET}BBBB-2222.vcf"]
    with c.ecriture():
        icloud.relire(c)
    [p] = points(c, "iphone_supprimee")
    actions.repondre(c, p["id"], "confirmer")
    assert not c.base.tous("SELECT * FROM liaisons WHERE uid = 'BBBB-2222'")


def test_coupe_circuit_trop_de_disparitions(tmp_path, services):
    ic = services["icloud"]
    for i in range(40):
        ic.modifier_sur_iphone(f"X-{i}", carte_simple(f"X-{i}", f"Personne Numero{i}"))
    cn = Carnet(_config(tmp_path), {k: v.transport() for k, v in services.items()})
    with cn.ecriture():
        icloud.relire(cn)
    for i in range(10):
        del ic.cartes[f"{CARNET}X-{i}.vcf"]
    with cn.ecriture(), pytest.raises(ErreurCarnet, match="5 %"):
        icloud.relire(cn)
    assert len(cn.fiches()) == 44 and not points(cn, "iphone_supprimee")
    with cn.ecriture():
        icloud.relire_quand_meme(cn)
    assert len(points(cn, "iphone_supprimee")) == 10


def test_lecture_incomplete_ne_change_rien(c, services):
    ic = services["icloud"]
    for i in range(5):
        ic.modifier_sur_iphone(f"Y-{i}", carte_simple(f"Y-{i}", f"Autre Numero{i}"))
    vrai = ic.__call__

    def amputee(r):
        rep = vrai(r)
        if r.method == "REPORT":
            corps = re.sub(r"<d:response><d:href>[^<]*Y-[0-4][^<]*</d:href>.*?</d:response>", "", rep.content.decode(), flags=re.S)
            return httpx.Response(207, content=corps.encode())
        return rep
    c.transports["icloud"] = httpx.MockTransport(amputee)
    with c.ecriture(), pytest.raises(Exception, match="incomplète"):
        icloud.relire(c)
    assert len(c.fiches()) == 4


# ================================================================ écriture

def test_valider_ecrit_garde_le_reste_et_prepare_annuler(c, services):
    ic = services["icloud"]
    f = c.fiche("DDDD-4444")
    f["societe"] = "Cave d'Arfeuille"
    ap = actions.apercu(c, "DDDD-4444", f)
    assert [d["champ"] for d in ap["champs"]] == ["societe"]
    res = actions.valider(c, "DDDD-4444", f)
    texte = ic.texte("DDDD-4444")
    assert "ORG:Cave d'Arfeuille;" in texte and "X-PERSO:garder" in texte      # ligne non gérée gardée
    assert any(Path(c.cfg.sauvegardes).glob("icloud-*-jour.vcf"))            # sauvegarde avant écriture
    actions.annuler(c, res["jeton"])
    assert "ORG:" not in ic.texte("DDDD-4444")
    with pytest.raises(ErreurCarnet):
        actions.annuler(c, res["jeton"])


def test_conflit_iphone_jamais_ecrase(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("DDDD-4444", ic.texte("DDDD-4444").replace("Paul", "Paolo"))   # pas encore relu
    f = c.fiche("DDDD-4444")
    f["fonction"] = "Vigneron"
    with pytest.raises(ErreurCarnet, match="iPhone"):
        actions.valider(c, "DDDD-4444", f)
    assert "Paolo" in ic.texte("DDDD-4444") and "Vigneron" not in ic.texte("DDDD-4444")
    [p] = points(c, "conflit")
    assert p["donnees"]["iphone"]["prenom"] == "Paolo"
    actions.repondre(c, p["id"], "reprendre")
    assert "Vigneron" in ic.texte("DDDD-4444")


def test_groupes_cartes_icloud(c, services):
    ic = services["icloud"]
    f = c.fiche("DDDD-4444")
    f["groupes"] = ["Famille", "Urgence"]
    actions.valider(c, "DDDD-4444", f)
    urgence = ic.texte("GGGG-0001")
    assert "urn:uuid:DDDD-4444" in urgence and "urn:uuid:AAAA-1111" in urgence
    famille = [t for _, t in ic.cartes.values() if "FN:Famille" in t]
    assert famille and "urn:uuid:DDDD-4444" in famille[0]
    with c.ecriture():
        assert icloud.relire(c)["modifies"] == 0
    assert c.fiches()["DDDD-4444"]["groupes"] == ["Famille", "Urgence"]


def test_fiche_trop_lourde_refusee(c, services):
    f = c.fiche("DDDD-4444")
    f["notes"] = "x" * 120_000
    with pytest.raises(ErreurCarnet, match="trop lourde"):
        actions.valider(c, "DDDD-4444", f)
    assert services["icloud"].ecritures == []


def test_verrou_un_seul_ecrivain(c):
    with c.ecriture():
        with pytest.raises(Occupe):
            nuit.passer(c, "test")


def test_restaurer_une_fiche(c, services):
    ic = services["icloud"]
    avant = ic.texte("BBBB-2222")
    nom = icloud.sauvegarder(c, "test")
    f = c.fiche("BBBB-2222")
    f["notes"] = "changée"
    actions.valider(c, "BBBB-2222", f)
    contenu = {x["uid"]: x for x in icloud.contenu_sauvegarde(c, nom)}
    assert contenu["BBBB-2222"]["etat"] == "differente" and contenu["CCCC-3333"]["etat"] == "identique"
    with c.ecriture():
        bilan = icloud.restaurer(c, nom, ["BBBB-2222"])
    assert bilan["restaurees"] == 1
    assert ic.texte("BBBB-2222") == avant
    assert not points(c, "iphone_modifiee")


def test_purge_des_sauvegardes(c):
    dossier = c.cfg.sauvegardes
    dossier.mkdir(parents=True, exist_ok=True)
    from app.temps import maintenant
    from datetime import timedelta
    jour = maintenant().date()
    for age in (0, 10, 40, 41, 70, 400):
        d = jour - timedelta(days=age)
        (dossier / f"icloud-{d:%Y-%m-%d}_000000-nuit.vcf").write_text("x")
    icloud.purger(c)
    restants = sorted(f.name[7:17] for f in dossier.glob("icloud-*.vcf"))
    assert len(restants) == 4 and f"{jour - timedelta(days=400):%Y-%m-%d}" not in restants


# ================================================================ la nuit

def test_nuit_liaisons_sures_et_ecritures_sures(c, services):
    ic = services["icloud"]
    bilan = nuit.passer(c, "test")
    assert bilan["erreur"] is None, bilan
    lies = c.liaisons()
    assert lies["DDDD-4444"]["immich"] == "im-paul" and lies["DDDD-4444"]["immich_statut"] == "auto"
    assert lies["AAAA-1111"]["immich"] == "im-claire" and lies["AAAA-1111"]["treemich"] == "t-claire"
    assert "BBBB-2222" not in lies                          # nom approchant : seulement proposé
    assert "PHOTO" in ic.texte("DDDD-4444")                  # photo posée (Paul n'en avait pas)
    assert bilan["ecrites"] == 1
    assert not any(m == "DELETE" for m, _ in ic.ecritures)
    assert len(ic.texte("DDDD-4444").encode()) < icloud.TAILLE_MAX
    assert points(c, "liaison") and points(c, "liaison")[0]["uid"] == "BBBB-2222"
    # La photo existante de Claire n'est jamais remplacée
    assert ic.texte("AAAA-1111").count("PHOTO") == 1


def test_nuit_sans_reference_ne_fait_que_lire(tmp_path, services):
    cn = Carnet(_config(tmp_path), {k: v.transport() for k, v in services.items()})
    bilan = nuit.passer(cn, "test")
    assert cn.base.lire("reference") and bilan["ecrites"] == 0 and not cn.liaisons()
    assert services["icloud"].ecritures == []


def test_nuit_date_manquante_et_plafond(c, services, monkeypatch):
    ic = services["icloud"]
    texte = ic.texte("DDDD-4444").replace("BDAY;value=date:1983-01-09\r\n", "")
    ic.modifier_sur_iphone("DDDD-4444", texte)
    with c.ecriture():
        icloud.relire(c)
    # Tant que la modification de l'iPhone n'est pas relue, la nuit ne touche pas la fiche
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    nuit.passer(c, "test")
    assert "BDAY" not in ic.texte("DDDD-4444")
    actions.repondre(c, points(c, "iphone_modifiee")[0]["id"], "garder")
    monkeypatch.setattr(nuit, "PLAFOND", 0)
    bilan = nuit.passer(c, "test")
    assert bilan["ecrites"] == 0 and bilan["reportees"] >= 1
    monkeypatch.setattr(nuit, "PLAFOND", 20)
    nuit.passer(c, "test")
    assert "BDAY" in ic.texte("DDDD-4444") and "1983-01-09" in ic.texte("DDDD-4444")


def test_nuit_lecture_en_erreur_n_ecrit_rien(c, services):
    c.transports["icloud"] = httpx.MockTransport(lambda r: httpx.Response(401))
    bilan = nuit.passer(c, "test")
    assert bilan["erreur_lecture"] and bilan["ecrites"] == 0
    assert services["synology"].ecritures == []


# ================================================================ fusion et doublons

def test_fusion_transfere_liaisons_et_retire_la_fiche(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("EEEE-5555", carte_simple("EEEE-5555", "Paul Martin", "TEL;type=CELL:+33 6 98 76 54 32\r\n"))
    with c.ecriture():
        icloud.relire(c)
    assert any({p["donnees"]["a"], p["donnees"]["b"]} == {"DDDD-4444", "EEEE-5555"} for p in points(c, "doublon"))
    liaisons.lier(c, "EEEE-5555", "immich", "im-paul")
    prop = actions.proposition_fusion(c, "DDDD-4444", "EEEE-5555")
    actions.fusionner(c, "DDDD-4444", "EEEE-5555", prop["proposee"])
    assert ic.texte("EEEE-5555") is None and "EEEE-5555" not in c.fiches()
    assert c.liaisons()["DDDD-4444"]["immich"] == "im-paul"
    assert not points(c, "doublon")


def test_doublon_pas_la_meme_personne(c, services):
    services["icloud"].modifier_sur_iphone("EEEE-5555", carte_simple("EEEE-5555", "Paul Martin", "TEL;type=CELL:+33 6 98 76 54 32\r\n"))
    with c.ecriture():
        icloud.relire(c)
    [p] = [p for p in points(c, "doublon") if p["donnees"]["b"] in ("EEEE-5555", "DDDD-4444")]
    actions.repondre(c, p["id"], "distincts")
    assert not [p for p in points(c, "doublon") if "EEEE-5555" in (p["donnees"]["a"], p["donnees"]["b"])]


# ================================================================ forme, émoji, liaisons, dates

def test_forme_du_nom_et_des_numeros(c, services):
    forme = {p["uid"]: p for p in points(c, "forme")}
    assert "AAAA-1111" in forme and "BBBB-2222" in forme
    ecarts = {e["champ"] for e in forme["AAAA-1111"]["donnees"]["ecarts"]}
    assert ecarts == {"nom", "telephone"}
    actions.repondre(c, forme["AAAA-1111"]["id"], "appliquer")
    texte = services["icloud"].texte("AAAA-1111")
    assert "FN:Claire MARTIN" in texte and "+33 6 12 34 56 78" in texte
    assert "AAAA-1111" not in {p["uid"] for p in points(c, "forme")}


def test_emoji_groupe(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("CCCC-3333", ic.texte("CCCC-3333").replace("FN:Plomberie Garonne", "FN:Plomberie Garonne 🔧")
                           .replace("ORG:Plomberie Garonne;", "ORG:Plomberie Garonne 🔧;"))
    with c.ecriture():
        icloud.relire(c)
    [p] = points(c, "emoji")
    actions.repondre(c, p["id"], "appliquer")
    assert "Artisans et services" in c.fiches()["CCCC-3333"]["groupes"]


def test_liaison_proposee_puis_pas_lui(c):
    liaisons.donnees(c)
    [p] = [p for p in points(c, "liaison") if p["uid"] == "BBBB-2222"]
    actions.repondre(c, p["id"], "pas_lui")
    assert not [p for p in points(c, "liaison") if p["uid"] == "BBBB-2222"]
    liaisons.lier(c, "BBBB-2222", "immich", "im-jp")
    liaisons.delier(c, "BBBB-2222", "immich")
    assert not liaisons.proches(c, "BBBB-2222")      # refusée pour de bon


def test_une_personne_un_seul_contact(c):
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    with pytest.raises(ErreurCarnet, match="déjà liée"):
        liaisons.lier(c, "BBBB-2222", "immich", "im-paul")


def test_date_tranchee_ecrite_partout(c, services):
    services["immich"].personnes[2]["birthDate"] = "1983-01-10"
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    liaisons.lier(c, "DDDD-4444", "treemich", "t-paul")
    liaisons.donnees(c, rafraichir=True)
    [p] = [p for p in points(c, "date") if p["uid"] == "DDDD-4444"]
    assert p["donnees"]["valeurs"] == {"carnet": "1983-01-09", "immich": "1983-01-10", "treemich": "1983-01-09"}
    actions.repondre(c, p["id"], "choisir", "1983-01-09")
    assert ("PUT", "/api/people/im-paul", {"birthDate": "1983-01-09"}) in services["immich"].ecrits
    assert services["treemich"].ecrits[-1] == ("/people/t-paul", {"birthDate": "1983-01-09"})


def test_renommage_et_relations(c, services):
    services["immich"].personnes[2]["name"] = "Paul Martin"
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    liaisons.lier(c, "DDDD-4444", "treemich", "t-paul")
    liaisons.lier(c, "AAAA-1111", "treemich", "t-claire")
    liaisons.donnees(c, rafraichir=True)
    [n] = [p for p in points(c, "nom") if p["uid"] == "DDDD-4444" and p["donnees"]["service"] == "immich"]
    actions.repondre(c, n["id"], "renommer")
    assert ("PUT", "/api/people/im-paul", {"name": "Paul MARTIN"}) in services["immich"].ecrits
    rel = [p for p in points(c, "relations") if p["uid"] == "DDDD-4444"]
    assert rel and rel[0]["donnees"]["ajouts"] == [{"valeur": "Claire MARTIN", "type": "conjoint"}]
    actions.repondre(c, rel[0]["id"], "ajouter")
    assert "Claire MARTIN" in services["icloud"].texte("DDDD-4444")


# ================================================================ photos

def test_portrait_choisi_et_affiche(c, services):
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    cands = photos.candidats(c, "DDDD-4444")
    assert [x["asset"] for x in cands] == ["p1"]
    photos.poser(c, "DDDD-4444", "p1")
    assert "PHOTO" in services["icloud"].texte("DDDD-4444")
    assert photos.vignette(c, "DDDD-4444") is not None
    a = photos.preparer_affiche(c, "DDDD-4444")
    assert a["immich"] == "aff-1"
    photos.marquer_posee(c, "DDDD-4444", True)
    assert photos.affiches(c)[0]["posee"]


# ================================================================ LinkedIn

CSV = ("Notes:\nx\n\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
       "Paul,Martin,https://www.linkedin.com/in/paul-martin,,Cave Martin,Caviste,01 Jan 2020\n"
       "Inconnu,Total,https://www.linkedin.com/in/inconnu,,Acme,Chef,01 Jan 2020\n")


def test_linkedin_incremental(c, services):
    b = linkedin.importer(c, CSV)
    assert b["rattachees"] == 1 and b["sans_contact"] == 1 and b["proposees"] == 1
    [p] = points(c, "linkedin")
    actions.repondre(c, p["id"], "appliquer")
    assert "ORG:Cave Martin;" in services["icloud"].texte("DDDD-4444")
    # Réimport identique : rien de nouveau
    assert linkedin.importer(c, CSV)["proposees"] == 0
    # Nouveau poste, la fiche portait l'ancien : écrit seul la nuit
    linkedin.importer(c, CSV.replace("Caviste", "Gérant"))
    assert not points(c, "linkedin")
    nuit.passer(c, "test")
    assert "TITLE:Gérant" in services["icloud"].texte("DDDD-4444")


def test_linkedin_detachee_reste_detachee(c):
    linkedin.importer(c, CSV)
    linkedin.rattacher(c, "linkedin.com/in/paul-martin", None)
    traiter.ignorer(c, "linkedin", points(c, "linkedin")[0]["cle"]) if points(c, "linkedin") else None
    b = linkedin.importer(c, CSV.replace("Caviste", "Autre"))
    assert b["rattachees"] == 0
    assert c.base.un("SELECT uid FROM linkedin WHERE url = 'linkedin.com/in/paul-martin'")["uid"] is None


def test_linkedin_api_portabilite(c):
    def repondre(r):
        if "accessToken" in r.url.path:
            return httpx.Response(200, json={"access_token": "jeton"})
        start = int(r.url.params.get("start", 0))
        if start:
            return httpx.Response(404, text="No data found")
        return httpx.Response(200, json={"elements": [{"snapshotDomain": "CONNECTIONS", "snapshotData": [
            {"First Name": "Paul", "Last Name": "Martin", "URL": "https://www.linkedin.com/in/paul-martin",
             "Company": "Cave Martin", "Position": "Caviste"}]}]})
    c.transports["linkedin"] = httpx.MockTransport(repondre)
    object.__setattr__(c, "cfg", _config(Path(c.cfg.state).parent, linkedin_client_id="id", linkedin_client_secret="s"))
    url = linkedin.autorisation(c)["url"]
    etat = re.search(r"state=([^&]+)", url).group(1)
    b = linkedin.code(c, f"https://localhost/carnet-linkedin?code=abc&state={etat}")
    assert b["rattachees"] == 1


# ================================================================ sorties

def test_synology_miroir_et_coupe_circuit(c, services):
    syno = services["synology"]
    b = sorties.copier_synology(c)
    assert b["crees"] == 5 and syno.texte("DDDD-4444") is not None
    for i in range(30):
        syno.modifier_sur_iphone(f"Z-{i}", carte_simple(f"Z-{i}", f"Etrange Numero{i}"))
    b = sorties.copier_synology(c)
    assert not b["ok"] and syno.texte("Z-0") is not None
    assert sorties.copier_synology(c, forcer=True)["supprimes"] == 30


def test_synology_ancienne_copie_remplacee(c, services):
    syno = services["synology"]
    for i in range(10):
        syno.modifier_sur_iphone(f"carnet-{i}", carte_simple(f"carnet-{i}", f"Ancien Numero{i}"))
    b = sorties.copier_synology(c)
    assert b["ok"] and b["supprimes"] == 10 and b["crees"] == 5


def test_kit_urgence(c):
    res = sorties.envoyer_kit(c)
    texte = (c.cfg.kit_config / "contacts-urgence.vcf").read_text()
    assert res["nb"] == 1 and "UID:AAAA-1111" in texte and "UID:DDDD-4444" not in texte


def test_home_assistant_adresses(c):
    from fastapi.testclient import TestClient
    from app import main
    main.ETAT["carnet"] = c
    with TestClient(main.app) as client:
        assert client.get("/ha/contacts").status_code == 401
        h = {"Authorization": "Bearer jeton-ha"}
        contacts = client.get("/ha/contacts", headers=h).json()["contacts"]
        assert {x["carnet_id"] for x in contacts} == {"AAAA-1111", "BBBB-2222", "CCCC-3333", "DDDD-4444"}
        ann = client.get("/ha/anniversaires", headers=h).json()["anniversaires"]
        assert [(a["jour"], a["mois"], a["annee"]) for a in ann][:2] == [(9, 1, 1983), (14, 3, 1985)]
        assert any(a["annee"] is None for a in ann)          # sans année : null
        liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
        assert client.get("/ha/personnes", headers=h).json()["personnes"] == [{"nom": "Paul MARTIN", "immich": True}]
        assert client.get("/ha/invite", params={"nom": "Paul MARTIN (2026-08-16 → 2026-08-23)"}, headers=h).json()["naissance"] == "1983-01-09"
        assert client.get("/ha/invite", params={"nom": "Personne"}, headers=h).status_code == 404
        statut = client.get("/status").json()
        assert statut["total"] == 4 and "a_reviser" in statut and statut["reference"]
    main.ETAT.clear()


def test_api_connexion_obligatoire(c):
    from fastapi.testclient import TestClient
    from app import main
    main.ETAT["carnet"] = c
    with TestClient(main.app) as client:
        assert client.get("/api/contacts").status_code == 401
        assert client.post("/api/connexion", json={"mot_de_passe": "faux"}).status_code == 401
        assert client.post("/api/connexion", json={"mot_de_passe": "secret"}).status_code == 200
        liste = client.get("/api/contacts").json()
        assert [x["nom"] for x in liste][0] == "jean-pierre DUBOIS" or len(liste) == 4
        fiche = client.get("/api/contacts/DDDD-4444").json()["fiche"]
        fiche["fonction"] = "Vigneron"
        assert client.post("/api/contacts/DDDD-4444/apercu", json={"fiche": fiche}).json()["champs"][0]["champ"] == "fonction"
        assert client.put("/api/contacts/DDDD-4444", json={"fiche": fiche}).status_code == 400   # version exigée
        etag = client.get("/api/contacts/DDDD-4444").json()["etag"]
        r = client.put("/api/contacts/DDDD-4444", json={"fiche": fiche, "etag": etag}).json()
        assert client.post(f"/api/annuler/{r['jeton']}").json()["ok"]
        assert client.get("/api/a-traiter").status_code == 200
        assert client.get("/api/etat").json()["services"]["icloud"]
        client.post("/api/deconnexion")
        assert client.get("/api/contacts").status_code == 401
    main.ETAT.clear()


def test_import_vcf_cree_apres_validation(c, services):
    from fastapi.testclient import TestClient
    from app import main
    main.ETAT["carnet"] = c
    with TestClient(main.app) as client:
        client.post("/api/connexion", json={"mot_de_passe": "secret"})
        vcf = carte_simple("IMP-1", "Zoé Durand", "TEL;type=CELL:06 55 44 33 22\r\n")
        r = client.post("/api/import", files={"fichier": ("x.vcf", vcf.encode(), "text/vcard")}).json()
        assert r["a_traiter"] == 1
        [p] = points(c, "import")
        assert services["icloud"].ecritures == []
        client.post(f"/api/a-traiter/{p['id']}", json={"action": "creer"})
        assert any("Zoé" in t for _, t in services["icloud"].cartes.values())
    main.ETAT.clear()


# ================================================================ reprise de la 1.3

def test_reprise_depuis_la_base_1_3(tmp_path, services):
    import sqlcipher3
    state = tmp_path / "state"
    state.mkdir()
    ancienne = sqlcipher3.connect(str(state / "carnet.db"))
    ancienne.execute("PRAGMA key = 'cle-ancienne'")
    ancienne.executescript("""
        CREATE TABLE etat (cle TEXT PRIMARY KEY, valeur TEXT);
        CREATE TABLE sources (id INTEGER PRIMARY KEY, source TEXT, uid TEXT, donnees TEXT, personne_id TEXT);
        CREATE TABLE distinctes (a INTEGER, b INTEGER);""")
    etat = {"icloud_suivi": {"p1": {"uid": "DDDD-4444"}},
            "liaisons": {"p1": {"immich": "im-paul", "treemich": "t-paul"}, "p2": {"immich": "im-jp"}},
            "liaisons_refusees": ["p3|im-claire"],
            "photos_hd": {"p1": {"asset": "p1", "manuel": True}},
            "photos_hd_candidats": {"p1": [{"asset": "p1", "boite": [0.3, 0.3, 0.6, 0.55], "taille": 400}]},
            "affiches": {"p1": {"immich_asset": "aff-9", "posee": "2026-10-01T10:00:00+02:00", "source": "p1"}}}
    for k, v in etat.items():
        ancienne.execute("INSERT INTO etat VALUES (?, ?)", (k, json.dumps(v)))
    ancienne.execute("INSERT INTO sources VALUES (1, 'icloud', 'AAAA-1111', '{}', 'p3')")
    ancienne.execute("INSERT INTO sources VALUES (2, 'linkedin', 'linkedin.com/in/paul-martin', ?, 'p1')",
                     (json.dumps({"prenom": "Paul", "nom": "MARTIN", "societe": "Cave", "fonction": "Caviste"}),))
    ancienne.commit()
    ancienne.close()
    avant = (state / "carnet.db").read_bytes()
    cn = Carnet(_config(tmp_path, ancienne_base=state / "carnet.db", ancienne_cle="cle-ancienne"),
                {k: v.transport() for k, v in services.items()})
    assert not reprise.a_faire(cn)              # il faut d'abord la référence iCloud
    with cn.ecriture():
        icloud.relire(cn)
    assert reprise.a_faire(cn)
    b = reprise.reprendre(cn)
    assert b["erreur"] is None and b["liaisons"] == 2 and b["ignorees"] == 1 and b["affiches"] == 1
    assert cn.liaisons()["DDDD-4444"] == {"immich": "im-paul", "immich_statut": "confirmee",
                                          "treemich": "t-paul", "treemich_statut": "confirmee"}
    assert cn.base.un("SELECT * FROM refus WHERE uid = 'AAAA-1111' AND ext_id = 'im-claire'")
    assert cn.base.un("SELECT uid FROM linkedin")["uid"] == "DDDD-4444"
    assert not reprise.a_faire(cn)              # une seule fois
    assert (state / "carnet.db").read_bytes() == avant      # l'ancienne base n'est jamais modifiée


def test_reprise_cle_fausse(tmp_path, services):
    import sqlcipher3
    state = tmp_path / "state"
    state.mkdir()
    a = sqlcipher3.connect(str(state / "carnet.db"))
    a.execute("PRAGMA key = 'bonne'")
    a.execute("CREATE TABLE etat (cle TEXT, valeur TEXT)")
    a.commit()
    a.close()
    cn = Carnet(_config(tmp_path, ancienne_base=state / "carnet.db", ancienne_cle="fausse"),
                {k: v.transport() for k, v in services.items()})
    with cn.ecriture():
        icloud.relire(cn)
    assert "CARNET_DB_KEY" in reprise.reprendre(cn)["erreur"]


# ================================================================ relecture indépendante : cas ajoutés

RICHE = ("BEGIN:VCARD\r\nVERSION:3.0\r\nN:DURAND;Marc;;Dr.;Jr\r\nFN:Marc DURAND\r\nORG:Hôpital;Cardiologie\r\n"
         "item1.TEL:+33 5 53 00 00 09\r\nitem1.X-ABLabel:Gîte\r\nTEL;type=FAX:+33 5 53 00 00 08\r\n"
         "ADR;type=WORK:BP 12;Bâtiment B;1 rue Haute;Agen;;47000;France\r\nIMPP;X-SERVICE-TYPE=Skype:skype:marc.d\r\n"
         "NOTE:Ligne 1\r\nUID:RICH-0001\r\nEND:VCARD\r\n")


def test_ecriture_garde_les_lignes_d_origine(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("RICH-0001", RICHE)
    with c.ecriture():
        icloud.relire(c)
    traiter.retirer(c, "iphone_nouvelle", "RICH-0001")
    f = c.fiche("RICH-0001")
    f["fonction"] = "Chef de service"
    actions.valider(c, "RICH-0001", f, etag_vu=actions._etag(c, "RICH-0001"))
    texte = ic.texte("RICH-0001")
    for ligne in ("N:DURAND;Marc;;Dr.;Jr", "ORG:Hôpital;Cardiologie", "X-ABLabel:Gîte", "TEL;type=FAX:",
                  "ADR;type=WORK:BP 12;Bâtiment B;1 rue Haute", "IMPP;X-SERVICE-TYPE=Skype:skype:marc.d", "NOTE:Ligne 1"):
        assert ligne in texte, ligne
    assert "TITLE:Chef de service" in texte


def test_page_restee_ouverte_n_ecrase_pas_l_iphone(c, services):
    ic = services["icloud"]
    vu = actions._etag(c, "DDDD-4444")
    ic.modifier_sur_iphone("DDDD-4444", ic.texte("DDDD-4444").replace("X-PERSO:garder\r\n", "EMAIL:paul@ici.fr\r\nX-PERSO:garder\r\n"))
    with c.ecriture():
        icloud.relire(c)                       # la nuit a relu : la base a la nouvelle version
    f = c.fiche("DDDD-4444")
    f["courriels"] = []                       # la page ouverte avant n'a pas le courriel
    f["fonction"] = "Vigneron"
    with pytest.raises(ErreurCarnet, match="depuis que tu l'as ouverte"):
        actions.valider(c, "DDDD-4444", f, etag_vu=vu)
    assert "paul@ici.fr" in ic.texte("DDDD-4444")
    assert points(c, "iphone_modifiee") and points(c, "conflit")


def test_carte_manquante_relue_une_par_une(c, services):
    ic = services["icloud"]
    vrai = ic.__call__

    def multiget_partiel(r):
        rep = vrai(r)
        if r.method == "REPORT" and r.content.decode().count("<d:href>") > 1:
            corps = re.sub(r"<d:response><d:href>[^<]*BBBB-2222[^<]*</d:href>.*?</d:response>", "", rep.content.decode(), flags=re.S)
            return httpx.Response(207, content=corps.encode())
        return rep
    c.transports["icloud"] = httpx.MockTransport(multiget_partiel)
    with c.ecriture():
        bilan = icloud.relire(c)
    assert bilan["supprimes"] == 0 and "BBBB-2222" in c.fiches()


def test_photo_par_lien_sans_identifiants_hors_icloud(c):
    vus = []

    def serveur(r):
        vus.append((r.url.host, r.headers.get("authorization")))
        return httpx.Response(200, content=b"\xff\xd8\xffimage")
    from app.carddav import CardDAV
    dav = CardDAV("https://contacts.icloud.com", "moi", "secret", transport=httpx.MockTransport(serveur))
    dav.telecharger("https://autre-site.example/photo.jpg")
    dav.telecharger("https://p42-contacts.icloud.com/photo.jpg")
    assert vus[0] == ("autre-site.example", None) and vus[1][1]


def test_erreur_de_groupe_apres_ecriture_garde_la_base_a_jour(c, services):
    ic = services["icloud"]
    vrai = ic.__call__

    def groupes_en_panne(r):
        if r.method == "PUT" and "GGGG-0001" in r.url.path:
            return httpx.Response(500)
        return vrai(r)
    c.transports["icloud"] = httpx.MockTransport(groupes_en_panne)
    f = c.fiche("DDDD-4444")
    f["fonction"] = "Vigneron"
    f["groupes"] = ["Urgence"]
    with pytest.raises(Exception):
        actions.valider(c, "DDDD-4444", f, etag_vu=actions._etag(c, "DDDD-4444"))
    c.transports["icloud"] = ic.transport()
    with c.ecriture():
        assert icloud.relire(c)["modifies"] == 0      # l'écriture n'est pas prise pour l'iPhone
    assert c.fiches()["DDDD-4444"]["fonction"] == "Vigneron"


def test_fusion_en_conflit_ne_vide_pas_les_groupes(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("EEEE-5555", carte_simple("EEEE-5555", "Paul Martin"))
    with c.ecriture():
        icloud.relire(c)
    ic.modifier_sur_iphone("AAAA-1111", ic.texte("AAAA-1111") + "")
    ic.cartes[f"{CARNET}AAAA-1111.vcf"][0] = '"change"'      # modifiée sur l'iPhone, pas encore relue
    with pytest.raises(ErreurCarnet):
        actions.fusionner(c, "EEEE-5555", "AAAA-1111", c.fiche("EEEE-5555"))
    assert "urn:uuid:AAAA-1111" in ic.texte("GGGG-0001")


def test_recreer_et_restaurer_remettent_les_groupes(c, services):
    ic = services["icloud"]
    nom = icloud.sauvegarder(c, "test")
    del ic.cartes[f"{CARNET}AAAA-1111.vcf"]
    ic.modifier_sur_iphone("GGGG-0001", ic.texte("GGGG-0001").replace("X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:AAAA-1111\r\n", ""))
    with c.ecriture():
        icloud.relire(c)
    [p] = points(c, "iphone_supprimee")
    actions.repondre(c, p["id"], "recreer")
    assert "urn:uuid:AAAA-1111" in ic.texte("GGGG-0001")
    f = c.fiche("AAAA-1111")
    f["groupes"] = []
    actions.valider(c, "AAAA-1111", f, etag_vu=actions._etag(c, "AAAA-1111"))
    assert "AAAA-1111" not in ic.texte("GGGG-0001")
    with c.ecriture():
        icloud.restaurer(c, nom, ["AAAA-1111"])
    assert "urn:uuid:AAAA-1111" in ic.texte("GGGG-0001")
    assert c.fiches()["AAAA-1111"]["groupes"] == ["Urgence"]


def test_nuit_linkedin_revérifie_la_fiche(c, services):
    ic = services["icloud"]
    linkedin.importer(c, CSV)
    actions.repondre(c, points(c, "linkedin")[0]["id"], "appliquer")
    linkedin.importer(c, CSV.replace("Caviste", "Gérant"))       # en attente pour la nuit
    f = c.fiche("DDDD-4444")
    f["fonction"] = "Maître de chai"                               # changé entre-temps
    actions.valider(c, "DDDD-4444", f, etag_vu=actions._etag(c, "DDDD-4444"))
    nuit.passer(c, "test")
    assert "TITLE:Maître de chai" in ic.texte("DDDD-4444")


def test_deux_groupes_du_meme_nom(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("GGGG-0002", "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Urgence\r\nFN:Urgence\r\n"
                           "X-ADDRESSBOOKSERVER-KIND:group\r\nX-ADDRESSBOOKSERVER-MEMBER:urn:uuid:AAAA-1111\r\n"
                           "UID:GGGG-0002\r\nEND:VCARD\r\n")
    with c.ecriture():
        icloud.relire(c)
    f = c.fiche("AAAA-1111")
    f["groupes"] = []
    actions.valider(c, "AAAA-1111", f, etag_vu=actions._etag(c, "AAAA-1111"))
    assert "AAAA-1111" not in ic.texte("GGGG-0001") and "AAAA-1111" not in ic.texte("GGGG-0002")
    with c.ecriture():
        assert icloud.relire(c)["modifies"] == 0


def test_reprise_retentee_apres_une_cle_fausse(tmp_path, services):
    import sqlcipher3
    state = tmp_path / "state"
    state.mkdir()
    a = sqlcipher3.connect(str(state / "carnet.db"))
    a.execute("PRAGMA key = 'bonne'")
    a.executescript("CREATE TABLE etat (cle TEXT, valeur TEXT); CREATE TABLE sources (id INTEGER, source TEXT, uid TEXT, "
                    "donnees TEXT, personne_id TEXT); CREATE TABLE distinctes (a INTEGER, b INTEGER);")
    a.commit()
    a.close()
    cn = Carnet(_config(tmp_path, ancienne_base=state / "carnet.db", ancienne_cle="fausse"),
                {k: v.transport() for k, v in services.items()})
    with cn.ecriture():
        icloud.relire(cn)
    assert reprise.reprendre(cn)["erreur"] and reprise.a_faire(cn)
    object.__setattr__(cn, "cfg", _config(tmp_path, ancienne_base=state / "carnet.db", ancienne_cle="bonne"))
    assert reprise.reprendre(cn)["erreur"] is None and not reprise.a_faire(cn)


# ================================================================ dates sans année (1900)

def test_date_en_1900_ecrite_sans_annee(c, services):
    ic = services["icloud"]
    f = c.fiche("DDDD-4444")
    f["anniversaire"] = "14/03/1900"
    actions.valider(c, "DDDD-4444", f, etag_vu=actions._etag(c, "DDDD-4444"))
    assert "BDAY;X-APPLE-OMIT-YEAR=1604;VALUE=date:1604-03-14" in ic.texte("DDDD-4444")
    assert c.fiches()["DDDD-4444"]["anniversaire"] == "--03-14"


def test_carte_icloud_en_1900_proposee_sans_annee(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("DDDD-4444", ic.texte("DDDD-4444").replace("BDAY;value=date:1983-01-09", "BDAY;value=date:1900-05-20"))
    with c.ecriture():
        icloud.relire(c)
    actions.repondre(c, points(c, "iphone_modifiee")[0]["id"], "garder")
    assert c.fiches()["DDDD-4444"]["anniversaire"] == "--05-20"
    [p] = [p for p in points(c, "forme") if p["uid"] == "DDDD-4444"]
    assert p["donnees"]["ecarts"][0]["apres"] == "20 mai (sans année)"
    actions.repondre(c, p["id"], "appliquer")
    assert "1604-05-20" in ic.texte("DDDD-4444") and "1900" not in ic.texte("DDDD-4444")


# ================================================================ carnet 2.1 : audit, réseaux

from app import completude, reseaux, telegram


def test_completude_et_validation(c, services):
    r = completude.resume(c)
    assert set(r["BBBB-2222"]["manques"]) == {"annee", "adresse"}          # date sans année = manquante
    assert r["CCCC-3333"]["manques"] == ["annee", "adresse"]
    assert completude.compteurs(c)["annee"] >= 2
    completude.valider(c, "BBBB-2222")
    assert completude.resume(c)["BBBB-2222"]["statut"] == "valide"
    assert completude.resume(c)["BBBB-2222"]["score"] == 4
    # Une écriture de carnet sur un champ non audité garde la validation
    f = c.fiche("BBBB-2222")
    f["notes"] = "note"
    actions.valider(c, "BBBB-2222", f, etag_vu=actions._etag(c, "BBBB-2222"))
    assert completude.resume(c)["BBBB-2222"]["statut"] == "valide"
    # Une écriture de carnet sur un champ audité la garde aussi (la fiche était à jour)
    f = c.fiche("BBBB-2222")
    f["adresses"] = [{"rue": "1 rue Neuve", "cp": "47000", "ville": "Agen", "pays": "", "region": "", "type": "domicile"}]
    actions.valider(c, "BBBB-2222", f, etag_vu=actions._etag(c, "BBBB-2222"))
    assert completude.resume(c)["BBBB-2222"]["statut"] == "valide"
    # Modifiée sur l'iPhone : à revoir
    ic = services["icloud"]
    ic.modifier_sur_iphone("BBBB-2222", ic.texte("BBBB-2222").replace("+33 5 53 11 22 33", "+33 5 53 99 99 99"))
    with c.ecriture():
        icloud.relire(c)
    assert completude.resume(c)["BBBB-2222"]["statut"] == "a_revoir"
    assert completude.compteurs(c)["a_revoir"] == 1
    completude.valider(c, "BBBB-2222")
    completude.analyse_globale(c, remettre_a_zero=True)
    assert completude.resume(c)["BBBB-2222"]["statut"] is None


def test_plateformes_depuis_la_carte_et_les_liaisons(c, services):
    ic = services["icloud"]
    ic.modifier_sur_iphone("DDDD-4444", ic.texte("DDDD-4444").replace("X-PERSO:garder\r\n",
                           "X-PERSO:garder\r\nIMPP;X-SERVICE-TYPE=WhatsApp:x-apple:+33698765432\r\n"))
    with c.ecriture():
        icloud.relire(c)
    liaisons.lier(c, "DDDD-4444", "immich", "im-paul")
    assert completude.resume(c)["DDDD-4444"]["plateformes"] == ["icloud", "immich", "whatsapp"]


def test_profils_ajoutes_et_delies(c, services):
    ic = services["icloud"]
    with pytest.raises(ErreurCarnet, match="facebook.com"):
        reseaux.ajouter_profil(c, "DDDD-4444", "facebook", "Paul Martin")
    reseaux.ajouter_profil(c, "DDDD-4444", "facebook", "https://www.facebook.com/paul.martin.47")
    reseaux.ajouter_profil(c, "DDDD-4444", "whatsapp", "06 98 76 54 32")
    texte = ic.texte("DDDD-4444")
    assert "facebook.com/paul.martin.47" in texte and "wa.me/33698765432" in texte
    assert {"facebook", "whatsapp"} <= set(completude.resume(c)["DDDD-4444"]["plateformes"])
    reseaux.delier(c, "DDDD-4444", "facebook")
    assert "facebook.com" not in ic.texte("DDDD-4444") and "wa.me" in ic.texte("DDDD-4444")
    assert "X-PERSO:garder" in ic.texte("DDDD-4444")


class FauxTelegram:
    """Client Telethon simulé : code, éventuelle double authentification, contacts."""
    def __init__(self, mot_de_passe=False):
        self.mdp = mot_de_passe
        self.sorti = False

    async def connect(self):
        pass

    async def send_code_request(self, tel):
        class R:
            phone_code_hash = "h"
        return R()

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
        if self.mdp and password is None:
            from telethon.errors import SessionPasswordNeededError
            raise SessionPasswordNeededError(request=None)

    async def __call__(self, requete):
        class U:
            def __init__(self, i, p, n, tel, pseudo):
                self.id, self.first_name, self.last_name, self.phone, self.username = i, p, n, tel, pseudo
                self.bot = self.deleted = False
        class R:
            users = [U(1, "Paul", "Martin", "33698765432", "paulm"), U(2, "Inconnu", "Total", "33600000000", None),
                     U(3, "Claire", "Martin", "33611112222", "clairem")]
        return R()

    async def is_user_authorized(self):
        return True

    async def log_out(self):
        self.sorti = True

    async def disconnect(self):
        pass


def test_telegram_import_manuel_et_session_fermee(c, services):
    faux = FauxTelegram(mot_de_passe=True)
    c.transports["telegram"] = lambda: faux
    with pytest.raises(ErreurCarnet):
        telegram.importer(c, "12345")                        # pas de code demandé
    telegram.demander_code(c, "06 11 22 33 44")
    r = telegram.importer(c, "12345")
    assert r["mot_de_passe"] and not faux.sorti             # double authentification demandée
    r = telegram.importer(c, "12345", "secret")
    assert r["lues"] == 3 and faux.sorti and not telegram.etat(c)["code_demande"]
    props = {p["donnees"]["ext_id"]: p for p in points(c, "reseau")}
    assert props["1"]["uid"] == "DDDD-4444" and props["1"]["donnees"]["raison"] == "même numéro"
    assert props["3"]["uid"] == "AAAA-1111" and props["3"]["donnees"]["telephone"] == "+33611112222"
    assert "2" not in props
    actions.repondre(c, props["3"]["id"], "lier_numero")
    texte = services["icloud"].texte("AAAA-1111")
    assert "t.me/clairem" in texte and "+33 6 11 11 22 22" in texte
    actions.repondre(c, props["1"]["id"], "pas_lui")
    telegram.demander_code(c, "06 11 22 33 44")
    telegram.importer(c, "1", "secret")                     # réimport : « Pas lui » reste refusé
    assert not points(c, "reseau")


def test_instagram_export_zip(c, services):
    import io as io_
    import zipfile
    tampon = io_.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("connections/followers_and_following/following.json", json.dumps({"relationships_following": [
            {"title": "paulmartin", "string_list_data": [{"href": "https://www.instagram.com/paulmartin", "timestamp": 1}]},
            {"title": "une_marque", "string_list_data": [{"href": "https://www.instagram.com/une_marque"}]}]}))
        z.writestr("connections/followers_and_following/followers_1.json", json.dumps([
            {"string_list_data": [{"value": "claire.martin", "href": "https://www.instagram.com/claire.martin"}]}]))
        z.writestr("your_instagram_activity/messages/inbox/x/message_1.json", "{}")
    r = reseaux.importer_instagram(c, tampon.getvalue(), "instagram.zip")
    assert r["lues"] == 3
    props = {p["donnees"]["pseudo"]: p for p in points(c, "reseau")}
    assert set(props) == {"paulmartin", "claire.martin"}
    actions.repondre_lot(c, [p["id"] for p in props.values()], "lier")
    assert "instagram.com/paulmartin" in services["icloud"].texte("DDDD-4444")
    assert not c.base.un("SELECT 1 FROM personnes_externes WHERE nom LIKE '%message%'")


def test_purge_des_personnes_jamais_rattachees(c):
    from datetime import timedelta
    from app.temps import maintenant
    reseaux.enregistrer(c, "instagram", [{"ext_id": "x", "nom": "x", "pseudo": "x"}])
    c.base.executer("UPDATE personnes_externes SET vu_le = ?", ((maintenant() - timedelta(days=91)).isoformat(),))
    assert reseaux.purger(c) == 1
