<script>
  // Vue iPhone : recherche dans les contacts vérifiés, liste au pouce, fiche en un toucher.
  import { api } from '../lib/api.js'
  import { ref } from '../lib/etat.svelte.js'
  import { cleTexte } from '../lib/cles.js'

  let tous = $state(null)
  let recherche = $state('')
  let groupe = $state('')

  api.get('/api/contacts').then((l) => (tous = l.filter((p) => p.statut !== 'ecarte')))

  const MAX = 150   // au-delà, affiner la recherche (la liste reste fluide)
  const filtres = $derived.by(() => {
    if (!tous) return []
    const q = cleTexte(recherche)
    const chiffres = recherche.replace(/\D/g, '')
    return tous.filter((p) =>
      (!groupe || p.groupes.includes(groupe)) &&
      (!q || cleTexte(`${p.nom} ${p.societe} ${p.courriel}`).includes(q)
        || (chiffres.length >= 3 && (p.telephone ?? '').replace(/\D/g, '').includes(chiffres))))
  })
</script>

<h1 class="sr-only">Chercher un contact</h1>
<div class="sticky top-[calc(3rem+env(safe-area-inset-top))] z-10 -mx-4 px-4 pt-1 pb-3 bg-cuir/95 backdrop-blur-md">
  <input class="w-full h-11 !rounded-xl !px-4 text-base" type="search" placeholder="Nom, société, courriel, numéro"
    bind:value={recherche} aria-label="Rechercher un contact" autocomplete="off" enterkeyhint="search" />
  <div class="flex gap-2 mt-2 overflow-x-auto -mx-4 px-4 pb-1" data-defile>
    <button class="shrink-0 h-8 px-3 rounded-full border text-sm {groupe === '' ? 'border-onglet text-papier' : 'border-couture text-mine'}"
      onclick={() => (groupe = '')}>Tous</button>
    {#each ref.groupes as g}
      <button class="shrink-0 h-8 px-3 rounded-full border text-sm {groupe === g ? 'border-onglet text-papier' : 'border-couture text-mine'}"
        aria-pressed={groupe === g} onclick={() => (groupe = groupe === g ? '' : g)}>{g}</button>
    {/each}
  </div>
</div>

{#if !tous}
  <p class="text-mine mt-6">Chargement…</p>
{:else}
  <p class="text-xs text-mine mb-2 tabular-nums">{filtres.length} contact{filtres.length > 1 ? 's' : ''}</p>
  <ul class="rounded-2xl border border-couture divide-y divide-couture overflow-hidden bg-reliure">
    {#each filtres.slice(0, MAX) as p (p.id)}
      <li>
        <a href={`#/fiche/${p.id}`} class="flex items-center gap-3 px-3 min-h-16 py-2 active:bg-couture">
          <span class="relative w-11 h-11 shrink-0 rounded-full overflow-hidden bg-couture grid place-items-center text-mine">
            {p.nom?.[0] ?? '?'}
            {#if p.photo}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/photos/${p.photo}?taille=88`}
              alt="" loading="lazy" width="44" height="44" onerror={(e) => e.currentTarget.remove()} />{/if}
          </span>
          <span class="flex-1 min-w-0">
            <span class="block truncate text-papier">{p.nom}</span>
            <span class="block truncate text-xs text-mine">{p.societe || p.telephone || p.courriel || p.groupes.join(', ')}</span>
          </span>
          <span class="text-mine" aria-hidden="true">›</span>
        </a>
      </li>
    {:else}
      <li class="px-4 py-6 text-mine text-sm">Aucun contact ne correspond.</li>
    {/each}
  </ul>
  {#if filtres.length > MAX}
    <p class="text-xs text-mine mt-3 text-center">{filtres.length - MAX} autres : précise la recherche.</p>
  {/if}
{/if}
