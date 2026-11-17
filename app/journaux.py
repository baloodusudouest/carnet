"""2.29 : « Pour les journaux » — ce que Julien sait d'une personne (passions, manies, petites histoires) pour
les journaux de Gazette (rumeurs loufoques de La Récidive).

Rangé par identifiant maison (app/personnes.py), dans la base de carnet seulement : jamais écrit dans iCloud,
Synology Contacts ou le kit. Gazette le lit (GET /gazette/personnes, champ `journaux`) et l'écrit
(PUT /gazette/personnes/{personne_id}/journaux, jeton commun) ; la fiche de carnet le montre et le modifie ;
le coffre « Contacts » le recopie dans la note de la personne. Le journal de carnet ne porte jamais le texte.
Permis en lecture seule : rien ne sort de carnet."""
from __future__ import annotations

from . import personnes
from .carnet import Carnet, ErreurCarnet
from .temps import iso, maintenant

MAX = 600


def tous(c: Carnet) -> dict[str, dict]:
    """identifiant maison → {texte, le, par}."""
    return c.memo("journaux", lambda: {l["personne"]: {"texte": l["texte"], "le": l["le"], "par": l["par"]}
                                       for l in c.base.tous("SELECT * FROM journaux")})


def de_personne(c: Carnet, ident: str | None) -> str:
    return (tous(c).get(ident) or {}).get("texte", "") if ident else ""


def fiche(c: Carnet, uid: str) -> dict:
    ident = personnes.de(c, uid)
    j = tous(c).get(ident) or {}
    return {"personne_id": ident, "texte": j.get("texte", ""), "le": j.get("le"), "par": j.get("par", "")}


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
