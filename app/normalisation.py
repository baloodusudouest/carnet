"""Mise en forme et clés de comparaison des valeurs d'une fiche."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from urllib.parse import urlparse

import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType

from .modele import CHAMPS_MULTIPLES, completer


class ValeurInvalide(ValueError):
    """Valeur saisie impossible à interpréter (le message est montré tel quel)."""


def sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in decompose if not unicodedata.combining(c))


def cle_texte(texte: str) -> str:
    """Clé de comparaison : minuscules, sans accents, ponctuation réduite.
    Les lettres de tous les alphabets sont gardées (cyrillique, grec, chinois…)."""
    t = sans_accents(texte).lower()
    t = re.sub(r"[^\w@+]+|_", " ", t)
    return " ".join(t.split())


# ---------------------------------------------------------------- noms

def _majuscule_initiale(mot: str) -> str:
    return mot[:1].upper() + mot[1:].lower() if mot else mot


def formater_prenom(prenom: str) -> str:
    """« jean-pierre » ou « JEAN-PIERRE » → « Jean-Pierre ». Une casse déjà mixte est respectée."""
    p = " ".join((prenom or "").split())
    if not p or (p != p.upper() and p != p.lower()):
        return p
    morceaux = re.split(r"([ \-'’])", p)
    return "".join(_majuscule_initiale(m) if m not in " -'’" else m for m in morceaux)


def formater_nom(nom: str) -> str:
    """Le nom de famille en majuscules (accents conservés) : « Prénom NOM »."""
    return " ".join((nom or "").split()).upper()


def separer_nom_complet(complet: str) -> tuple[str, str]:
    """Repli quand une source n'a qu'un nom complet. Un mot déjà en majuscules est pris
    pour le nom de famille ; sinon le dernier mot."""
    mots = (complet or "").split()
    if not mots:
        return "", ""
    if len(mots) == 1:
        return mots[0], ""
    majuscules = [m for m in mots if len(m) > 1 and m.isupper()]
    if majuscules and len(majuscules) < len(mots):
        nom = " ".join(majuscules)
        prenom = " ".join(m for m in mots if m not in majuscules)
        return prenom, nom
    return " ".join(mots[:-1]), mots[-1]


# ---------------------------------------------------------------- téléphones

def telephone(brut: str, type_: str | None, region: str = "FR") -> dict | None:
    """Retourne {valeur (E.164, extension en « ;ext= »), type, affichage, valide, mobile}.
    Sans type connu : « mobile » pour un numéro de mobile, sinon « autre ».
    Un numéro illisible est gardé tel quel, marqué non valide, pour que l'utilisateur décide."""
    texte = (brut or "").strip()
    if not texte:
        return None
    if texte.startswith("00"):
        texte = "+" + texte[2:]
    try:
        num = phonenumbers.parse(texte, region)
    except phonenumbers.NumberParseException:
        num = None
    if num is not None and phonenumbers.is_valid_number(num):
        mobile = phonenumbers.number_type(num) in (PhoneNumberType.MOBILE,
                                                   PhoneNumberType.FIXED_LINE_OR_MOBILE)
        valeur = phonenumbers.format_number(num, PhoneNumberFormat.E164)
        if num.extension:
            valeur += f";ext={num.extension}"
        return {
            "valeur": valeur,
            "type": type_ or ("mobile" if mobile else "autre"),
            "affichage": phonenumbers.format_number(num, PhoneNumberFormat.INTERNATIONAL),
            "valide": True,
            "mobile": mobile,
        }
    return {"valeur": texte, "type": type_ or "autre", "affichage": texte, "valide": False,
            "mobile": False}


def portable_fr(valeur: str) -> bool:
    return str(valeur).startswith(("+336", "+337"))


def type_pro_attendu(t: dict) -> str | None:
    """Règle bureau / travail pour un numéro français professionnel : un portable (+33 6, +33 7)
    est « travail », un fixe (+33 1 à 5, 8, 9) est « bureau ». None si la règle ne s'applique pas."""
    v = str(t.get("valeur", ""))
    if t.get("type") not in ("bureau", "travail") or not v.startswith("+33"):
        return None
    return "travail" if portable_fr(v) else "bureau"


def type_telephone_propose(t: dict) -> dict:
    """Propositions de type : un portable français noté « domicile » ou « autre » devient « mobile » ;
    entre « bureau » et « travail », la règle de type_pro_attendu s'applique."""
    if t.get("type") in ("domicile", "autre") and portable_fr(t.get("valeur", "")):
        return {**t, "type": "mobile"}
    attendu = type_pro_attendu(t)
    if attendu and attendu != t.get("type"):
        return {**t, "type": attendu}
    return t


