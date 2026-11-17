<script>
  // 2.28 : alimentation d'une personne (allergies, intolérances, « aucune connue », vérifiée le,
  // aliments non aimés, plaisirs coupables). Reste dans carnet : jamais écrite dans iCloud.
  // Home Assistant n'en reçoit que le statut (inconnu / aucune / à connaître).
  import { api } from '../lib/api.js'
  import { dire, erreur } from '../lib/etat.svelte.js'

  let { uid, alimentation, onchange = () => {} } = $props()
  const LISTES = ['allergies', 'intolerances', 'non_aimes', 'plaisirs']
  const AIDES = {
    allergies: 'séparées par des virgules',
    intolerances: 'séparées par des virgules',
    non_aimes: 'pour préparer les repas',
    plaisirs: 'pour l\'hôte seulement',
  }
  let brouillon = $state(null)
  let attente = $state(false)
  const a = $derived(alimentation)

  function dateLisible(v) {
    return v ? `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}` : ''
  }
  function modifier() {
    brouillon = { ...Object.fromEntries(LISTES.map((k) => [k, a[k].join(', ')])), aucune: a.aucune, verifiee: false }
  }
  const sante = $derived(brouillon && (brouillon.allergies.trim() || brouillon.intolerances.trim()))
  async function enregistrer() {
    attente = true
    try {
      await api.put(`/api/contacts/${encodeURIComponent(uid)}/alimentation`, {
        ...Object.fromEntries(LISTES.map((k) => [k, brouillon[k]])),
        aucune: brouillon.aucune && !sante, verifiee: brouillon.verifiee,
      })
      brouillon = null
      dire('Alimentation enregistrée dans carnet.')
      onchange()
    } catch (err) { erreur(err) } finally { attente = false }
  }
</script>

<div class="feuille bloc alimentation">
  <div class="ligne-titre">
    <h2 class="titre">Alimentation</h2>
    <span class={'statut statut-' + a.statut}>{a.statut_libelle}</span>
  </div>
  {#if brouillon}
    <form class="formulaire" onsubmit={(ev) => { ev.preventDefault(); enregistrer() }}>
      {#each LISTES as k}
        <label>
          <span>{a.libelles[k]} <span class="discret petit">({AIDES[k]})</span></span>
          <input type="text" bind:value={brouillon[k]} autocomplete="off" />
        </label>
      {/each}
      <label class="case">
        <input type="checkbox" bind:checked={brouillon.aucune} disabled={!!sante} />
        <span>Aucune allergie ni intolérance connue</span>
      </label>
      <label class="case">
        <input type="checkbox" bind:checked={brouillon.verifiee} />
        <span>Vérifié avec la personne aujourd'hui</span>
      </label>
      <p class="discret petit">Rangé dans carnet seulement : rien n'est écrit dans iCloud. Home Assistant ne reçoit que le statut.</p>
      <div class="boutons-gauche">
        <button type="submit" class="bouton bouton-principal" disabled={attente}>{attente ? 'Enregistrement…' : 'Enregistrer'}</button>
        <button type="button" class="bouton" disabled={attente} onclick={() => (brouillon = null)}>Abandonner</button>
      </div>
    </form>
  {:else}
    <dl>
      {#each LISTES as k}{#if a[k].length}<dt>{a.libelles[k]}</dt><dd>{a[k].join(', ')}</dd>{/if}{/each}
      {#if a.verifiee_le}<dt>Vérifiée le</dt><dd>{dateLisible(a.verifiee_le)}</dd>{/if}
    </dl>
    {#if a.statut === 'inconnu'}<p class="discret">Rien n'est connu : à demander avant un repas ou un séjour.</p>{/if}
    <div class="boutons-gauche">
      <button class="bouton" onclick={modifier}>{a.statut === 'inconnu' && !a.non_aimes.length && !a.plaisirs.length ? 'Renseigner' : 'Modifier'}</button>
    </div>
  {/if}
</div>

<style>
  .ligne-titre { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 0.4rem 1rem; }
  .statut { font-size: 0.85rem; padding: 0.15rem 0.6rem; border-radius: 999px; border: 1px solid currentColor; }
  .statut-inconnu { color: var(--color-mine); opacity: 0.85; }
  .statut-aucune { color: var(--color-valide); }
  .statut-a_connaitre { color: var(--color-alerte); font-weight: 600; }
  .formulaire { display: grid; gap: 0.8rem; margin-top: 0.8rem; }
  .formulaire label { display: grid; gap: 0.3rem; }
  .formulaire .case { display: flex; align-items: center; gap: 0.6rem; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.35rem 1rem; margin: 0.8rem 0; }
  dt { color: var(--color-mine); opacity: 0.8; }
  .boutons-gauche { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.6rem; }
</style>
