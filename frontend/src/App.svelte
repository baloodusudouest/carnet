<script>
  import { api } from './lib/api.js'
  import { session, ref, statut, message, route, aller } from './lib/etat.svelte.js'
  import Connexion from './pages/Connexion.svelte'
  import Accueil from './pages/Accueil.svelte'
  import Revision from './pages/Revision.svelte'
  import Contacts from './pages/Contacts.svelte'
  import Export from './pages/Export.svelte'
  import Archives from './pages/Archives.svelte'
  import Revue from './pages/Revue.svelte'
  import ICloud from './pages/ICloud.svelte'
  import Groupes from './pages/Groupes.svelte'

  const PAGES = [
    { cle: 'accueil', nom: 'Accueil' },
    { cle: 'revision', nom: 'Révision' },
    { cle: 'contacts', nom: 'Contacts' },
    { cle: 'revue', nom: 'Revue' },
    { cle: 'groupes', nom: 'Groupes' },
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
</script>

{#if session.connecte === false}
  <Connexion />
{:else if session.connecte}
  <div class="min-h-screen flex flex-col">
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
          <button class="hover:text-papier" onclick={deconnecter}>Se déconnecter</button>
        </div>
      </div>
    </header>

    <main class="flex-1 mx-auto w-full max-w-[1400px] px-6 py-5">
      {#if route.page === 'revision'}
        <Revision />
      {:else if route.page === 'contacts'}
        <Contacts />
      {:else if route.page === 'revue'}
        <Revue />
      {:else if route.page === 'export'}
        <Export />
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
  </div>
{/if}

{#if visible && message.texte}
  <div
    role="status"
    class="fixed bottom-6 left-1/2 -translate-x-1/2 max-w-xl px-4 py-2.5 rounded-lg border shadow-lg text-sm z-50
      {message.erreur ? 'bg-[#3a1f1f] border-alerte text-papier' : 'bg-reliure border-tranche text-papier'}"
  >
    {message.texte}
  </div>
{/if}
