<script>
  import { tick, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { ref, statut, route, aller, annoncer } from '../lib/etat.svelte.js'
  import { CLES, texteItem, anniversaireLisible, dateCourte } from '../lib/cles.js'
  import Fusion from '../components/Fusion.svelte'
  import Aide from '../components/Aide.svelte'

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
  const RACCOURCIS_GROUPES = { u: 'Urgence', f: 'Famille', a: 'Amis', r: 'Artisans et services', t: 'Travail', j: 'Jardin secret' }
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
  let chargeLe = ''
  let minuteur = null

  async function chargerFile() {
    file = await api.get('/api/file')
    Object.assign(statut, await api.get('/api/statut'))
  }

  async function ouvrir(id) {
    await sauverMaintenant()
    try {
      dossier = await api.get(`/api/personnes/${id}`)
    } catch (e) {
      annoncer(e.message, true)
      dossier = null
      return
    }
    fiche = $state.snapshot(dossier.fiche)
    chargeLe = JSON.stringify(fiche)
    actif = 0
    edition = null
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
  const ligneActive = $derived(navigables[Math.min(actif, navigables.length - 1)])
  const position = $derived(dossier ? file.findIndex((p) => p.id === dossier.id) : -1)
  const raisons = $derived(dossier ? [...new Set(dossier.raisons.flatMap((r) => r.raisons))] : [])

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

  function basculerGroupe(groupe) {
    const g = fiche.groupes
    const i = g.indexOf(groupe)
    if (i >= 0) g.splice(i, 1)
    else g.push(groupe)
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
      await api.put(`/api/personnes/${dossier.id}`, { fiche, valider: true })
      chargeLe = JSON.stringify(fiche)
      const pos = position
      await chargerFile()
      annoncer('Contact vérifié.')
      const suivant = file[Math.max(0, Math.min(pos < 0 ? 0 : pos, file.length - 1))]
      if (suivant) aller('revision', suivant.id)
      else { dossier = null; aller('revision') }
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
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
    else if (k === 'c' && ligne?.type === 'multiple') typeSuivant(ligne)
    else traite = false
    if (traite) e.preventDefault()
  }

  $effect(() => {
    // garde la ligne active visible
    const cle = ligneActive?.cle
    if (cle) document.querySelector(`[data-ligne="${CSS.escape(cle)}"]`)?.scrollIntoView({ block: 'nearest' })
  })

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
    <h1 class="titre text-3xl mb-3">Rien à relire</h1>
    <p class="text-mine mb-6">Tous les contacts importés sont vérifiés. Importe un nouvel export ou passe à l'export.</p>
    <div class="flex justify-center gap-3">
      <a class="bouton" href="#/accueil">Importer</a>
      <a class="bouton bouton-principal" href="#/export">Exporter</a>
    </div>
  </div>
{:else}
  <div class="flex flex-wrap items-end gap-x-6 gap-y-3 mb-5">
    <div>
      <p class="text-sm text-mine tabular-nums">
        {#if position >= 0}Fiche {position + 1} sur {file.length} à relire{:else}Contact {dossier.statut === 'verifie' ? 'déjà vérifié' : 'hors file'}{/if}
      </p>
      <h1 class="titre text-3xl leading-tight">
        {[fiche.prenom, fiche.nom].filter(Boolean).join(' ') || fiche.societe || '(sans nom)'}
      </h1>
    </div>
    <div class="flex flex-wrap gap-2 pb-1">
      {#if dossier.statut === 'verifie'}
        <span class="text-sm rounded-full border border-valide/50 text-valide px-2.5 py-0.5">Vérifié le {dateCourte(dossier.verifie_le)}</span>
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
    </div>
    <div class="ml-auto flex gap-2">
      <button class="bouton" onclick={() => deplacer(-1)} title="Précédent (←)">Précédent</button>
      <button class="bouton" onclick={() => deplacer(1)} title="Passer (→)">Passer</button>
      <button class="bouton bouton-principal" onclick={valider} disabled={occupe} title="Valider (Entrée)">
        Valider la fiche
      </button>
    </div>
  </div>

  <div class="overflow-x-auto rounded-xl border border-couture">
    <table class="w-full border-collapse text-[0.93rem]">
      <thead>
        <tr class="bg-reliure">
          <th class="w-36 text-left font-normal text-mine text-sm px-4 py-3 align-bottom">Champ</th>
          {#each colonnes as c, ci (c.id)}
            <th class="text-left font-normal px-4 py-3 align-bottom border-l border-couture min-w-44">
              <span class="flex items-center gap-2">
                <kbd>{ci + 1}</kbd>
                <span class="font-medium text-papier">{c.libelle}</span>
                {#if c.enrichissement}<span class="text-xs text-mine">complément</span>{/if}
              </span>
              <span class="block text-xs text-mine mt-0.5 truncate" title={c.fichier}>{c.fichier}, {dateCourte(c.importe_le)}</span>
              {#if colonnes.filter((x) => !x.enrichissement).length > 1 || c.enrichissement}
                <button class="text-xs text-mine hover:text-alerte underline underline-offset-2 mt-1"
                  onclick={() => detacher(c)}>Pas la même personne</button>
              {/if}
            </th>
          {/each}
          <th class="text-left px-4 py-3 align-bottom min-w-72 bg-papier text-[#2a211c] rounded-tr-xl">
            <span class="titre text-lg">Fiche retenue</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {#each lignes as l (l.cle)}
          {#if l.type === 'entete'}
            <tr class="border-t border-couture">
              <td class="px-4 pt-4 pb-1.5 text-sm text-mine" colspan={colonnes.length + 1}>{l.libelle}{#if l.vide}<span class="ml-2 text-xs">aucun</span>{/if}</td>
              <td class="px-4 pt-4 pb-1.5 bg-papier text-right">
                <button class="text-xs text-[#6b5a48] hover:text-[#2a211c] underline underline-offset-2"
                  onclick={() => ajouter(l.champ)}>Ajouter un {l.unite}</button>
              </td>
            </tr>
          {:else}
            {@const i = navigables.indexOf(l)}
            {@const estActive = ligneActive?.cle === l.cle}
            <tr data-ligne={l.cle} class="border-t border-couture/60 {estActive ? 'bg-onglet-sombre/35' : ''}"
              onclick={() => (actif = i)}>
              <td class="px-4 py-2 text-sm text-mine align-top relative">
                {#if estActive}<span class="absolute left-0 top-1 bottom-1 w-1 rounded-r bg-onglet"></span>{/if}
                {l.type === 'simple' ? l.libelle : ''}
              </td>

              {#if l.type === 'simple'}
                {#each l.valeurs as v, ci}
                  {@const choisie = v && (l.champ === 'photo' ? fiche.photo === v : egal(fiche[l.champ], v))}
                  <td class="px-2 py-1 border-l border-couture/60 align-top">
                    {#if v}
                      <button class="w-full text-left rounded-md px-2 py-1 border transition-colors
                          {choisie ? 'border-onglet/70 text-papier' : 'border-transparent text-mine hover:text-papier hover:border-tranche'}"
                        onclick={(e) => { e.stopPropagation(); actif = i; choisir(l, v) }}>
                        {#if l.champ === 'photo'}
                          <img src={`/api/photos/${v}`} alt={`Photo ${colonnes[ci].libelle}`} class="w-12 h-12 rounded-full object-cover" />
                        {:else}
                          <span class="whitespace-pre-line break-words {l.champ === 'notes' ? 'line-clamp-3' : ''}">{affichage(l.champ, v)}</span>
                        {/if}
                      </button>
                    {/if}
                  </td>
                {/each}
                <td class="px-4 py-1.5 bg-papier text-[#2a211c] align-top" data-edition={edition === l.cle ? '' : undefined}>
                  {#if edition === l.cle}
                    {#if l.champ === 'notes'}
                      <textarea rows="4" class="w-full !bg-white !text-[#2a211c] !border-[#c9b9a3]" bind:value={fiche.notes}
                        onblur={() => (edition = null)}></textarea>
                    {:else}
                      <input class="w-full !bg-white !text-[#2a211c] !border-[#c9b9a3]" bind:value={fiche[l.champ]}
                        placeholder={l.champ === 'anniversaire' ? 'AAAA-MM-JJ ou --MM-JJ' : ''}
                        onblur={() => (edition = null)} />
                    {/if}
                  {:else if l.champ === 'photo'}
                    {#if fiche.photo}<img src={`/api/photos/${fiche.photo}`} alt="Retenue" class="w-12 h-12 rounded-full object-cover" />{:else}<span class="text-[#9a8a76] italic">aucune</span>{/if}
                  {:else}
                    <button class="w-full text-left min-h-7 {l.champ === 'nom' ? 'tracking-wide' : ''}"
                      ondblclick={() => editer(i)} title="Double-clic ou E pour modifier">
                      {#if fiche[l.champ]}
                        <span class="whitespace-pre-line break-words {l.champ === 'prenom' || l.champ === 'nom' ? 'titre text-lg' : ''}">{affichage(l.champ, fiche[l.champ])}</span>
                      {:else}<span class="text-[#9a8a76] italic">vide</span>{/if}
                    </button>
                  {/if}
                </td>
              {:else}
                {#each l.presence as p, ci}
                  <td class="px-4 py-1.5 border-l border-couture/60 align-top text-mine">
                    {#if p}
                      <span class="block break-words {l.inclus ? 'text-papier' : ''}">{texteItem(l.champ, p)}</span>
                      <span class="text-xs">{p.type}{p.valide === false ? ' · numéro non reconnu' : ''}</span>
                    {/if}
                  </td>
                {/each}
                <td class="px-4 py-1.5 bg-papier text-[#2a211c] align-top" data-edition={edition === l.cle ? '' : undefined}>
                  <div class="flex items-start gap-2.5">
                    <input type="checkbox" class="mt-1.5 accent-[#8a5a12] w-4 h-4 shrink-0" checked={l.inclus}
                      onchange={() => basculer(l)} aria-label="Garder cette valeur" />
                    <div class="flex-1 min-w-0">
                      {#if edition === l.cle && l.inclus}
                        {@const item = fiche[l.champ][l.index]}
                        {#if l.champ === 'adresses'}
                          <div class="grid gap-1.5">
                            <textarea rows="2" class="!bg-white !text-[#2a211c] !border-[#c9b9a3]" placeholder="Rue (plusieurs lignes possibles)" bind:value={item.rue}></textarea>
                            <div class="flex gap-1.5">
                              <input class="w-24 !bg-white !text-[#2a211c] !border-[#c9b9a3]" placeholder="Code postal" bind:value={item.cp} />
                              <input class="flex-1 !bg-white !text-[#2a211c] !border-[#c9b9a3]" placeholder="Ville" bind:value={item.ville} />
                            </div>
                            <input class="!bg-white !text-[#2a211c] !border-[#c9b9a3]" placeholder="Pays" bind:value={item.pays}
                              onblur={() => (edition = null)} />
                          </div>
                        {:else}
                          <input class="w-full !bg-white !text-[#2a211c] !border-[#c9b9a3]" bind:value={item.valeur}
                            oninput={() => { if (l.champ === 'telephones') { item.affichage = item.valeur; item.valide = true } }}
                            onblur={() => (edition = null)} />
                        {/if}
                      {:else}
                        <button class="block w-full text-left break-words {l.inclus ? '' : 'text-[#9a8a76] line-through decoration-[#b9a68f]'}"
                          ondblclick={() => editer(i)}>{texteItem(l.champ, l.inclus ? fiche[l.champ][l.index] : l.item) || '…'}</button>
                      {/if}
                    </div>
                    <select class="!py-0.5 !px-1.5 text-sm !bg-transparent !text-[#2a211c] !border-[#c9b9a3]"
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

        <tr class="border-t border-couture">
          <td class="px-4 py-3 text-sm text-mine align-top">Groupes</td>
          <td colspan={colonnes.length} class="px-4 py-3 text-sm text-mine align-top">
            {#each colonnes as c}
              {#if c.donnees.groupes?.length}<span class="mr-3">{c.libelle} : {c.donnees.groupes.join(', ')}</span>{/if}
            {/each}
          </td>
          <td class="px-4 py-3 bg-papier rounded-br-xl">
            <div class="flex flex-wrap gap-1.5">
              {#each ref.groupes as g}
                {@const dedans = fiche.groupes.includes(g)}
                <button class="text-sm rounded-full px-2.5 py-0.5 border transition-colors
                    {dedans ? 'bg-[#2a211c] text-papier border-[#2a211c]' : 'border-[#c9b9a3] text-[#6b5a48] hover:border-[#2a211c]'}"
                  aria-pressed={dedans} onclick={() => basculerGroupe(g)}>
                  {g} <span class="opacity-60 text-xs">{LETTRE_GROUPE[g]?.toUpperCase()}</span>
                </button>
              {/each}
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="flex flex-wrap items-center gap-4 mt-4 text-sm text-mine">
    <button class="hover:text-papier underline underline-offset-2" onclick={() => (tousLesChamps = !tousLesChamps)}>
      {tousLesChamps ? 'Masquer les champs vides' : 'Afficher tous les champs'}
    </button>
    <button class="hover:text-papier underline underline-offset-2" onclick={() => (fusionOuverte = true)}>Fusionner avec un autre contact…</button>
    <button class="hover:text-papier underline underline-offset-2" onclick={repartir}>Revenir à la proposition automatique</button>
    <button class="ml-auto hover:text-papier" onclick={() => (aideOuverte = !aideOuverte)}><kbd>?</kbd> Raccourcis clavier</button>
  </div>

  {#if aideOuverte}<Aide fermer={() => (aideOuverte = false)} />{/if}
  {#if fusionOuverte}<Fusion exclure={dossier.id} choisir={fusionner} fermer={() => (fusionOuverte = false)} />{/if}
{/if}
