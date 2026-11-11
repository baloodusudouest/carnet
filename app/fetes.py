"""Fête d'un prénom, d'après le calendrier français usuel (celui des agendas et des almanachs).

Aucun appel réseau : le calendrier est dans ce fichier. Il a été établi à la main pour carnet
(novembre 2026) et n'a pas valeur de référence : un prénom absent ou mal daté se corrige sur la
fiche, où une fête saisie à la main n'est jamais remplacée.

Règle : le prénom entier d'abord (« Jean-Baptiste » a sa fête, le 24 juin) ; sinon son premier
élément (« Marie-Claude » → Marie, « Jean Pierre » → Jean) ; accents, casse et traits d'union
ignorés. Un prénom inconnu ne reçoit pas de fête : il apparaît dans les manques « Sans fête ».
"""
from __future__ import annotations

import re
import unicodedata

# mois → « jour Prénom[/Autre prénom fêté le même jour] », un jour par élément
_CALENDRIER = {
    1: "2 Basile|3 Geneviève|4 Odilon|5 Édouard|6 Mélaine/Tiphaine|7 Raymond/Virginie/Cédric|8 Lucien|9 Alix"
       "|10 Guillaume|11 Paulin|12 Tatiana|13 Yvette|14 Nina|15 Rémi/Rachel|16 Marcel|17 Roseline|18 Prisca|19 Marius"
       "|20 Sébastien/Fabien|21 Agnès|22 Vincent|23 Barnard|24 François-de-Sales|26 Paule|27 Angèle|28 Thomas-d-Aquin"
       "|29 Gildas|30 Martine|31 Marcelle",
    2: "1 Ella|2 Théophane|3 Blaise/Oscar|4 Véronique/Vanessa/Bérénice|5 Agathe|6 Gaston/Dorothée|7 Eugénie|8 Jacqueline"
       "|9 Apolline|10 Arnaud|12 Félix|13 Béatrice|14 Valentin|15 Claude|16 Julienne|17 Alexis|18 Bernadette|19 Gabin"
       "|20 Aimée|21 Pierre-Damien|22 Isabelle|23 Lazare|24 Modeste|25 Roméo|26 Nestor|27 Honorine|28 Romain|29 Auguste",
    3: "1 Aubin/Jonathan|2 Charles-le-Bon|3 Guénolé|4 Casimir|5 Olive|6 Colette/Nicole|7 Félicité|8 Jean-de-Dieu"
       "|9 Françoise|10 Vivien|11 Rosine|12 Justine|13 Rodrigue|14 Mathilde/Maud|15 Louise|16 Bénédicte|17 Patrice"
       "|18 Cyrille|19 Joseph|20 Herbert|21 Clémence/Axel|22 Léa|23 Victorien|24 Catherine-de-Suède|25 Humbert"
       "|26 Larissa|27 Habib|28 Gontran|29 Gwladys|30 Amédée|31 Benjamin",
    4: "1 Hugues|2 Sandrine|3 Richard|4 Isidore|5 Irène|6 Marcellin|7 Jean-Baptiste-de-la-Salle|8 Julie/Constance"
       "|9 Gautier|10 Fulbert|11 Stanislas|12 Jules|13 Ida|14 Maxime/Ludivine|15 Paterne|16 Benoît-Joseph|17 Anicet"
       "|18 Parfait|19 Emma|20 Odette|21 Anselme|22 Alexandre|23 Georges|24 Fidèle|25 Marc|26 Alida|27 Zita"
       "|28 Valérie|29 Catherine-de-Sienne|30 Robert",
    5: "1 Jérémie|2 Boris/Zoé|3 Philippe|4 Sylvain/Florian|5 Judith|6 Prudence|7 Gisèle/Flavie|8 Désiré|9 Pacôme"
       "|10 Solange|11 Estelle|12 Achille|13 Rolande/Maël|14 Matthias|15 Denise|16 Honoré|17 Pascal|18 Éric/Corinne"
       "|19 Yves|20 Bernardin|21 Constantin|22 Émile|23 Didier|24 Donatien|25 Sophie|26 Bérenger|27 Augustin-de-Cantorbéry"
       "|28 Germain|29 Aymar|30 Ferdinand/Jeanne|31 Pétronille",
    6: "1 Justin|2 Blandine|3 Kévin|4 Clotilde|5 Igor|6 Norbert|7 Gilbert|8 Médard|9 Diane|10 Landry|11 Barnabé/Yolande"
       "|12 Guy|13 Antoine|14 Élisée|15 Germaine|16 Jean-François/Régis/Aurélien|17 Hervé|18 Léonce|19 Romuald"
       "|20 Silvère|21 Rodolphe|22 Alban|23 Audrey|24 Jean-Baptiste|25 Prosper/Éléonore|26 Anthelme|27 Fernand|28 Irénée"
       "|29 Pierre/Paul|30 Martial",
    7: "1 Thierry|2 Martinien|3 Thomas|4 Florent/Éliane|5 Antoine-Marie|6 Mariette|7 Raoul|8 Thibault/Edgar/Killian"
       "|9 Amandine/Marianne|10 Ulrich|11 Benoît|12 Olivier|13 Henri/Joël/Eugène|14 Camille|15 Donald|16 Carmen"
       "|17 Charlotte/Caroline/Arlette|18 Frédéric|19 Arsène|20 Marina/Élie|21 Victor|22 Marie-Madeleine/Madeleine"
       "|23 Brigitte|24 Christine|25 Jacques|26 Anne/Joachim|27 Nathalie/Lilian|28 Samson|29 Marthe|30 Juliette|31 Ignace",
    8: "1 Alphonse|2 Julien|3 Lydie|4 Jean-Marie|5 Abel|7 Gaétan|8 Dominique|9 Amour|10 Laurent|11 Claire/Suzanne"
       "|12 Clarisse|13 Hippolyte|14 Évrard|15 Marie|16 Armel|17 Hyacinthe|18 Hélène/Laetitia|19 Jean-Eudes"
       "|20 Bernard/Samuel|21 Christophe/Noémie|22 Fabrice|23 Rose|24 Barthélemy|25 Louis|26 Natacha|27 Monique"
       "|28 Augustin|29 Sabine|30 Fiacre|31 Aristide",
    9: "1 Gilles|2 Ingrid|3 Grégoire|4 Rosalie|5 Raïssa|6 Bertrand/Éva/Évelyne|7 Reine|8 Adrien|9 Alain|10 Inès"
       "|11 Adelphe|12 Apollinaire|13 Aimé|15 Roland|16 Édith|17 Renaud/Lambert|18 Nadège|19 Émilie|20 Davy"
       "|21 Matthieu|22 Maurice|23 Constant|24 Thècle|25 Hermann|26 Côme/Damien|27 Vincent-de-Paul|28 Venceslas"
       "|29 Michel/Gabriel/Raphaël|30 Jérôme",
    10: "1 Thérèse|2 Léger|3 Gérard/Blanche|4 François|5 Fleur/Chloé|6 Bruno|7 Serge/Gustave|8 Pélagie/Morgane"
        "|9 Denis/Sarah|10 Ghislain|11 Firmin|12 Wilfried|13 Géraud|14 Juste|15 Thérèse-d-Avila/Aurélie|16 Edwige"
        "|17 Baudouin/Solène|18 Luc|19 René/Laure|20 Adeline/Aline|21 Céline/Ursule|22 Élodie|23 Jean-de-Capistran"
        "|24 Florentin|25 Crépin|26 Dimitri|27 Émeline|28 Simon/Jude|29 Narcisse|30 Bienvenue|31 Quentin",
    11: "3 Hubert|4 Charles|5 Sylvie|6 Bertille/Léonard|7 Carine/Ernest|8 Geoffroy|9 Théodore|10 Léon|11 Martin"
        "|12 Christian/Tristan|13 Brice|14 Sidoine|15 Albert/Arthur/Léopold/Victoire|16 Marguerite|17 Élisabeth"
        "|18 Aude|19 Tanguy|20 Edmond/Octave|22 Cécile|23 Clément|24 Flora|25 Catherine|26 Delphine|27 Séverin"
        "|28 Jacques-de-la-Marche|29 Saturnin|30 André",
    12: "1 Florence|2 Viviane|3 François-Xavier/Xavier|4 Barbara|5 Gérald|6 Nicolas|7 Ambroise|9 Pierre-Fourier"
        "|10 Romaric|11 Daniel|12 Jeanne-Françoise/Chantal|13 Lucie/Jocelyn|14 Odile|15 Ninon/Christiane|16 Alice"
        "|17 Gaël|18 Gatien|19 Urbain|20 Théophile|21 Pierre-Canisius|22 Françoise-Xavière|23 Armand|24 Adèle"
        "|25 Noël/Emmanuel|26 Étienne|27 Jean|28 Gaspard|29 David|30 Roger|31 Sylvestre",
}

