<script>
  import { onDestroy } from 'svelte'
  import { api } from '../lib/api.js'
  import { annoncer } from '../lib/etat.svelte.js'
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
  charger(true)

  async function suivre() {
    const avant = tache?.etat
    tache = (await api.get('/api/icloud')).tache
    if (['lecture', 'ecriture'].includes(tache.etat)) minuteur = setTimeout(suivre, 800)
    else if (['lecture', 'ecriture'].includes(avant)) {
      annoncer(tache.message, tache.etat === 'erreur')
      await charger()
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
    {#if id}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/immich/visage/${id}`} alt=""
      onerror={(e) => e.currentTarget.remove()} loading="lazy" />{/if}
  </span>
{/snippet}

<div class="max-w-5xl">
  <div class="flex flex-wrap items-end gap-4 mb-2">
    <div>
      <h1 class="titre text-3xl">Liaisons Immich et Treemich</h1>
      <p class="text-mine text-sm max-w-3xl">Une fois un contact lié, son visage Immich devient sa photo et ses relations
        Treemich (conjoint, parents, enfants, frères et sœurs) complètent ses noms associés. Tout se met à jour chaque nuit ;
        une relation qui contredit ce que tu as saisi passe par la Revue.</p>
    </div>
    <button class="bouton ml-auto" disabled={enCours} onclick={actualiser}>Mettre à jour maintenant</button>
  </div>

  {#if tache && tache.etat !== 'repos' && tache.operation === 'liens'}
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
        {pluriel(donnees.liees.length, 'contact lié', 'contacts liés')}.</p>

      <section class="mb-10">
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

      <section>
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
    {/if}
  {:else}
    <p class="text-mine mt-6">Lecture d'Immich et de Treemich…</p>
  {/if}
</div>
