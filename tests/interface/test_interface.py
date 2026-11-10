"""Tests de l'interface dans Chromium, sur PC et à la taille d'un iPhone (390 × 844).
Il faut l'interface compilée dans app/static (voir la CI)."""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

playwright = pytest.importorskip("playwright.sync_api")
RACINE = Path(__file__).resolve().parents[2]
if not (RACINE / "app" / "static" / "index.html").is_file():
    pytest.skip("interface non compilée", allow_module_level=True)


@pytest.fixture(scope="module")
def adresse(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "tests.interface.serveur", str(tmp_path_factory.mktemp("ui")), str(port)],
                            cwd=RACINE)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield base
    proc.terminate()


@pytest.fixture(scope="module")
def navigateur():
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(params=["pc", "iphone"])
def page(request, navigateur, adresse):
    mobile = request.param == "iphone"
    ctx = navigateur.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 860},
                                 is_mobile=mobile, has_touch=mobile)
    pg = ctx.new_page()
    erreurs = []
    pg.on("pageerror", lambda e: erreurs.append(str(e)))
    pg.goto(adresse)
    pg.fill("#mdp", "essai")
    pg.click("text=Ouvrir le carnet")
    pg.wait_for_selector("nav.onglets")
    pg.erreurs = erreurs
    yield pg
    assert not erreurs, erreurs
    ctx.close()


def test_trois_onglets_et_badge(page):
    onglets = page.locator("nav.onglets a.onglet")
    assert onglets.count() == 3
    assert re.fullmatch(r"\d+", page.locator(".badge").inner_text())


def test_a_traiter_garder_une_modification_iphone(page):
    # Le serveur est partagé : la première fiche de l'iPhone déjà gardée, on prend la suivante
    carte = page.locator("article", has=page.get_by_role("button", name="Garder", exact=True)).first
    carte.get_by_role("button", name="Garder", exact=True).click()
    page.wait_for_selector(".message")
    assert "gardée" in page.locator(".message").inner_text()


