<script>
  import { api } from '../lib/api.js'
  import { cleTexte } from '../lib/cles.js'

  let { exclure, choisir, fermer } = $props()
  let tous = $state([])
  let recherche = $state('')
  let actif = $state(0)
  let champ

  api.get('/api/contacts').then((l) => (tous = l.filter((p) => p.id !== exclure)))
  $effect(() => champ?.focus())

  const resultats = $derived.by(() => {
    const q = cleTexte(recherche)
    if (!q) return []
    return tous.filter((p) => cleTexte(`${p.nom} ${p.societe} ${p.courriel} ${p.telephone}`).includes(q)).slice(0, 8)
  })

  function touche(e) {
    if (e.key === 'Escape') fermer()
    else if (e.key === 'ArrowDown') { actif = Math.min(actif + 1, resultats.length - 1); e.preventDefault() }
    else if (e.key === 'ArrowUp') { actif = Math.max(actif - 1, 0); e.preventDefault() }
    else if (e.key === 'Enter' && resultats[actif]) { e.preventDefault(); choisir(resultats[actif]) }
  }
</script>

<div class="fixed inset-0 bg-black/60 grid place-items-start justify-center pt-[15vh] z-40" role="presentation"
  onclick={(e) => e.target === e.currentTarget && fermer()}>
  <div class="w-full max-w-lg rounded-xl border border-tranche bg-reliure p-5" role="dialog" aria-modal="true" aria-labelledby="titre-fusion">
    <h2 id="titre-fusion" class="titre text-xl mb-1">Fusionner avec un autre contact</h2>
    <p class="text-sm text-mine mb-4">Ses fiches rejoindront celle-ci, puis tu choisiras les valeurs à garder.</p>
    <input bind:this={champ} bind:value={recherche} oninput={() => (actif = 0)} onkeydown={touche}
      class="w-full" placeholder="Nom, société, courriel ou téléphone" aria-label="Rechercher un contact" />
    <ul class="mt-3 divide-y divide-couture">
      {#each resultats as p, i (p.id)}
        <li>
          <button class="w-full text-left px-3 py-2 rounded-md {i === actif ? 'bg-onglet-sombre/50' : 'hover:bg-couture/50'}"
            onclick={() => choisir(p)}>
            <span class="block">{p.nom}</span>
            <span class="block text-xs text-mine">{[p.telephone, p.courriel, p.societe].filter(Boolean).join(', ')}</span>
          </button>
        </li>
      {:else}
        {#if recherche}<li class="text-sm text-mine px-3 py-2">Aucun contact ne correspond.</li>{/if}
      {/each}
    </ul>
  </div>
</div>
