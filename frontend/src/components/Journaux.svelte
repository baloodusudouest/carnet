<script>
  // 2.29 : « Pour les journaux » — ce que Julien sait d'une personne (passions, manies, petites histoires),
  // lu et complété par Gazette pour les rumeurs loufoques de La Récidive. Reste dans carnet : jamais dans iCloud.
  import { api } from '../lib/api.js'
  import { dire, erreur } from '../lib/etat.svelte.js'

  let { uid, journaux, onchange = () => {} } = $props()
  let brouillon = $state(null)
  let attente = $state(false)
  const j = $derived(journaux)

  function dateLisible(v) {
    return v ? `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}` : ''
  }
  async function enregistrer() {
    attente = true
    try {
      await api.put(`/api/contacts/${encodeURIComponent(uid)}/journaux`, { texte: brouillon })
      brouillon = null
      dire('« Pour les journaux » enregistré dans carnet.')
      onchange()
    } catch (err) { erreur(err) } finally { attente = false }
  }
</script>

<div class="feuille bloc journaux">
  <h2 class="titre">Pour les journaux</h2>
  {#if brouillon !== null}
    <form class="formulaire" onsubmit={(ev) => { ev.preventDefault(); enregistrer() }}>
      <label>
        <span>Ce qu'on sait d'elle ou de lui <span class="discret petit">(passions, manies, petites histoires)</span></span>
        <textarea rows="4" maxlength="600" bind:value={brouillon}></textarea>
      </label>
      <p class="discret petit">Pour les rumeurs loufoques de La Récidive (Gazette). Rangé dans carnet seulement : rien n'est écrit dans iCloud.</p>
      <div class="boutons-gauche">
        <button type="submit" class="bouton bouton-principal" disabled={attente}>{attente ? 'Enregistrement…' : 'Enregistrer'}</button>
        <button type="button" class="bouton" disabled={attente} onclick={() => (brouillon = null)}>Abandonner</button>
      </div>
    </form>
  {:else}
    {#if j.texte}
      <p class="texte">{j.texte}</p>
      <p class="discret petit">{j.par === 'gazette' ? 'Écrit depuis Gazette' : 'Écrit dans carnet'}{j.le ? ` le ${dateLisible(j.le)}` : ''}.</p>
    {:else}<p class="discret">Rien pour l'instant : Gazette le remplira quand tu écriras des indices pour les rumeurs.</p>{/if}
    <div class="boutons-gauche">
      <button class="bouton" onclick={() => (brouillon = j.texte || '')}>{j.texte ? 'Modifier' : 'Écrire'}</button>
    </div>
  {/if}
</div>

<style>
  .formulaire { display: grid; gap: 0.8rem; margin-top: 0.8rem; }
  .formulaire label { display: grid; gap: 0.3rem; }
  .texte { white-space: pre-line; margin: 0.8rem 0 0.3rem; }
</style>
