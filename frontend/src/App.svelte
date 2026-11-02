<script>
  import { api } from './lib/api.js'
  import { session, ref, statut, message, route, ecran, choisirVue, bilan, chargerBilan } from './lib/etat.svelte.js'
  import Connexion from './pages/Connexion.svelte'
  import Accueil from './pages/Accueil.svelte'
  import Importer from './pages/Importer.svelte'
  import Revision from './pages/Revision.svelte'
  import Contacts from './pages/Contacts.svelte'
  import Export from './pages/Export.svelte'
  import Archives from './pages/Archives.svelte'
  import Revue from './pages/Revue.svelte'
  import ICloud from './pages/ICloud.svelte'
  import Groupes from './pages/Groupes.svelte'
  import Liaisons from './pages/Liaisons.svelte'
  import Chercher from './pages/Chercher.svelte'
  import Fiche from './pages/Fiche.svelte'
  import Photos from './pages/Photos.svelte'
  import Etat from './pages/Etat.svelte'

  // Quatre onglets, les mêmes sur PC et sur iPhone : tout ce qui attend une décision est dans
  // « À traiter » ; « État » dit si la synchro et les sauvegardes vont bien. Les anciennes
  // adresses (#/revision, #/icloud…) restent valables.
  const ONGLETS = [
    { cle: 'traiter', nom: 'À traiter', sous: [
      { cle: 'accueil', nom: 'Boîte' }, { cle: 'revision', nom: 'Révision' },
      { cle: 'revue', nom: 'À compléter' }, { cle: 'liaisons', nom: 'Liaisons' }] },
    { cle: 'contacts', nom: 'Contacts', sous: [
      { cle: 'contacts', nom: 'Tous les contacts', mobile: 'chercher' }, { cle: 'groupes', nom: 'Groupes' },
      { cle: 'importer', nom: 'Importer' }], aussi: ['fiche', 'chercher'] },
    { cle: 'photos', nom: 'Photos', sous: [] },
    { cle: 'etat', nom: 'État', sous: [
      { cle: 'etat', nom: 'Synchro' }, { cle: 'export', nom: 'Sauvegardes et export' },
      { cle: 'icloud', nom: 'iCloud en détail' }, { cle: 'archives', nom: 'Archives' }], aussi: ['plus'] },
  ]
  const groupeDe = (page) => ONGLETS.find((o) => o.cle === page || o.sous.some((x) => x.cle === page || x.mobile === page)
    || o.aussi?.includes(page))?.cle ?? 'traiter'

  // Compteurs (bilan rechargé quand on change de page, au plus toutes les 20 s)
  let dernierBilan = 0
  $effect(() => {
    route.page
    if (session.connecte && Date.now() - dernierBilan > 20000) {
      dernierBilan = Date.now()
      chargerBilan(api).catch(() => {})
    }
  })
  const compteurs = $derived.by(() => {
    const b = bilan.donnees
    const l = b?.liaisons
    return {
      revision: statut.a_reviser || 0,
      revue: b?.revue || 0,
      liaisons: l ? l.propositions + l.orthographes + l.noms_immich : 0,
      photos: b?.photos ? b.photos.hd + b.photos.affiches : 0,
    }
  })
  const aTraiter = $derived(compteurs.revision + compteurs.revue + compteurs.liaisons)
  // État : pastille rouge si la synchro, la veille ou la sauvegarde de la nuit ont un souci
  const alerteEtat = $derived.by(() => {
    const s = bilan.donnees?.statut
    if (!s) return false
    return (s.synchro && !s.synchro.ok) || (s.veille && !s.veille.ok) || (s.sauvegarde && !s.sauvegarde.ok)
  })
  const badge = (cle) => (cle === 'traiter' ? aTraiter : cle === 'photos' ? compteurs.photos : 0)

  async function demarrer() {
    try {
      const s = await api.get('/api/session')
      session.connecte = s.connecte
    } catch {
      session.connecte = false
    }
  }

  async function charger() {
    Object.assign(ref, await api.get('/api/config'))
  }

  $effect(() => {
    if (session.connecte) charger()
  })

  demarrer()

  // Message bref : effacé au changement de page, plus long s'il porte un bouton
  let visible = $state(false)
  $effect(() => {
    if (!message.id) return
    visible = true
    const t = setTimeout(() => (visible = false), message.erreur ? 7000 : message.action ? 6000 : 3500)
    return () => clearTimeout(t)
  })
  let pagePrecedente = route.page
  $effect(() => {
    if (route.page !== pagePrecedente) {
      pagePrecedente = route.page
      if (!message.erreur) visible = false
    }
  })

  async function deconnecter() {
    await api.post('/api/deconnexion')
    session.connecte = false
  }

  const progression = $derived(statut.total ? Math.round((statut.verifies / statut.total) * 100) : 0)

  const mobile = $derived(ecran.etroit && !ecran.forcerPC)
  // Sur iPhone, la liste des contacts devient « Chercher » ; sur PC, « Chercher » est la liste ;
  // l'ancienne page « Plus » mène à « État »
  const page = $derived(route.page === 'plus' ? 'etat'
    : mobile && route.page === 'contacts' && !route.id ? 'chercher'
    : !mobile && route.page === 'chercher' ? 'contacts' : route.page)
  const groupe = $derived(groupeDe(page))
  const onglet = $derived(ONGLETS.find((o) => o.cle === groupe))
  const sousOnglets = $derived(onglet?.sous ?? [])
  const lienOnglet = (o) => `#/${mobile ? (o.sous[0]?.mobile ?? o.sous[0]?.cle ?? o.cle) : (o.sous[0]?.cle ?? o.cle)}`
  const lienSous = (x) => `#/${mobile && x.mobile ? x.mobile : x.cle}`
  const sousActif = (x) => page === x.cle || page === x.mobile

  // Vue PC sur iPhone ou iPad (écran tactile ou étroit) : bouton menu en bas à droite,
  // pour garder la barre du haut à portée de pouce même après avoir défilé
  const TACTILE = matchMedia('(hover: none)')
  let tactile = $state(TACTILE.matches)
  TACTILE.addEventListener('change', (e) => (tactile = e.matches))
  const raccourci = $derived(!mobile && (ecran.etroit || tactile))
  let menuOuvert = $state(false)
  let boutonCache = $state(false)
  let dernierY = 0
  function defilement() {
    const y = window.scrollY
    if (Math.abs(y - dernierY) < 8) return
    boutonCache = y > dernierY && y > 120 && !menuOuvert
    dernierY = y
  }
  $effect(() => {
    route.page
    menuOuvert = false
  })
  // La Révision mobile a sa propre barre d'actions en bas : la barre d'onglets lui laisse la place
  const pleinEcran = $derived(mobile && page === 'revision')