def cle_telephone(tel: dict) -> str:
    return tel["valeur"] if tel.get("valide") else re.sub(r"\D", "", tel["valeur"])


# ---------------------------------------------------------------- autres valeurs

def courriel(brut: str, type_: str) -> dict | None:
    v = (brut or "").strip().strip("<>").strip()
    if v.lower().startswith("mailto:"):
        v = v[7:]
    # Un lien (https://t.me/@pseudo) n'est pas une adresse e-mail, même avec un « @ »
    if "@" not in v or "://" in v or " " in v or v.lower().startswith("www."):
        return None
    return {"valeur": v, "type": type_}


# Messageries grand public : une adresse ailleurs est très probablement professionnelle
DOMAINES_PERSO = {
    "gmail.com", "googlemail.com", "icloud.com", "me.com", "mac.com", "msn.com", "aol.com",
    "ymail.com", "proton.me", "protonmail.com", "pm.me", "tutanota.com", "orange.fr", "wanadoo.fr",
    "free.fr", "sfr.fr", "neuf.fr", "laposte.net", "bbox.fr", "numericable.fr", "club-internet.fr",
    "aliceadsl.fr", "cegetel.net", "noos.fr", "voila.fr", "nordnet.fr", "mail.ru",
}
PREFIXES_PERSO = ("hotmail.", "outlook.", "live.", "yahoo.", "gmx.", "yandex.", "web.de")


def courriel_perso(adresse: str) -> bool:
    domaine = adresse.rsplit("@", 1)[-1].strip().lower()
    return domaine in DOMAINES_PERSO or domaine.startswith(PREFIXES_PERSO)


def type_courriel_propose(c: dict) -> dict:
    """Propose « travail » pour une adresse hors messagerie grand public (exemple@sicaf.fr)."""
    if c.get("type") != "travail" and not courriel_perso(c["valeur"]):
        return {**c, "type": "travail"}
    return c


def domaine_pro(adresse: str) -> str | None:
    """« b.martin@sicaf-cosmetiques.fr » → « sicaf-cosmetiques.fr » ; None pour une messagerie perso."""
    if "@" not in adresse or courriel_perso(adresse):
        return None
    return adresse.rsplit("@", 1)[-1].strip().lower()


def societe_depuis_domaine(domaine: str) -> str:
    """Nom de société deviné à partir du domaine : « sicaf-cosmetiques.fr » → « Sicaf Cosmetiques »,
    « edf.fr » → « EDF », « mail.groupe-exemple.com » → « Groupe Exemple »."""
    morceaux = domaine.split(".")
    nom = morceaux[-2] if len(morceaux) >= 2 else morceaux[0]
    if len(morceaux) >= 3 and morceaux[-2] in ("co", "com", "gouv", "asso"):
        nom = morceaux[-3]
    mots = [m for m in re.split(r"[-_]+", nom) if m]
    # Sigle : 3 lettres ou moins, ou sans voyelle (edf, sncf) ; sinon un mot (port, cosmetiques)
    return " ".join(m.upper() if len(m) <= 3 or not re.search(r"[aeiouy]", m) else m.capitalize()
                    for m in mots)


def cle_courriel(c: dict) -> str:
    return c["valeur"].strip().lower()


DOMAINES_RESEAUX = {
    "linkedin.com": "linkedin", "facebook.com": "facebook", "fb.com": "facebook",
    "instagram.com": "instagram", "tiktok.com": "tiktok", "x.com": "x", "twitter.com": "x",
    "t.me": "telegram", "telegram.me": "telegram", "wa.me": "whatsapp", "signal.me": "signal",
}


def _reseau(url: str) -> str | None:
    hote = urlparse(url if "://" in url else f"https://{url}").hostname or ""
    for domaine, reseau in DOMAINES_RESEAUX.items():
        if hote == domaine or hote.endswith("." + domaine):
            return reseau
    return None


def site(brut: str, type_: str | None = None) -> dict | None:
    """Une adresse web. Les liens internes d'applications (ms-outlook://…, x-apple:…) sont ignorés."""
    v = (brut or "").strip()
    if not v:
        return None
    schema = re.match(r"^([a-z][a-z0-9+.-]*):", v, re.I)
    if schema and schema.group(1).lower() not in ("http", "https") and not re.match(r"^[^/]+\.[a-z]{2,}(:\d+)?(/|$)", v, re.I):
        return None
    if not type_ or type_ in ("site", "autre"):
        type_ = _reseau(v) or type_
    return {"valeur": v, "type": type_ or "site"}


def cle_site(s: dict) -> str:
    v = s["valeur"].strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^www\.", "", v)
    return v.rstrip("/")


