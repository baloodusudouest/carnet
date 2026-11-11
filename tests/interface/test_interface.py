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
    assert onglets.count() == 5          # 2.8 : Photos et Réglages s'ajoutent
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
    # 2.8 : les filtres viennent du tableau des attentes (ici, Amis attend le jour de naissance)
    page.locator(".manques .pastille", has_text="Sans jour de naissance").click()
    filtrees = page.locator(".ligne").count()
    assert 0 < filtrees < total
    page.locator(".manques .pastille", has_text="Sans jour de naissance").click()
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


def test_annonce_avant_un_traitement_par_lot(page):
    """2.6.5 : avant « Confirmer », carnet dit ce que le lot fera. Rien n'est confirmé ici."""
    page.click("nav.onglets a[aria-label='À traiter']")
    filtre = page.locator(".filtres .pastille", has_text="Réseaux")
    if not filtre.count():
        pytest.skip("points réseau déjà traités")
    filtre.click()
    tout_lier = page.get_by_role("button", name=re.compile(r"^Tout lier \(\d+\)$"))
    if not tout_lier.count():
        pytest.skip("un seul point réseau : pas de traitement par lot")
    tout_lier.click()
    annonce = page.locator(".lot .annonce")
    annonce.wait_for()
    assert "seront modifiées dans iCloud" in annonce.inner_text()
    assert "copie d'iCloud" in annonce.inner_text()
    page.get_by_role("button", name="Annuler", exact=True).click()
    page.get_by_role("button", name=re.compile(r"^Tout ignorer \(\d+\)$")).click()
    annonce.wait_for()
    assert "Rien n'est écrit dans iCloud" in annonce.inner_text()
    page.get_by_role("button", name="Annuler", exact=True).click()
    assert not annonce.count()


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
    page.locator(".tuile", has_text="Manques").click()             # 2.8 : la tuile Complétude s'appelle Manques
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


def test_reseaux_aller_a_la_partie_et_rattacher_un_importe(page):
    page.click("nav.onglets a[aria-label='État']")
    page.locator(".tuile", has_text="Réseaux").click()
    page.locator("button.reseau", has_text="Telegram").click()
    page.wait_for_timeout(700)
    assert page.locator("#reseau-telegram").is_visible()
    liste = page.locator(".non-lies", has_text="Importés de Telegram sans fiche")
    liste.get_by_role("button", name=re.compile("Importés de Telegram")).click()
    page.wait_for_selector(".non-lies ul, .non-lies p")
    ligne = liste.locator("li", has_text="Hugo B.")
    if not ligne.count():
        pytest.skip("déjà rattaché par l'autre format")
    assert "proposé dans À traiter" not in ligne.inner_text()       # nom abrégé : aucune proposition
    ligne.get_by_role("button", name="Rattacher…").click()
    liste.locator("input[aria-label='Fiche à rattacher']").fill("Bonnet")
    liste.get_by_role("button", name="Hugo BONNET").click()
    page.wait_for_selector(".message >> text=rattaché")
    page.wait_for_selector(".non-lies li:has-text('Hugo B.')", state="detached")


# ------------------------------------------------------------------ 2.8 : manques, réglages, photos, import

def test_28_manques_dans_a_traiter_ouvrent_la_liste(page):
    compteur = page.locator(".badge").inner_text()
    page.locator(".filtres .pastille", has_text="Manques").click()
    ligne = page.locator(".ligne-manque", has_text="Sans photo ni logo")
    nombre = int(ligne.locator(".nombre").inner_text())
    assert nombre > 0 and page.locator(".badge").inner_text() == compteur      # les manques ne comptent pas
    assert page.get_by_role("link", name="Traiter dans Photos").count() == 1
    ligne.click()
    page.wait_for_selector(".ligne")
    assert page.locator(".ligne").count() == nombre
    assert page.locator(".manques .pastille[aria-pressed='true']").inner_text().startswith("Sans photo ni logo")