</script>

<svelte:window onscroll={defilement} />

{#snippet icone(cle)}
  <svg viewBox="0 0 24 24" class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    {#if cle === 'traiter'}<path d="M4 13.5 6.5 5h11L20 13.5V18a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z" /><path d="M4 13.5h4.5l1 2h5l1-2H20" />
    {:else if cle === 'contacts'}<circle cx="12" cy="9" r="3.5" /><path d="M5.5 19c.8-3.2 3.4-5 6.5-5s5.7 1.8 6.5 5" />
    {:else if cle === 'photos'}<rect x="3.5" y="5" width="17" height="14" rx="3" /><circle cx="9" cy="10" r="1.6" /><path d="m4 17 5-4.5 3.5 3 3-2.5 4.5 4" />
    {:else}<path d="M4 12h3l2.5-6 4 12 2.5-6H20" />{/if}
  </svg>
{/snippet}

{#snippet pastille(n, alerte = false)}
  {#if alerte}<span class="ml-1.5 inline-block w-2 h-2 rounded-full bg-alerte" aria-label="à vérifier"></span>
  {:else if n}<span class="ml-1.5 rounded-full bg-onglet-sombre text-onglet text-xs px-1.5 tabular-nums">{n}</span>{/if}
{/snippet}

{#if session.connecte === false}
  <Connexion />
{:else if session.connecte}
  <div class="min-h-screen flex flex-col">
    {#if mobile}
      <header class="sticky top-0 z-20 border-b border-couture bg-cuir/90 backdrop-blur-md pt-[env(safe-area-inset-top)]">
        <div class="px-4 flex items-center h-12">
          <a href="#/accueil" class="titre text-xl text-papier min-h-11 flex items-center">carnet</a>
          <span class="ml-auto text-xs text-mine tabular-nums">{statut.verifies} / {statut.total} vérifiés</span>
        </div>
        {#if sousOnglets.length > 1 && page !== 'fiche' && page !== 'revision'}
          <nav class="flex gap-2 overflow-x-auto px-4 pb-2" data-defile aria-label="Pages de l'onglet">
            {#each sousOnglets as x}
              <a href={lienSous(x)} class="shrink-0 h-9 px-3.5 rounded-full border text-sm flex items-center
                {sousActif(x) ? 'border-onglet text-papier bg-onglet/10' : 'border-couture text-mine'}"
                aria-current={sousActif(x) ? 'page' : undefined}>{x.nom}{@render pastille(compteurs[x.cle])}</a>
            {/each}
          </nav>
        {/if}
      </header>
    {:else}
    <!-- Vue PC : sous la barre d'état de l'iPhone (safe area) et repliée sur deux lignes si l'écran est étroit -->
    <header class="border-b border-couture bg-reliure/60 pt-[env(safe-area-inset-top)]">
      <div class="mx-auto max-w-[1400px] px-6 flex flex-wrap items-center gap-x-8 min-h-14">
        <a href="#/accueil" class="titre text-xl text-papier">carnet</a>
        <nav class="flex gap-1 h-14 order-last w-full md:order-none md:w-auto" aria-label="Sections">
          {#each ONGLETS as o}
            <a href={lienOnglet(o)} class="relative px-3 flex items-center text-sm transition-colors
                {groupe === o.cle ? 'text-papier' : 'text-mine hover:text-papier'}" aria-current={groupe === o.cle ? 'page' : undefined}>
              {o.nom}{@render pastille(badge(o.cle), o.cle === 'etat' && alerteEtat)}
              {#if groupe === o.cle}<span class="absolute left-2 right-2 bottom-0 h-0.5 bg-onglet rounded-t"></span>{/if}
            </a>
          {/each}
        </nav>
        <div class="ml-auto flex items-center gap-4 h-14 text-sm text-mine">
          <span class="tabular-nums hidden md:inline" title="Contacts vérifiés">{statut.verifies} / {statut.total} vérifiés</span>
          <span class="w-28 h-1.5 rounded-full bg-couture overflow-hidden hidden md:block" aria-hidden="true">
            <span class="block h-full bg-valide" style="width: {progression}%"></span>
          </span>
          {#if ecran.etroit}<button class="h-9 px-3 rounded-full border border-onglet text-onglet" onclick={() => choisirVue(false)}>Vue iPhone</button>{/if}
          <button class="hover:text-papier" onclick={deconnecter}>Se déconnecter</button>
        </div>
      </div>
    </header>
    {/if}

    <main class="flex-1 mx-auto w-full max-w-[1400px] {mobile ? `px-4 pt-4 ${pleinEcran ? 'pb-[calc(6rem+env(safe-area-inset-bottom))]' : 'pb-[calc(5rem+env(safe-area-inset-bottom))]'}` : raccourci ? 'px-6 pt-5 pb-24' : 'px-6 py-5'}">
      {#if !mobile && sousOnglets.length}
        <nav class="flex flex-wrap gap-1 mb-5 border-b border-couture" aria-label="Pages de l'onglet">
          {#each sousOnglets as x}
            <a href={`#/${x.cle}`} class="relative px-3 py-2 text-sm rounded-t-md
              {sousActif(x) ? 'text-papier bg-reliure' : 'text-mine hover:text-papier'}" aria-current={sousActif(x) ? 'page' : undefined}>
              {x.nom}{@render pastille(compteurs[x.cle])}
              {#if sousActif(x)}<span class="absolute left-2 right-2 -bottom-px h-0.5 bg-onglet rounded-t"></span>{/if}
            </a>
          {/each}
        </nav>
      {/if}
      {#if page === 'chercher'}
        <Chercher />
      {:else if page === 'fiche'}
        <Fiche />
      {:else if page === 'photos'}
        <Photos />
      {:else if page === 'etat'}
        <Etat {deconnecter} />
      {:else if page === 'revision'}
        <Revision />
      {:else if page === 'contacts'}
        <Contacts />
      {:else if page === 'importer'}
        <Importer />
      {:else if page === 'revue'}
        <Revue />
      {:else if page === 'export'}
        <Export />
      {:else if page === 'liaisons'}
        <Liaisons />
      {:else if page === 'groupes'}
        <Groupes />
      {:else if page === 'icloud'}
        <ICloud />
      {:else if page === 'archives'}
        <Archives />
      {:else}
        <Accueil />
      {/if}
    </main>

    {#if mobile && !pleinEcran}
      <nav class="fixed bottom-0 inset-x-0 z-30 border-t border-couture bg-reliure/90 backdrop-blur-md pb-[env(safe-area-inset-bottom)]"
        aria-label="Sections">
        <div class="grid grid-cols-4">
          {#each ONGLETS as o}
            <a href={lienOnglet(o)} class="relative flex flex-col items-center justify-center gap-0.5 h-14 text-[11px] font-medium
              {groupe === o.cle ? 'text-onglet' : 'text-mine'}" aria-current={groupe === o.cle ? 'page' : undefined}>
              <span class="relative">{@render icone(o.cle)}
                {#if o.cle === 'etat' && alerteEtat}<span class="absolute -top-0.5 -right-1 w-2.5 h-2.5 rounded-full bg-alerte" aria-label="à vérifier"></span>
                {:else if badge(o.cle)}<span class="absolute -top-1.5 left-4 min-w-5 h-5 px-1 rounded-full bg-onglet text-onglet-sombre text-[11px] leading-5 text-center tabular-nums">{badge(o.cle) > 99 ? '99+' : badge(o.cle)}</span>{/if}
              </span>{o.nom}
            </a>
          {/each}
        </div>
      </nav>
    {:else if raccourci}
      <!-- Vue PC sur écran tactile ou étroit : bouton en bas à droite, mêmes accès que la barre du haut -->
      {#if menuOuvert}
        <button class="fixed inset-0 z-40 bg-black/50" aria-label="Fermer le menu" onclick={() => (menuOuvert = false)}></button>
        <nav id="menu-raccourci" class="fixed z-50 right-4 bottom-[calc(5.5rem+env(safe-area-inset-bottom))] w-72 max-h-[calc(100dvh-8rem-env(safe-area-inset-top)-env(safe-area-inset-bottom))] overflow-y-auto
          rounded-2xl border border-couture bg-reliure shadow-2xl py-2 text-sm" aria-label="Menu">
          {#each ONGLETS as o}
            {#if o.sous.length}
              <p class="px-4 pt-1.5 pb-0.5 text-xs text-mine">{o.nom}</p>
              {#each o.sous as x}
                <a href={`#/${x.cle}`} onclick={() => (menuOuvert = false)}
                  class="flex items-center px-4 min-h-11 {sousActif(x) ? 'text-onglet' : 'text-papier'} active:bg-couture">
                  <span class="flex-1">{x.nom}</span>{@render pastille(compteurs[x.cle])}
                </a>
              {/each}
            {:else}
              <a href={`#/${o.cle}`} onclick={() => (menuOuvert = false)}
                class="flex items-center px-4 min-h-11 {page === o.cle ? 'text-onglet' : 'text-papier'} active:bg-couture">
                <span class="flex-1">{o.nom}</span>{@render pastille(badge(o.cle))}</a>
            {/if}
          {/each}
          <div class="border-t border-couture mt-2 pt-2">
            <p class="px-4 pb-1 text-xs text-mine tabular-nums">{statut.verifies} / {statut.total} vérifiés</p>
            {#if ecran.etroit}
              <button class="w-full text-left px-4 min-h-11 text-papier active:bg-couture" onclick={() => { menuOuvert = false; choisirVue(false) }}>Vue iPhone</button>
            {/if}
            <button class="w-full text-left px-4 min-h-11 text-alerte active:bg-couture" onclick={() => { menuOuvert = false; deconnecter() }}>Se déconnecter</button>
          </div>
        </nav>
      {/if}
      <button class="fixed z-50 right-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] w-14 h-14 rounded-full bg-onglet text-onglet-sombre shadow-2xl
        transition-transform duration-200 {boutonCache ? 'translate-y-[calc(100%+2rem+env(safe-area-inset-bottom))]' : ''}
        flex items-center justify-center" aria-label="Menu" aria-expanded={menuOuvert} aria-controls="menu-raccourci"
        onclick={() => (menuOuvert = !menuOuvert)}>
        {#if menuOuvert}
          <svg viewBox="0 0 24 24" class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        {:else}
          <svg viewBox="0 0 24 24" class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
        {/if}
        {#if aTraiter && !menuOuvert}<span class="absolute -top-1 -right-1 min-w-5 h-5 px-1 rounded-full bg-alerte text-papier text-[11px] leading-5 tabular-nums">{aTraiter}</span>{/if}
      </button>
    {/if}
  </div>
{/if}

{#if visible && message.texte}
  <div role="status" aria-live="polite"
    class="fixed {mobile ? `${pleinEcran ? 'bottom-[calc(5.5rem+env(safe-area-inset-bottom))]' : 'bottom-[calc(4.5rem+env(safe-area-inset-bottom))]'} w-[calc(100%-2rem)]` : 'bottom-6 left-6 max-w-md'} {mobile ? 'left-1/2 -translate-x-1/2' : ''}
      flex items-center gap-3 pl-4 pr-2 py-2 min-h-11 rounded-lg border shadow-lg text-sm z-50
      {message.erreur ? 'bg-[#3a1f1f] border-alerte text-papier' : 'bg-reliure border-tranche text-papier'}">
    <span class="flex-1 py-0.5">{message.texte}</span>
    {#if message.action}
      <button class="shrink-0 h-9 px-3 rounded-md text-onglet font-medium hover:bg-couture"
        onclick={() => { visible = false; message.action.faire() }}>{message.action.libelle}</button>
    {/if}
    <button class="shrink-0 w-9 h-9 rounded-md text-mine hover:text-papier" aria-label="Fermer le message" onclick={() => (visible = false)}>×</button>
  </div>
{/if}