# Prénoms courants fêtés avec un autre : « Prénom du calendrier : variantes »
_VARIANTES = """
Michel: Michaël Mickaël Michèle Michelle Micheline Michael Mike Miguel
Étienne: Stéphane Stéphanie Steven Steve Esteban Fanny Stefan Stephan Stéfanie
Laurent: Laurence Laurette Lorenzo
Laure: Laura Laurie Lauriane Laurine Lorraine
Patrice: Patrick Patricia Pat
Pascal: Pascale Pascaline
Daniel: Danielle Danièle Dany Daniela Daniele
Jeanne: Jeannine Janine Jeannette Jeanine Johanna Joanna Jane
Jean: Yann Yannick Yoann Yohann Johan Yohan Ivan Yvan Jeannot Juan John Johnny Jehan Yanis Ian
Joseph: Josette Joséphine Josiane José Josée Josépha Giuseppe Jo
Paule: Paulette Pauline Paula Paola
Paul: Pablo Paolo Pol
Louise: Louisette Héloïse Éloïse Louisa Luisa
Louis: Ludovic Loïc Clovis Luis Lewis Loïs Loïck
François: France Francine Francis Franck Frank Francesca Francesco Francisco Fanchon Franz
Françoise: Fanchette
Fabien: Fabienne Fabiola
Yves: Yvon Yvonne Erwan Erwann Yvonnick Ivo
Guillaume: William Willy Liam Guillemette Wilhelm Guilhem
Henri: Henriette Harry Enzo Henry Enrico
Jacques: Jacky Jacquot James Jack Jim Diego Jacob
Nadège: Nadine Nadia Nadya
Alexandre: Alexandra Alex Sacha Sandra Alexia Alexane Sandro Alessandro
Sylvie: Sylvia Sylviane Sylvette Silvia Sylvaine
Valérie: Valéry Valéria
Anne: Anaïs Annie Anna Annabelle Annick Anouk Nancy Hannah Anita Annette Anouck Nanette Annaëlle Ana
Sébastien: Bastien Sébastienne Bastian
Benoît: Benoîte Bénédict
Charles: Charly Carl Karl Carlos Charlène Charline Charley Carlo
Charlotte: Carole Carla Carolyne Charlie Carline
Claire: Clara Clarence Clairette
Claude: Claudine Claudette Claudie Claudia Claudio Claudius
Clémence: Clémentine
Élisabeth: Élise Elsa Lisa Élisa Lise Lison Betty Babette Liliane Lili Lily Elisabeth Isabeau Bettina Elizabeth Lisbeth
Isabelle: Isabel Isabella Isa
Émilie: Amélie Emily Émilia Emilia
Emmanuel: Emmanuelle Manuel Manuela Manu
Éric: Erika Erick Érica Erik
Estelle: Stella Estella
Eugénie: Eugénia
Florence: Florentine
Frédéric: Frédérique Fred Frédérick Frederick Freddy
Gaël: Gaëlle Gwenaël Gwenaëlle
Gabriel: Gabrielle Gaby Gabriela Gabriella
Geneviève: Ginette Jennifer Jenny Guenièvre
Georges: Georgette Georgia Youri Jorge Joris Georgina
Gérald: Géraldine
Ghislain: Ghislaine Guylaine
Grégoire: Grégory Greg
Éléonore: Aliénor Léonore Nora Eleanor
Hélène: Elena Éléna Léna Lena Héléna Ellen Nelly Marlène Hélèna Ilona
Hugues: Hugo Huguette Ugo
Jérémie: Jérémy Jeremy
Joël: Joëlle Joel
Julie: Julia Julianne Giulia
Julien: Julian Jullien Julio
Justine: Justina
Léon: Léo Léonie Lionel Léone Léonce Leo
Luc: Lucas Luca Lukas Lucka
Lucie: Lucile Lucille Lucette Lucia Aurore Luce Lucy
Lucien: Lucienne
Lydie: Lydia
Madeleine: Magali Magalie Madeline Magdalena Maddy Madelon Mado
Marguerite: Margot Margaux Maggy Mégane Megan Daisy Greta Marjorie Margaret Peggy
Marie: Maria Marion Marielle Maryse Marylène Maryline Marilyne Mireille Muriel Murielle Myriam Manon Mylène Maryvonne Mary Mariam Maëva Marilou Marylou Miriam Marika Mariana Maryam Marie-Jo
Marina: Marine Marinette
Martine: Martina
Mathilde: Mathilda Matilda Tilda
Matthieu: Mathieu Mathéo Matéo Mathis Matis Matt Matthew Matteo Mattéo Mathys
Maxime: Max Maximilien Maxence Maximin
Monique: Monica Mona
Nicolas: Colin Coline Nico Nicola Nick Colas Niels Nils Klaus
Noël: Noëlle Noélie Noëlla
Nathalie: Natalie Nathalia Natalia
Natacha: Natasha
Olivier: Olivia Oliver
Philippe: Philippine Phil Felipe Filip
Pierre: Pierrick Perrine Pierrette Peter Pedro Pierrot Pierre-Yves Piotr Pietro Pétra Pernelle
Raphaël: Raphaëlle Rafael Raphaëla
Raymond: Raymonde Ramon
Reine: Régine Regina Réjane
Rémi: Rémy
René: Renée
Robert: Roberte Robin Bob Roberto Bobby Robine
Roland: Orlando Rolland
Romain: Romane Roman Romy
Rose: Rosa Rosy Rosette Rosie Rosemonde
Sabine: Sabrina
Simon: Simone Siméon
Sophie: Sonia Sofia Sophia Sonya
Suzanne: Suzy Suzon Susan Suzette
Tatiana: Tania Tanya
Théodore: Théo Théa Theo
Thérèse: Tessa Teresa Thérésa Térésa
Thibault: Thibaut Thibaud Théobald Tibo
Thomas: Tom Tommy Tomas
Valentin: Valentine Valentina
Véronique: Véronica Véro
Victor: Victoria Victorine Vicky Viktor
Viviane: Vivianne Vivian
Xavier: Xavière
Alain: Alan Allan
Albert: Alberte Albertine Alberto Bertie
Alice: Alicia Alison Alyssa Alissa Alysson
André: Andrée Andréa Andy Andrew Andreas Andrea
Angèle: Angélique Angela Angéline Angelina Angélina Angie Ange
Adrien: Adrienne Adriana Adrian Adriano
Aimée: Amy
Amandine: Amanda Mandy
Antoine: Anthony Antonin Antoinette Toinette Tony Antonio Anton Antony Antonia Toni Antonella
Armand: Armande Armando
Arnaud: Arnaude Arnold
Aurélie: Aurélia Aurélienne Auréline
Bernard: Bernarde Bernardo Bernhard
Brigitte: Britt Birgit Brigit
Bruno: Brunehilde
Catherine: Cathy Katia Karen Katell Ketty Kathy Katy Karine Katherine Kathleen Katarina Catalina Caterina Kate Katie Cathie Katrina
Carine: Karina Carina
Cécile: Cécilia Célia Cecilia Sheila
Céline: Célina Céliane
Christine: Christelle Christel Christina Kristel Kristina Christèle Cristina Tina
Christophe: Christopher Kristof Christopher Chris Cristobal
Christian: Christiana Kristian
Cyrille: Cyril Cyrielle
Damien: Damienne Damian
David: Davina Dave
Delphine: Delphin
Denis: Dennis
Denise: Denyse
Didier: Didière
Dominique: Dominic Domenico Dominica Domingo
Édith: Edith
Édouard: Eddy Edward Teddy Ted Eddie
Élodie: Elodie
Émile: Émilien Emilio Emil
Fernand: Fernande Fernando Hernan
Florent:
Geoffroy: Geoffrey Jeoffrey Jeffrey Geoffray Jeff
Gérard: Gérarde Gerhard
Gilbert: Gilberte Gilberto
Gilles: Gil
Gisèle: Gisela Giselle
Hervé: Hervéa
Hubert: Huberte
Inès: Ines
Irène: Irina Iréna
Jérôme: Geronimo
Kévin: Kevin
Léa: Lia
Marc: Marco Marcus Mark Markus
Marcel: Marceau Marcello
Marthe: Martha
Maurice: Mauricette Mauricio Morris
Odile: Odilia
Odette: Odetta
Quentin: Quentine
Richard: Ricardo Rick Richie
Roger: Rogère Rogerio
Sandrine: Sandie Sandy
Serge: Sergio Sergueï
Solange:
Stanislas: Stan
Thierry: Terry Thierri
Vincent: Vincente Vincenzo Vicente
Virginie: Virginia
Yvette: Yveline
"""


