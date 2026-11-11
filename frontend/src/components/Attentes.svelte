<script>
  // Ce que chaque groupe doit avoir (tableau des attentes). Dans Connexion depuis la 2.9.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  let tableau = $state(null)
  let enAttente = $state(null)   // case en cours de confirmation : { groupe, info, attendue, apercu }
  let attente = $state(false)
  async function charger() { try { tableau = await api.get('/api/attentes') } catch (e) { erreur(e) } }
  // Une case : carnet dit d'abord ce que ça change, puis on enregistre
  async function proposer(groupe, info, attendue) {
    try { enAttente = { groupe, info, attendue, apercu: await api.post('/api/attentes/apercu', { groupe, info, attendue }) } }
    catch (e) { erreur(e) }
  }
  async function enregistrer() {
    attente = true
    try {
      const r = await api.post('/api/attentes', { groupe: enAttente.groupe, info: enAttente.info, attendue: enAttente.attendue })
      tableau = r.tableau
      dire('Enregistré.')
      enAttente = null
      rafraichirContacts(); rafraichirAccueil()
    } catch (e) { erreur(e) } finally { attente = false }
  }
  const coche = (g, info) => enAttente?.groupe === g.nom && enAttente?.info === info ? enAttente.attendue : g.attentes.includes(info)
  const nomInfo = (cle) => tableau.infos.find((i) => i.cle === cle)?.nom
  onMount(charger)
</script>

{#if !tableau}
  <p class="discret">Chargement…</p>
{:else}
<div class="feuille bloc attentes">
  <h2 class="titre">Ce que chaque groupe doit avoir</h2>
  <p class="discret">Une case cochée : l'information est attendue pour les contacts du groupe. Les attentes de plusieurs groupes s'additionnent.
    Aujourd'hui, {tableau.total.incompletes} fiche(s) sur {tableau.total.fiches} ont au moins un manque.</p>

  {#if enAttente}
    <div class="confirmer" role="status">
      <p><strong>{enAttente.groupe}</strong> {enAttente.attendue ? 'attendra' : 'n\'attendra plus'} « {nomInfo(enAttente.info)} » :
        « {enAttente.apercu.libelle} » passera de {enAttente.apercu.avant} à {enAttente.apercu.apres} fiche(s).</p>
      <span class="boutons">
        <button class="bouton bouton-principal" disabled={attente} onclick={enregistrer}>Enregistrer</button>
        <button class="bouton" onclick={() => (enAttente = null)}>Annuler</button></span>
    </div>
  {/if}

  {#if etat.large}
    <div class="defile">
      <table>
        <thead><tr><th scope="col">Groupe</th>{#each tableau.infos as i}<th scope="col"><span>{i.nom}</span></th>{/each}</tr></thead>
        <tbody>
          {#each tableau.groupes as g (g.nom)}
            <tr>
              <th scope="row">{g.nom} <span class="discret">{g.nombre}</span></th>
              {#each tableau.infos as i}
                <td><input type="checkbox" checked={coche(g, i.cle)} aria-label={`${g.nom} : ${i.nom}`}
                           onchange={(ev) => { ev.currentTarget.checked = g.attentes.includes(i.cle); proposer(g.nom, i.cle, !g.attentes.includes(i.cle)) }} /></td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <!-- iPhone : un groupe à la fois, sa liste de cases -->
    {#each tableau.groupes as g (g.nom)}
      <details class="groupe">
        <summary><span>{g.nom} <span class="discret">{g.nombre}</span></span><span class="discret resume">{g.attentes.length ? `${g.attentes.length} attendue(s)` : 'rien'}</span></summary>
        <div class="cases">
          {#each tableau.infos as i}
            <label><input type="checkbox" checked={coche(g, i.cle)}
                          onchange={(ev) => { ev.currentTarget.checked = g.attentes.includes(i.cle); proposer(g.nom, i.cle, !g.attentes.includes(i.cle)) }} /> {i.nom}</label>
          {/each}
        </div>
      </details>
    {/each}
  {/if}
</div>

{/if}

<style>
  h2 { font-size: 1.2rem; }
  .bloc { padding: 1rem; display: grid; gap: 0.7rem; }
  .defile { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
  thead th { position: sticky; top: 0; background: var(--color-cuir); vertical-align: bottom; padding: 0.35rem 0.3rem; font-weight: 600;
    color: var(--color-mine); font-size: 0.78rem; text-align: center; min-width: 4.6rem; }
  thead th:first-child, tbody th { text-align: left; min-width: 11rem; }
  tbody th { font-weight: 600; padding: 0.3rem 0.5rem 0.3rem 0; white-space: nowrap; }
  tbody tr { border-top: 1px solid var(--color-couture); }
  td { text-align: center; padding: 0.3rem; }
  input[type='checkbox'] { accent-color: var(--color-onglet); width: 1.15rem; height: 1.15rem; }
  .confirmer { position: sticky; top: calc(0.5rem + env(safe-area-inset-top)); z-index: 2; display: grid; gap: 0.5rem; padding: 0.75rem 0.9rem;
    border: 1px solid var(--color-onglet); border-radius: 10px; background: var(--color-reliure); }
  .boutons { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .groupe { border-top: 1px solid var(--color-couture); }
  .groupe summary { display: flex; justify-content: space-between; align-items: center; min-height: 3rem; cursor: pointer; font-weight: 600; }
  .groupe .resume { font-weight: 400; font-size: 0.85rem; }
  .cases { display: grid; gap: 0.1rem; padding-bottom: 0.6rem; }
  .cases label { display: flex; align-items: center; gap: 0.6rem; min-height: 2.6rem; }
</style>