def adresse(rue: str, cp: str, ville: str, region: str, pays: str, type_: str) -> dict | None:
    a = {
        "rue": "\n".join(ligne.strip() for ligne in (rue or "").replace("\r", "").split("\n")
                         if ligne.strip()),
        "cp": (cp or "").strip(), "ville": (ville or "").strip(),
        "region": (region or "").strip(), "pays": (pays or "").strip(), "type": type_,
    }
    if not any(a[k] for k in ("rue", "cp", "ville", "region", "pays")):
        return None
    return a


def cle_adresse(a: dict) -> str:
    cle = cle_texte(" ".join(a.get(k, "") for k in ("rue", "cp", "ville")))
    return cle or cle_texte(" ".join(a.get(k, "") for k in ("region", "pays")))


def nom_associe(brut: str, type_: str) -> dict | None:
    v = " ".join((brut or "").split())
    return {"valeur": v, "type": type_} if v else None


def cle_nom_associe(n: dict) -> str:
    return cle_texte(n["valeur"]) or n["valeur"].strip().lower()


CLES = {
    "telephones": cle_telephone,
    "courriels": cle_courriel,
    "adresses": cle_adresse,
    "sites": cle_site,
    "noms_associes": cle_nom_associe,
}


# Texte ajouté automatiquement par Outlook dans les contacts synchronisés : ce n'est pas une note
# (complet, ou tronqué par l'export : on retire alors le reste de la ligne)
BOILERPLATE_NOTES = [
    re.compile(r"Ce contact est en lecture seule\b.*?modifier dans Outlook\.?", re.S | re.I),
    re.compile(r"This contact is read-only\b.*?edit it in Outlook\.?", re.S | re.I),
    re.compile(r"Ce contact est en lecture seule\b[^\n]*", re.I),
    re.compile(r"This contact is read-only\b[^\n]*", re.I),
]


def note(texte: str) -> str:
    """Nettoie une note : retire le texte automatique d'Outlook ; une note sans aucune lettre
    ni chiffre (« ***** ***** », « --- ») est considérée vide."""
    t = str(texte or "")
    for motif in BOILERPLATE_NOTES:
        t = motif.sub("", t)
    t = t.strip()
    return t if any(c.isalnum() for c in t) else ""


# Règles « émoji → groupe » lues dans la configuration (CARNET_EMOJI_GROUPES), jamais dans le code
EMOJI_GROUPES: dict[str, str] = {}


def configurer_emojis(texte: str) -> None:
    """« 🍕:Amis;🔧:Artisans et services » → {"🍕": "Amis", "🔧": "Artisans et services"}."""
    EMOJI_GROUPES.clear()
    for regle in (texte or "").split(";"):
        emoji, _, groupe = regle.partition(":")
        if emoji.strip() and groupe.strip():
            EMOJI_GROUPES[emoji.strip()] = groupe.strip()


def groupes_par_emoji(fiche: dict) -> dict:
    """Ajoute le groupe associé quand un émoji configuré apparaît n'importe où dans la fiche."""
    if EMOJI_GROUPES:
        texte = json.dumps({k: v for k, v in fiche.items() if k != "groupes"}, ensure_ascii=False)
        for emoji, groupe in EMOJI_GROUPES.items():
            if emoji in texte and groupe not in fiche.setdefault("groupes", []):
                fiche["groupes"].append(groupe)
    return fiche


def nettoyer(fiche: dict) -> dict:
    """Appliqué aussi aux fiches déjà importées, à la lecture : notes et liens parasites."""
    fiche["notes"] = note(fiche.get("notes"))
    # site() renvoie la valeur reclassée (un lien t.me importé comme « site » devient « telegram »)
    sites = [r for s in fiche.get("sites", []) if (r := site(s.get("valeur", ""), s.get("type")))]
    courriels = []
    for c in fiche.get("courriels", []):
        if courriel(c.get("valeur", ""), c.get("type", "domicile")):
            courriels.append(type_courriel_propose(c))
        elif (s := site(c.get("valeur", ""))):  # lien rangé par erreur dans les courriels
            sites.append(s)
    fiche["courriels"], fiche["sites"] = courriels, sites
    fiche["telephones"] = [type_telephone_propose(t) for t in fiche.get("telephones", [])]
    groupes_par_emoji(fiche)
    return fiche


# ---------------------------------------------------------------- dates

MOIS = {"janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4,
        "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9,
        "octobre": 10, "oct": 10, "novembre": 11, "nov": 11, "decembre": 12, "dec": 12}


