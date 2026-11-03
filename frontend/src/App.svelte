<script>
  import { onMount } from 'svelte'
  import { api } from './lib/api.js'
  import { etat, aller, annuler, rafraichirAccueil, rafraichirContacts } from './lib/etat.svelte.js'
  import Connexion from './pages/Connexion.svelte'
  import ATraiter from './pages/ATraiter.svelte'
  import Contacts from './pages/Contacts.svelte'
  import Fiche from './pages/Fiche.svelte'
  import Fusion from './pages/Fusion.svelte'
  import Etat from './pages/Etat.svelte'

  const onglets = [
    { page: 'a-traiter', nom: 'À traiter' },
    { page: 'contacts', nom: 'Contacts' },
    { page: 'etat', nom: 'État' },
  ]
  const actif = $derived(etat.route.page === 'fusion' ? 'a-traiter' : etat.route.page)
  const compte = $derived(etat.accueil?.a_traiter?.total ?? 0)
  const alerte = $derived(etat.accueil?.nuit?.erreur || etat.accueil?.tache?.etat === 'erreur')

  async function demarrer() {
    const s = await api.get('/api/session')
    etat.connecte = s.connecte
    if (s.connecte) { await rafraichirAccueil(); rafraichirContacts() }
  }

  onMount(() => {
    demarrer()
    let id
    const boucle = async () => {
      if (etat.connecte) await rafraichirAccueil()
      id = setTimeout(boucle, etat.accueil?.tache?.etat === 'en_cours' ? 3000 : 60000)
    }
    id = setTimeout(boucle, 3000)
    return () => clearTimeout(id)
  })
</script>

{#if etat.connecte === false}
  <Connexion onconnecte={demarrer} />
{:else if etat.connecte}
  <div class="cadre">
    <nav class="onglets" aria-label="Sections">
      <span class="marque titre">carnet</span>
      {#each onglets as o}
        <a href={'#/' + o.page} class="onglet" aria-current={actif === o.page ? 'page' : undefined}>
          <span>{o.nom}</span>
          {#if o.page === 'a-traiter' && compte}<span class="badge">{compte}</span>{/if}
          {#if o.page === 'etat' && alerte}<span class="point" aria-label="Problème à voir"></span>{/if}
        </a>
      {/each}
    </nav>

    <main class="contenu">
      {#if etat.accueil?.tache?.etat === 'en_cours'}
        <p class="tache" role="status">{etat.accueil.tache.message}</p>
      {/if}
      {#if etat.route.page === 'contacts' && etat.route.args[0]}
        {#key etat.route.args[0]}<Fiche uid={etat.route.args[0]} />{/key}
      {:else if etat.route.page === 'contacts'}
        <Contacts />
      {:else if etat.route.page === 'fusion'}
        <Fusion a={etat.route.args[0]} b={etat.route.args[1]} />
      {:else if etat.route.page === 'etat'}
        <Etat />
      {:else}
        <ATraiter />
      {/if}
    </main>
  </div>

  {#if etat.message}
    <div class="message" class:erreur={etat.message.erreur} role={etat.message.erreur ? 'alert' : 'status'}>
      <span>{etat.message.texte}</span>
      {#if etat.message.jeton}
        <button class="bouton" onclick={() => { const j = etat.message.jeton; etat.message = null; annuler(j) }}>Annuler</button>
      {/if}
    </div>
  {/if}
{/if}

<style>
  .cadre { min-height: 100dvh; }
  .contenu { padding: 1rem 1rem calc(5.5rem + env(safe-area-inset-bottom)); max-width: 72rem; margin: 0 auto; }
  .onglets {
    position: fixed; z-index: 20; left: 0; right: 0; bottom: 0; display: flex;
    background: var(--color-reliure); border-top: 1px solid var(--color-couture);
    padding-bottom: env(safe-area-inset-bottom);
  }
  .marque { display: none; }
  .onglet {
    flex: 1; display: flex; align-items: center; justify-content: center; gap: 0.4rem;
    min-height: 3.25rem; color: var(--color-mine); font-weight: 500; position: relative;
  }
  .onglet[aria-current='page'] { color: var(--color-papier); }
  .onglet[aria-current='page']::before {
    content: ''; position: absolute; top: -1px; left: 25%; right: 25%; height: 3px; border-radius: 0 0 3px 3px;
    background: var(--color-onglet);
  }
  .badge {
    min-width: 1.4rem; padding: 0 0.35rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600;
    background: var(--color-onglet); color: #23190a; text-align: center;
  }
  .point { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--color-alerte); }
  .tache { margin-bottom: 0.75rem; padding: 0.5rem 0.8rem; border-left: 3px solid var(--color-onglet); color: var(--color-mine); }
  .message {
    position: fixed; z-index: 30; left: 1rem; right: 1rem; bottom: calc(4.25rem + env(safe-area-inset-bottom));
    display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    max-width: 34rem; margin: 0 auto; padding: 0.6rem 0.6rem 0.6rem 1rem; border-radius: 10px;
    background: #2f2723; border: 1px solid var(--color-tranche); box-shadow: 0 8px 24px rgb(0 0 0 / 0.45);
  }
  .message.erreur { border-color: var(--color-alerte); }
  @media (min-width: 900px) {
    .onglets {
      top: 0; right: auto; width: 13rem; flex-direction: column; align-items: stretch; gap: 0.15rem;
      border-top: 0; border-right: 1px solid var(--color-couture); padding: 1.25rem 0.75rem;
    }
    .marque { display: block; font-size: 1.6rem; padding: 0 0.75rem 1.25rem; color: var(--color-papier); }
    .onglet { flex: none; justify-content: space-between; padding: 0 0.75rem; min-height: 2.75rem; border-radius: 8px; }
    .onglet[aria-current='page'] { background: color-mix(in srgb, var(--color-onglet) 10%, transparent); }
    .onglet[aria-current='page']::before { top: 25%; bottom: 25%; left: 0; right: auto; width: 3px; height: auto; border-radius: 0 3px 3px 0; }
    .contenu { margin-left: 13rem; padding: 1.75rem 2.5rem 3rem; }
    .message { bottom: 1.5rem; left: 14rem; }
  }
</style>
