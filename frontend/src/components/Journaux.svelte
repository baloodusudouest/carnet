<script>
  // 2.29 : « Pour les journaux » — ce que Julien sait d'une personne (passions, manies, petites histoires),
  // lu et complété par Gazette pour les rumeurs loufoques de La Récidive. Reste dans carnet : jamais dans iCloud.
  import { api } from '../lib/api.js'
  import { dire, erreur } from '../lib/etat.svelte.js'

  let { uid, journaux, onchange = () => {} } = $props()
  let brouillon = $state(null)
  let attente = $state(false)
  const j = $derived(journaux)

  const NOMS = { recidive: 'La Récidive', gazette: 'La Gazette' }
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

  <!-- 2.30 : numéros approuvés dans Gazette (lecture seule ici) -->
  <h3 class="sous-titre">Journaux parus</h3>
  {#if j.parus?.length}
    <ul class="parus">
      {#each j.parus as p (p.cle)}
        <li>
          <details>
            <summary><b>{dateLisible(p.le)} — {NOMS[p.journal] ?? p.journal}{p.numero ? ` N° ${p.numero}` : ''}</b>{p.titre ? ` · ${p.titre}` : ''}</summary>
            {#if p.evenement}<p class="petit"><span class="discret">Événement :</span> {p.evenement}</p>{/if}
            {#if p.indices}<p class="petit"><span class="discret">Indices :</span> {p.indices}</p>{/if}
            {#if p.descriptions?.length}<p class="petit discret">Photos (pour l'IA)</p><ul class="petit">{#each p.descriptions as x}<li>{x}</li>{/each}</ul>{/if}
            {#if p.textes?.length}<p class="petit discret">Imprimé</p><ul class="petit">{#each p.textes as x}<li>{x}</li>{/each}</ul>{/if}
          </details>
        </li>
      {/each}
    </ul>
  {:else}<p class="discret petit">Aucun numéro encore : Gazette en ajoute un à chaque Récidive approuvée.</p>{/if}
</div>

<style>
  .formulaire { display: grid; gap: 0.8rem; margin-top: 0.8rem; }
  .formulaire label { display: grid; gap: 0.3rem; }
  .texte { white-space: pre-line; margin: 0.8rem 0 0.3rem; }
  .sous-titre { font-size: 0.95rem; margin: 1.2rem 0 0.4rem; }
  .parus { display: grid; gap: 0.5rem; padding: 0; list-style: none; }
  .parus summary { cursor: pointer; overflow-wrap: anywhere; }
  .parus ul { margin: 0.2rem 0 0.4rem 1.1rem; padding: 0; }
  .parus p { margin: 0.3rem 0; overflow-wrap: anywhere; }
</style>