def anniversaire(brut: str, sans_annee: bool = False, ordre: str = "jm") -> str:
    """Accepte AAAA-MM-JJ (ou A-M-J sans zéros), AAAAMMJJ, --MM-JJ, « 15 mars 1985 »,
    « 15 mars », J/M/AAAA, J.M.AAAA. `ordre` dit comment lire 05/03 : « jm » (France, saisie)
    ou « mj » (export Outlook américain) ; un nombre > 12 tranche de lui-même.
    Retourne « AAAA-MM-JJ », « --MM-JJ » (année inconnue) ou « » si la date est illisible."""
    t = (brut or "").strip()
    if not t or t in ("0/0/00", "00/00/0000"):
        return ""
    t = t.split("T")[0]
    a = m = j = None
    if mo := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t) or re.fullmatch(r"(\d{4})(\d{2})(\d{2})", t):
        a, m, j = (int(x) for x in mo.groups())
    elif mo := re.fullmatch(r"--(\d{2})-?(\d{2})", t):
        m, j = (int(x) for x in mo.groups())
    elif mo := re.fullmatch(r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?", t):
        x, y = int(mo.group(1)), int(mo.group(2))
        a = int(mo.group(3)) if mo.group(3) else None
        if a is not None and a < 100:
            a += 1900 if a > 30 else 2000
        if x > 12:
            j, m = x, y
        elif y > 12:
            m, j = x, y
        else:
            (j, m) = (x, y) if ordre == "jm" else (y, x)
    elif mo := re.fullmatch(r"(\d{1,2})(?:er)?\s+([^\W\d_]+)\.?(?:\s+(\d{4}))?", sans_accents(t).lower()):
        j, nom_mois = int(mo.group(1)), mo.group(2)
        m = MOIS.get(nom_mois)
        a = int(mo.group(3)) if mo.group(3) else None
        if m is None:
            return ""
    else:
        return ""
    if a is not None and (sans_annee or a <= 1604):
        a = None  # 1604 = année « inconnue » chez Apple
    try:
        date(a or 2000, m, j)
    except ValueError:
        return ""
    return f"{a:04d}-{m:02d}-{j:02d}" if a else f"--{m:02d}-{j:02d}"


# ---------------------------------------------------------------- fiche entière

def dedoublonner(fiche: dict) -> dict:
    """Retire les valeurs répétées dans les champs multiples (même clé). Une valeur dont la
    clé est vide est gardée (jamais de suppression silencieuse)."""
    for champ in CHAMPS_MULTIPLES:
        vues, gardees = set(), []
        for item in fiche.get(champ, []):
            cle = CLES[champ](item)
            if not cle:
                gardees.append(item)
            elif cle not in vues:
                vues.add(cle)
                gardees.append(item)
        fiche[champ] = gardees
    return fiche


def normaliser_fiche(fiche: dict, region: str = "FR") -> dict:
    """Mise en forme d'une fiche saisie ou modifiée dans l'interface.
    Lève ValeurInvalide si l'anniversaire saisi n'est pas reconnu (plutôt que de l'effacer)."""
    f = completer(fiche)
    f["prenom"] = formater_prenom(f["prenom"])
    f["nom"] = formater_nom(f["nom"])
    for cle in ("surnom", "societe", "fonction"):
        f[cle] = " ".join(str(f[cle] or "").split())
    f["notes"] = note(f["notes"])
    saisi = str(f["anniversaire"] or "").strip()
    f["anniversaire"] = anniversaire(saisi) if saisi else ""
    if saisi and not f["anniversaire"]:
        raise ValeurInvalide(f"Anniversaire « {saisi} » non reconnu : écris par exemple 15/03/1985, "
                             "15 mars 1985 ou 15 mars.")
    tels = []
    for t in f["telephones"]:
        # La valeur garde l'extension éventuelle (« ;ext=12 »)
        n = telephone(t.get("valeur", ""), t.get("type") or None, region)
        if n:
            tels.append(n)
    f["telephones"] = tels
    f["courriels"] = [c for c in (courriel(x.get("valeur", ""), x.get("type") or "domicile")
                                  for x in f["courriels"]) if c]
    f["sites"] = [s for s in (site(x.get("valeur", ""), x.get("type")) for x in f["sites"]) if s]
    f["noms_associes"] = [n for n in (nom_associe(x.get("valeur", ""), x.get("type") or "autre")
                                      for x in f["noms_associes"]) if n]
    f["adresses"] = [a for a in (adresse(x.get("rue", ""), x.get("cp", ""), x.get("ville", ""),
                                         x.get("region", ""), x.get("pays", ""),
                                         x.get("type") or "domicile") for x in f["adresses"]) if a]
    groupes_par_emoji(f)
    f["groupes"] = sorted(set(g for g in f["groupes"] if isinstance(g, str) and g.strip()))
    return dedoublonner(f)
