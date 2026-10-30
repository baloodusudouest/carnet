<script>
  import { api } from '../lib/api.js'
  import { session } from '../lib/etat.svelte.js'

  let motDePasse = $state('')
  let erreur = $state('')
  let attente = $state(false)

  async function connecter(e) {
    e.preventDefault()
    attente = true
    erreur = ''
    try {
      await api.post('/api/connexion', { mot_de_passe: motDePasse })
      session.connecte = true
    } catch (err) {
      erreur = err.message
      motDePasse = ''
    } finally {
      attente = false
    }
  }
</script>

<div class="min-h-screen grid place-items-center px-6">
  <form onsubmit={connecter} class="w-full max-w-sm">
    <div class="relative rounded-xl border border-couture bg-reliure px-8 pt-10 pb-8">
      <!-- Onglets d'un carnet d'adresses, sur la tranche droite -->
      <div class="absolute -right-3 top-8 flex flex-col gap-1.5" aria-hidden="true">
        {#each ['A', 'F', 'M', 'S'] as l, i}
          <span class="w-3 h-7 rounded-r-md text-[10px] grid place-items-center
            {i === 0 ? 'bg-onglet text-onglet-sombre' : 'bg-couture text-mine'}">{l}</span>
        {/each}
      </div>
      <h1 class="titre text-4xl mb-1">carnet</h1>
      <p class="text-mine mb-8">Tes contacts, relus un par un.</p>
      <label class="block text-sm text-mine mb-1.5" for="mdp">Mot de passe</label>
      <!-- svelte-ignore a11y_autofocus -->
      <input id="mdp" type="password" autocomplete="current-password" class="w-full" autofocus
        bind:value={motDePasse} required />
      {#if erreur}
        <p class="text-alerte text-sm mt-2" role="alert">{erreur}</p>
      {/if}
      <button class="bouton bouton-principal w-full justify-center mt-6" disabled={attente}>
        {attente ? 'Vérification…' : 'Ouvrir le carnet'}
      </button>
    </div>
  </form>
</div>
