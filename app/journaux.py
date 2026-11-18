"""2.29 : « Pour les journaux » — ce que Julien sait d'une personne (passions, manies, petites histoires) pour
les journaux de Gazette (rumeurs loufoques de La Récidive).

Rangé par identifiant maison (app/personnes.py), dans la base de carnet seulement : jamais écrit dans iCloud,
Synology Contacts ou le kit. Gazette le lit (GET /gazette/personnes, champ `journaux`) et l'écrit
(PUT /gazette/personnes/{personne_id}/journaux, jeton commun) ; la fiche de carnet le montre et le modifie ;
le coffre « Contacts » le recopie dans la note de la personne. Le journal de carnet ne porte jamais le texte.
Permis en lecture seule : rien ne sort de carnet.

2.30 : « Journaux parus » — chaque numéro de La Récidive approuvé dans Gazette arrive ici (date du séjour, N°,
événement du séjour, indices, descriptions des photos écrites pour l'IA, textes imprimés) : la fiche contact garde
toute l'histoire des journaux de la personne, Gazette la relit pour ne pas se répéter et broder dessus, le coffre
« Contacts » la recopie. PUT /gazette/personnes/{personne_id}/parus/{cle} (jeton commun).

2.31 : « Livre d'or » — les mots laissés par les invités dans le livre d'or de la maison (carte de Home Assistant),
envoyés par Home Assistant à chaque signature (POST /ha/livre-or). Chaque signataire reconnu reçoit le mot sur sa
fiche ; un nom que carnet ne reconnaît pas attend d'être rattaché depuis une fiche. Gazette les lit pour ses rumeurs,
son courrier des lecteurs et son droit de réponse.

2.33 : « Fiche complète » — le texte libre devient une liste de pépites rangées par rubriques (voir plus bas) ;
le texte libre est versé une fois en pépites « autre » à la première lecture, puis n'est plus écrit."""
from __future__ import annotations

import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from . import personnes
from .carnet import Carnet, ErreurCarnet
from .garde import Occupe
from .temps import iso, maintenant

MAX = 600
PARUS_LISTE = 10            # numéros donnés à Gazette (les plus récents) ; la fiche les montre tous
LIMITES = {"evenement": 200, "indices": 600, "titre": 200}
LISTES = {"descriptions": (12, 400), "textes": (60, 500)}


def tous(c: Carnet) -> dict[str, dict]:
    """identifiant maison → {texte, le, par}."""
    return c.memo("journaux", lambda: {l["personne"]: {"texte": l["texte"], "le": l["le"], "par": l["par"]}
                                       for l in c.base.tous("SELECT * FROM journaux")})


def de_personne(c: Carnet, ident: str | None) -> str:
    """Texte « Pour les journaux » donné aux anciennes versions de Gazette (champ `journaux` de /gazette/personnes).
    2.33 : une fois le texte versé dans la fiche complète, ce sont les pépites (sans les sujets interdits), une par
    ligne, coupées à MAX caractères."""
    if not ident:
        return ""
    if migre(c, ident):
        lignes = [l["texte"] for l in c.base.tous("SELECT texte FROM journaux_pepites WHERE personne = ? AND interdit = 0 "
                                                  "ORDER BY le, id", (ident,))]
        return "\n".join(lignes)[:MAX].rstrip()
    return (tous(c).get(ident) or {}).get("texte", "")


def fiche(c: Carnet, uid: str) -> dict:
    ident = personnes.de(c, uid)
    j = {} if migre(c, ident) else (tous(c).get(ident) or {})    # 2.33 : texte versé en pépites : plus affiché
    return {"personne_id": ident, "texte": j.get("texte", ""), "le": j.get("le"), "par": j.get("par", ""),
            "parus": parus(c, ident),                     # 2.30
            "livre_or": livre_or(c, ident), "orphelins": orphelins(c)}     # 2.31


def _propre(texte) -> str:
    if texte is None:
        return ""
    if not isinstance(texte, str):
        raise ErreurCarnet("Un texte est attendu.")
    texte = "\n".join(" ".join(l.split()) for l in texte.replace("\r", "").split("\n")).strip()
    if len(texte) > MAX:
        raise ErreurCarnet(f"Texte trop long ({MAX} caractères au plus).")
    return texte


def ecrire(c: Carnet, ident: str, texte, par: str) -> dict:
    """Enregistre le texte d'une personne (vide : retiré). `par` : « carnet » ou « gazette »."""
    if not ident or not personnes.uid_de(c, ident):
        raise ErreurCarnet("Personne inconnue de carnet.")
    texte = _propre(texte)
    if migre(c, ident):
        # 2.33 : texte déjà versé dans la fiche complète : la colonne n'est plus écrite, les lignes nouvelles
        # deviennent des pépites « autre » à trier (une ancienne Gazette continue de marcher)
        nouvelles = 0
        for m in _decouper(texte):
            if not ajouter(c, ident, {"texte": m, "rubrique": "autre", "source": "carnet"}, par).get("deja"):
                nouvelles += 1
        return {"personne_id": ident, "texte": texte, "pepites": nouvelles}
    if not texte:
        c.base.executer("DELETE FROM journaux WHERE personne = ?", (ident,))
    else:
        c.base.executer("INSERT INTO journaux(personne, texte, le, par) VALUES (?, ?, ?, ?) ON CONFLICT(personne) DO UPDATE "
                        "SET texte = excluded.texte, le = excluded.le, par = excluded.par", (ident, texte, iso(maintenant()), par))
    c.base.noter("journaux", "« Pour les journaux » d'une fiche mis à jour", {"personne_id": ident, "par": par})
    return {"personne_id": ident, "texte": texte}


