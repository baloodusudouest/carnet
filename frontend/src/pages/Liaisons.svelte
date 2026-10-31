<script>
  import { onDestroy } from 'svelte'
  import { api } from '../lib/api.js'
  import { annoncer, ref } from '../lib/etat.svelte.js'
  import { dateCourte, pluriel, anniversaireLisible } from '../lib/cles.js'

  // Liaisons contact ↔ personne Immich (photo) ↔ personne Treemich (relations familiales).
  let donnees = $state(null)
  let choix = $state({})        // pid → id Immich choisi parmi les candidats
  let tache = $state(null)
  let filtre = $state('')
  let minuteur = null

  const enCours = $derived(['lecture', 'ecriture'].includes(tache?.etat))
  const exactes = $derived(donnees ? donnees.propositions.filter((p) => p.exacte) : [])
  const liees = $derived(donnees ? donnees.liees.filter((p) => !filtre || p.nom.toLowerCase().includes(filtre.toLowerCase())) : [])

  async function charger(rafraichir = false) {
    try {
      donnees = await api.get(`/api/liaisons${rafraichir ? '?rafraichir=true' : ''}`)
      for (const p of donnees.propositions) if (!(p.pid in choix)) choix[p.pid] = p.immich[0]?.id ?? ''
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  charger()   // dernière lecture d'Immich et de Treemich (faite chaque nuit) ; « Relire » pour la refaire

  let relecture = $state(false)
  async function relire() {
    relecture = true
    try {
      await charger(true)
      annoncer('Immich et Treemich relus.')
    } finally {
      relecture = false
    }
  }

  async function suivre() {
    const avant = tache?.etat
    tache = (await api.get('/api/icloud')).tache
    if (['lecture', 'ecriture'].includes(tache.etat)) minuteur = setTimeout(suivre, 800)
    else if (['lecture', 'ecriture'].includes(avant)) {
      annoncer(tache.message, tache.etat === 'erreur')
      if (tache.operation === 'naissances') await chargerNaissances()
      else if (tache.operation === 'portraits') await chargerPortraits()
      else if (tache.operation === 'affiches') await chargerAffiches()
      else await charger()
    }
  }
  onDestroy(() => clearTimeout(minuteur))

  async function valider(liste) {
    try {
      await api.post('/api/liaisons/valider', { liaisons: liste })
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  const liaisonDe = (p) => ({ pid: p.pid, immich: choix[p.pid] || null, treemich: p.treemich?.id ?? null })

  async function refuser(p) {
    if (choix[p.pid]) await api.post('/api/liaisons/refuser', { pid: p.pid, immich: choix[p.pid] })
    donnees.propositions = donnees.propositions.filter((x) => x.pid !== p.pid)
  }

  async function delier(p) {
    await api.post('/api/liaisons/delier', { pid: p.pid })
    annoncer(`${p.nom} n'est plus lié.`)
    await charger()
  }

  // Orthographe : garder celle de carnet (écrite dans Immich et Treemich) ou celle d'Immich (écrite dans carnet)
  let occupe = $state(null)
  async function corrigerNom(p, garder) {
    occupe = p.pid
    try {
      const r = await api.post('/api/liaisons/nom', { pid: p.pid, garder })
      annoncer(`Nom retenu partout : ${r.nom}.`)
      await charger(true)
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
    }
  }

  // Noms Immich au format « Prénom NOM »
  let noms = $state({})
  async function renommer(liste) {
    occupe = 'renommage'
    let n = 0
    try {
      for (const x of liste) {
        await api.post('/api/immich/renommer', { id: x.id, nom: noms[x.id] ?? x.propose })
        n++
      }
      annoncer(`${pluriel(n, 'personne renommée', 'personnes renommées')} dans Immich.`)
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
      await charger(true)
    }
  }
  const ecarts = $derived(donnees ? donnees.liees.filter((p) => p.ecart_nom) : [])

  // Dates de naissance → Immich et Treemich (étape 5)
  let naissances = $state(null)
  let remplacer = $state(false)
  let confirmeDates = $state(false)
  let essai = $state('')
  async function chargerNaissances() {
    naissances = await api.get('/api/naissances')
  }
  chargerNaissances()
  async function lancerNaissances(chemin, corps) {
    try {
      await api.post(chemin, corps)
      await suivre()
      await chargerNaissances()
      confirmeDates = false
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  const ETATS = { ajouter: 'à ajouter', differente: 'différente', identique: 'identique',
    annee_inconnue: 'année inconnue', rien_dans_carnet: 'absente de carnet' }
  const aEcrire = (l, c) => l[c] && (l[c].etat === 'ajouter' || (remplacer && l[c].etat === 'differente'))

  // Photos HD : le meilleur visage Immich (entier, grand, net) devient la photo du contact
  let portraits = $state(null)
  let ouvert = $state(null)       // pid dont on montre les autres choix
  let filtrePortraits = $state('sans')
  async function chargerPortraits() {
    try {
      portraits = await api.get('/api/portraits')
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  chargerPortraits()
  async function chercherPortraits() {
    try {
      await api.post('/api/portraits/recherche')
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  async function choisirPortrait(l, asset) {
    occupe = l.pid
    try {
      await api.post('/api/portraits/choix', { pid: l.pid, asset })
      annoncer(asset ? `Photo de ${l.nom} changée (aussi dans Immich).` : `carnet choisira la meilleure photo de ${l.nom} au prochain passage.`)
      await chargerPortraits()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
    }
  }
  const lignesPortraits = $derived(portraits ? portraits.lignes.filter((l) =>
    filtrePortraits === 'tous' || (filtrePortraits === 'sans' ? !l.hd : l.hd?.manuel)) : [])
  const netteteLisible = (n, ecran) => ecran >= 0.5 ? 'pixélisé (écran ?)' : n == null ? 'netteté inconnue' : n >= 110 ? 'net' : n >= 70 ? 'assez net' : 'un peu flou'
  const faceLisible = (f) => f == null ? '' : f >= 0.7 ? ' · de face' : f >= 0.4 ? ' · trois quarts' : ' · profil ou masqué'

  // Affiches plein écran pour l'iPhone : images verticales dans l'album Immich « Affiches de contacts »
  let affiches = $state(null)
  async function chargerAffiches() {
    try {
      affiches = await api.get('/api/affiches')
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  chargerAffiches()
  async function basculerGroupe(g) {
    const groupes = affiches.groupes.includes(g) ? affiches.groupes.filter((x) => x !== g) : [...affiches.groupes, g]
    affiches = await api.post('/api/affiches/groupes', { groupes })
  }
  let filtreAffiches = $state('a_choisir')
  // Loupe : la proposition survolée, en grand, à côté du pointeur
  let loupe = $state(null)
  function montrerLoupe(e, l, p) {
    const largeur = 300, hauteur = Math.round(largeur * 19.5 / 9)
    const x = e.clientX + 24 + largeur > window.innerWidth ? e.clientX - 24 - largeur : e.clientX + 24
    const y = Math.min(Math.max(e.clientY - hauteur / 2, 8), window.innerHeight - hauteur - 8)
    loupe = { src: `/api/affiches/proposition/${l.pid}/${p.asset}?grand=true`, x, y, largeur, hauteur }
  }
  async function choisirAffiche(l, asset) {
    occupe = l.pid
    try {
      await api.post('/api/affiches/choix', { pid: l.pid, asset })
      annoncer(asset ? `Affiche de ${l.nom} rangée dans l'album Immich.` : `Affiche de ${l.nom} retirée.`)
      await chargerAffiches()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
    }
  }
  const lignesAffiches = $derived(affiches ? affiches.lignes.filter((l) =>
    filtreAffiches === 'tous' || (filtreAffiches === 'a_choisir' ? !l.manuel && l.propositions.length : l.manuel)) : [])
  async function preparerAffiches() {
    try {
      await api.post('/api/affiches/preparation')
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  // Sommaire (comme dans la Revue) : nombre d'éléments qui demandent une action
  const sommaire = $derived(donnees ? [
    { cle: 'a-valider', titre: 'À valider', n: donnees.propositions.length },
    { cle: 'orthographes', titre: 'Orthographes différentes', n: ecarts.length },
    { cle: 'noms-immich', titre: 'Noms Immich « Prénom NOM »', n: donnees.a_formater?.length ?? 0 },
    { cle: 'naissances', titre: 'Dates de naissance', n: naissances?.plan
      ? ['immich', 'treemich'].reduce((t, c) => t + naissances.plan.resume[c].ajouter, 0) : 0 },
    { cle: 'photos-hd', titre: 'Photos HD', n: portraits?.lignes.filter((l) => !l.hd && l.candidats.length).length ?? 0 },
    { cle: 'affiches', titre: 'Affiches iPhone', n: affiches?.lignes.filter((l) => !l.manuel && l.propositions.length).length ?? 0 },
    { cle: 'liees', titre: 'Contacts liés', n: donnees.liees.length, info: true },
  ] : [])
  function allerA(cle) {
    document.getElementById(cle)?.scrollIntoView({ behavior: 'smooth' })
  }

  async function actualiser() {
    try {
      await api.post('/api/liaisons/actualiser')
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }
</script>

{#snippet visage(id, nom)}
  <span class="relative w-11 h-11 shrink-0 rounded-full overflow-hidden bg-couture grid place-items-center text-mine text-sm">
    {nom?.[0] ?? '?'}
    {#if id}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/immich/visage/${id}?taille=88`} alt=""
      onerror={(e) => e.currentTarget.remove()} loading="lazy" />{/if}
  </span>
{/snippet}

{#if loupe}
  <div class="fixed z-50 pointer-events-none rounded-xl overflow-hidden border border-onglet/60 shadow-2xl bg-couture"
    style={`left:${loupe.x}px;top:${loupe.y}px;width:${loupe.largeur}px;height:${loupe.hauteur}px`}>
    <img class="w-full h-full object-cover" src={loupe.src} alt="" />
  </div>
{/if}

<div class="max-w-7xl">
  <div class="flex flex-wrap items-end gap-4 mb-2">
    <div>
      <h1 class="titre text-3xl">Liaisons Immich et Treemich</h1>
      <p class="text-mine text-sm max-w-3xl">Une fois un contact lié, son visage Immich devient sa photo et ses relations
        Treemich (conjoint, parents, enfants, frères et sœurs) complètent ses noms associés. Tout se met à jour chaque nuit ;
        une relation qui contredit ce que tu as saisi passe par la Revue.</p>
    </div>
    <button class="bouton ml-auto" disabled={enCours} onclick={actualiser}>Mettre à jour maintenant</button>
  </div>

  {#if tache && tache.etat !== 'repos' && ['liens', 'naissances', 'portraits', 'affiches'].includes(tache.operation)}
    <p class="text-sm mb-3 {tache.etat === 'erreur' ? 'text-alerte' : 'text-mine'}">{tache.message}
      {#if enCours && tache.total}<span class="tabular-nums"> ({tache.fait}/{tache.total})</span>{/if}</p>
  {/if}

  {#if donnees}
    {#if !donnees.immich && !donnees.treemich}
      <div class="rounded-xl border border-onglet/60 bg-reliure p-5 mt-4 text-sm">
        Renseigne dans la stack <code>CARNET_IMMICH_CLE</code> (clé d'API Immich) et
        <code>CARNET_TREEMICH_EMAIL</code> / <code>CARNET_TREEMICH_PASSWORD</code>, puis redéploie.
      </div>
    {:else}
      {#each donnees.erreurs as e}<p class="text-sm text-alerte mb-2">{e}</p>{/each}
      <p class="text-sm text-mine mb-6">{pluriel(donnees.nb_immich, 'personne nommée', 'personnes nommées')} dans Immich,
        {pluriel(donnees.nb_treemich, 'personne', 'personnes')} dans Treemich ;
        {pluriel(donnees.liees.length, 'contact lié', 'contacts liés')}.
        {#if donnees.lu_le}<span class="whitespace-nowrap">Lu le {dateCourte(donnees.lu_le)}.</span>{/if}
        <button class="underline underline-offset-2 hover:text-papier disabled:opacity-50" disabled={relecture || enCours}
          onclick={relire}>{relecture ? 'Lecture…' : 'Relire Immich et Treemich'}</button></p>

      <div class="flex gap-8">
      <!-- Sommaire, comme dans la Revue -->
      <nav class="sticky top-6 self-start w-64 shrink-0 hidden lg:flex flex-col gap-0.5" aria-label="Sections">
        {#each sommaire as x}
          <a href="#/liaisons" onclick={(e) => { e.preventDefault(); allerA(x.cle) }}
            class="flex items-center gap-2 px-3 py-1.5 rounded-l-md text-sm {x.n ? 'text-papier hover:bg-couture' : 'text-mine/60'}">
            <span class="flex-1 truncate">{x.titre}</span>
            <span class="tabular-nums text-xs rounded-full px-1.5 {x.n && !x.info ? 'bg-onglet text-onglet-sombre font-semibold' : ''}">{x.n}</span>
          </a>
        {/each}
      </nav>
      <div class="flex-1 min-w-0">
      <section id="a-valider" class="mb-10 scroll-mt-6">
        <div class="flex flex-wrap items-center gap-4 mb-2">
          <h2 class="titre text-xl">À valider <span class="text-mine text-base font-normal">({donnees.propositions.length})</span></h2>
          {#if exactes.length}
            <button class="bouton bouton-principal ml-auto" disabled={enCours}
              onclick={() => valider(exactes.map(liaisonDe))}>
              {exactes.length === 1 ? 'Valider la correspondance exacte' : `Valider les ${exactes.length} correspondances exactes`}</button>
          {/if}
        </div>
        <p class="text-sm text-mine mb-3">Exacte : même nom, une seule personne possible, pas de date de naissance contraire.</p>
        {#if donnees.propositions.length}
          <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
            {#each donnees.propositions as p (p.pid)}
              {@const im = p.immich.find((x) => x.id === choix[p.pid])}
              <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
                <div class="w-52 min-w-0">
                  <a href={`#/revision/${p.pid}`} class="block truncate hover:text-onglet">{p.nom}</a>
                  <span class="block text-xs text-mine truncate">{p.anniversaire ? anniversaireLisible(p.anniversaire) : p.groupes.join(', ')}</span>
                </div>
                <span class="text-mine">→</span>
                {@render visage(im?.id, im?.nom)}
                <div class="w-56 min-w-0 text-sm">
                  {#if p.immich.length > 1}
                    <select class="w-full" bind:value={choix[p.pid]} aria-label={`Personne Immich pour ${p.nom}`}>
                      {#each p.immich as x}<option value={x.id}>{x.nom}{x.naissance ? ` (${x.naissance.slice(0, 4)})` : ''}</option>{/each}
                      <option value="">Aucune</option>
                    </select>
                  {:else if im}
                    <span class="block truncate">{im.nom}</span>
                  {:else}
                    <span class="text-mine">Pas de personne Immich</span>
                  {/if}
                  <span class="block text-xs text-mine truncate">Treemich : {p.treemich?.nom ?? '—'}</span>
                </div>
                {#if p.exacte}<span class="text-xs rounded-full px-2 py-0.5 bg-valide/20 text-valide">exacte</span>{/if}
                <span class="ml-auto flex gap-2">
                  <button class="bouton !py-1" disabled={enCours || (!choix[p.pid] && !p.treemich)} onclick={() => valider([liaisonDe(p)])}>Valider</button>
                  <button class="text-sm text-mine underline underline-offset-2 hover:text-papier" onclick={() => refuser(p)}>Pas lui</button>
                </span>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="text-sm text-mine">Aucune proposition : chaque contact au nom connu d'Immich ou de Treemich est déjà lié.</p>
        {/if}
      </section>

      {#if ecarts.length}
        <section id="orthographes" class="mb-10 scroll-mt-6">
          <h2 class="titre text-xl">Orthographes différentes <span class="text-mine text-base font-normal">({ecarts.length})</span></h2>
          <p class="text-sm text-mine mb-3">Choisis l'orthographe juste : elle est écrite dans carnet, Immich et Treemich, au format « Prénom NOM ».
            Pense à corriger aussi une réservation en cours qui utiliserait l'ancien nom.</p>
          <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
            {#each ecarts as p (p.pid)}
              <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 {occupe === p.pid ? 'opacity-60' : ''}">
                {@render visage(p.immich?.id, p.nom)}
                <span class="text-sm text-mine w-64 truncate">Immich : {p.immich?.nom ?? '—'} · Treemich : {p.treemich?.nom ?? '—'}</span>
                <span class="ml-auto flex flex-wrap gap-2">
                  <button class="bouton !py-1" disabled={occupe !== null} onclick={() => corrigerNom(p, 'carnet')}>Garder « {p.nom_immich_propose} »</button>
                  {#if p.immich}<button class="bouton !py-1" disabled={occupe !== null} onclick={() => corrigerNom(p, 'immich')}>Garder « {p.immich.nom} »</button>{/if}
                </span>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if donnees.a_formater?.length}
        {@const lies = donnees.a_formater.filter((x) => x.lie)}
        <section id="noms-immich" class="mb-10 scroll-mt-6">
          <div class="flex flex-wrap items-center gap-4 mb-2">
            <h2 class="titre text-xl">Noms Immich au format « Prénom NOM » <span class="text-mine text-base font-normal">({donnees.a_formater.length})</span></h2>
            {#if lies.length}
              <button class="bouton bouton-principal ml-auto" disabled={occupe !== null} onclick={() => renommer(lies)}>
                Renommer les {lies.length} personnes liées</button>
            {/if}
          </div>
          <p class="text-sm text-mine mb-3">Pour une personne liée, le nom vient de carnet ; sinon carnet le devine (vérifie les noms composés).
            La personne Treemich correspondante est renommée aussi.</p>
          <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
            {#each donnees.a_formater as x (x.id)}
              <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
                {@render visage(x.id, x.nom)}
                <span class="w-56 truncate">{x.nom}</span>
                <span class="text-mine">→</span>
                <input class="w-64" value={noms[x.id] ?? x.propose} oninput={(e) => (noms[x.id] = e.currentTarget.value)}
                  aria-label={`Nouveau nom de ${x.nom}`} />
                {#if x.lie}<span class="text-xs text-mine">lié</span>{/if}
                <button class="bouton !py-1 ml-auto" disabled={occupe !== null} onclick={() => renommer([x])}>Renommer</button>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if naissances}
        {@const plan = naissances.plan}
        <section id="naissances" class="mb-10 scroll-mt-6">
          <div class="flex flex-wrap items-end gap-4 mb-2">
            <div>
              <h2 class="titre text-xl">Dates de naissance vers Immich et Treemich</h2>
              <p class="text-sm text-mine max-w-3xl">carnet fait foi. Une date sans année ne peut pas être écrite. Une date
                différente n'est remplacée que si tu le demandes ; avant d'écrire dans Treemich, l'arbre est exporté en GEDCOM
                dans carnet/archives, et chaque ancienne valeur est notée dans le journal.</p>
            </div>
            <button class="bouton {plan ? '' : 'bouton-principal'} ml-auto" disabled={enCours}
              onclick={() => lancerNaissances('/api/naissances/simulation')}>{plan ? 'Refaire la simulation' : 'Simuler'}</button>
          </div>
          {#if plan}
            <div class="grid sm:grid-cols-2 gap-3 mb-3 text-sm">
              {#each ['immich', 'treemich'] as c}
                <div class="rounded-xl border border-couture bg-reliure px-4 py-3">
                  <span class="text-papier">{c === 'immich' ? 'Immich' : 'Treemich'}</span> :
                  <span class="text-mine">{plan.resume[c].ajouter} à ajouter, {plan.resume[c].differente} différente(s),
                    {plan.resume[c].identique} identique(s), {plan.resume[c].annee_inconnue} sans année</span>
                </div>
              {/each}
            </div>
            <details class="mb-4">
              <summary class="cursor-pointer text-sm text-mine">Détail par contact</summary>
              <table class="mt-2 w-full text-sm">
                <thead><tr class="text-mine text-xs text-left"><th class="py-1">Contact</th><th>carnet</th><th>Immich</th><th>Treemich</th></tr></thead>
                <tbody>
                  {#each plan.lignes.filter((l) => ['immich', 'treemich'].some((c) => l[c] && l[c].etat !== 'identique' && l[c].etat !== 'rien_dans_carnet')) as l (l.pid)}
                    <tr class="border-t border-couture">
                      <td class="py-1">{l.nom}</td>
                      <td class="tabular-nums">{l.carnet}</td>
                      {#each ['immich', 'treemich'] as c}
                        <td class="tabular-nums {aEcrire(l, c) ? 'text-onglet' : 'text-mine'}">
                          {#if l[c]}{l[c].actuelle || '—'} <span class="text-xs">({ETATS[l[c].etat]})</span>{:else}—{/if}</td>
                      {/each}
                    </tr>
                  {/each}
                </tbody>
              </table>
            </details>
            <label class="flex items-center gap-2 text-sm mb-3">
              <input type="checkbox" bind:checked={remplacer} /> Remplacer aussi les dates différentes (sinon seules les dates absentes sont ajoutées)
            </label>
            <div class="grid gap-4 lg:grid-cols-2">
              <div class="rounded-xl border border-couture bg-reliure p-4 text-sm">
                <p class="mb-2">1. Essai sur une personne</p>
                <div class="flex flex-wrap gap-2">
                  <select class="flex-1" bind:value={essai} aria-label="Personne pour l'essai">
                    <option value="">Choisir…</option>
                    {#each plan.lignes.filter((l) => aEcrire(l, 'immich') || aEcrire(l, 'treemich')) as l}<option value={l.pid}>{l.nom}</option>{/each}
                  </select>
                  <button class="bouton !py-1" disabled={!essai || enCours} onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'immich', essai, remplacer })}>Immich</button>
                  <button class="bouton !py-1" disabled={!essai || enCours} onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'treemich', essai, remplacer })}>Treemich</button>
                </div>
              </div>
              <div class="rounded-xl border border-onglet/60 bg-reliure p-4 text-sm">
                <p class="mb-2">2. Écriture complète</p>
                <label class="flex items-start gap-2 mb-2"><input type="checkbox" class="mt-1" bind:checked={confirmeDates} />
                  <span>J'ai vérifié la simulation.</span></label>
                <div class="flex gap-2">
                  <button class="bouton bouton-principal !py-1" disabled={!confirmeDates || enCours}
                    onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'immich', confirme: true, remplacer })}>Écrire dans Immich</button>
                  <button class="bouton bouton-principal !py-1" disabled={!confirmeDates || enCours}
                    onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'treemich', confirme: true, remplacer })}>Écrire dans Treemich</button>
                </div>
              </div>
            </div>
          {/if}
          {#if naissances.journal.length}
            <ul class="mt-4 divide-y divide-couture border-y border-couture text-sm">
              {#each naissances.journal as j}
                <li class="py-2">
                  <span class="text-papier">{dateCourte(j.le)}</span>
                  <span class="text-mine">· {j.essai ? 'Essai' : 'Écriture'} {j.cible} : {j.ecrites.length} date(s){j.sauvegarde ? ` · export ${j.sauvegarde}` : ''}</span>
                  {#if j.ecrites.length}
                    <details class="text-xs text-mine"><summary class="cursor-pointer">Anciennes valeurs</summary>
                      {#each j.ecrites as e}<span class="block">{e.nom} : {e.avant || '—'} → {e.apres}</span>{/each}</details>
                  {/if}
                  {#if j.erreurs.length}
                    <details class="text-xs text-alerte"><summary class="cursor-pointer">{j.erreurs.length} erreur(s)</summary>
                      {#each j.erreurs as e}<span class="block">{e}</span>{/each}</details>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}

      {#if portraits?.immich}
        {@const avecHd = portraits.lignes.filter((l) => l.hd).length}
        <section id="photos-hd" class="mb-10 scroll-mt-6">
          <div class="flex flex-wrap items-end gap-4 mb-2">
            <div>
              <h2 class="titre text-xl">Photos HD depuis Immich <span class="text-mine text-base font-normal">({avecHd}/{portraits.lignes.length})</span></h2>
              <p class="text-sm text-mine max-w-3xl">Pour chaque contact lié sans photo ou avec la vignette Immich, carnet cherche le visage
                entier le plus grand et le plus net, et le découpe en portrait carré depuis la photo d'origine. Il devient la photo du
                contact (iCloud suivra à la prochaine écriture) et la photo de la personne dans Immich. Une photo venue d'iCloud ou de
                Gmail est gardée. Un choix fait ici n'est plus changé automatiquement.</p>
            </div>
            <button class="bouton {portraits.journal.length ? '' : 'bouton-principal'} ml-auto" disabled={enCours}
              onclick={chercherPortraits}>{portraits.journal.length ? 'Relancer la recherche' : 'Chercher les photos HD'}</button>
          </div>
          {#if portraits.journal.length}
            {@const j = portraits.journal[0]}
            <p class="text-xs text-mine mb-3">Dernière recherche le {dateCourte(j.le)} : {j.changees} photo(s) posée(s),
              {j.sans_photo_hd} contact(s) sans visage assez grand{portraits.prochaine ? ` · prochaine recherche automatique vers le ${dateCourte(portraits.prochaine)}` : ''}.
              {#if j.erreurs.length}<span class="block text-alerte">{j.erreurs.join(' · ')}</span>{/if}</p>
            <div class="flex gap-2 text-sm mb-3" role="group" aria-label="Filtrer les photos HD">
              {#each [['sans', 'Sans photo HD'], ['manuel', 'Choisies à la main'], ['tous', 'Tous']] as [v, t]}
                <button class="rounded-full px-3 py-1 border {filtrePortraits === v ? 'border-onglet text-papier' : 'border-couture text-mine'}"
                  onclick={() => (filtrePortraits = v)}>{t}</button>
              {/each}
            </div>
            <ul class="divide-y divide-couture border-y border-couture">
              {#each lignesPortraits as l (l.pid)}
                <li class="py-2 text-sm {occupe === l.pid ? 'opacity-60' : ''}">
                  <div class="flex flex-wrap items-center gap-3">
                    <span class="relative w-14 h-14 shrink-0 rounded-lg overflow-hidden bg-couture grid place-items-center text-mine">
                      {l.nom[0]}
                      {#if l.photo}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/photos/${l.photo}?taille=112&v=${l.hd?.le ?? ''}`} alt=""
                        onerror={(e) => e.currentTarget.remove()} loading="lazy" />{/if}
                    </span>
                    <span class="flex-1 min-w-0">
                      <a href={`#/revision/${l.pid}`} class="block truncate hover:text-onglet">{l.nom}</a>
                      <span class="block text-xs text-mine">
                        {#if l.hd}visage de {l.hd.taille} px, {netteteLisible(l.hd.nettete, l.hd.ecran)}{faceLisible(l.hd.face)}{l.hd.manuel ? ' · choisie à la main' : ''}
                        {:else if l.candidats.length}pas encore posée{:else}aucune photo où le visage est entier et assez grand{/if}</span>
                    </span>
                    {#if l.candidats.length}
                      <button class="text-xs text-mine underline underline-offset-2 hover:text-papier"
                        onclick={() => (ouvert = ouvert === l.pid ? null : l.pid)}>{ouvert === l.pid ? 'Fermer' : `Autres choix (${l.candidats.length})`}</button>
                    {/if}
                    {#if l.hd?.manuel}
                      <button class="text-xs text-mine underline underline-offset-2 hover:text-papier" disabled={occupe !== null}
                        onclick={() => choisirPortrait(l, null)}>Laisser carnet choisir</button>
                    {/if}
                  </div>
                  {#if ouvert === l.pid}
                    <div class="flex flex-wrap gap-3 mt-3 pl-[4.25rem]">
                      {#each l.candidats as cand (cand.asset)}
                        <button class="w-28 text-left rounded-lg overflow-hidden border-2 {l.hd?.asset === cand.asset ? 'border-onglet' : 'border-transparent hover:border-couture'}"
                          disabled={occupe !== null} onclick={() => choisirPortrait(l, cand.asset)} aria-label={`Choisir cette photo pour ${l.nom}`}>
                          <img class="w-28 h-28 object-cover bg-couture" src={`/api/portraits/apercu/${l.pid}/${cand.asset}`} alt="" loading="lazy" />
                          <span class="block text-[11px] text-mine px-1 py-0.5 leading-tight">{cand.taille} px · {netteteLisible(cand.nettete, cand.ecran)}{faceLisible(cand.face)}{cand.le ? ` · ${cand.le.slice(0, 4)}` : ''}</span>
                        </button>
                      {/each}
                    </div>
                  {/if}
                </li>
              {:else}
                <li class="py-3 text-sm text-mine">Rien dans ce filtre.</li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}

      {#if affiches && portraits?.immich}
        {@const choisies = affiches.lignes.filter((l) => l.manuel).length}
        <section id="affiches" class="mb-10 scroll-mt-6">
          <div class="flex flex-wrap items-end gap-4 mb-2">
            <div>
              <h2 class="titre text-xl">Affiches plein écran pour l'iPhone <span class="text-mine text-base font-normal">({choisies}/{affiches.lignes.length})</span></h2>
              <p class="text-sm text-mine max-w-3xl">Pour les contacts des groupes cochés, carnet propose jusqu'à 6 photos Immich qui se prêtent
                au plein écran (visage de face, net, avec de la place autour), déjà cadrées à la verticale. Rien n'est envoyé sans ton choix :
                la photo choisie est rangée dans l'album Immich « Affiches de contacts » (archivée, hors chronologie). Les propositions
                sont rafraîchies avec la recherche mensuelle ; un choix n'est jamais changé.</p>
            </div>
            <button class="bouton {affiches.journal.length ? '' : 'bouton-principal'} ml-auto" disabled={enCours || !affiches.groupes.length}
              onclick={preparerAffiches}>{affiches.journal.length ? 'Actualiser les propositions' : 'Chercher les propositions'}</button>
          </div>
          <div class="flex flex-wrap gap-2 text-sm mb-3" role="group" aria-label="Groupes pour les affiches">
            {#each ref.groupes as g}
              <button class="rounded-full px-3 py-1 border {affiches.groupes.includes(g) ? 'border-onglet text-papier bg-onglet/10' : 'border-couture text-mine'}"
                aria-pressed={affiches.groupes.includes(g)} onclick={() => basculerGroupe(g)}>{g}</button>
            {/each}
          </div>
          {#if affiches.journal.length}
            {@const j = affiches.journal[0]}
            <p class="text-xs text-mine mb-3">Dernière recherche le {dateCourte(j.le)} : propositions pour {j.proposees ?? j.nouvelles ?? 0} contact(s),
              {j.sans_photo} sans photo qui convienne{j.retirees ? `, ${j.retirees} affiche(s) retirée(s)` : ''}.
              {#if j.erreurs.length}<span class="block text-alerte">{j.erreurs.join(' · ')}</span>{/if}</p>
          {/if}
          <details class="mb-3 text-sm">
            <summary class="cursor-pointer text-mine">Sur l'iPhone : créer l'affiche d'un contact</summary>
            <ol class="list-decimal pl-5 mt-2 space-y-1 text-mine">
              <li>Dans l'app Immich, ouvre l'album « Affiches de contacts », ouvre l'image et enregistre-la dans Photos (Partager › Enregistrer).</li>
              <li>Contacts › la fiche › Modifier › Photo et affiche du contact › Photos : choisis l'image.</li>
              <li>En haut, choisis Affiche, puis OK deux fois (pas « Retour »).</li>
            </ol>
          </details>
          {#if affiches.lignes.length}
            <div class="flex gap-2 text-sm mb-3" role="group" aria-label="Filtrer les affiches">
              {#each [['a_choisir', 'À choisir'], ['choisies', 'Choisies'], ['tous', 'Tous']] as [v, t]}
                <button class="rounded-full px-3 py-1 border {filtreAffiches === v ? 'border-onglet text-papier' : 'border-couture text-mine'}"
                  onclick={() => (filtreAffiches = v)}>{t}</button>
              {/each}
            </div>
            <div class="overflow-x-auto rounded-xl border border-couture" data-defile>
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-xs text-mine text-left">
                    <th class="px-3 py-2 font-normal">Contact</th>
                    {#each [1, 2, 3, 4, 5, 6] as n}<th class="px-1 py-2 font-normal text-center">Photo {n}</th>{/each}
                  </tr>
                </thead>
                <tbody>
                  {#each lignesAffiches as l (l.pid)}
                    <tr class="border-t border-couture align-top {occupe === l.pid ? 'opacity-60' : ''}">
                      <td class="px-3 py-2 w-48">
                        <a href={`#/revision/${l.pid}`} class="block truncate hover:text-onglet">{l.nom}</a>
                        <span class="block text-xs text-mine truncate">{l.groupes.filter((g) => affiches.groupes.includes(g)).join(', ')}</span>
                        <span class="block text-xs mt-1 {l.manuel ? 'text-valide' : 'text-mine'}">
                          {l.manuel ? 'choisie ✓' : l.affiche ? 'préparée sans ton choix' : l.propositions.length ? 'à choisir' : 'aucune photo qui convienne'}</span>
                        {#if l.affiche}
                          <button class="text-xs text-mine underline underline-offset-2 hover:text-papier mt-1" disabled={occupe !== null}
                            onclick={() => choisirAffiche(l, null)}>Retirer l'affiche</button>
                        {/if}
                      </td>
                      {#each [0, 1, 2, 3, 4, 5] as k}
                        {@const p = l.propositions[k]}
                        <td class="px-1 py-2 text-center">
                          {#if p}
                            <button class="w-20 rounded-lg overflow-hidden border-2 {l.choisie === p.asset ? 'border-onglet' : 'border-transparent hover:border-couture'}"
                              disabled={occupe !== null} onclick={() => choisirAffiche(l, p.asset)}
                              aria-label={`Photo ${k + 1} pour l'affiche de ${l.nom}`} aria-pressed={l.choisie === p.asset}>
                              <img class="w-full aspect-[9/19.5] object-cover bg-couture" src={`/api/affiches/proposition/${l.pid}/${p.asset}`} alt="" loading="lazy"
                                onmouseenter={(e) => montrerLoupe(e, l, p)} onmousemove={(e) => montrerLoupe(e, l, p)} onmouseleave={() => (loupe = null)} />
                              <span class="block text-[10px] text-mine leading-tight py-0.5">{netteteLisible(p.nettete, p.ecran)}{faceLisible(p.face)}{p.le ? ` · ${p.le.slice(0, 4)}` : ''}</span>
                            </button>
                          {/if}
                        </td>
                      {/each}
                    </tr>
                  {:else}
                    <tr><td colspan="7" class="px-3 py-3 text-mine">Rien dans ce filtre.</td></tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {:else if affiches.groupes.length}
            <p class="text-sm text-mine">Aucun contact lié à Immich dans ces groupes.</p>
          {/if}
        </section>
      {/if}

      <section id="liees" class="scroll-mt-6">
        <div class="flex flex-wrap items-center gap-4 mb-2">
          <h2 class="titre text-xl">Contacts liés <span class="text-mine text-base font-normal">({donnees.liees.length})</span></h2>
          <input class="ml-auto w-56" placeholder="Filtrer" bind:value={filtre} aria-label="Filtrer les contacts liés" />
        </div>
        <ul class="grid sm:grid-cols-2 gap-x-6 divide-y divide-couture border-y border-couture">
          {#each liees as p (p.pid)}
            <li class="flex items-center gap-3 py-2 text-sm">
              {@render visage(p.immich?.id, p.nom)}
              <span class="flex-1 min-w-0">
                <a href={`#/revision/${p.pid}`} class="block truncate hover:text-onglet">{p.nom}</a>
                <span class="block text-xs text-mine truncate">Immich : {p.immich?.nom ?? '—'} · Treemich : {p.treemich?.nom ?? '—'}</span>
              </span>
              <button class="text-xs text-mine underline underline-offset-2 hover:text-papier" onclick={() => delier(p)}>Délier</button>
            </li>
          {/each}
        </ul>
        {#if donnees.dernier_passage}
          <p class="text-xs text-mine mt-3">Dernière mise à jour le {dateCourte(donnees.dernier_passage.le)} :
            {donnees.dernier_passage.photos} photo(s), {donnees.dernier_passage.relations} relation(s),
            {donnees.dernier_passage.a_revoir} à revoir.</p>
        {/if}
      </section>
      </div>
      </div>
    {/if}
  {:else}
    <p class="text-mine mt-6">Lecture d'Immich et de Treemich…</p>
  {/if}
</div>
