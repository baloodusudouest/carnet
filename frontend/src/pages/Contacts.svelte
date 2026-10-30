<script>
  import { api } from '../lib/api.js'
  import { ref, aller } from '../lib/etat.svelte.js'
  import { cleTexte, sansAccents } from '../lib/cles.js'

  let tous = $state([])
  let recherche = $state('')
  let groupe = $state('')
  let filtre = $state('tous')
  let lettre = $state('')

  api.get('/api/contacts').then((l) => (tous = l))

  const initiale = (nom) => {
    const c = sansAccents(nom).trim().charAt(0).toUpperCase()
    return /[A-Z]/.test(c) ? c : '#'
  }
  const ALPHABET = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '#']

  const filtres = $derived.by(() => {
    const q = cleTexte(recherche)
    return tous.filter((p) =>
      (!q || cleTexte(`${p.nom} ${p.societe} ${p.courriel} ${p.telephone}`).includes(q)) &&
      (!groupe || p.groupes.includes(groupe)) &&
      (filtre === 'tous' || (filtre === 'verifie' ? p.statut === 'verifie' : p.statut !== 'verifie')))
  })
  const presentes = $derived(new Set(filtres.map((p) => initiale(p.nom))))
  const affiches = $derived(lettre ? filtres.filter((p) => initiale(p.nom) === lettre) : filtres)
</script>

<div class="flex flex-wrap items-end gap-4 mb-6">
  <div>
    <h1 class="titre text-3xl">Contacts</h1>
    <p class="text-mine text-sm tabular-nums">{affiches.length} sur {tous.length}</p>
  </div>
  <input class="ml-auto w-72" type="search" placeholder="Nom, société, courriel, téléphone" bind:value={recherche}
    aria-label="Rechercher" />
  <select bind:value={groupe} aria-label="Groupe">
    <option value="">Tous les groupes</option>
    {#each ref.groupes as g}<option value={g}>{g}</option>{/each}
  </select>
  <select bind:value={filtre} aria-label="Statut">
    <option value="tous">Tous les statuts</option>
    <option value="verifie">Vérifiés</option>
    <option value="a_reviser">À relire</option>
  </select>
</div>

<div class="flex gap-0">
  <!-- Onglets alphabétiques, comme sur la tranche d'un carnet d'adresses -->
  <nav class="sticky top-6 self-start flex flex-col mr-4" aria-label="Initiales">
    <button class="text-xs w-8 py-1 rounded-l-md mb-1 {lettre === '' ? 'bg-onglet text-onglet-sombre font-semibold' : 'text-mine hover:text-papier'}"
      onclick={() => (lettre = '')}>tous</button>
    {#each ALPHABET as l}
      <button
        class="text-xs w-8 py-[3px] rounded-l-md transition-colors
          {lettre === l ? 'bg-onglet text-onglet-sombre font-semibold' : presentes.has(l) ? 'text-papier hover:bg-couture' : 'text-couture cursor-default'}"
        disabled={!presentes.has(l)} aria-pressed={lettre === l}
        onclick={() => (lettre = lettre === l ? '' : l)}>{l}</button>
    {/each}
  </nav>

  <div class="flex-1 min-w-0 rounded-xl border border-couture overflow-hidden {lettre ? 'border-l-onglet border-l-2' : ''}">
    <table class="w-full text-[0.93rem]">
      <thead class="bg-reliure text-mine text-sm">
        <tr>
          <th class="text-left font-normal px-4 py-2.5">Nom</th>
          <th class="text-left font-normal px-4 py-2.5">Téléphone</th>
          <th class="text-left font-normal px-4 py-2.5">Courriel</th>
          <th class="text-left font-normal px-4 py-2.5">Groupes</th>
          <th class="text-left font-normal px-4 py-2.5">Sources</th>
          <th class="text-left font-normal px-4 py-2.5">Statut</th>
        </tr>
      </thead>
      <tbody>
        {#each affiches as p (p.id)}
          <tr class="border-t border-couture/70 hover:bg-reliure cursor-pointer" onclick={() => aller('revision', p.id)}>
            <td class="px-4 py-2">
              <a href={`#/revision/${p.id}`} class="hover:text-onglet" onclick={(e) => e.stopPropagation()}>{p.nom}</a>
              {#if p.societe && !p.nom.includes(p.societe)}<span class="block text-xs text-mine">{p.societe}</span>{/if}
            </td>
            <td class="px-4 py-2 tabular-nums whitespace-nowrap">{p.telephone}</td>
            <td class="px-4 py-2 text-mine truncate max-w-56">{p.courriel}</td>
            <td class="px-4 py-2 text-sm text-mine">{p.groupes.join(', ')}</td>
            <td class="px-4 py-2 text-sm text-mine">{p.sources.map((s) => ref.sources[s]).join(', ')}</td>
            <td class="px-4 py-2 text-sm whitespace-nowrap">
              {#if p.statut === 'verifie'}<span class="text-valide">Vérifié</span>{#if p.brouillon}<span class="block text-xs text-onglet">modifié, à valider</span>{/if}
              {:else if p.doublon}<span class="text-onglet">Doublon à fusionner</span>
              {:else}<span class="text-mine">À relire</span>{/if}
            </td>
          </tr>
        {:else}
          <tr><td colspan="6" class="px-4 py-10 text-center text-mine">
            {tous.length ? 'Aucun contact ne correspond à ces filtres.' : 'Aucun contact : commence par importer un export depuis l’accueil.'}
          </td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
