# Reprise — carnet

Fichier à lire en premier dans une nouvelle session, et à mettre à jour à chaque fin de session, dans le même commit que le code.

## État (11/11/2026)

- **2.12.0 sur `main`** (12/11/2026) : « Relancer la recherche pour tous » dans Photos (`galerie.chercher_toutes`, `POST /api/photos/propositions` avec `tous`), sans limite de lot, lecture seule d'Immich. Table `choisis` : un choix fait dans Photos replie la ligne (`photos.retenir_choix`), une recherche la remontre. **Durée sur les vraies données inconnue** (une soixantaine d'appels par contact). Icône de Treemich, un arbre dessiné par carnet (`main.ARBRE`, servi par `/api/logo-reseau/treemich`).
- **2.11.2** (12/11/2026) : un nom associé se choisit parmi les noms du carnet (`Editeur.svelte`, liste `noms-du-carnet` tirée de `/api/contacts`) ou s'écrit à la main.
- **2.11.1** (12/11/2026) : Treemich reprend le visage après Immich (`photos.vignette_treemich`, adresse `POST /people/{id}/thumbnail/import/immich` relevée dans l'interface de Treemich le 12/11). **Pas vue sur les vraies données** : vérifier que trois secondes suffisent à Immich pour refaire sa vignette.
- **2.11.0** (11/11/2026) : Photos, tuiles « Portraits » et « Affiches » pour tous les contacts avec le choix de carnet (`photos.note_portrait`), pose par lot des choix (`galerie.poser_choix`, `preparer_choix`), visage de la personne mis à jour dans Immich (`photos.vignette_immich`). **Pas vue sur les vraies données.** À vérifier au premier essai : la clé Immich de carnet a-t-elle le droit `person.update` ; (Treemich : réglé en 2.11.1.)
- **2.10.0** (11/11/2026) : fenêtre de propositions (5 photos, 5 affiches) ouverte en touchant la photo d'une fiche en modification ; affiche du logo à la couleur de la société.
- 2.9.2 (11/11/2026) : mariages par couple dans `/ha/anniversaires` ; côté Home Assistant, `maison/anniversaires.yaml` v2 lit les mariages et `/ha/fetes` (master doc HA 1.50).
- 2.9.1 (11/11/2026) : liste des couples dans Connexion › Treemich, messages corrigés. Vérifié sur l'installation de Julien le 11/11 : l'écriture d'un mariage dans Treemich fonctionne (lue dans l'arbre) ; « Vérifier » sur Treemich prend environ 50 secondes.
- 2.9.0 (11/11/2026) : réorganisation en six onglets (À traiter en tuiles, Contacts, Groupes, Photos, Connexion avec une icône par service, Réglages). Faite sans dossier ni conseil préalables, à la demande de Julien ; le dossier tel que construit a été mis à jour après le code.
- 2.8.5 avant elle : la 2.8 complète (vérification de l'accord avec Treemich en 2.8.5 ; attentes et manques, Photos, champs nouveaux, fêtes et dates de famille, import unique, suppression confirmée, logo par société, noms de société, accord immédiat avec Treemich, Réseaux dans Réglages). Julien a une 2.8 en service.
- Interrupteurs : Julien a allumé « dates de famille » le 11/11 ; « fêtes » est éteint à la livraison.
- Conseil : [`docs/2.8-conseil.md`](docs/2.8-conseil.md). Essai sur le vrai iCloud : [`docs/essai-2.8.md`](docs/essai-2.8.md).
- Dossier « tel que construit » : [`docs/dossier.md`](docs/dossier.md), à jour pour la 2.9.0.

## Prochaine étape

0. **2.9.0** : Julien la met en service (`CARNET_VERSION=2.9.0`, copie de `/state` avant) et dit ce qui gêne à l'usage. À regarder avec lui : la tuile « Pas de groupe » compte maintenant dans le chiffre de l'onglet (il sera plus haut) ; « Synchroniser » sur Immich et Treemich n'a été essayé que sur des services simulés ; les logos des réseaux dans les tuiles.

Restes de la 2.8, toujours valables :

1. Julien met la 2.8.0 en service **en lecture seule un jour** (`CARNET_LECTURE_SEULE=oui`), copie de `/state` avant. Il vérifie : les nombres de la famille « Manques » (la sonde donnait 437 fiches incomplètes, 406 sans photo, 59 sans téléphone, avant l'exemption des fiches d'entreprise et sans la colonne Fête), le tableau des attentes, la liste « ce que carnet écrirait ».
2. Il enlève la lecture seule, puis allume « fêtes » ; une semaine plus tard, « dates de famille ». Relire « Écrit par carnet tout seul » après chaque première nuit.
3. À voir à l'usage : le calendrier des fêtes (prénoms introuvables dans la ligne « Sans fête »), le logo glissé depuis Google Images sur iPhone et sur PC, l'écriture réelle d'un mariage dans Treemich (jamais essayée sur la vraie installation).
4. Home Assistant : `maison/anniversaires.yaml` v2 livré le 11/11 (mariages et fêtes dans `calendar.anniversaires`, alerte 08:00, carte) ; **installé et validé par Julien le 11/11/2026**.
5. Idée gardée : route unique d'évènements pour Home Assistant.
6. Après une semaine d'usage : document du socle et planche de couleurs.

## Décisions tranchées

- iCloud est la source maître ; toute modification faite sur l'iPhone repasse par « À traiter ».
- Aucune suppression automatique ; la nuit n'écrit que les mises à jour sûres.
- Suppression d'une fiche : seulement à la demande de Julien, depuis la modification de la fiche, et toujours après confirmation (2.8.0). Le serveur refuse sans `confirmation` vraie.
- Trois onglets jusqu'à la 2.7 ; cinq à partir de la 2.8.0 (Photos, Réglages) ; **six à partir de la 2.9.0** : À traiter, Contacts, Groupes, Photos, Connexion, Réglages. État n'existe plus.
- 2.9.0 (réponses de Julien) : À traiter en grille de tuiles ; « pas de groupe » compte dans le chiffre de l'onglet, « contact incomplet » non ; Connexion porte tous les services, les réseaux, Home Assistant, le kit et le tableau des attentes ; « Synchroniser » écrit le sûr et envoie le reste dans À traiter ; la nuit est gardée, avec un interrupteur par service ; six icônes sans nom sur iPhone.
- Le nouvel habillage (minimalisme, tuiles bento pour État, sombre par défaut et clair selon l'appareil, shadcn-svelte, ocre conservé) **remplace** l'actuel, sans version en parallèle (décision du 11/11/2026).
- L'habillage ne change aucune route de l'API ni le schéma de la base, ni les textes, ni la navigation ; les tests d'interface ne sont pas réécrits.
- L'anneau de progression, la jauge autour de l'avatar et l'index en tranche sont gardés et reteintés.
- Le mot de passe reste `CARNET_PASSWORD` ; connexion unique plus tard, avec l'Anneau unique.
- Conseil du 11/11/2026 : ménage, habillage et parcours sont trois livraisons séparées.
- Habillage 2.7.0 : les couleurs gardent leurs noms d'origine (`--color-cuir`, `--color-papier`…), seules leurs valeurs changent ; le clair se fait par `prefers-color-scheme`, sans bouton. Julien a trouvé le premier essai (neutres froids, bouton plein neutre) trop froid : les neutres sont teintés vers l'ocre et le bouton plein est en ocre.
- shadcn-svelte n'est pas introduit dans carnet, ni en 2.7.0 ni en 2.8.0 (avis du conseil) : fenêtre et case à cocher natives, habillées par les classes maison.
- 2.8.0 : fête et dates de famille s'écrivent sans validation mais derrière deux interrupteurs éteints à la livraison ; les dates de famille remplissent le côté vide et n'écrasent jamais ; cinq onglets.

## Pièges

- L'historique du dépôt a été réécrit le 11/11/2026 sur toutes les branches (adresse locale, dossier personnel et noms réels utilisés en exemples remplacés). Un ancien clone doit être refait, pas fusionné. Les références des anciennes demandes de fusion sur GitHub gardent l'ancien historique : seul leur support peut les purger. Les images antérieures à la 2.10.0 sont à supprimer du registre.
- Rien de personnel dans le dépôt public : exemples inventés pour les sociétés, les chemins et les adresses.
- 2.11 : les candidats trouvés avant la 2.11 n'ont pas le nombre de visages (`photos.a_jour`) : l'écran demande de les relire. Une relecture coûte une soixantaine d'appels à Immich par contact : toujours par lots.
- 2.11 : la vignette Immich n'a pas d'annulation (Immich ne dit pas quelle photo servait avant).
- 2.10 : la « couleur de la société » est calculée depuis le logo (`logos.couleurs`), elle n'est pas enregistrée. L'affiche du logo n'est faite que pour un contact non relié à Immich ; une personne reliée garde une affiche en photo.
- 2.10 : l'affiche du logo n'a été vue que sur des logos d'essai ; à juger sur de vrais logos (fond blanc opaque, logo très large, logo monochrome).
- Treemich n'affiche pas le mariage dans « Life events » : il est sur le lien du couple (Profile › Relatives › crayon du conjoint). Ne pas conclure qu'une date n'est pas partie sans regarder là, ou la liste des couples de Connexion › Treemich.
- 2.9 : l'écran « Connexion » (les services) est `frontend/src/pages/Services.svelte`. `pages/Connexion.svelte` est la page du mot de passe : ne pas la remplacer.
- 2.9 : `POST /api/connexion` (mot de passe) est la seule route d'`/api/` ouverte sans session avec `/api/session` ; `GET /api/connexion` (état des services) est protégée. L'exemption se fait sur le chemin **et** la méthode : ne pas l'élargir.
- 2.9 : dans `app/main.py`, ne jamais nommer une route comme un module importé (`connexion`, `groupes`…) : la fonction masque le module et la route casse à l'appel. Un test du back passe par l'API pour le voir.
- 2.9 : les interrupteurs de nuit d'iCloud et de Treemich sont les anciens `auto_fetes` et `auto_famille` ; les autres sont des clés `nuit_<service>`, allumées par défaut.
- 2.9 : plusieurs écrans ont une grille `nav.tuiles` ; dans les tests, viser la grille par son nom (`nav[aria-label='Services']`…), sinon on attrape celle de l'écran précédent.
- 2.8 : toute écriture automatique nouvelle passe par `famille.appliquer` (interrupteur, plafond de nuit, table `automatiques`). Une réponse de Julien dans « À traiter » écrit tout de suite et n'est pas journalisée comme automatique.
- Le logo se choisit par société (`logos_societes`) et ne remplace jamais une photo : `galerie.fiches_de_la_societe` ne rend que des fiches sans photo et non reliées à Immich.
- Les logos en attente d'un choix sont dans `c.logos`, pas dans le cache `c._memo` (vidé à chaque écriture).
- Le tableau des attentes n'est inscrit qu'une fois (`attentes_semees`) : un groupe créé plus tard n'attend rien tant que Julien ne coche pas.
- Dates supplémentaires d'une carte : l'iPhone réécrit (ordre, `type=pref`, paramètre de la date sans année retiré). Comparer des valeurs ; l'an 1604 veut dire « sans année ». Le libellé natif d'Apple pour les dates s'affiche « fête » en français : ne pas l'utiliser pour le mariage.
- La recherche automatique de logos ne couvre qu'une fiche de société sur dix : le logo glissé est le chemin principal.
- Treemich range le mariage et le divorce sur le couple, pas sur la personne : lire `GET /relationships`, écrire par `PATCH /people/<id>/relationships`. Les évènements de vie d'une personne ne les contiennent jamais.
- carnet écrit dans le vrai compte iCloud : Watchtower est désactivé, toute mise à jour est manuelle dans Portainer.
- Treemich limite les connexions et le rythme des requêtes : une seule session réutilisée.
- Pousser sur `main` reconstruit et republie l'image `latest`.
- Les tests d'interface s'appuient sur des textes, des rôles d'accessibilité et quelques noms internes (`.ligne`, `.message`, `nav.onglets`, `.tranche`, `.jauge`, `.volet-liste`) : les conserver pendant l'habillage.
- Tant que l'ancien et le nouvel habillage coexistent, un écran pas encore refait peut se dégrader sans qu'un test le voie : regarder les captures de tous les écrans à chaque étape.
- Mode lecture seule : toute nouvelle écriture vers un service extérieur doit appeler `c.exiger_ecriture(...)` et passer par un client gardé (`_garde`).

## Retour arrière

- Copier `/state` avant la mise en service de la 2.7.0.
- `CARNET_VERSION=2.7.2` dans Portainer pour revenir avant la 2.8 ; la base est la même (les tables de la 2.8 sont ignorées). Ce qui a été écrit dans iCloud ou Treemich par la 2.8 ne revient pas : utiliser « Défaire » avant, ou la sauvegarde d'iCloud.

## Non-objectifs

- Pas de multi-utilisateur, pas d'import Gmail ni Outlook, pas de graphique.
