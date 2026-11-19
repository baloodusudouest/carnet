"""3.2 : visualisations du coffre Contacts — étiquettes (`tags`) pour colorer le graphe de Graphview, schéma Mermaid
de la fiche « Arbre », frise Mermaid de la note Contact. Personnes et données inventées."""
from __future__ import annotations

from app import coffre, evenements as E, liaisons, personnes

from .test_228 import c, note  # noqa: F401 — fixture réutilisée
from .test_carnet import services  # noqa: F401

PAUL, CLAIRE = "DDDD-4444", "AAAA-1111"


def _entete(texte: str) -> list[str]:
    return coffre._separer(texte)[0]


# ================================================================ étiquettes

def test_32_etiquettes_des_trois_sortes_de_notes(c):  # noqa: F811
    paul = personnes.de(c, PAUL)
    E.recevoir(c, "gazette", "sejour-1", {"type": "sejour", "date": "2026-07-02", "titre": "Séjour d'été",
                                           "personnes": [{"personne_id": paul}]})
    coffre.synchroniser(c)
    racine = c.cfg.contacts
    assert coffre._tags(_entete(note(c, "Paul MARTIN"))) == ["contact"]
    fiche = (racine / "Personnes" / "Paul MARTIN" / "Paul MARTIN — Séjours.md").read_text(encoding="utf-8")
    assert coffre._tags(_entete(fiche)) == ["fiche"]
    evt = (racine / "Événements" / "Séjours" / "2026-07-02 — Séjour d'été.md").read_text(encoding="utf-8")
    assert coffre._tags(_entete(evt)) == ["evenement"]


def test_32_etiquettes_a_la_main_gardees_sous_toutes_leurs_formes(c):  # noqa: F811
    coffre.synchroniser(c)
    chemin = c.cfg.contacts / "Personnes" / "Paul MARTIN" / "Paul MARTIN.md"
    for forme, attendu in (("tags: [famille, \"#voisin\"]", ["contact", "famille", "voisin"]),
                           ("tags: famille, voisin", ["contact", "famille", "voisin"]),
                           ("tags:\n  - famille\n  - contact", ["contact", "famille"])):
        texte = chemin.read_text(encoding="utf-8")
        lignes, corps = coffre._separer(texte)
        lignes = [l for l in coffre._entete_gardee(lignes)] + [x for x in coffre._entete_carnet(c, c.fiches()[PAUL],
                  personnes.de(c, PAUL), "présente", "2026-01-01") if not x.startswith(("tags:", "  - contact"))]
        lignes += forme.split("\n")
        chemin.write_text("---\n" + "\n".join(lignes) + "\n---\n" + corps, encoding="utf-8")
        coffre.synchroniser(c)
        nouveau = chemin.read_text(encoding="utf-8")
        assert coffre._tags(_entete(nouveau)) == attendu, forme
        assert nouveau.count("tags:") == 1 and nouveau.count("personne_id:") == 1
    assert coffre.synchroniser(c)["mises_a_jour"] == 0                  # rien de changé : rien de réécrit


# ================================================================ arbre

def test_32_arbre_mermaid_parents_fratrie_conjoint_enfants(c, monkeypatch):  # noqa: F811
    liaisons.lier(c, PAUL, "treemich", "t-paul")
    monkeypatch.setattr(coffre, "arbre", lambda _c: {PAUL: [("père", "Jean MARTIN"), ("mère", "Rose \"Rosette\" MARTIN"),
                                                            ("sœur", "Claire MARTIN"), ("conjoint", "Inès <Garnier>"),
                                                            ("enfant", "Léo MARTIN")]})
    coffre.synchroniser(c)
    texte = (c.cfg.contacts / "Personnes" / "Paul MARTIN" / "Paul MARTIN — Arbre.md").read_text(encoding="utf-8")
    debut, fin = texte.index("```mermaid"), texte.index("```", texte.index("```mermaid") + 3)
    schema = texte[debut:fin]
    assert coffre.MERMAID_THEME in schema and "flowchart TD" in schema and 'moi["Paul MARTIN"]' in schema
    assert 'n1["Jean MARTIN<br/><small>père</small>"]' in schema and "n1 --> moi" in schema and "n2 --> moi" in schema
    assert "#quot;Rosette#quot;" in schema and "Inès ‹Garnier›" in schema           # libellés sûrs
    assert "n1 --> n3" in schema                                        # la sœur sous le premier parent
    assert "moi === n4" in schema and "moi --> n5" in schema
    assert "- sœur : [[Claire MARTIN]]" in texte[fin:]                   # la liste des liens reste sous le schéma
    assert coffre._tags(_entete(texte)) == ["fiche"]


def test_32_arbre_sans_parents_fratrie_reliee_a_la_personne():
    s = coffre.arbre_mermaid("Paul MARTIN", [("frère ou sœur", "Claire MARTIN"), ("cousin", "Max MARTIN")])
    assert "moi --- n1" in s and "moi -.- n2" in s and s.startswith("```mermaid") and s.endswith("```")


# ================================================================ frise

def test_32_frise_dans_la_note_contact(c):  # noqa: F811
    paul, claire = personnes.de(c, PAUL), personnes.de(c, CLAIRE)
    E.recevoir(c, "gazette", "sejour-1", {"type": "sejour", "date": "2025-05-10", "titre": "Séjour : printemps",
                                           "personnes": [{"personne_id": paul}, {"personne_id": claire}]})
    E.recevoir(c, "douze-points", "soiree-1", {"type": "douze_points", "date": "2026-05-16", "titre": "Soirée Eurovision 2026",
                                                "personnes": [{"personne_id": paul}]})
    E.recevoir(c, "gazette", "sejour-2", {"type": "sejour", "date": "2026-07-02", "titre": "Séjour d'été #2",
                                           "personnes": [{"personne_id": paul}]})
    coffre.synchroniser(c)
    texte = note(c, "Paul MARTIN")
    assert "## Frise" in texte
    frise = texte[texte.index("## Frise"):]
    assert "timeline" in frise and "  2025 : Séjour – printemps" in frise
    assert "  2026 : Soirée Eurovision 2026 : Séjour d'été – 2" in frise   # dans l'ordre des dates
    assert "  2025 : Séjour – printemps" in note(c, "Claire MARTIN")
    assert coffre.synchroniser(c)["mises_a_jour"] == 0


def test_32_frise_limitee_par_annee_et_vide():
    evts = [(f"2026-01-{j:02d}", f"Soirée {j}") for j in range(1, 12)]
    s = coffre.frise_mermaid(evts)
    assert s.count(" : ") == coffre.FRISE_PAR_ANNEE + 1 and "et 3 autres" in s
    assert coffre.frise_mermaid([]) is None and coffre.frise_mermaid([("", "Sans date")]) is None


def test_32_pas_de_frise_sans_evenement(c):  # noqa: F811
    coffre.synchroniser(c)
    assert "## Frise" not in note(c, "Paul MARTIN") and "```mermaid" not in note(c, "Paul MARTIN")