def test_28_reglages_une_case_annonce_puis_change_les_manques(page):
    page.click("nav.onglets a[aria-label='Réglages']")
    page.wait_for_selector("text=Ce que chaque groupe doit avoir")
    if page.locator("details.groupe").count():                                  # iPhone : un groupe à la fois
        page.locator("details.groupe", has_text="Clients").locator("summary").click()
        case = page.locator("details.groupe", has_text="Clients").get_by_label("Adresse")
    else:
        case = page.get_by_label("Clients : Adresse")
    avant = case.is_checked()
    case.click()
    annonce = page.locator(".confirmer")
    annonce.wait_for()
    assert "Sans adresse" in annonce.inner_text() and "passera de" in annonce.inner_text()
    annonce.get_by_role("button", name="Annuler").click()                        # rien n'est enregistré avant « Enregistrer »
    page.wait_for_function("!document.querySelector('.confirmer')")
    assert case.is_checked() == avant
    case.click()
    annonce.wait_for()
    annonce.get_by_role("button", name="Enregistrer").click()
    page.wait_for_selector(".message")
    page.wait_for_function("!document.querySelector('.confirmer')")
    assert case.is_checked() != avant
    # Les deux interrupteurs sont là, éteints
    bascules = page.get_by_role("switch")
    assert bascules.count() == 2 and not bascules.nth(0).is_checked() and not bascules.nth(1).is_checked()
    assert page.get_by_role("button", name="Se déconnecter").count() == 1


def test_28_photos_logo_depose_puis_pose(page):
    import io
    from PIL import Image
    page.click("nav.onglets a[aria-label='Photos']")
    page.wait_for_selector(".tuile")
    assert page.locator(".tuile").count() == 4
    fiche = page.locator("li.fiche", has_text="Plomberie Garonne")
    if not fiche.count():
        pytest.skip("logo déjà posé par l'autre appareil (serveur partagé)")
    assert fiche.get_by_role("link", name="Chercher sur Google Images").get_attribute("href").startswith("https://www.google.com/search")
    image = io.BytesIO()
    Image.new("RGB", (240, 240), (30, 90, 160)).save(image, "PNG")
    fiche.locator("input[type=file]").set_input_files({"name": "logo.png", "mimeType": "image/png", "buffer": image.getvalue()})
    fiche.locator("text=prêt à poser").wait_for()
    assert fiche.locator("img.apercu-logo").count() == 1
    page.get_by_role("button", name=re.compile(r"Poser les logos \(1\)")).click()
    page.wait_for_function("!document.body.innerText.includes('Plomberie Garonne')", timeout=20000)


def test_28_import_annonce_avant_d_importer(page):
    page.click("nav.onglets a[aria-label='Contacts']")
    page.get_by_role("button", name="Importer").click()
    fenetre = page.locator("dialog[open]")
    fenetre.wait_for()
    assert fenetre.get_by_role("button", name="Importer").is_disabled()
    fenetre.locator("input[type=file]").set_input_files({"name": "notes.txt", "mimeType": "text/plain", "buffer": b"rien a voir"})
    fenetre.locator(".refus").wait_for()
    assert "non reconnu" in fenetre.locator(".refus").inner_text()
    carte = "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Essai;Import;;;\r\nFN:Import Essai\r\nTEL:+33 6 01 02 03 04\r\nEND:VCARD\r\n"
    fenetre.locator("input[type=file]").set_input_files({"name": "un.vcf", "mimeType": "text/vcard", "buffer": carte.encode()})
    fenetre.locator(".reconnu").wait_for()
    assert "1 fiche(s)" in fenetre.locator(".reconnu").inner_text()
    fenetre.get_by_role("button", name="Fermer").click()                        # on n'importe pas : rien n'a été ajouté
    page.wait_for_function("!document.querySelector('dialog[open]')")


def test_28_supprimer_une_fiche_demande_toujours_confirmation(page):
    base = page.url.split("#")[0]
    page.goto(base + "#/contacts/F-18")
    page.get_by_role("button", name="Modifier les informations").click()
    page.get_by_role("button", name="Supprimer cette fiche…").click()
    confirmation = page.get_by_role("alertdialog", name="Confirmer la suppression")
    assert "Sophie" in confirmation.inner_text() and "iPhone" in confirmation.inner_text()
    confirmation.get_by_role("button", name="Garder la fiche").click()            # on peut toujours renoncer
    assert page.get_by_role("alertdialog").count() == 0
    page.get_by_role("button", name="Supprimer cette fiche…").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Supprimer définitivement").click()
    page.wait_for_selector(".message >> text=supprimée d'iCloud")
    assert "#/contacts" in page.url and "F-18" not in page.url
    # « Annuler » la remet (le serveur est partagé entre PC et iPhone : la fiche doit revenir)
    page.locator(".message").get_by_role("button", name="Annuler").click()
    page.wait_for_selector(".message >> text=Annulé")
    page.goto(base + "#/contacts/F-18")
    page.wait_for_selector("h1:has-text('Sophie')")