def cle(prenom: str) -> str:
    """Prénom → clé de comparaison : sans accents, en minuscules, éléments séparés par « - »."""
    t = unicodedata.normalize("NFKD", prenom or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("œ", "oe")
    return "-".join(re.findall(r"[a-z]+", t))


def _construire() -> dict[str, str]:
    table: dict[str, str] = {}
    for mois, jours in _CALENDRIER.items():
        for bloc in jours.split("|"):
            jour, noms = bloc.split(" ", 1)
            for nom in noms.split("/"):
                # Le premier jour rencontré l'emporte, sauf pour les prénoms très fréquents dont
                # la fête usuelle n'est pas la première de l'année (corrigés plus bas)
                table.setdefault(cle(nom), f"--{mois:02d}-{int(jour):02d}")
    usuelles = {"marie": "--08-15", "jean": "--12-27", "jacques": "--07-25", "catherine": "--11-25",
                "therese": "--10-01", "francois": "--10-04", "antoine": "--06-13", "thomas": "--07-03",
                "vincent": "--01-22", "charles": "--11-04", "augustin": "--08-28", "pierre": "--06-29",
                "damien": "--09-26", "jean-baptiste": "--06-24", "jeanne": "--05-30", "francoise": "--03-09"}
    table.update(usuelles)
    for ligne in _VARIANTES.strip().splitlines():
        base, _, variantes = ligne.partition(":")
        date = table.get(cle(base))
        if not date:
            continue
        for v in variantes.split():
            table.setdefault(cle(v), date)
    return table


TABLE = _construire()


def pour(prenom: str) -> str | None:
    """Fête du prénom : « --MM-JJ », ou None s'il n'est pas au calendrier."""
    k = cle(prenom)
    if not k:
        return None
    return TABLE.get(k) or TABLE.get(k.split("-")[0])


__all__ = ["pour", "cle", "TABLE"]