def test_contacts_recherche_et_tranche(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.wait_for_selector(".ligne")
    page.fill("input[type=search]", "fabre")
    assert page.locator(".ligne").count() == 1
    page.fill("input[type=search]", "")
    if page.viewport_size["width"] > 500:
        assert page.locator(".tranche button").count() >= 5        # PC : onglets de la tranche
    else:
        assert page.locator(".index button").count() == 27         # iPhone : index fin A à Z et #


def test_tri_par_prenom_ou_par_nom(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.wait_for_selector(".ligne")
    page.get_by_role("button", name="Prénom", exact=True).click()
    assert page.locator(".ligne .nom").first.inner_text().startswith("Agnès")
    page.get_by_role("button", name="Nom", exact=True).click()
    assert page.locator(".lettre").first.inner_text() == "A"
    assert page.locator(".ligne .nom").first.inner_text().startswith("Manon ANDRE")
    page.reload()
    page.wait_for_selector(".ligne")
    assert page.get_by_role("button", name="Nom", exact=True).get_attribute("aria-pressed") == "true"   # choix gardé
    page.get_by_role("button", name="Prénom", exact=True).click()


def test_pc_liste_et_fiche_cote_a_cote(page):
    if page.viewport_size["width"] < 900:
        pytest.skip("PC seulement")
    page.click("nav.onglets a[aria-label='Contacts']")
    page.click(".ligne:has-text('Paul MARTIN')")
    page.wait_for_selector(".volet-fiche h1:has-text('Paul MARTIN')")
    assert page.locator(".volet-liste .ligne").count() > 5


def test_fiche_apercu_puis_ecrire_et_annuler(page):
    page.goto(page.url.split("#")[0] + "#/contacts/DDDD-4444")
    page.get_by_role("button", name="Modifier les informations").click()
    page.locator("label:has-text('Fonction') input").fill("Vigneron")
    page.click("text=Voir les changements")
    assert "Vigneron" in page.locator(".apercu").inner_text()
    page.click("text=Écrire dans iCloud")
    page.wait_for_selector(".message >> text=Annuler")
    page.click(".message >> text=Annuler")
    page.wait_for_selector(".message >> text=revenue")


def test_cibles_tactiles_et_champs(page):
    if page.viewport_size["width"] > 500:
        pytest.skip("contrôle tactile : iPhone seulement")
    page.goto(page.url.split("#")[0] + "#/contacts/DDDD-4444")
    page.get_by_role("button", name="Modifier les informations").click()
    tailles = page.eval_on_selector_all("button.bouton, a.bouton, .onglet", "els => els.map(e => e.getBoundingClientRect().height)")
    assert min(tailles) >= 43.5
    polices = page.eval_on_selector_all("input, select, textarea", "els => els.map(e => parseFloat(getComputedStyle(e).fontSize))")
    assert min(polices) >= 16


def test_pas_de_defilement_horizontal(page):
    for route in ("#/a-traiter", "#/contacts", "#/contacts/AAAA-1111", "#/etat"):
        page.goto(page.url.split("#")[0] + route)
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), route


def test_etat_et_deconnexion(page):
    page.click("nav.onglets a[aria-label='État']")
    page.locator(".tuile", has_text="Sauvegardes").click()
    page.wait_for_selector("h2:has-text(\"Sauvegardes d'iCloud\")")
    page.locator(".tuile", has_text="Journal").click()
    assert page.locator("h2", has_text="Sauvegardes d'iCloud").count() == 0      # une section à la fois
    page.click("text=Se déconnecter")
    page.wait_for_selector("#mdp")


# ------------------------------------------------------------------ 2.1 : complétude et réseaux

def test_filtres_de_completude_et_jauges(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.wait_for_selector(".ligne")
    total = page.locator(".ligne").count()
    assert page.locator(".ligne .jauge").count() == total
    page.locator(".manques .pastille", has_text="Sans adresse").click()
    filtrees = page.locator(".ligne").count()
    assert 0 < filtrees <= total
    page.locator(".manques .pastille", has_text="Sans adresse").click()
    assert page.locator(".ligne").count() == total


def test_valider_puis_retirer_la_validation(page):
    page.goto(page.url.split("#")[0] + "#/contacts/F-05")
    bloc = page.locator(".completude")
    bloc.get_by_role("button", name=re.compile("Valider la fiche|Revalider")).click()
    page.wait_for_selector(".completude >> text=Fiche validée")
    bloc.get_by_role("button", name="Retirer la validation").click()
    page.wait_for_selector(".completude >> text=Valider la fiche")


def test_ajouter_puis_delier_un_profil_facebook(page):
    page.goto(page.url.split("#")[0] + "#/contacts/F-06")
    page.wait_for_selector("h2:has-text('Plateformes')")
    page.select_option("select[aria-label='Réseau à ajouter']", "facebook")
    page.fill("input[aria-label='Profil Facebook']", "https://www.facebook.com/francois.muller.demo")
    page.get_by_role("button", name="Ajouter", exact=True).click()
    page.wait_for_selector(".reseaux >> text=Facebook")
    page.locator(".reseaux li.liaison", has_text="Facebook").get_by_role("button", name="Délier").click()
    assert "francois.muller.demo" in page.locator(".confirmer").inner_text()     # l'adresse retirée est montrée
    page.get_by_role("button", name="Délier Facebook").click()
    page.wait_for_selector(".reseaux li:has-text('Facebook')", state="detached")


def test_a_traiter_famille_reseaux(page):
    page.click("nav.onglets a[aria-label='À traiter']")
    filtre = page.locator(".filtres .pastille", has_text="Réseaux")
    if not filtre.count():
        pytest.skip("points réseau déjà traités par l'autre format")
    filtre.click()
    carte = page.locator("article", has_text="Réseau à rattacher").first
    assert carte.get_by_role("button", name="Pas lui").count() == 1
    carte.get_by_role("button", name="Lier", exact=True).click()
    page.wait_for_selector(".message >> text=Lié")


def test_etat_reseaux_et_remise_a_zero_confirmee(page):
    page.click("nav.onglets a[aria-label='État']")
    page.locator(".tuile", has_text="Réseaux").click()
    page.wait_for_selector("h3:has-text('Telegram')")
    assert page.locator("text=CARNET_TELEGRAM_API_ID").count() == 1          # non configuré dans la démo
    page.locator(".tuile", has_text="Complétude").click()
    page.get_by_role("button", name="Remettre les validations à zéro…").click()
    bouton = page.get_by_role("button", name="Remettre à zéro et analyser")
    assert bouton.is_disabled()
    page.fill("input[aria-label='Confirmation']", "remettre")
    assert bouton.is_disabled()
    page.get_by_role("button", name="Annuler", exact=True).click()


def test_manifeste_pwa(adresse):
    r = httpx.get(adresse + "/manifest.json")
    assert r.status_code == 200 and r.json()["display"] == "standalone"
    assert httpx.get(adresse + "/icone-512.png").status_code == 200


# ------------------------------------------------------------------ 2.2 : pilule et boutons à anneau

def test_pilule_libelle_de_l_onglet_actif(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.wait_for_selector("nav.onglets a[aria-label='Contacts'][aria-current='page']")
    page.wait_for_timeout(500)                                  # fin de l'élargissement de la pilule
    actif = page.locator("nav.onglets a[aria-current='page']")
    assert actif.locator(".libelle").bounding_box()["width"] > 20
    inactif = page.locator("nav.onglets a[aria-label='État'] .libelle").bounding_box()["width"]
    large = page.viewport_size["width"] >= 900
    assert (inactif > 20) if large else (inactif < 2)      # iPhone : icône seule ; PC : rail avec libellés


def test_export_vcf_par_le_bouton_a_anneau(page):
    page.click("nav.onglets a[aria-label='État']")
    page.locator(".tuile", has_text="Sauvegardes").click()
    with page.expect_download() as tele:
        page.get_by_role("button", name="Exporter tout le carnet (.vcf)").click()
    assert tele.value.suggested_filename.startswith("carnet-") and tele.value.suggested_filename.endswith(".vcf")
    page.wait_for_selector(".bouton-anneau[data-etat='succes']")
    page.route("**/api/export.vcf", lambda r: r.fulfill(status=502, json={"detail": "iCloud ne répond pas."}))
    page.wait_for_selector(".bouton-anneau[data-etat='repos']", timeout=6000)
    page.get_by_role("button", name="Exporter tout le carnet (.vcf)").click()
    page.wait_for_selector(".bouton-anneau[data-etat='echec'] >> text=iCloud ne répond pas.")


def test_glisser_deposer_un_export_instagram(page):
    if page.viewport_size["width"] < 900:
        pytest.skip("glisser-déposer : PC seulement")
    page.click("nav.onglets a[aria-label='État']")
    page.locator(".tuile", has_text="Réseaux").click()
    cible = page.locator("label.bouton-anneau", has_text="Déposer l'export Instagram")
    assert "ou glisse le fichier ici" in cible.inner_text()
    contenu = '{"relationships_following": [{"title": "glisse.depot", "string_list_data": [{"value": "glisse.depot"}]}]}'
    poignee = page.evaluate_handle("""(texte) => {
        const dt = new DataTransfer(); dt.items.add(new File([texte], 'following.json', { type: 'application/json' })); return dt }""", contenu)
    page.dispatch_event("body", "dragenter", {"dataTransfer": poignee})
    cible.dispatch_event("dragover", {"dataTransfer": poignee})
    page.wait_for_selector("label.bouton-anneau.survol >> text=Lâche le fichier")
    cible.dispatch_event("drop", {"dataTransfer": poignee})
    page.wait_for_selector("label.bouton-anneau[data-etat='succes']")
    assert "Instagram : 1 compte(s) lu(s)" in page.locator(".message").inner_text()
