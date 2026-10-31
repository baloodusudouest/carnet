<script>
  import { api } from './lib/api.js'
  import { session, ref, statut, message, route, aller, ecran, choisirVue } from './lib/etat.svelte.js'
  import Connexion from './pages/Connexion.svelte'
  import Accueil from './pages/Accueil.svelte'
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
  import Plus from './pages/Plus.svelte'

  const PAGES = [
    { cle: 'accueil', nom: 'Accueil' },
    { cle: 'revision', nom: 'Révision' },
    { cle: 'contacts', nom: 'Contacts' },
    { cle: 'revue', nom: 'Revue' },
    { cle: 'groupes', nom: 'Groupes' },
    { cle: 'liaisons', nom: 'Liaisons' },
    { cle: 'export', nom: 'Export et kit' },
    { cle: 'icloud', nom: 'iCloud' },
    { cle: 'archives', nom: 'Archives' },
  ]

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
    Object.assign(statut, await api.get('/api/statut'))
  }

  $effect(() => {
    if (session.connecte) charger()
  })

  demarrer()

  let visible = $state(false)
  $effect(() => {
    if (!message.id) return
    visible = true
    const t = setTimeout(() => (visible = false), message.erreur ? 7000 : 3500)
    return () => clearTimeout(t)
  })

  async function deconnecter() {
    await api.post('/api/deconnexion')
    session.connecte = false
  }

  const progression = $derived(statut.total ? Math.round((statut.verifies / statut.total) * 100) : 0)

  // Vue iPhone : barre d'onglets en bas (Chercher, Photos, Plus), les autres pages dans « Plus »
  const mobile = $derived(ecran.etroit && !ecran.forcerPC)
  const ONGLETS_MOBILE = [
    { cle: 'chercher', nom: 'Chercher', pages: ['chercher', 'contacts', 'fiche', 'accueil'] },
    { cle: 'photos', nom: 'Photos', pages: ['photos'] },
    { cle: 'plus', nom: 'Plus', pages: [] },
  ]
  const ongletActif = $derived(ONGLETS_MOBILE.find((o) => o.pages.includes(route.page))?.cle ?? 'plus')
  // Sur iPhone, l'accueil et la liste des contacts deviennent « Chercher »
  const page = $derived(mobile && ['accueil', 'contacts'].includes(route.page) && !route.id ? 'chercher' : route.page)
</script>

{#snippet icone(cle)}
  <svg viewBox="0 0 24 24" class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    {#if cle === 'chercher'}<circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" />
    {:else if cle === 'photos'}<rect x="3.5" y="5" width="17" height="14" rx="3" /><circle cx="9" cy="10" r="1.6" /><path d="m4 17 5-4.5 3.5 3 3-2.5 4.5 4" />
    {:else}<circle cx="6" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="18" cy="12" r="1.3" />{/if}
  </svg>
{/snippet}

{#if session.connecte === false}
  <Connexion />
{:else if session.connecte}
  <div class="min-h-screen flex flex-col">
    {#if mobile}
      <header class="sticky top-0 z-20 border-b border-couture bg-cuir/90 backdrop-blur-md pt-[env(safe-area-inset-top)]">
        <div class="px-4 flex items-center h-12">
          <a href="#/chercher" class="titre text-xl text-papier">carnet</a>
          <span class="ml-auto text-xs text-mine tabular-nums">{statut.verifies} / {statut.total} vérifiés</span>
        </div>
      </header>
    {:else}
    <header class="border-b border-couture bg-reliure/60">
      <div class="mx-auto max-w-[1400px] px-6 flex items-center gap-8 h-14">
        <a href="#/accueil" class="titre text-xl text-papier">carnet</a>
        <nav class="flex gap-1 h-full" aria-label="Sections">
          {#each PAGES as p}
            <a
              href={`#/${p.cle}`}
              class="relative px-3 flex items-center text-sm transition-colors
                {route.page === p.cle ? 'text-papier' : 'text-mine hover:text-papier'}"
              aria-current={route.page === p.cle ? 'page' : undefined}
            >
              {p.nom}
              {#if p.cle === 'revision' && statut.a_reviser}
                <span class="ml-1.5 rounded-full bg-onglet-sombre text-onglet text-xs px-1.5 tabular-nums">{statut.a_reviser}</span>
              {/if}
              {#if route.page === p.cle}
                <span class="absolute left-2 right-2 bottom-0 h-0.5 bg-onglet rounded-t"></span>
              {/if}
            </a>
          {/each}
        </nav>
        <div class="ml-auto flex items-center gap-4 text-sm text-mine">
          <span class="tabular-nums" title="Contacts vérifiés">
            {statut.verifies} / {statut.total} vérifiés
          </span>
          <span class="w-28 h-1.5 rounded-full bg-couture overflow-hidden" aria-hidden="true">
            <span class="block h-full bg-valide" style="width: {progression}%"></span>
          </span>
          {#if ecran.etroit}<button class="hover:text-papier" onclick={() => choisirVue(false)}>Vue iPhone</button>{/if}
          <button class="hover:text-papier" onclick={deconnecter}>Se déconnecter</button>
        </div>
      </div>
    </header>
    {/if}

    <main class="flex-1 mx-auto w-full max-w-[1400px] {mobile ? 'px-4 pt-4 pb-[calc(5rem+env(safe-area-inset-bottom))]' : 'px-6 py-5'}">
      {#if page === 'chercher'}
        <Chercher />
      {:else if page === 'fiche'}
        <Fiche />
      {:else if page === 'photos'}
        <Photos />
      {:else if page === 'plus'}
        <Plus {deconnecter} />
      {:else if page === 'revision'}
        <Revision />
      {:else if route.page === 'contacts'}
        <Contacts />
      {:else if route.page === 'revue'}
        <Revue />
      {:else if route.page === 'export'}
        <Export />
      {:else if route.page === 'liaisons'}
        <Liaisons />
      {:else if route.page === 'groupes'}
        <Groupes />
      {:else if route.page === 'icloud'}
        <ICloud />
      {:else if route.page === 'archives'}
        <Archives />
      {:else}
        <Accueil />
      {/if}
    </main>

    {#if mobile}
      <nav class="fixed bottom-0 inset-x-0 z-30 border-t border-couture bg-reliure/90 backdrop-blur-md pb-[env(safe-area-inset-bottom)]"
        aria-label="Sections">
        <div class="grid grid-cols-3">
          {#each ONGLETS_MOBILE as o}
            <a href={`#/${o.cle}`} class="flex flex-col items-center justify-center gap-0.5 h-14 text-[11px] font-medium
              {ongletActif === o.cle ? 'text-onglet' : 'text-mine'}" aria-current={ongletActif === o.cle ? 'page' : undefined}>
              {@render icone(o.cle)}{o.nom}
            </a>
          {/each}
        </div>
      </nav>
    {/if}
  </div>
{/if}

{#if visible && message.texte}
  <div
    role="status"
    class="fixed {mobile ? 'bottom-[calc(4.5rem+env(safe-area-inset-bottom))] w-[calc(100%-2rem)]' : 'bottom-6'} left-1/2 -translate-x-1/2 max-w-xl px-4 py-2.5 rounded-lg border shadow-lg text-sm z-50
      {message.erreur ? 'bg-[#3a1f1f] border-alerte text-papier' : 'bg-reliure border-tranche text-papier'}"
  >
    {message.texte}
  </div>
{/if}