def definir(c: Carnet, uid: str, corps: dict) -> dict:
    """Depuis la fiche de carnet."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Données attendues.")
    ecrire(c, personnes.de(c, uid), corps.get("texte"), "carnet")
    return fiche(c, uid)


# ================================================================ 2.30 : journaux parus

def parus(c: Carnet, ident: str | None) -> list[dict]:
    """Les numéros parus d'une personne, du plus récent au plus ancien."""
    if not ident:
        return []
    tout = c.memo("journaux_parus", lambda: [dict(l) for l in c.base.tous(
        "SELECT * FROM journaux_parus ORDER BY le DESC, cle DESC")])
    return [{"cle": l["cle"], "le": l["le"], "maj": l["maj"], **json.loads(l["donnees"])} for l in tout if l["personne"] == ident]


def _texte(v, maxi: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, (str, int)):
        raise ErreurCarnet("Un texte est attendu.")
    return " ".join(str(v).split())[:maxi]


def ecrire_paru(c: Carnet, ident: str, cle: str, corps: dict) -> dict:
    """Enregistre (ou remplace) un numéro paru. `corps` : {journal, numero, le, titre, evenement, indices,
    descriptions[], textes[]} ; textes coupés à leur longueur maximale, listes vides retirées."""
    if not ident or not personnes.uid_de(c, ident):
        raise ErreurCarnet("Personne inconnue de carnet.")
    if not re.fullmatch(r"[a-z]+-\d{4}-\d{2}-\d{2}", cle or ""):
        raise ErreurCarnet("Clé de numéro invalide (attendu : recidive-AAAA-MM-JJ).")
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    le = str(corps.get("le") or cle[-10:])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", le):
        raise ErreurCarnet("Date du séjour invalide (AAAA-MM-JJ).")
    d = {"journal": _texte(corps.get("journal") or cle.split("-")[0], 30)}
    try:
        d["numero"] = int(corps["numero"]) if corps.get("numero") not in (None, "") else None
    except (TypeError, ValueError):
        raise ErreurCarnet("Numéro invalide.")
    for k, maxi in LIMITES.items():
        d[k] = _texte(corps.get(k), maxi)
    for k, (n, maxi) in LISTES.items():
        v = corps.get(k) or []
        if not isinstance(v, list):
            raise ErreurCarnet(f"« {k} » : une liste est attendue.")
        d[k] = [t for t in (_texte(x, maxi) for x in v) if t][:n]
    c.base.executer("INSERT INTO journaux_parus(personne, cle, le, donnees, maj) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(personne, cle) DO UPDATE SET le = excluded.le, donnees = excluded.donnees, maj = excluded.maj",
                    (ident, cle, le, json.dumps(d, ensure_ascii=False), iso(maintenant())))
    c.base.noter("journaux", "Journal paru reçu de Gazette", {"personne_id": ident, "cle": cle})
    return {"personne_id": ident, "cle": cle, "le": le, **d}


def paru_lisible(p: dict) -> str:
    """« 19/11/2026 — La Récidive N° 2 » pour la fiche et le coffre."""
    nom = {"recidive": "La Récidive", "gazette": "La Gazette"}.get(p.get("journal") or "", p.get("journal") or "Journal")
    le = p.get("le") or ""
    return f"{le[8:10]}/{le[5:7]}/{le[:4]} — {nom}" + (f" N° {p['numero']}" if p.get("numero") else "")


# ================================================================ 2.31 : livre d'or

LIVRE_LISTE = 10            # mots donnés à Gazette (les plus récents)


def _livre(c: Carnet) -> list[dict]:
    return c.memo("livre_or", lambda: [dict(l) for l in c.base.tous("SELECT * FROM livre_or ORDER BY le DESC, id DESC")])


def livre_or(c: Carnet, ident: str | None) -> list[dict]:
    """Les mots du livre d'or d'une personne, du plus récent au plus ancien."""
    if not ident:
        return []
    return [{k: l[k] for k in ("id", "message", "chambre", "le", "nom")} for l in _livre(c) if l["personne"] == ident]


def orphelins(c: Carnet) -> list[dict]:
    """Les mots dont le signataire n'a pas été reconnu (à rattacher depuis une fiche)."""
    return [{k: l[k] for k in ("id", "message", "chambre", "le", "nom")} for l in _livre(c) if not l["personne"]]


