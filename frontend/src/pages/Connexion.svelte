<script>
  import { api } from '../lib/api.js'
  let { onconnecte } = $props()
  let mot = $state('')
  let message = $state('')
  let attente = $state(false)

  async function entrer(e) {
    e.preventDefault()
    attente = true
    message = ''
    try {
      await api.post('/api/connexion', { mot_de_passe: mot })
      onconnecte()
    } catch (err) { message = err.message } finally { attente = false }
  }
</script>

<form class="connexion" onsubmit={entrer}>
  <h1 class="titre">carnet</h1>
  <label for="mdp" class="discret">Mot de passe</label>
  <input id="mdp" type="password" autocomplete="current-password" bind:value={mot} required />
  {#if message}<p class="erreur" role="alert">{message}</p>{/if}
  <button class="bouton bouton-principal" disabled={attente}>{attente ? 'Vérification…' : 'Ouvrir le carnet'}</button>
</form>

<style>
  .connexion { max-width: 20rem; margin: 22vh auto 0; padding: 0 1.25rem; display: grid; gap: 0.6rem; }
  h1 { font-size: 2.6rem; margin-bottom: 1rem; }
  .erreur { color: var(--color-alerte); }
</style>
