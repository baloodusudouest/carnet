<script>
  // Liste repliable des personnes importées qui ne sont liées à aucune fiche.
  // Filtre, affichage par paquets de 30 ; « Rattacher » ouvre une recherche de fiche
  // pré-remplie avec le nom (un seul champ ouvert à la fois, pas un menu par ligne).
  import { etat } from '../lib/etat.svelte.js'
  import { cleTexte } from '../lib/texte.js'

  let {
    titre = 'Importés sans fiche', items = null, charger = null,
    rattacher, detacher = null, detail = () => '', cle = (x) => x.ext_id,
  } = $props()

  let ouvert = $state(false)
  let liste = $state(null)            // chargée à la première ouverture si `charger` est donné
  let filtre = $state('')
  let limite = $state(30)
  let choix = $state(null)            // clé de la ligne en cours de rattachement
  let recherche = $state('')
  let attente = $state(false)

  const source = $derived(items ?? liste)
  const nombre = $derived(source?.length ?? null)
  const visibles = $derived.by(() => {
    const q = cleTexte(filtre)
    return (source || []).filter((x) => !q || cleTexte(`${x.nom} ${detail(x)} ${x.pseudo || ''}`).includes(q))
  })
  const fiches = $derived.by(() => {
    const q = cleTexte(recherche)
    if (q.length < 2) return []
    return (etat.contacts || []).filter((c) => cleTexte(c.nom).includes(q)).slice(0, 8)
  })

  async function basculer() {
    ouvert = !ouvert
    if (ouvert && charger && liste === null) liste = await charger()
  }
  export async function recharger() { if (charger) liste = await charger() }
  // Recherche pré-remplie avec le nom de famille (rien pour un pseudo sans espace)
  function ouvrirChoix(x) { choix = cle(x); recherche = /\s/.test(x.nom.trim()) ? x.nom.trim().split(/\s+/).slice(-1)[0] : '' }
  async function lier(x, uid) {
    attente = true
    try { await rattacher(x, uid); choix = null; if (charger) liste = await charger() } finally { attente = false }
  }
  async function enlever(x) {
    attente = true
    try { await detacher(x); if (charger) liste = await charger() } finally { attente = false }
  }
</script>

<div class="non-lies">
  <button class="entete" aria-expanded={ouvert} onclick={basculer}>
    <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
    <span>{titre}{#if nombre !== null}{' '}({nombre}){/if}</span>
    <span class="action">{ouvert ? 'Réduire' : 'Développer'}</span>
  </button>

  {#if ouvert}
    {#if source === null}
      <p class="discret">Chargement…</p>
    {:else if !source.length}
      <p class="discret">Tout le monde est rattaché à une fiche.</p>
    {:else}
      {#if source.length > 10}
        <input type="search" bind:value={filtre} placeholder="Filtrer par nom, société, pseudo…" aria-label="Filtrer la liste"
               oninput={() => (limite = 30)} />
      {/if}
      <ul>
        {#each visibles.slice(0, limite) as x (cle(x))}
          <li>
            <span class="qui">
              <span class="nom">{x.nom}{#if x.propose}<span class="propose">proposé dans À traiter</span>{/if}</span>
              {#if detail(x)}<span class="discret">{detail(x)}</span>{/if}
            </span>
            {#if choix === cle(x)}
              <div class="choix">
                <input type="search" bind:value={recherche} placeholder="Chercher la fiche…" aria-label="Fiche à rattacher" />
                <ul class="fiches" role="listbox" aria-label="Fiches trouvées">
                  {#each fiches as f (f.uid)}
                    <li><button class="bouton" disabled={attente} onclick={() => lier(x, f.uid)}>{f.nom}</button></li>
                  {:else}
                    <li class="discret">{recherche.length < 2 ? 'Tape au moins 2 lettres.' : 'Aucune fiche à ce nom.'}</li>
                  {/each}
                </ul>
                <button class="bouton" onclick={() => (choix = null)}>Fermer</button>
              </div>
            {:else}
              <span class="boutons">
                <button class="bouton" disabled={attente} onclick={() => ouvrirChoix(x)}>Rattacher…</button>
                {#if detacher}<button class="bouton" disabled={attente} onclick={() => enlever(x)}>Détacher</button>{/if}
              </span>
            {/if}
          </li>
        {/each}
      </ul>
      {#if visibles.length > limite}
        <button class="bouton plus" onclick={() => (limite += 30)}>Afficher 30 de plus ({visibles.length - limite} restantes)</button>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .non-lies { display: grid; gap: 0.5rem; }
  .entete {
    display: flex; align-items: center; gap: 0.5rem; min-height: 2.75rem; padding: 0 0.75rem; border-radius: 8px;
    border: 1px solid var(--color-couture); font-weight: 600; text-align: left;
  }
  .entete:hover { border-color: var(--color-tranche); }
  .entete:focus-visible { outline: 2px solid var(--color-onglet); outline-offset: 2px; }
  .chevron { width: 1.1rem; height: 1.1rem; fill: none; stroke: var(--color-onglet); stroke-width: 2.2; stroke-linecap: round;
    stroke-linejoin: round; transition: transform 0.2s ease; flex: none; }
  [aria-expanded='true'] .chevron { transform: rotate(90deg); }
  .action { margin-left: auto; font-size: 0.82rem; font-weight: 500; color: var(--color-mine); }
  ul { display: grid; gap: 0.1rem; }
  li { display: grid; gap: 0.4rem; padding: 0.5rem 0; border-bottom: 1px solid var(--color-couture); }
  .qui { display: grid; }
  .nom { font-weight: 600; display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem; }
  .propose { font-size: 0.75rem; font-weight: 500; color: var(--color-onglet); }
  .boutons { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .choix { display: grid; gap: 0.4rem; padding: 0.6rem; border-radius: 8px; background: color-mix(in srgb, var(--color-papier) 4%, transparent); }
  .fiches { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .fiches li { border: 0; padding: 0; }
  .plus, .choix > .bouton { justify-self: start; }
  @media (prefers-reduced-motion: reduce) { .chevron { transition: none; } }
</style>