def _noms(corps: dict) -> list[str]:
    """`noms` (liste) ou `invites` (« Audrey & Paul », « Audrey et Paul », « Audrey, Paul »)."""
    noms = corps.get("noms")
    if isinstance(noms, str):
        noms = [noms]
    if not noms:
        noms = re.split(r"\s*(?:&|,|\bet\b|/|\+)\s*", str(corps.get("invites") or ""))
    res = []
    for n in noms or []:
        n = re.sub(r"\s*\(.*$", "", " ".join(str(n).split())).strip()     # « Nom (dates) » : dates retirées
        if n and n.casefold() not in ("invité", "invite", "invités") and n not in res:
            res.append(n[:80])
    return res[:4]


def recevoir_livre(c: Carnet, corps: dict) -> dict:
    """POST /ha/livre-or : {noms[] ou invites, message, chambre, le}. Rattache le mot à chaque signataire reconnu (même
    recherche par nom que /ha/invite, sur toutes les fiches) ; un nom inconnu ou porté par plusieurs fiches reste à
    rattacher. Un mot déjà reçu n'entre pas deux fois."""
    import hashlib
    from .normalisation import cle_texte
    from .sorties import contacts_ha
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    message = "\n".join(" ".join(l.split()) for l in str(corps.get("message") or "").replace("\r", "").split("\n")).strip()[:2000]
    if not message:
        raise ErreurCarnet("Mot vide.")
    le = str(corps.get("le") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", le):
        le = iso(maintenant())[:10]
    chambre = " ".join(str(corps.get("chambre") or "").split())[:60]
    noms = _noms(corps) or ["Invité"]
    fiches = contacts_ha(c)
    rattaches, inconnus, nouveaux = [], [], 0
    for nom in noms:
        cle_n = cle_texte(nom)
        trouves = {p["personne_id"] for p in fiches if p.get("personne_id") and cle_n in (cle_texte(p["nom"]), cle_texte(p["nom_carnet"]))}
        ident = next(iter(trouves)) if len(trouves) == 1 else ""
        (rattaches if ident else inconnus).append(nom)
        cle = hashlib.sha1(f"{cle_n}|{le}|{message}".encode()).hexdigest()[:20]
        avant = c.base.tous("SELECT id FROM livre_or WHERE cle = ?", (cle,))
        if avant:
            continue
        c.base.executer("INSERT INTO livre_or(cle, personne, nom, message, chambre, le, recu) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (cle, ident, nom, message, chambre, le, iso(maintenant())))
        nouveaux += 1
    c.base.noter("journaux", "Mot du livre d'or reçu de Home Assistant",
                 {"rattaches": len(rattaches), "a_rattacher": len(inconnus), "nouveaux": nouveaux})
    return {"rattaches": rattaches, "a_rattacher": inconnus, "nouveaux": nouveaux}


def rattacher_livre(c: Carnet, mot_id: int, uid: str) -> dict:
    """Rattache un mot du livre d'or à la fiche `uid` (depuis la fiche, « C'est elle / lui »)."""
    ident = personnes.de(c, uid)
    if not ident:
        raise ErreurCarnet("Fiche inconnue.")
    if not c.base.tous("SELECT id FROM livre_or WHERE id = ?", (int(mot_id),)):
        raise ErreurCarnet("Mot du livre d'or introuvable.")
    c.base.executer("UPDATE livre_or SET personne = ? WHERE id = ?", (ident, int(mot_id)))
    return {"ok": True}


# ================================================================ 2.33 : fiche complète (pépites)
#
# La fiche complète remplace le texte libre « Pour les journaux » : chaque détail est une pépite
# {id, rubrique, texte (≤ 200), le, source, parue_le}, écrite une par une par carnet (session) ou Gazette
# (jeton commun), avec contrôle de `le` (409 si la pépite a changé entre-temps). Les rubriques sont dans
# app/rubriques_journaux.json, recopié à l'identique dans Gazette. Rubrique « interdits » : « Sujets interdits »
# (interdit = 1), jamais envoyés à l'IA par Gazette. Rien ne sort de carnet : permis en lecture seule.

RUBRIQUES = json.loads((Path(__file__).with_name("rubriques_journaux.json")).read_text(encoding="utf-8"))
INTERDITS = RUBRIQUES["interdits"]["cle"]                      # « interdits »
CLES = [r["cle"] for f in RUBRIQUES["familles"] for r in f["rubriques"]]
TITRES = {r["cle"]: r["titre"] for f in RUBRIQUES["familles"] for r in f["rubriques"]} | {INTERDITS: RUBRIQUES["interdits"]["titre"]}
SOURCES = ("julien", "carnet", "recidive", "sillage")
PEPITE_MAX = 200
PEPITES_MAX = 500                     # par personne : garde-fou
PALIERS = ((30, "inépuisable"), (15, "bien fournie"), (5, "de quoi rire"))
MIGRES = "journaux_migres"            # kv : identifiant maison → `le` du texte libre absorbé (une seule fois)
DATE_JOUR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PepiteChangee(Occupe):
    """La pépite a changé (ou a été effacée) depuis sa lecture : 409, relire la fiche."""


class Introuvable(ErreurCarnet):
    """Personne ou pépite inconnue : 404."""


def _plier(t: str) -> str:
    """Minuscules sans accents, pour comparer et ranger par mots-clés."""
    return "".join(ch for ch in unicodedata.normalize("NFD", t.casefold()) if unicodedata.category(ch) != "Mn")


# Mots-clés du rangement de la ligne « vrac » (sans IA) : le premier mot trouvé l'emporte, sinon « autre ».
# Écrits sans accents ni majuscules ; un mot court est cherché comme mot entier, un mot long comme début de mot.
MOTS_CLES = {
    "interdits": ["interdit", "pas un mot", "ne jamais", "jamais parler", "tabou"],
    "metier": ["travail", "travaille", "metier", "boulot", "bureau", "patron", "collegue", "retraite", "infirmier",
               "infirmiere", "prof", "professeur", "ingenieur", "medecin", "boulanger", "comptable", "chantier"],
    "conjoint": ["mari", "femme de", "epouse", "conjoint", "compagnon", "compagne", "copain", "copine", "marie", "pacse"],
    "enfants": ["fils", "fille", "enfant", "bebe", "ado", "petits-enfants", "petit-fils", "petite-fille"],
    "animaux": ["chien", "chat", "chatte", "cheval", "lapin", "perroquet", "poisson rouge", "hamster", "tortue", "poule"],
    "famille": ["frere", "soeur", "mere", "pere", "maman", "papa", "cousin", "cousine", "oncle", "tante", "grand-mere",
                "grand-pere", "belle-mere", "beau-pere", "mamie", "papi"],
    "amis": ["ami", "amie", "amis", "bande", "pote", "copains"],
    "voiture": ["voiture", "auto", "moto", "velo", "trottinette", "camping-car", "permis", "train", "bus"],
    "ville-maison": ["habite", "maison", "appartement", "village", "ville", "jardin", "demenage", "quartier"],
    "plats-detestes": ["deteste", "horreur de", "supporte pas", "ecoeure", "beurk"],
    "plats-aimes": ["adore manger", "raffole", "gourmand", "gourmande", "dessert", "chocolat", "pizza", "fromage",
                    "gateau", "frites", "plat prefere", "cuisine"],
    "boissons": ["vin", "biere", "cafe", "the", "whisky", "rhum", "cocktail", "champagne", "pastis", "soda", "boit"],
    "musique": ["chante", "chanteur", "chanteuse", "musique", "concert", "groupe de", "album", "guitare", "piano", "karaoke"],
    "ecrans": ["film", "serie", "emission", "netflix", "tele", "cinema", "telerealite", "documentaire"],
    "livres": ["livre", "roman", "lit des", "lecture", "bd", "manga", "polar"],
    "sports": ["sport", "foot", "football", "rugby", "tennis", "course", "marathon", "piscine", "nage", "randonnee",
               "ski", "salle de sport", "match", "petanque", "golf", "yoga"],
    "jeux": ["jeu", "jeux", "console", "playstation", "xbox", "switch", "escape game", "belote", "tarot", "scrabble",
             "monopoly", "poker"],
    "loisirs": ["collection", "collectionne", "bricolage", "jardinage", "tricot", "couture", "peinture", "photo", "loisir"],
    "voyages": ["voyage", "vacances", "pays", "ile", "plage", "montagne", "week-end", "road trip", "croisiere"],
    "fetes": ["eurovision", "fete", "noel", "anniversaire", "reveillon", "carnaval", "soiree", "deguise"],
    "peurs": ["peur", "phobie", "terrorise", "angoisse", "araignee", "vertige"],
    "agace": ["agace", "enerve", "deteste quand", "insupporte", "rale"],
    "talents": ["talent", "doue", "douee", "sait faire", "imite", "jongle"],
    "defauts": ["defaut", "toujours en retard", "tete en l'air", "maladroit", "maladroite", "radin", "bavard", "bavarde"],
    "manies": ["manie", "toujours", "jamais sans", "chaque fois", "obsede", "obsedee", "range"],
    "style": ["porte", "chemise", "chaussures", "chapeau", "lunettes", "look", "tenue", "habille", "baskets", "pull"],
    "sommeil": ["dort", "sieste", "ronfle", "reveil", "matin", "couche", "lever", "insomnie", "grasse matinee"],
    "techno": ["telephone", "iphone", "ordinateur", "internet", "appli", "tablette", "selfie", "instagram", "facebook"],
    "traits": ["genereux", "genereuse", "timide", "rigolo", "rigolote", "calme", "colerique", "curieux", "curieuse",
               "gentil", "gentille", "tetu", "tetue", "drole", "caractere"],
    "gaffes": ["gaffe", "betise", "oublie", "perdu", "casse", "renverse", "tombe", "rate", "trompe"],
    "surnoms": ["surnom", "surnomme", "appelle", "dit le", "dite la"],
    "phrases": ["dit toujours", "phrase", "expression", "repete", "\""],
    "running-gags": ["running gag", "a chaque sejour", "chaque sejour", "comme d'habitude", "encore une fois"],
    "sejours": ["sejour", "la derniere fois", "chez nous", "chambre", "petit-dejeuner", "est venu", "est venue"],
    "projets": ["reve", "projet", "voudrait", "aimerait", "un jour", "envie de"],
    "anecdotes": ["histoire", "anecdote", "une fois", "il parait", "souvenir"],
    "ton": ["taquin", "tendre", "absurde"],
    "ressemble": ["ressemble", "sosie", "personnage", "on dirait"],
    "si-c-etait": ["si c'etait", "si elle etait", "si il etait", "s'il etait"],
}


def _mots(texte: str) -> str:
    """Texte plié, mots séparés par une espace (une apostrophe ferme le mot : « l'eurovision » → « l' eurovision »)."""
    return " " + re.sub(r"[^\w'\"-]+", " ", _plier(texte or "").replace("’", "'").replace("'", "' ")) + " "


def ranger(texte: str) -> str:
    """Rubrique la plus probable d'une ligne « vrac » : celle qui a le plus de mots-clés trouvés (ordre de
    MOTS_CLES en cas d'égalité) ; « autre » si aucun."""
    t = _mots(texte)
    meilleure, score = "autre", 0
    for rubrique, mots in MOTS_CLES.items():
        n = 0
        for m in mots:
            m = _mots(m).strip()
            if len(m) <= 4 or " " in m:
                n += f" {m} " in t
            else:
                n += f" {m}" in t
        if n > score:
            meilleure, score = rubrique, n
    return meilleure


def _nouveau_le(ancien: str | None = None) -> str:
    """Horodatage d'une écriture, à la microseconde, toujours plus grand que l'ancien (même heure figée en test)."""
    t = maintenant()
    if ancien:
        try:
            avant = datetime.fromisoformat(ancien)
            if t <= avant:
                t = avant + timedelta(microseconds=1)
        except ValueError:
            pass
    return t.isoformat(timespec="microseconds")


def _ident(c: Carnet, ident: str) -> str:
    """Identifiant maison actuel (en suivant les fusions) ; Introuvable si la personne n'a plus de fiche."""
    uid = personnes.uid_de(c, ident) if ident else None
    if not uid:
        raise Introuvable("Personne inconnue de carnet.")
    return personnes.de(c, uid)


def _pepite(l) -> dict:
    return {"id": l["id"], "rubrique": l["rubrique"], "texte": l["texte"], "interdit": bool(l["interdit"]),
            "source": l["source"], "parue_le": l["parue_le"], "le": l["le"], "par": l["par"]}


def _lignes(c: Carnet, ident: str) -> list[dict]:
    return [_pepite(l) for l in c.base.tous("SELECT * FROM journaux_pepites WHERE personne = ? ORDER BY le, id", (ident,))]


def _texte_pepite(v) -> str:
    if not isinstance(v, str):
        raise ErreurCarnet("Un texte est attendu.")
    v = " ".join(v.split())
    if not v:
        raise ErreurCarnet("Pépite vide.")
    if len(v) > PEPITE_MAX:
        raise ErreurCarnet(f"Pépite trop longue ({PEPITE_MAX} caractères au plus).")
    return v


def _rubrique(corps: dict, texte: str, defaut: str | None = None) -> str:
    """Rubrique demandée ; `interdit: true` → « interdits » ; absente ou « vrac » → rangée par mots-clés."""
    if corps.get("interdit") is True:
        return INTERDITS
    r = corps.get("rubrique", defaut)
    if r in (None, "", "vrac"):
        return ranger(texte)
    if r not in TITRES:
        raise ErreurCarnet(f"Rubrique inconnue : {str(r)[:40]}.")
    return r


def _date_ou_rien(v) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not DATE_JOUR.match(v):
        raise ErreurCarnet("Date attendue : AAAA-MM-JJ.")
    return v


def _decouper(texte: str, phrases_toujours: bool = False) -> list[str]:
    """Texte libre → morceaux d'au plus 200 caractères : une ligne, ou une phrase si la ligne est longue
    (`phrases_toujours` : une phrase par morceau, pour les indices d'un séjour)."""
    res = []
    for ligne in (texte or "").replace("\r", "").split("\n"):
        ligne = " ".join(ligne.split()).strip(" -•*")
        if not ligne:
            continue
        phrases = [ligne] if len(ligne) <= PEPITE_MAX and not phrases_toujours else [p for p in re.split(r"(?<=[.!?…])\s+", ligne) if p]
        for p in phrases:
            while len(p) > PEPITE_MAX:                    # phrase très longue : coupée entre deux mots
                coupe = p.rfind(" ", 0, PEPITE_MAX) if " " in p[:PEPITE_MAX] else PEPITE_MAX
                res.append(p[:coupe].strip())
                p = p[coupe:].strip()
            if p:
                res.append(p)
    return res


def _inserer(cx, ident: str, rubrique: str, texte: str, source: str, par: str, parue_le: str | None = None) -> dict:
    d = {"id": "pp-" + secrets.token_hex(6), "personne": ident, "rubrique": rubrique, "texte": texte,
         "interdit": int(rubrique == INTERDITS), "source": source, "parue_le": parue_le, "le": _nouveau_le(), "par": par}
    cx.execute("INSERT INTO journaux_pepites(id, personne, rubrique, texte, interdit, source, parue_le, le, par) "
               "VALUES (:id, :personne, :rubrique, :texte, :interdit, :source, :parue_le, :le, :par)", d)
    return _pepite(d)


def migre(c: Carnet, ident: str) -> bool:
    return ident in (c.base.lire(MIGRES, {}) or {})


def migrer(c: Carnet, ident: str) -> int:
    """À la première lecture de la fiche complète : chaque ligne (ou phrase) du texte libre « Pour les journaux »
    devient une pépite « autre », source « carnet », à trier. Une seule fois par personne ; la colonne `texte`
    reste en base (rien n'est effacé) mais n'est plus affichée ni écrite. Renvoie le nombre de pépites créées."""
    if migre(c, ident):                                  # déjà fait : simple lecture, aucune écriture
        return 0
    with c.base.transaction() as cx:
        l = cx.execute("SELECT valeur FROM kv WHERE cle = ?", (MIGRES,)).fetchone()
        faits = json.loads(l["valeur"]) if l and l["valeur"] else {}
        if ident in faits:
            return 0
        j = cx.execute("SELECT texte, le FROM journaux WHERE personne = ?", (ident,)).fetchone()
        morceaux = _decouper(j["texte"]) if j else []
        for m in morceaux[:PEPITES_MAX]:
            _inserer(cx, ident, "autre", m, "carnet", "migration")
        faits[ident] = j["le"] if j else ""
        cx.execute("INSERT INTO kv(cle, valeur) VALUES (?, ?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                   (MIGRES, json.dumps(faits, ensure_ascii=False)))
    if morceaux:
        c.base.noter("journaux", "Texte « Pour les journaux » versé dans la fiche complète",
                     {"personne_id": ident, "pepites": len(morceaux)})
    return len(morceaux)


def pepites(c: Carnet, ident: str) -> list[dict]:
    """Les pépites d'une personne (migration du texte libre faite d'abord, une seule fois)."""
    migrer(c, ident)
    return _lignes(c, ident)


def jauge(liste: list[dict]) -> dict:
    """Nombre de pépites hors sujets interdits, et le palier atteint (5, 15, 30)."""
    n = sum(1 for p in liste if not p["interdit"])
    palier = next((nom for seuil, nom in PALIERS if n >= seuil), "")
    prochain = next((seuil for seuil, _ in reversed(PALIERS) if n < seuil), None)
    return {"nombre": n, "palier": palier, "prochain": prochain}


_CONJOINTS = {"conjoint", "partenaire", "mari", "épouse"}
_ENFANTS = {"enfant", "fils", "fille"}
_ANIMAUX = {"animal", "animal de compagnie", "chien", "chienne", "chat", "chatte", "cheval", "lapin"}


def connu(c: Carnet, uid: str) -> dict:
    """Ce que carnet sait déjà (lu sur place dans la fiche, jamais recopié en pépite sans « Ajouter ») :
    métier, conjoint, enfants, animaux, alimentation, et la personne d'Immich liée (pour Sillage)."""
    from . import alimentation, famille
    from .modele import nom_affiche
    f = c.fiche(uid)
    assoc = [(str(x.get("type") or "").casefold(), str(x.get("valeur") or "").strip()) for x in f.get("noms_associes") or []]
    conjoints = [v for t, v in assoc if v and t in _CONJOINTS]
    if (autre := famille.conjoints(c).get(uid)):
        try:
            nom = nom_affiche(c.fiche(autre))
            if nom and nom not in conjoints:
                conjoints.append(nom)
        except ErreurCarnet:
            pass
    a = alimentation.de_personne(c, personnes.de(c, uid)) or {}
    return {"metier": " — ".join(v for v in (f.get("fonction"), f.get("service"), f.get("societe")) if v),
            "conjoint": conjoints,
            "enfants": [v for t, v in assoc if v and t in _ENFANTS],
            "animaux": [v for t, v in assoc if v and t in _ANIMAUX],
            "alimentation": {k: list(a.get(k) or []) for k in alimentation.LISTES},
            "immich_id": c.liaisons().get(uid, {}).get("immich") or ""}


def suggestions(c: Carnet, uid: str, ident: str, liste: list[dict]) -> list[dict]:
    """Pré-remplissage à valider (« Ajouter ») : ce que carnet sait (source « carnet ») et les anciens numéros de
    La Récidive (événements, indices ; source « recidive »). Ce qui est déjà une pépite n'est pas reproposé."""
    k = connu(c, uid)
    res: list[dict] = []
    if k["metier"]:
        res.append({"rubrique": "metier", "texte": k["metier"], "source": "carnet"})
    res += [{"rubrique": "conjoint", "texte": v, "source": "carnet"} for v in k["conjoint"]]
    res += [{"rubrique": "enfants", "texte": v, "source": "carnet"} for v in k["enfants"]]
    res += [{"rubrique": "animaux", "texte": v, "source": "carnet"} for v in k["animaux"]]
    res += [{"rubrique": "plats-aimes", "texte": v, "source": "carnet"} for v in k["alimentation"]["plaisirs"]]
    res += [{"rubrique": "plats-detestes", "texte": v, "source": "carnet"} for v in k["alimentation"]["non_aimes"]]
    for p in parus(c, ident):
        if p.get("evenement"):
            res.append({"rubrique": "sejours", "texte": f"{p['evenement']} ({paru_lisible(p)[:10]})"[:PEPITE_MAX],
                        "source": "recidive"})
        for m in _decouper(p.get("indices") or "", phrases_toujours=True):
            res.append({"rubrique": ranger(m), "texte": m, "source": "recidive"})
    deja = {_plier(p["texte"]) for p in liste}
    vus, propres = set(), []
    for s in res:
        cle = _plier(s["texte"])
        if cle and cle not in deja and cle not in vus:
            vus.add(cle)
            propres.append(s)
    return propres[:60]


def fiche_complete(c: Carnet, ident: str) -> dict:
    """GET de la fiche complète (carnet et Gazette)."""
    ident = _ident(c, ident)
    uid = personnes.uid_de(c, ident)
    liste = pepites(c, ident)
    return {"personne_id": ident, "rubriques": RUBRIQUES, "pepites": liste, "jauge": jauge(liste),
            "connu": connu(c, uid), "suggestions": suggestions(c, uid, ident, liste)}


def fiche_complete_uid(c: Carnet, uid: str) -> dict:
    return fiche_complete(c, personnes.de(c, uid))


def ajouter(c: Carnet, ident: str, corps: dict, par: str) -> dict:
    """POST d'une pépite : {texte, rubrique? (absente ou « vrac » : rangée par mots-clés), interdit?, source?,
    parue_le?}. Une pépite identique dans la même rubrique n'entre pas deux fois (renvoyée avec `deja`)."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    ident = _ident(c, ident)
    texte = _texte_pepite(corps.get("texte"))
    rubrique = _rubrique(corps, texte)
    source = corps.get("source") or "julien"
    if source not in SOURCES:
        raise ErreurCarnet("Source inconnue (julien, carnet, recidive ou sillage).")
    parue_le = _date_ou_rien(corps.get("parue_le"))
    liste = pepites(c, ident)
    if (meme := next((p for p in liste if p["rubrique"] == rubrique and _plier(p["texte"]) == _plier(texte)), None)):
        return {**meme, "deja": True}
    if len(liste) >= PEPITES_MAX:
        raise ErreurCarnet(f"{PEPITES_MAX} pépites au plus par personne.")
    with c.base.transaction() as cx:
        p = _inserer(cx, ident, rubrique, texte, source, par, parue_le)
    c.base.noter("journaux", "Pépite ajoutée à une fiche complète", {"personne_id": ident, "par": par})
    return p


def _lire_le(corps: dict | None, le_requete: str | None) -> str:
    le = (corps or {}).get("le") if isinstance(corps, dict) else None
    le = le or le_requete
    if not le or not isinstance(le, str):
        raise ErreurCarnet("`le` de la pépite absent : relis la fiche.")
    return le


def _verifier(c: Carnet, ident: str, pid: str, le: str):
    l = c.base.un("SELECT * FROM journaux_pepites WHERE id = ? AND personne = ?", (pid, ident))
    if not l:
        raise Introuvable("Pépite introuvable (effacée entre-temps ?) : relis la fiche.")
    if l["le"] != le:
        raise PepiteChangee("Cette pépite a changé entre-temps (depuis l'autre appli) : relis la fiche.")
    return l


def modifier(c: Carnet, ident: str, pid: str, corps: dict, par: str) -> dict:
    """PUT d'une pépite : {le, texte?, rubrique?, interdit?, parue_le?}. Déplacer = changer de rubrique
    (« interdits » ou `interdit: true` pour la ranger dans les sujets interdits)."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    ident = _ident(c, ident)
    migrer(c, ident)
    le = _lire_le(corps, None)
    with c.base.transaction() as cx:
        l = cx.execute("SELECT * FROM journaux_pepites WHERE id = ? AND personne = ?", (pid, ident)).fetchone()
        if not l:
            raise Introuvable("Pépite introuvable (effacée entre-temps ?) : relis la fiche.")
        if l["le"] != le:
            raise PepiteChangee("Cette pépite a changé entre-temps (depuis l'autre appli) : relis la fiche.")
        texte = _texte_pepite(corps["texte"]) if "texte" in corps else l["texte"]
        if corps.get("interdit") is False and "rubrique" not in corps and l["rubrique"] == INTERDITS:
            rubrique = ranger(texte)                     # sortie des sujets interdits sans rubrique : rangée
        elif "rubrique" in corps or corps.get("interdit") is True:
            rubrique = _rubrique(corps, texte)
        else:
            rubrique = l["rubrique"]
        parue_le = _date_ou_rien(corps["parue_le"]) if "parue_le" in corps else l["parue_le"]
        d = {"id": pid, "rubrique": rubrique, "texte": texte, "interdit": int(rubrique == INTERDITS),
             "parue_le": parue_le, "le": _nouveau_le(l["le"]), "par": par, "ancien": le}
        cur = cx.execute("UPDATE journaux_pepites SET rubrique = :rubrique, texte = :texte, interdit = :interdit, "
                         "parue_le = :parue_le, le = :le, par = :par WHERE id = :id AND le = :ancien", d)
        if cur.rowcount != 1:
            raise PepiteChangee("Cette pépite a changé entre-temps (depuis l'autre appli) : relis la fiche.")
        nouvelle = cx.execute("SELECT * FROM journaux_pepites WHERE id = ?", (pid,)).fetchone()
    return _pepite(nouvelle)


def effacer(c: Carnet, ident: str, pid: str, corps: dict | None, par: str, le_requete: str | None = None) -> dict:
    """DELETE d'une pépite : `le` dans le corps (ou en paramètre `?le=`)."""
    ident = _ident(c, ident)
    le = _lire_le(corps, le_requete)
    with c.base.transaction() as cx:
        cur = cx.execute("DELETE FROM journaux_pepites WHERE id = ? AND personne = ? AND le = ?", (pid, ident, le))
        efface = cur.rowcount == 1
    if not efface:
        _verifier(c, ident, pid, le)                      # dit pourquoi : introuvable (404) ou changée (409)
        raise PepiteChangee("Cette pépite a changé entre-temps : relis la fiche.")
    c.base.noter("journaux", "Pépite effacée d'une fiche complète", {"personne_id": ident, "par": par})
    return {"ok": True, "id": pid}


def marquer_parues(c: Carnet, ident: str, corps: dict) -> dict:
    """POST …/fiche/parues : {ids: [...], date: AAAA-MM-JJ} — les pépites tirées pour les textes retenus d'un numéro
    approuvé reçoivent `parue_le`. `le` ne change pas (ce n'est pas une modification du détail : pas de 409 pour
    une écriture en cours dans carnet). Les identifiants inconnus sont ignorés et comptés."""
    if not isinstance(corps, dict):
        raise ErreurCarnet("Un objet est attendu.")
    ident = _ident(c, ident)
    ids = corps.get("ids")
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise ErreurCarnet("`ids` : une liste d'identifiants de pépites est attendue.")
    date = _date_ou_rien(corps.get("date"))
    if not date:
        raise ErreurCarnet("`date` du numéro attendue (AAAA-MM-JJ).")
    marquees = 0
    with c.base.transaction() as cx:
        for pid in dict.fromkeys(ids[:PEPITES_MAX]):
            marquees += cx.execute("UPDATE journaux_pepites SET parue_le = ? WHERE id = ? AND personne = ?",
                                   (date, pid, ident)).rowcount
    return {"ok": True, "marquees": marquees, "ignorees": len(set(ids)) - marquees}


def resume_coffre(c: Carnet, ident: str) -> list[str]:
    """Section « Pour les journaux (Gazette) » de la note du coffre Contacts : la fiche complète (rubriques,
    pépites, « Sujets interdits »). Vide s'il n'y a aucune pépite."""
    liste = pepites(c, ident)
    if not liste:
        return []
    j = jauge(liste)
    l = ["", "## Pour les journaux (Gazette)",
         f"- **Fiche complète** : {j['nombre']} pépite{'s' if j['nombre'] > 1 else ''}" + (f" ({j['palier']})" if j["palier"] else "")]
    def ligne(p):
        plus = [] if p["source"] == "julien" else [p["source"]]
        if p["parue_le"]:
            plus.append(f"parue le {p['parue_le'][8:10]}/{p['parue_le'][5:7]}/{p['parue_le'][:4]}")
        return f"  - {p['texte']}" + (f" ({', '.join(plus)})" if plus else "")
    for famille in RUBRIQUES["familles"]:
        bloc = []
        for r in famille["rubriques"]:
            dedans = [p for p in liste if p["rubrique"] == r["cle"] and not p["interdit"]]
            if dedans:
                bloc += [f"- **{r['titre']}**", *[ligne(p) for p in dedans]]
        if bloc:
            l += ["", f"### {famille['titre']}", *bloc]
    perdues = [p for p in liste if not p["interdit"] and p["rubrique"] not in CLES]
    if perdues:
        l += ["", "### Autre", "- **Rubrique inconnue**", *[ligne(p) for p in perdues]]
    interdits = [p for p in liste if p["interdit"]]
    if interdits:
        l += ["", f"### {RUBRIQUES['interdits']['titre']}", *[f"- {p['texte']}" for p in interdits]]
    return l
