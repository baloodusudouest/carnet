"""Fiches : lecture d'une carte iCloud, comparaison champ par champ (aperçu avant d'écrire),
contrôles de forme (« Prénom NOM », numéros), doublons et réunion de deux fiches."""
from __future__ import annotations

from . import doublons, normalisation, synchro, vcard
from .fusion import reunir
from .modele import CHAMPS_MULTIPLES, completer, fiche_vide, nom_affiche
from .normalisation import CLES, cle_texte

LIBELLES = {"prenom": "Prénom", "nom": "Nom", "surnom": "Surnom", "societe": "Société", "fonction": "Fonction",
            "anniversaire": "Anniversaire", "notes": "Notes", "telephones": "Téléphones", "courriels": "Courriels",
            "adresses": "Adresses", "sites": "Sites", "noms_associes": "Noms associés", "groupes": "Groupes",
            "photo": "Photo"}
CHAMPS = ["prenom", "nom", "surnom", "societe", "fonction", "anniversaire", "telephones", "courriels",
          "adresses", "sites", "noms_associes", "notes", "groupes"]


def lire(texte: str, groupes: list[str], region: str = "FR") -> tuple[dict, bool]:
    """Carte iCloud → (fiche, a_une_photo). Les groupes viennent des cartes de groupe."""
    lue, _ = vcard.lire_carte(texte, region)
    fiche = completer(lue.fiche if lue else fiche_vide())
    fiche["photo"] = None
    fiche["groupes"] = sorted(set(groupes))
    return fiche, synchro.a_une_photo(texte)


def _texte_item(champ: str, x: dict) -> str:
    if champ == "telephones":
        return f"{x.get('affichage') or x.get('valeur')} ({x.get('type') or 'autre'})"
    if champ == "adresses":
        return ", ".join(v for v in (x.get("rue"), " ".join(p for p in (x.get("cp"), x.get("ville")) if p),
                                     x.get("pays")) if v) + f" ({x.get('type') or 'autre'})"
    return f"{x.get('valeur')} ({x.get('type') or 'autre'})" if x.get("type") else str(x.get("valeur"))


def valeurs(fiche: dict, champ: str) -> list[str]:
    v = fiche.get(champ)
    if champ in CHAMPS_MULTIPLES:
        return [_texte_item(champ, x) for x in v or []]
    if champ == "groupes":
        return sorted(v or [])
    return [str(v)] if v else []


def differences(avant: dict, apres: dict, photo: bool = False) -> list[dict]:
    """Champs qui changent : [{champ, libelle, avant: [...], apres: [...]}]. Sert à l'aperçu
    avant Valider et au détail des modifications faites sur l'iPhone."""
    res = []
    for champ in CHAMPS:
        a, b = valeurs(avant, champ), valeurs(apres, champ)
        if a != b:
            res.append({"champ": champ, "libelle": LIBELLES[champ], "avant": a, "apres": b})
    if photo:
        res.append({"champ": "photo", "libelle": "Photo", "avant": [], "apres": ["nouvelle photo"]})
    return res


def preparer(fiche: dict, region: str = "FR") -> dict:
    """Fiche saisie dans l'interface → fiche normalisée (formats imposés, groupes par émoji)."""
    propre = normalisation.normaliser_fiche({k: v for k, v in fiche.items() if k != "a_photo"}, region)
    propre["photo"] = None
    return propre


# ------------------------------------------------------------ contrôles de forme

def ecarts_de_forme(texte: str, fiche: dict, region: str = "FR") -> list[dict]:
    """Ce que la carte iCloud écrit autrement que le format voulu : nom affiché et numéros.
    La fiche lue est déjà normalisée ; on compare donc avec les valeurs brutes de la carte."""
    ecarts = []
    brutes = {nom: v for g, nom, v in map(synchro._decouper, synchro.deplier(texte))}
    fn = synchro._devaleur(brutes.get("FN", "")).strip()
    voulu = " ".join(p for p in (fiche.get("prenom"), fiche.get("nom")) if p)
    if voulu and fn and fn != voulu:
        ecarts.append({"champ": "nom", "avant": fn, "apres": voulu})
    for g, nom, v in map(synchro._decouper, synchro.deplier(texte)):
        if nom != "TEL":
            continue
        brut = synchro._devaleur(v).strip().removeprefix("tel:")
        t = normalisation.telephone(brut, None, region)
        if t and t.get("valide") and t.get("affichage") and brut != t["affichage"]:
            ecarts.append({"champ": "telephone", "avant": brut, "apres": t["affichage"]})
    return ecarts


# ------------------------------------------------------------ doublons

def paires_doublons(fiches: dict[str, dict], interdites: set[tuple[str, str]]) -> list[dict]:
    uids = sorted(fiches)
    sigs = [doublons.signature(i, fiches[u]) for i, u in enumerate(uids)]
    res = []
    for a, b, score, raisons in doublons.rapprochements(sigs):
        ua, ub = uids[a], uids[b]
        if (ua, ub) in interdites or (ub, ua) in interdites:
            continue
        res.append({"a": ua, "b": ub, "score": score, "raisons": raisons})
    return res


def cle_paire(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def proposer_fusion(garder: dict, absorber: dict) -> dict:
    """Fiche réunie : `garder` d'abord, complétée par `absorber`."""
    f = reunir({k: v for k, v in garder.items() if k != "a_photo"}, {k: v for k, v in absorber.items() if k != "a_photo"})
    f["photo"] = None
    return f


def meme_nom(fiche: dict, nom: str) -> bool:
    return cle_texte(nom_affiche(fiche)) == cle_texte(nom)


__all__ = ["CLES", "lire", "differences", "preparer", "ecarts_de_forme", "paires_doublons", "proposer_fusion"]
