<script>
  import { tick, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { ref, statut, route, aller, annoncer, ecran, choisirVue } from '../lib/etat.svelte.js'
  import { CLES, texteItem, anniversaireLisible, dateCourte, rechercheLinkedin } from '../lib/cles.js'
  import Fusion from '../components/Fusion.svelte'
  import Aide from '../components/Aide.svelte'
  import Proches from '../components/Proches.svelte'

  const SIMPLES = [
    { champ: 'prenom', libelle: 'Prénom', toujours: true },
    { champ: 'nom', libelle: 'Nom', toujours: true },
    { champ: 'surnom', libelle: 'Surnom' },
    { champ: 'societe', libelle: 'Société', toujours: true },
    { champ: 'fonction', libelle: 'Fonction' },
    { champ: 'anniversaire', libelle: 'Anniversaire', toujours: true },
    { champ: 'photo', libelle: 'Photo' },
    { champ: 'notes', libelle: 'Notes' },
  ]
  const MULTIPLES = [
    { champ: 'telephones', libelle: 'Téléphones', unite: 'téléphone' },
    { champ: 'courriels', libelle: 'Courriels', unite: 'courriel' },
    { champ: 'adresses', libelle: 'Adresses', unite: 'adresse' },
    { champ: 'sites', libelle: 'Sites et réseaux', unite: 'site' },
    { champ: 'noms_associes', libelle: 'Noms associés', unite: 'nom associé' },
  ]
  const RACCOURCIS_GROUPES = { i: 'Moi', u: 'Urgence', f: 'Famille', a: 'Amis', r: 'Artisans et services', o: 'Collègues', c: 'Clients', j: 'Jardin secret' }
  const LETTRE_GROUPE = Object.fromEntries(Object.entries(RACCOURCIS_GROUPES).map(([k, v]) => [v, k]))
  const ORDRE = ['icloud', 'gmail', 'outlook', 'linkedin']

  let file = $state([])
  let dossier = $state(null)
  let fiche = $state(null)
  let actif = $state(0)
  let edition = $state(null)
  let tousLesChamps = $state(false)
  let fusionOuverte = $state(false)
  let aideOuverte = $state(false)
  let occupe = $state(false)
  let detailOuvert = $state(false)   // vue iPhone : champs identiques dépliés
  const mobile = $derived(ecran.etroit && !ecran.forcerPC)
  let chargeLe = ''
  let minuteur = null

  async function chargerFile() {
    file = await api.get('/api/file')
    Object.assign(statut, await api.get('/api/statut'))
  }

  // Fiche suivante chargée d'avance : elle s'affiche sans attendre après « Valider » ou « Passer »
  const enAvance = new Map()   // id → { dossier, le }
  function precharger() {
    const pos = dossier ? file.findIndex((p) => p.id === dossier.id) : -1
    for (const p of [file[pos + 1], file[pos - 1]]) {
      if (p && !enAvance.has(p.id)) {
        enAvance.set(p.id, { promesse: api.get(`/api/personnes/${p.id}`), le: Date.now() })
        enAvance.get(p.id).promesse.catch(() => enAvance.delete(p.id))
      }
    }
  }

  async function ouvrir(id) {
    if (dossier?.id === id) return
    await sauverMaintenant()
    try {
      const pret = enAvance.get(id)
      enAvance.delete(id)
      dossier = pret && Date.now() - pret.le < 60000 ? await pret.promesse : await api.get(`/api/personnes/${id}`)
    } catch (e) {
      annoncer(e.message, true)
      dossier = null
      return
    }
    fiche = $state.snapshot(dossier.fiche)
    chargeLe = JSON.stringify(fiche)
    // Société absente : la proposition déduite des courriels pro est pré-remplie (en couleur)
    if (dossier.statut !== 'verifie' && !fiche.societe && dossier.societe_deduite) {
      fiche.societe = dossier.societe_deduite.valeur
    }
    actif = 0
    edition = null
    detailOuvert = false
    window.scrollTo?.({ top: 0 })
    precharger()
  }

  // Ouverture : l'identifiant de l'ancre, sinon le premier de la file
  // (seul l'identifiant de l'ancre déclenche ce chargement : le reste est lu sans suivi)
  $effect(() => {
    const id = route.id
    untrack(() => {
      ;(async () => {
        if (!file.length) await chargerFile()
        if (id) await ouvrir(id)
        else if (file.length) aller('revision', file[0].id)
        else dossier = null
      })()
    })
  })

  // Brouillon enregistré automatiquement, 0,8 s après la dernière modification
  $effect(() => {
    if (!fiche || !dossier) return
    const texte = JSON.stringify(fiche)
    if (texte === chargeLe) return
    clearTimeout(minuteur)
    minuteur = setTimeout(() => sauverMaintenant(), 800)
  })

  // Un seul enregistrement à la fois, dans l'ordre : la validation attend le brouillon parti avant elle
  let enVol = Promise.resolve()

  function sauverMaintenant(fermeture = false) {
    clearTimeout(minuteur)
    if (!fiche || !dossier) return enVol
    const texte = JSON.stringify(fiche)
    if (texte === chargeLe) return enVol
    const id = dossier.id
    enAvance.delete(id)
    const corps = { fiche: $state.snapshot(fiche), valider: false }
    enVol = enVol.then(async () => {
      try {
        await api.put(`/api/personnes/${id}`, corps, fermeture)
        chargeLe = texte // seulement après succès : un échec sera renvoyé à la prochaine modification
      } catch (e) {
        annoncer(`Brouillon non enregistré : ${e.message}`, true)
      }
    })
    return enVol
  }

  // ------------------------------------------------------------ colonnes et lignes

  const colonnes = $derived(
    dossier
      ? [...dossier.sources].sort((a, b) => a.enrichissement - b.enrichissement ||
          ORDRE.indexOf(a.source) - ORDRE.indexOf(b.source) || a.id - b.id)
      : [],
  )

  const lignes = $derived.by(() => {
    if (!dossier || !fiche) return []
    const res = []
    for (const s of SIMPLES) {
      const valeurs = colonnes.map((c) => (s.champ === 'photo' ? (c.a_photo ? c.id : null) : c.donnees[s.champ] || ''))
        // une note faite seulement de symboles (« ***** ») compte pour vide
        .map((v) => (s.champ === 'notes' && !/[\p{L}\p{N}]/u.test(v) ? '' : v))
      const utile = valeurs.some(Boolean) || (fiche[s.champ] ?? '') !== '' && fiche[s.champ] !== null
      if (s.toujours || utile || tousLesChamps) res.push({ type: 'simple', cle: s.champ, ...s, valeurs })
    }
    for (const m of MULTIPLES) {
      // Une ligne par valeur distincte. Les valeurs retenues gardent une clé liée à leur
      // position (la saisie ne fait pas sauter la ligne) ; les autres, une clé liée à la valeur.
      const items = new Map()
      fiche[m.champ].forEach((item, i) => {
        let k = CLES[m.champ](item)
        if (!k || items.has(k)) k = `saisie-${i}`
        items.set(k, { item, index: i, cle: `${m.champ}#${i}`, presence: colonnes.map(() => null) })
      })
      colonnes.forEach((c, ci) => {
        for (const item of c.donnees[m.champ] ?? []) {
          const k = CLES[m.champ](item)
          if (!items.has(k)) items.set(k, { item, index: -1, cle: `${m.champ}:${k}`, presence: colonnes.map(() => null) })
          items.get(k).presence[ci] = item
        }
      })
      if (!items.size) {
        res.push({ type: 'entete', cle: `entete-${m.champ}`, ...m, vide: true })
        continue
      }
      res.push({ type: 'entete', cle: `entete-${m.champ}`, ...m })
      for (const [k, v] of items) {
        res.push({ type: 'multiple', champ: m.champ, vcle: k, ...v, inclus: v.index >= 0 })
      }
    }
    return res
  })

  const navigables = $derived(lignes.filter((l) => l.type !== 'entete'))
  const vides = $derived(lignes.filter((l) => l.type === 'entete' && l.vide))
  const ligneActive = $derived(navigables[Math.min(actif, navigables.length - 1)])
  const position = $derived(dossier ? file.findIndex((p) => p.id === dossier.id) : -1)
  const raisons = $derived(dossier ? [...new Set(dossier.raisons.flatMap((r) => r.raisons))] : [])
  const profilLinkedin = $derived(fiche?.sites?.find((x) => x.type === 'linkedin'))

  // ------------------------------------------------------------ vue iPhone : une carte par champ

  // Valeurs distinctes d'un champ simple, avec les sources qui les donnent
  function options(l) {
    const res = new Map()
    l.valeurs.forEach((v, ci) => {
      if (!v) return
      const k = l.champ === 'photo' ? `p${v}` : String(v)
      if (!res.has(k)) res.set(k, { valeur: v, sources: [] })
      res.get(k).sources.push(colonnes[ci].libelle)
    })
    return [...res.values()]
  }
  const estChoisie = (l, v) => (l.champ === 'photo' ? fiche.photo === v : egal(fiche[l.champ], v))
  // Champ sans décision à prendre : une seule valeur (ou aucune) et c'est celle retenue
  function identique(l) {
    if (l.type !== 'simple') return false
    const o = options(l)
    if (o.length > 1) return false
    const v = o[0]?.valeur ?? (l.champ === 'photo' ? null : '')
    return l.champ === 'photo' ? (fiche.photo ?? null) === v : egal(fiche[l.champ], v)
  }
  const simplesAChoisir = $derived(lignes.filter((l) => l.type === 'simple' && !identique(l)))
  const simplesIdentiques = $derived(lignes.filter((l) => l.type === 'simple' && identique(l)))
  const multiples = $derived(MULTIPLES.map((m) => ({ ...m, items: lignes.filter((l) => l.type === 'multiple' && l.champ === m.champ) })))
  const sourcesDe = (l) => l.presence.map((p, ci) => (p ? colonnes[ci].libelle : null)).filter(Boolean)
  const indexDe = (l) => navigables.indexOf(l)

  // ------------------------------------------------------------ actions sur la fiche

  function choisir(ligne, valeur) {
    fiche[ligne.champ] = ligne.champ === 'photo' ? valeur : valeur ?? ''
  }

  async function basculer(ligne, colonne = null) {
    const liste = fiche[ligne.champ]
    const suivie = ligneActive?.cle === ligne.cle
    const vcle = CLES[ligne.champ](ligne.item)
    if (ligne.inclus) {
      liste.splice(ligne.index, 1)
    } else {
      const modele = (colonne !== null && ligne.presence[colonne]) || ligne.presence.find(Boolean) || ligne.item
      liste.push(structuredClone($state.snapshot(modele)))
    }
    // La ligne change de place (retenues d'abord) : la sélection la suit
    if (suivie) {
      await tick()
      const i = navigables.findIndex((l) => l.type === 'multiple' && l.champ === ligne.champ && l.vcle === vcle)
      if (i >= 0) actif = i
    }
  }

  function changerType(ligne, type) {
    const i = ligne.inclus ? ligne.index : fiche[ligne.champ].length
    if (!ligne.inclus) basculer(ligne)
    fiche[ligne.champ][i].type = type
  }

  function typeSuivant(ligne) {
    const types = ref.types[ligne.champ]
    const actuel = ligne.inclus ? fiche[ligne.champ][ligne.index].type : ligne.item.type
    changerType(ligne, types[(types.indexOf(actuel) + 1) % types.length])
  }

  function ajouter(champ) {
    const vide = champ === 'adresses'
      ? { rue: '', cp: '', ville: '', region: '', pays: 'France', type: 'domicile' }
      : { valeur: '', type: ref.types[champ][0] }
    fiche[champ].push(vide)
    tick().then(() => {
      const i = navigables.findIndex((l) => l.type === 'multiple' && l.champ === champ && l.index === fiche[champ].length - 1)
      if (i >= 0) editer(i)
    })
  }

  // Règles de type par groupe (intégrés et créés, voir ref.regles) :
  // « travail » (Artisans, Collègues, Clients…) : portable → travail, fixe → bureau
  // « proches » (Famille, Amis, Jardin secret…) : un seul portable → mobile (prioritaire)
  const avecRegle = (regle) => fiche.groupes.some((g) => ref.regles?.[g] === regle)
  function regleProches() {
    const pros = avecRegle('travail')
    if (pros) {
      for (const t of fiche.telephones) {
        if (t.nature) t.type = t.nature === 'mobile' ? 'travail' : 'bureau'
      }
    }
    // Clients : les adresses sont celles du travail
    if (fiche.groupes.includes('Clients')) for (const a of fiche.adresses) a.type = 'travail'
    // Fiche d'entreprise (société sans prénom ni nom) : standard « principal », portable « travail »
    if (pros && fiche.societe && !fiche.prenom && !fiche.nom) {
      for (const t of fiche.telephones) t.type = t.nature === 'mobile' ? 'travail' : 'principal'
    }
    if (!avecRegle('proches')) return
    // un seul portable : mobile ; deux ou plus : la Revue demande lequel est celui du travail
    const portables = fiche.telephones.filter((t) => t.nature === 'mobile')
    if (portables.length === 1) portables[0].type = 'mobile'
  }

  function basculerGroupe(groupe) {
    const g = fiche.groupes
    const i = g.indexOf(groupe)
    if (i >= 0) g.splice(i, 1)
    else {
      g.push(groupe)
    }
    regleProches()
  }

  async function editer(i = actif) {
    const ligne = navigables[i]
    if (!ligne || ligne.champ === 'photo') return
    actif = i
    if (ligne.type === 'multiple' && !ligne.inclus) {
      await basculer(ligne)
      await tick()
    }
    edition = ligneActive?.cle ?? ligne.cle
    await tick()
    document.querySelector('[data-edition] input:not([type=checkbox]), [data-edition] textarea')?.focus()
  }

  // ------------------------------------------------------------ dossier entier

  async function valider() {
    if (occupe || !dossier) return
    occupe = true
    clearTimeout(minuteur)
    try {
      await enVol
      const valide = { id: dossier.id, nom: [fiche.prenom, fiche.nom].filter(Boolean).join(' ') || fiche.societe || 'Contact' }
      await api.put(`/api/personnes/${dossier.id}`, { fiche, valider: true })
      chargeLe = JSON.stringify(fiche)
      enAvance.delete(valide.id)
      const pos = position
      await chargerFile()
      annoncer(`${valide.nom} vérifié.`, false, { libelle: 'Rouvrir', faire: () => aller('revision', valide.id) })
      const suivant = file[Math.max(0, Math.min(pos < 0 ? 0 : pos, file.length - 1))]
      if (suivant) aller('revision', suivant.id)
      else { dossier = null; aller('revision') }
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }

  // Mettre de côté : le contact quitte la file, l'export et le kit ; un nouvel import ne le ramène pas
  async function ecarter() {
    if (occupe || !dossier) return
    occupe = true
    clearTimeout(minuteur)
    try {
      await enVol
      const nom = [fiche.prenom, fiche.nom].filter(Boolean).join(' ') || fiche.societe || 'Ce contact'
      await api.post(`/api/personnes/${dossier.id}/ecarter`)
      chargeLe = JSON.stringify(fiche)
      const pos = position
      await chargerFile()
      annoncer(`${nom} est mis de côté. Tu le retrouves dans Contacts, filtre « Mis de côté ».`)
      const suivant = file[Math.max(0, Math.min(pos < 0 ? 0 : pos, file.length - 1))]
      if (suivant) aller('revision', suivant.id)
      else { dossier = null; aller('revision') }
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }

  async function restaurer() {
    try {
      dossier = await api.post(`/api/personnes/${dossier.id}/restaurer`)
      await chargerFile()
      annoncer('Contact remis en révision.')
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  function deplacer(sens) {
    if (!file.length) return
    const pos = position < 0 ? (sens > 0 ? -1 : 0) : position
    const cible = file[(pos + sens + file.length) % file.length]
    if (cible) aller('revision', cible.id)
  }

  async function detacher(colonne) {
    await sauverMaintenant()
    try {
      const r = await api.post(`/api/personnes/${dossier.id}/detacher`, { source_id: colonne.id })
      dossier = r.dossier
      fiche = $state.snapshot(r.dossier.fiche)
      chargeLe = JSON.stringify(fiche)
      await chargerFile()
      annoncer(colonne.enrichissement
        ? 'Fiche LinkedIn retirée de ce contact.'
        : `Fiche ${colonne.libelle} séparée : elle forme maintenant un contact à part dans la file.`)
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  async function fusionner(autre) {
    fusionOuverte = false
    await sauverMaintenant()
    try {
      dossier = await api.post(`/api/personnes/${dossier.id}/fusionner`, { autre: autre.id })
      fiche = $state.snapshot(dossier.fiche)
      chargeLe = JSON.stringify(fiche)
      await chargerFile()
      annoncer(`${autre.nom} a été fusionné dans ce contact.`)
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  async function repartir() {
    try {
      dossier = await api.post(`/api/personnes/${dossier.id}/repartir`)
      fiche = $state.snapshot(dossier.fiche)
      chargeLe = JSON.stringify(fiche)
      annoncer('Fiche remise à la proposition automatique.')
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  // ------------------------------------------------------------ clavier

  function clavier(e) {
    if (!dossier || fusionOuverte || e.ctrlKey || e.metaKey || e.altKey) return
    const cible = e.target
    const saisie = cible.closest?.('input:not([type=checkbox]), textarea, select')
    if (saisie) {
      if (e.key === 'Escape' || (e.key === 'Enter' && cible.tagName === 'INPUT')) {
        e.preventDefault()
        edition = null
        cible.blur()
      }
      return
    }
    if (aideOuverte && e.key === 'Escape') return (aideOuverte = false)
    const ligne = ligneActive
    const k = e.key
    let traite = true
    if (k === 'ArrowDown') actif = Math.min(actif + 1, navigables.length - 1)
    else if (k === 'ArrowUp') actif = Math.max(actif - 1, 0)
    else if (k === 'ArrowRight') deplacer(1)
    else if (k === 'ArrowLeft') deplacer(-1)
    else if (k === 'Enter') valider()
    else if (k === 'e') editer()
    else if (k === '?') aideOuverte = !aideOuverte
    else if (k === 'm') fusionOuverte = true
    else if (k === 'x') ecarter()
    else if (k in RACCOURCIS_GROUPES) basculerGroupe(RACCOURCIS_GROUPES[k])
    else if (/^[1-9]$/.test(k) && ligne) {
      const c = Number(k) - 1
      if (c >= colonnes.length) traite = false
      else if (ligne.type === 'simple') choisir(ligne, ligne.valeurs[c] || (ligne.champ === 'photo' ? null : ''))
      else if (ligne.presence[c] || ligne.inclus) basculer(ligne, c)
    } else if ((k === '0' || k === 'Backspace' || k === 'Delete') && ligne) {
      if (ligne.type === 'simple') choisir(ligne, ligne.champ === 'photo' ? null : '')
      else if (ligne.inclus) basculer(ligne)
    } else if (k === ' ' && ligne?.type === 'multiple') basculer(ligne)
    else if (k === 'y' && ligne?.type === 'multiple') typeSuivant(ligne)
    else traite = false
    if (traite) e.preventDefault()
  }

  $effect(() => {
    // garde la ligne active visible
    const cle = ligneActive?.cle
    if (cle) document.querySelector(`[data-ligne="${CSS.escape(cle)}"]`)?.scrollIntoView({ block: 'nearest' })
  })

  // La société retenue est-elle la proposition déduite (et pas une valeur venue d'une source) ?
  function estDeduite(l) {
    const d = dossier?.societe_deduite?.valeur
    return !!d && fiche.societe === d && !l.valeurs.includes(d)
  }

  function egal(a, b) {
    return (a ?? '') === (b ?? '')
  }
  function affichage(champ, v) {
    return champ === 'anniversaire' ? anniversaireLisible(v) : v
  }
</script>

<svelte:window onkeydown={clavier} onbeforeunload={() => sauverMaintenant(true)} />

{#if !dossier || !fiche}
  <div class="max-w-xl mx-auto text-center py-24">
    <h1 class="titre text-2xl md:text-3xl mb-3">Rien à relire</h1>
    <p class="text-mine mb-6">Toutes les fiches sont vérifiées. La synchro de nuit les écrit dans iCloud.</p>
    <div class="flex justify-center gap-3">
      <a class="bouton" href="#/accueil">À traiter</a>
      <a class="bouton" href="#/importer">Importer un export</a>
    </div>
  </div>
{:else if mobile}
  <!-- Vue iPhone : la fiche retenue en haut, un choix par carte, les actions en bas au pouce -->
  <div class="-mt-2">
    <div class="flex items-center gap-2 mb-2 text-sm">
      <a href="#/accueil" class="min-h-11 flex items-center text-onglet">‹ À traiter</a>
      <span class="flex-1 text-center text-mine tabular-nums">{#if position >= 0}Fiche {position + 1} / {file.length}{:else}{dossier.statut === 'verifie' ? 'Déjà vérifiée' : 'Hors file'}{/if}</span>
      <button class="min-h-11 px-2 text-mine" onclick={() => deplacer(-1)} aria-label="Fiche précédente">‹ Préc.</button>
    </div>

    <section class="rounded-2xl border border-onglet/50 bg-retenue p-4 mb-3" aria-label="Fiche retenue">
      <div class="flex items-center gap-3">
        <span class="relative w-14 h-14 shrink-0 rounded-full overflow-hidden bg-couture grid place-items-center text-mine text-lg">
          {(fiche.prenom || fiche.nom || fiche.societe || '?')[0]}
          {#if fiche.photo}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/photos/${fiche.photo}?taille=112`} alt=""
            onerror={(e) => e.currentTarget.remove()} />{/if}
        </span>
        <div class="min-w-0">
          <h1 class="titre text-2xl leading-tight break-words">{[fiche.prenom, fiche.nom].filter(Boolean).join(' ') || fiche.societe || '(sans nom)'}</h1>
          <p class="text-sm text-mine truncate">{[fiche.societe && (fiche.prenom || fiche.nom) ? fiche.societe : null, colonnes.map((c) => c.libelle).join(' + ')].filter(Boolean).join(' · ')}</p>
        </div>
      </div>
      {#if dossier.a_revoir || raisons.length || dossier.statut === 'ecarte'}
        <div class="flex flex-wrap gap-1.5 mt-3">
          {#if dossier.statut === 'ecarte'}<span class="text-xs rounded-full border border-alerte/60 text-alerte px-2 py-0.5">Mis de côté</span>{/if}
          {#if dossier.a_revoir}<span class="text-xs rounded-full border border-onglet/60 text-onglet px-2 py-0.5">{dossier.a_revoir}</span>{/if}
          {#each raisons as r}<span class="text-xs rounded-full bg-couture text-mine px-2 py-0.5">{r}</span>{/each}
        </div>
      {/if}
    </section>

    {#key dossier.id}<Proches pid={dossier.id} bind:fiche reunir={fusionner} />{/key}

    {#each simplesAChoisir as l (l.cle)}
      <section class="rounded-2xl border border-couture bg-reliure p-3 mb-3" aria-label={l.libelle}>
        <div class="flex items-center mb-2">
          <h2 class="flex-1 text-sm text-mine">{l.libelle}</h2>
          {#if l.champ !== 'photo'}
            <button class="min-h-11 px-2 text-sm text-onglet" onclick={() => (edition = edition === l.cle ? null : l.cle)}>{edition === l.cle ? 'OK' : 'Modifier'}</button>
          {/if}
        </div>
        {#if edition === l.cle}
          <div data-edition>
            {#if l.champ === 'notes'}
              <textarea rows="4" class="w-full" bind:value={fiche.notes}></textarea>
            {:else}
              <input class="w-full h-11" bind:value={fiche[l.champ]} placeholder={l.champ === 'anniversaire' ? '15/03/1985 ou 15 mars' : ''} />
            {/if}
          </div>
        {:else}
          <div class="grid gap-2" role="radiogroup" aria-label={l.libelle}>
            {#each options(l) as o}
              {@const oui = estChoisie(l, o.valeur)}
              <button role="radio" aria-checked={oui} onclick={() => choisir(l, o.valeur)}
                class="flex items-center gap-3 min-h-12 px-3 py-2 rounded-xl border text-left {oui ? 'border-onglet bg-onglet/15' : 'border-couture'}">
                <span class="w-5 h-5 shrink-0 rounded-full border-2 grid place-items-center {oui ? 'border-onglet' : 'border-champ'}">
                  {#if oui}<span class="w-2.5 h-2.5 rounded-full bg-onglet"></span>{/if}</span>
                {#if l.champ === 'photo'}
                  <img class="w-12 h-12 rounded-full object-cover bg-couture" src={`/api/photos/${o.valeur}?taille=96`} alt="" onerror={(e) => e.currentTarget.remove()} />
                {:else}
                  <span class="flex-1 min-w-0 break-words {l.champ === 'notes' ? 'whitespace-pre-line line-clamp-4' : ''}">{affichage(l.champ, o.valeur)}</span>
                {/if}
                <span class="shrink-0 ml-auto text-xs text-mine text-right">{o.sources.join(', ')}</span>
              </button>
            {/each}
            {#if l.champ !== 'photo' && fiche[l.champ] && !options(l).some((o) => estChoisie(l, o.valeur))}
              <p class="px-3 text-sm text-papier">Saisi : {affichage(l.champ, fiche[l.champ])}</p>
            {/if}
            <button role="radio" aria-checked={l.champ === 'photo' ? !fiche.photo : !fiche[l.champ]}
              onclick={() => choisir(l, l.champ === 'photo' ? null : '')}
              class="min-h-11 px-3 rounded-xl text-left text-sm {(l.champ === 'photo' ? !fiche.photo : !fiche[l.champ]) ? 'text-onglet' : 'text-mine'}">
              {l.champ === 'photo' ? 'Aucune photo' : 'Laisser vide'}</button>
          </div>
        {/if}
      </section>
    {/each}

    {#if simplesIdentiques.length}
      <section class="rounded-2xl border border-couture bg-reliure mb-3">
        <button class="w-full min-h-12 px-3 flex items-center gap-2 text-left text-sm" aria-expanded={detailOuvert} onclick={() => (detailOuvert = !detailOuvert)}>
          <span class="flex-1 text-mine">{simplesIdentiques.length} champ{simplesIdentiques.length > 1 ? 's' : ''} sans choix à faire</span>
          <span class="text-mine">{detailOuvert ? '▾' : '▸'}</span>
        </button>
        {#if detailOuvert}
          <ul class="divide-y divide-couture border-t border-couture">
            {#each simplesIdentiques as l (l.cle)}
              <li class="px-3 py-2">
                {#if edition === l.cle}
                  <div data-edition class="flex gap-2 items-center">
                    <span class="w-24 shrink-0 text-xs text-mine">{l.libelle}</span>
                    {#if l.champ === 'notes'}<textarea rows="3" class="flex-1" bind:value={fiche.notes}></textarea>
                    {:else}<input class="flex-1 h-11" bind:value={fiche[l.champ]} />{/if}
                    <button class="min-h-11 px-2 text-sm text-onglet" onclick={() => (edition = null)}>OK</button>
                  </div>
                {:else}
                  <button class="w-full flex gap-2 items-baseline text-left min-h-11" disabled={l.champ === 'photo'} onclick={() => (edition = l.cle)}>
                    <span class="w-24 shrink-0 text-xs text-mine">{l.libelle}</span>
                    <span class="flex-1 min-w-0 break-words {fiche[l.champ] ? 'text-papier' : 'text-mine/70 italic'}">
                      {l.champ === 'photo' ? (fiche.photo ? 'photo retenue' : 'aucune') : fiche[l.champ] ? affichage(l.champ, fiche[l.champ]) : 'vide'}</span>
                  </button>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#each multiples as m (m.champ)}
      <section class="rounded-2xl border border-couture bg-reliure p-3 mb-3" aria-label={m.libelle}>
        <div class="flex items-center mb-1">
          <h2 class="flex-1 text-sm text-mine">{m.libelle}</h2>
          <button class="min-h-11 px-2 text-sm text-onglet" onclick={() => ajouter(m.champ)}>Ajouter</button>
        </div>
        {#if !m.items.length}<p class="text-sm text-mine/70 pb-1">Aucun{m.champ === 'adresses' ? 'e' : ''} {m.unite}.</p>{/if}
        <ul class="grid gap-2">
          {#each m.items as l (l.cle)}
            {@const item = l.inclus ? fiche[l.champ][l.index] : l.item}
            <li class="rounded-xl border {l.inclus ? 'border-onglet/60' : 'border-couture'} p-2">
              <div class="flex items-start gap-3">
                <input type="checkbox" class="mt-2.5 shrink-0 accent-[#d9a441]" checked={l.inclus} onchange={() => basculer(l)}
                  aria-label={`Garder ${texteItem(l.champ, item) || m.unite}`} />
                <div class="flex-1 min-w-0">
                  {#if edition === l.cle && l.inclus}
                    <div data-edition class="grid gap-1.5">
                      {#if l.champ === 'adresses'}
                        <textarea rows="2" class="w-full" placeholder="Rue" bind:value={item.rue}></textarea>
                        <div class="flex gap-1.5"><input class="w-24 h-11" placeholder="CP" bind:value={item.cp} /><input class="flex-1 min-w-0 h-11" placeholder="Ville" bind:value={item.ville} /></div>
                        <input class="w-full h-11" placeholder="Pays" bind:value={item.pays} />
                      {:else}
                        <input class="w-full h-11" bind:value={item.valeur}
                          oninput={() => { if (l.champ === 'telephones') { item.affichage = item.valeur; item.valide = true } }} />
                      {/if}
                      <button class="justify-self-start min-h-11 text-sm text-onglet" onclick={() => (edition = null)}>OK</button>
                    </div>
                  {:else}
                    <button class="w-full text-left min-h-11 py-1.5 break-words {l.inclus ? 'text-papier' : 'text-mine/70 line-through decoration-mine'}"
                      onclick={() => (l.inclus ? (edition = l.cle) : basculer(l))}>{texteItem(l.champ, item) || '…'}</button>
                  {/if}
                  <p class="text-xs text-mine">{sourcesDe(l).join(', ') || 'saisi'}{item?.valide === false ? ' · non reconnu' : ''}</p>
                </div>
                <select class="shrink-0 w-28 h-11 !px-2 text-sm" value={item.type} onchange={(e) => changerType(l, e.currentTarget.value)} aria-label="Type">
                  {#each ref.types[l.champ] ?? [] as t}<option value={t}>{t}</option>{/each}
                </select>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/each}

    <section class="rounded-2xl border border-couture bg-reliure p-3 mb-3" aria-label="Groupes">
      <h2 class="text-sm text-mine mb-2">Groupes</h2>
      <div class="flex flex-wrap gap-1.5">
        {#each fiche.groupes.filter((g) => !ref.groupes.includes(g)) as ancien}
          <button class="pastille !border-dashed !border-onglet !text-onglet" onclick={() => basculerGroupe(ancien)}>{ancien} (à classer) ×</button>
        {/each}
        {#each ref.groupes as g}
          <button class="pastille" aria-pressed={fiche.groupes.includes(g)} onclick={() => basculerGroupe(g)}>{g}</button>
        {/each}
      </div>
    </section>

    <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-mine mb-2">
      <button class="min-h-11 underline underline-offset-2" onclick={() => (fusionOuverte = true)}>Fusionner avec un autre contact…</button>
      <button class="min-h-11 underline underline-offset-2" onclick={repartir}>Revenir à la proposition automatique</button>
      {#each colonnes.filter((c) => colonnes.filter((x) => !x.enrichissement).length > 1 || c.enrichissement) as c}
        <button class="min-h-11 underline underline-offset-2 hover:text-alerte" onclick={() => detacher(c)}>Séparer la fiche {c.libelle}</button>
      {/each}
    </div>
  </div>

  <!-- Barre d'actions au pouce, toujours visible -->
  <div class="fixed inset-x-0 bottom-0 z-30 border-t border-couture bg-reliure/95 backdrop-blur-md px-3 pt-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))]">
    <div class="grid grid-cols-[1fr_1fr_1.6fr] gap-2">
      <button class="h-14 rounded-xl border border-couture text-papier" onclick={() => deplacer(1)}>Passer</button>
      {#if dossier.statut === 'ecarte'}
        <button class="h-14 rounded-xl border border-couture text-papier" onclick={restaurer}>Remettre</button>
      {:else}
        <button class="h-14 rounded-xl border border-couture text-papier disabled:opacity-50" disabled={occupe} onclick={ecarter}>De côté</button>
      {/if}
      <button class="h-14 rounded-xl bg-onglet text-onglet-sombre font-semibold disabled:opacity-50" disabled={occupe} onclick={valider}>Valider</button>
    </div>
  </div>
  {#if fusionOuverte}<Fusion exclure={dossier.id} choisir={fusionner} fermer={() => (fusionOuverte = false)} />{/if}
{:else}
  <!-- En-tête et boutons restent en haut de l'écran : Valider est toujours à portée -->
  <div class="sticky top-0 z-10 -mx-6 px-6 pt-2 pb-2 mb-3 bg-cuir/95 backdrop-blur-md flex flex-wrap items-end gap-x-6 gap-y-2">
    <div>
      <p class="text-sm text-mine tabular-nums">
        {#if position >= 0}Fiche {position + 1} sur {file.length} à relire{:else}Contact {dossier.statut === 'verifie' ? 'déjà vérifié' : 'hors file'}{/if}
      </p>
      <h1 class="titre text-2xl leading-tight">
        {[fiche.prenom, fiche.nom].filter(Boolean).join(' ') || fiche.societe || '(sans nom)'}
      </h1>
    </div>
    <div class="flex flex-wrap gap-2 pb-1">
      {#if dossier.statut === 'verifie'}
        <span class="text-sm rounded-full border border-valide/50 text-valide px-2.5 py-0.5">Vérifié le {dateCourte(dossier.verifie_le)}</span>
      {/if}
      {#if dossier.statut === 'ecarte'}
        <span class="text-sm rounded-full border border-alerte/60 text-alerte px-2.5 py-0.5">Mis de côté : ni exporté, ni renvoyé</span>
      {/if}
      {#if dossier.statut === 'verifie' && dossier.brouillon}
        <span class="text-sm rounded-full border border-onglet/60 text-onglet px-2.5 py-0.5">Modifications pas encore validées : l'export garde l'ancienne version</span>
      {/if}
      {#if dossier.a_revoir}
        <span class="text-sm rounded-full border border-onglet/60 text-onglet px-2.5 py-0.5">À revoir : {dossier.a_revoir}</span>
      {/if}
      {#each raisons as r}
        <span class="text-sm rounded-full bg-couture text-mine px-2.5 py-0.5">{r}</span>
      {/each}
      {#if profilLinkedin}
        <a class="text-sm rounded-full border border-valide/60 bg-valide/15 text-valide px-2.5 py-0.5" href={profilLinkedin.valeur.startsWith('http') ? profilLinkedin.valeur : `https://${profilLinkedin.valeur}`}
          target="_blank" rel="noopener noreferrer" title="Profil LinkedIn de la fiche">LinkedIn ✓</a>
      {:else}
        <a class="text-sm rounded-full border border-couture text-mine hover:text-papier px-2.5 py-0.5"
          href={rechercheLinkedin([fiche.prenom, fiche.nom].filter(Boolean).join(' '), fiche.societe)} target="_blank" rel="noopener noreferrer"
          title="Chercher sur LinkedIn ; colle ensuite l'adresse du profil dans « Ajouter : site »">Chercher sur LinkedIn</a>
      {/if}
    </div>
    <div class="ml-auto flex flex-wrap gap-2">
      <button class="bouton" onclick={() => deplacer(-1)} title="Précédent (←)">Précédent</button>
      <button class="bouton" onclick={() => deplacer(1)} title="Passer (→)">Passer</button>
      {#if dossier.statut === 'ecarte'}
        <button class="bouton" onclick={restaurer}>Remettre en révision</button>
      {:else}
        <button class="bouton hover:!border-alerte hover:text-alerte" onclick={ecarter} disabled={occupe}
          title="Le contact ne sera ni exporté ni renvoyé, même après un nouvel import (X)">Mettre de côté</button>
      {/if}
      <button class="bouton bouton-principal" onclick={valider} disabled={occupe} title="Valider (Entrée)">
        Valider la fiche
      </button>
    </div>
  </div>

  {#key dossier.id}<Proches pid={dossier.id} bind:fiche reunir={fusionner} />{/key}

  <!-- Tableau à largeur fixe : tout tient à l'écran, les valeurs trop longues sont raccourcies
       (le texte complet s'affiche au survol). Sur un écran étroit (vue PC sur iPhone), il garde
       une largeur lisible et défile de côté au doigt. -->
  <div class="rounded-xl border border-couture {ecran.etroit ? 'overflow-x-auto overscroll-x-contain' : 'overflow-hidden'}" data-defile>
    <table class="w-full table-fixed border-collapse text-sm"
      style={ecran.etroit ? `min-width: ${7 + colonnes.length * 9 + 20}rem` : undefined}>
      <colgroup>
        <col class="w-28" />
        {#each colonnes as c (c.id)}<col />{/each}
        <col class="w-[36%]" />
      </colgroup>
      <thead>
        <tr class="bg-reliure">
          <th class="text-left font-normal text-mine px-3 py-2 align-bottom">Champ</th>
          {#each colonnes as c, ci (c.id)}
            <th class="text-left font-normal px-3 py-2 align-bottom border-l border-couture">
              <span class="flex items-center gap-1.5 min-w-0">
                <kbd>{ci + 1}</kbd>
                <span class="font-medium text-papier truncate">{c.libelle}</span>
                {#if c.enrichissement}<span class="text-xs text-mine">complément</span>{/if}
              </span>
              <span class="flex items-center gap-2 text-xs text-mine mt-0.5 min-w-0">
                <span class="truncate" title={`${c.fichier}, ${dateCourte(c.importe_le)}`}>{c.fichier}</span>
                {#if colonnes.filter((x) => !x.enrichissement).length > 1 || c.enrichissement}
                  <button class="shrink-0 ml-auto hover:text-alerte underline underline-offset-2"
                    onclick={() => detacher(c)}>Pas la même personne</button>
                {/if}
              </span>
            </th>
          {/each}
          <th class="text-left px-3 py-2 align-bottom bg-retenue text-papier">
            <span class="titre text-base">Fiche retenue</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {#each lignes as l (l.cle)}
          {#if l.type === 'entete'}
            {#if !l.vide}
              <tr class="border-t border-couture">
                <td class="px-3 pt-2 pb-0.5 text-xs text-mine" colspan={colonnes.length + 1}>{l.libelle}</td>
                <td class="px-3 pt-2 pb-0.5 bg-retenue text-right">
                  <button class="text-xs text-mine hover:text-papier underline underline-offset-2"
                    onclick={() => ajouter(l.champ)}>Ajouter</button>
                </td>
              </tr>
            {/if}
          {:else}
            {@const i = navigables.indexOf(l)}
            {@const estActive = ligneActive?.cle === l.cle}
            <tr data-ligne={l.cle} class="border-t border-couture/60 {estActive ? 'bg-onglet-sombre/35' : ''}"
              onclick={() => (actif = i)}>
              <td class="px-3 py-1 text-mine align-top relative truncate">
                {#if estActive}<span class="absolute left-0 top-1 bottom-1 w-1 rounded-r bg-onglet"></span>{/if}
                {l.type === 'simple' ? l.libelle : ''}
              </td>

              {#if l.type === 'simple'}
                {#each l.valeurs as v, ci}
                  {@const choisie = v && (l.champ === 'photo' ? fiche.photo === v : egal(fiche[l.champ], v))}
                  <td class="px-1.5 py-0.5 border-l border-couture/60 align-top">
                    {#if v}
                      <button class="w-full min-w-0 text-left rounded-md px-1.5 py-0.5 border transition-colors
                          {choisie ? 'bg-onglet/15 border-onglet text-papier' : 'border-transparent text-mine hover:text-papier hover:border-tranche'}"
                        title={l.champ === 'photo' ? undefined : affichage(l.champ, v)}
                        onclick={(e) => { e.stopPropagation(); actif = i; choisir(l, v) }}>
                        {#if l.champ === 'photo'}
                          <img src={`/api/photos/${v}?taille=72`} alt="" class="w-9 h-9 rounded-full object-cover bg-couture"
                            onerror={(e) => e.currentTarget.replaceWith(Object.assign(document.createElement('span'), { className: 'text-xs text-mine', textContent: 'photo illisible' }))} />
                        {:else}
                          <span class="block {l.champ === 'notes' ? 'line-clamp-2 whitespace-pre-line break-words' : 'truncate'}">{affichage(l.champ, v)}</span>
                        {/if}
                      </button>
                    {/if}
                  </td>
                {/each}
                <td class="px-3 py-0.5 bg-retenue text-papier align-top" data-edition={edition === l.cle ? '' : undefined}>
                  {#if edition === l.cle}
                    {#if l.champ === 'notes'}
                      <textarea rows="3" class="w-full resize-none !bg-cuir !text-papier !border-champ" bind:value={fiche.notes}
                        onblur={() => (edition = null)}></textarea>
                    {:else}
                      <input class="w-full !py-0.5 !bg-cuir !text-papier !border-champ" bind:value={fiche[l.champ]}
                        placeholder={l.champ === 'anniversaire' ? '15/03/1985 ou 15 mars' : ''}
                        onblur={() => (edition = null)} />
                    {/if}
                  {:else if l.champ === 'photo'}
                    {#if fiche.photo}<img src={`/api/photos/${fiche.photo}?taille=72`} alt="" class="w-9 h-9 rounded-full object-cover bg-couture"
                      onerror={(e) => e.currentTarget.replaceWith(Object.assign(document.createElement('span'), { className: 'text-xs text-mine', textContent: 'photo illisible' }))} />{:else}<span class="text-mine/70 italic">aucune</span>{/if}
                  {:else if l.champ === 'societe' && estDeduite(l)}
                    <!-- Proposition déduite de l'adresse e-mail : fond ocre jusqu'à ce que tu la modifies -->
                    <button class="w-full min-w-0 flex items-baseline gap-2 text-left py-0.5"
                      ondblclick={() => editer(i)}
                      title={`Société ${dossier.societe_deduite.origine} : vérifie-la (E pour modifier, 0 pour vider)`}>
                      <span class="truncate rounded px-1.5 bg-onglet/20 border border-dashed border-onglet">{fiche.societe}</span>
                      <span class="shrink-0 text-xs text-onglet truncate">{dossier.societe_deduite.origine}</span>
                    </button>
                  {:else if l.champ === 'societe' && !fiche.societe && dossier.societe_deduite}
                    <button class="w-full min-w-0 text-left py-0.5 text-onglet"
                      onclick={() => (fiche.societe = dossier.societe_deduite.valeur)}
                      title={`Société ${dossier.societe_deduite.origine}`}>
                      <span class="rounded px-1.5 border border-dashed border-onglet">Proposer « {dossier.societe_deduite.valeur} »</span>
                    </button>
                  {:else}
                    <button class="w-full min-w-0 text-left py-0.5 {l.champ === 'nom' ? 'tracking-wide' : ''}"
                      ondblclick={() => editer(i)} title={fiche[l.champ] ? `${affichage(l.champ, fiche[l.champ])}\n(double-clic ou E pour modifier)` : 'Double-clic ou E pour modifier'}>
                      {#if fiche[l.champ]}
                        <span class="block {l.champ === 'notes' ? 'line-clamp-2 whitespace-pre-line break-words' : 'truncate'} {l.champ === 'prenom' || l.champ === 'nom' ? 'titre text-base' : ''}">{affichage(l.champ, fiche[l.champ])}</span>
                      {:else}<span class="text-mine/70 italic">vide</span>{/if}
                    </button>
                  {/if}
                </td>
              {:else}
                {#each l.presence as p}
                  <td class="px-3 py-1 border-l border-couture/60 align-top text-mine">
                    {#if p}
                      <span class="flex items-baseline gap-2 min-w-0" title={`${texteItem(l.champ, p)} (${p.type})`}>
                        <span class="truncate {l.inclus ? 'text-papier' : ''}">{texteItem(l.champ, p)}</span>
                        <span class="shrink-0 ml-auto text-xs">{p.valide === false ? 'non reconnu' : p.type}</span>
                      </span>
                    {/if}
                  </td>
                {/each}
                <td class="px-3 py-0.5 bg-retenue text-papier align-top" data-edition={edition === l.cle ? '' : undefined}>
                  <div class="flex items-center gap-2 min-w-0">
                    <input type="checkbox" class="accent-[#d9a441] w-4 h-4 shrink-0" checked={l.inclus}
                      onchange={() => basculer(l)} aria-label="Garder cette valeur" />
                    <div class="flex-1 min-w-0">
                      {#if edition === l.cle && l.inclus}
                        {@const item = fiche[l.champ][l.index]}
                        {#if l.champ === 'adresses'}
                          <div class="grid gap-1 py-1 w-full min-w-0">
                            <textarea rows="2" class="w-full min-w-0 resize-none !bg-cuir !text-papier !border-champ" placeholder="Rue (plusieurs lignes possibles)" bind:value={item.rue}></textarea>
                            <!-- une ligne par paire de champs : rien ne déborde sur le menu du type -->
                            <div class="flex gap-1 min-w-0">
                              <input size="5" class="w-20 shrink-0 !py-0.5 !bg-cuir !text-papier !border-champ" placeholder="CP" bind:value={item.cp} />
                              <input size="5" class="flex-1 min-w-0 !py-0.5 !bg-cuir !text-papier !border-champ" placeholder="Ville" bind:value={item.ville} />
                            </div>
                            <input size="5" class="w-full min-w-0 !py-0.5 !bg-cuir !text-papier !border-champ" placeholder="Pays" bind:value={item.pays}
                              onblur={() => (edition = null)} />
                          </div>
                        {:else}
                          <input class="w-full !py-0.5 !bg-cuir !text-papier !border-champ" bind:value={item.valeur}
                            oninput={() => { if (l.champ === 'telephones') { item.affichage = item.valeur; item.valide = true } }}
                            onblur={() => (edition = null)} />
                        {/if}
                      {:else}
                        {@const texte = texteItem(l.champ, l.inclus ? fiche[l.champ][l.index] : l.item) || '…'}
                        <button class="block w-full min-w-0 text-left truncate py-0.5 {l.inclus ? '' : 'text-mine/70 line-through decoration-mine'}"
                          title={texte} ondblclick={() => editer(i)}>{texte}</button>
                      {/if}
                    </div>
                    <select class="shrink-0 w-24 self-start mt-0.5 !py-0 !px-1 text-xs !bg-transparent !text-papier !border-champ"
                      value={l.inclus ? fiche[l.champ][l.index].type : l.item.type}
                      onchange={(e) => changerType(l, e.currentTarget.value)} aria-label="Type">
                      {#each ref.types[l.champ] ?? [] as t}<option value={t}>{t}</option>{/each}
                    </select>
                  </div>
                </td>
              {/if}
            </tr>
          {/if}
        {/each}

        {#if vides.length}
          <tr class="border-t border-couture">
            <td class="px-3 py-1.5 text-xs text-mine" colspan={colonnes.length + 1}>
              Aucune valeur : {vides.map((v) => v.libelle.toLowerCase()).join(', ')}
            </td>
            <td class="px-3 py-1.5 bg-retenue text-xs text-mine">
              Ajouter :
              {#each vides as v, k}
                <button class="underline underline-offset-2 hover:text-papier" onclick={() => ajouter(v.champ)}>{v.unite}</button>{k < vides.length - 1 ? ', ' : ''}
              {/each}
            </td>
          </tr>
        {/if}

        <tr class="border-t border-couture">
          <td class="px-3 py-2 text-mine align-top">Groupes</td>
          <td colspan={colonnes.length} class="px-3 py-2 text-xs text-mine align-top">
            {#each colonnes as c}
              {#if c.donnees.groupes?.length}<span class="mr-3">{c.libelle} : {c.donnees.groupes.join(', ')}</span>{/if}
            {/each}
          </td>
          <td class="px-3 py-2 bg-retenue">
            <div class="flex flex-wrap gap-1">
              {#each fiche.groupes.filter((g) => !ref.groupes.includes(g)) as ancien}
                <button class="text-xs rounded-full px-2 py-0.5 border border-dashed border-onglet text-onglet"
                  title="Ancien groupe : choisis Collègues ou Clients, puis clique ici pour le retirer"
                  onclick={() => basculerGroupe(ancien)}>{ancien} (à classer) ×</button>
              {/each}
              {#each ref.groupes as g}
                {@const dedans = fiche.groupes.includes(g)}
                <button class="text-xs rounded-full px-2 py-0.5 border transition-colors
                    {dedans ? 'bg-onglet text-onglet-sombre border-onglet' : 'border-couture text-mine hover:border-papier'}"
                  aria-pressed={dedans} onclick={() => basculerGroupe(g)}>
                  {g} <span class="opacity-60">{LETTRE_GROUPE[g]?.toUpperCase()}</span>
                </button>
              {/each}
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="flex flex-wrap items-center gap-4 mt-3 text-sm text-mine">
    <button class="hover:text-papier underline underline-offset-2" onclick={() => (tousLesChamps = !tousLesChamps)}>
      {tousLesChamps ? 'Masquer les champs vides' : 'Afficher tous les champs'}
    </button>
    <button class="hover:text-papier underline underline-offset-2" onclick={() => (fusionOuverte = true)}>Fusionner avec un autre contact…</button>
    <button class="hover:text-papier underline underline-offset-2" onclick={repartir}>Revenir à la proposition automatique</button>
    {#if dossier.statut === 'verifie'}
      <a class="hover:text-papier underline underline-offset-2" href={`/api/icloud/brute/${dossier.id}`} download>Fiche iCloud brute (.vcf)</a>
    {/if}
    <button class="ml-auto hover:text-papier" onclick={() => (aideOuverte = !aideOuverte)}><kbd>?</kbd> Raccourcis clavier</button>
  </div>

  {#if aideOuverte}<Aide fermer={() => (aideOuverte = false)} />{/if}
  {#if fusionOuverte}<Fusion exclure={dossier.id} choisir={fusionner} fermer={() => (fusionOuverte = false)} />{/if}
{/if}
