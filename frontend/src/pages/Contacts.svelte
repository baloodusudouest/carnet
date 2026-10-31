<script>
  import { api } from '../lib/api.js'
  import { ref, aller, annoncer } from '../lib/etat.svelte.js'
  import { cleTexte, sansAccents } from '../lib/cles.js'

  let tous = $state([])
  let recherche = $state('')
  let groupe = $state('')
  let filtre = $state('tous')
  let source = $state('')
  let injoignables = $state(false)
  let lettre = $state('')
  let choisis = $state(new Set())   // fiches cochées pour une fusion manuelle

  // Tous les contacts, y compris les relations LinkedIn sans contact (pour les rattacher à la main)
  const charger = () => api.get('/api/contacts?tout=true').then((l) => (tous = l))
  charger()

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
      (!source || p.sources.includes(source)) &&
      (!injoignables || !p.joignable) &&
      (filtre === 'tous' ? !['ecarte', 'linkedin'].includes(p.statut)
        : filtre === 'toutes_fiches' ? true
        : filtre === 'fusions' ? p.statut === 'a_reviser' && p.a_revoir === 'fusion manuelle' : p.statut === filtre))
  })
  const presentes = $derived(new Set(filtres.map((p) => initiale(p.nom))))
  const affiches = $derived(lettre ? filtres.filter((p) => initiale(p.nom) === lettre) : filtres)

  function cocher(id) {
    const n = new Set(choisis)
    n.has(id) ? n.delete(id) : n.add(id)
    choisis = n
  }
  const selection = $derived(tous.filter((p) => choisis.has(p.id)))
  const contactsChoisis = $derived(selection.filter((p) => p.statut !== 'linkedin').length)
  let fusionEnCours = $state(false)
  async function fusionner() {
    if (!confirm(`Réunir ${selection.length} fiches en un seul contact ?\n\n${selection.map((p) => '• ' + p.nom).join('\n')}\n\nLe choix des valeurs se fera ensuite dans la Révision.`)) return
    fusionEnCours = true
    try {
      const n = choisis.size
      await api.post('/api/contacts/fusion', { ids: [...choisis] })
      choisis = new Set()
      await charger()   // on reste ici : la fiche réunie est marquée « fusion à réviser »
      annoncer(`${n} fiches réunies : la fusion est à finir dans l'onglet Révision.`)
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      fusionEnCours = false
    }
  }
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
    <option value="tous">Contacts (vérifiés et à relire)</option>
    <option value="verifie">Vérifiés</option>
    <option value="a_reviser">À vérifier</option>
    <option value="ecarte">Mis de côté</option>
    <option value="fusions">Fusions à réviser</option>
    <option value="linkedin">LinkedIn uniquement (sans contact)</option>
    <option value="toutes_fiches">Toutes les fiches</option>
  </select>
  <select bind:value={source} aria-label="Source">
    <option value="">Toutes les sources</option>
    {#each Object.entries(ref.sources).filter(([k]) => k !== 'immich') as [k, v]}<option value={k}>{v}</option>{/each}
  </select>
  <label class="flex items-center gap-2 text-sm text-mine">
    <input type="checkbox" bind:checked={injoignables} /> Sans téléphone ni courriel
  </label>
  <p class="basis-full text-xs text-mine">Clique sur une ligne pour la cocher, sur le nom pour l'ouvrir.
    <span class="inline-block w-2.5 h-2.5 rounded-sm bg-[#a78bfa] align-middle ml-2"></span> fusion faite ici, à finir dans la Révision.</p>
</div>

{#if choisis.size}
  <div class="sticky top-2 z-20 mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-onglet/60 bg-reliure/95 backdrop-blur px-4 py-2.5 text-sm shadow-lg">
    <span>{choisis.size} fiche{choisis.size > 1 ? 's' : ''} cochée{choisis.size > 1 ? 's' : ''}</span>
    <span class="text-mine truncate max-w-xl">{selection.map((p) => p.nom).join(' · ')}</span>
    <span class="ml-auto flex gap-2">
      <button class="bouton !py-1" onclick={() => (choisis = new Set())}>Tout décocher</button>
      <button class="bouton bouton-principal !py-1" disabled={choisis.size < 2 || !contactsChoisis || fusionEnCours}
        title={!contactsChoisis ? 'LinkedIn ne crée pas de contact : coche aussi le contact à compléter' : ''}
        onclick={fusionner}>Fusionner</button>
    </span>
  </div>
{/if}

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
          <th class="w-10 pl-4 py-2.5"><span class="sr-only">Cocher pour fusionner</span></th>
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
          {@const fusion = p.statut === 'a_reviser' && p.a_revoir === 'fusion manuelle'}
          <tr class="border-t border-couture/70 hover:bg-reliure cursor-pointer
            {choisis.has(p.id) ? 'bg-onglet-sombre/30' : fusion ? 'bg-[#2b2238] shadow-[inset_3px_0_0_#a78bfa]' : ''}"
            onclick={() => cocher(p.id)}>
            <td class="pl-4 py-2" onclick={(e) => e.stopPropagation()}>
              <input type="checkbox" class="w-4 h-4 accent-[var(--color-onglet)]" checked={choisis.has(p.id)}
                onchange={() => cocher(p.id)} aria-label={`Cocher ${p.nom} pour une fusion`} />
            </td>
            <td class="px-4 py-2">
              {#if p.statut === 'linkedin'}<span>{p.nom}</span>
              {:else}<a href={`#/revision/${p.id}`} class="hover:text-onglet" onclick={(e) => e.stopPropagation()}>{p.nom}</a>{/if}
              {#if (p.societe || p.fonction) && !p.nom.includes(p.societe)}<span class="block text-xs text-mine">{[p.fonction, p.societe].filter(Boolean).join(' · ')}</span>{/if}
            </td>
            <td class="px-4 py-2 tabular-nums whitespace-nowrap">{p.telephone}</td>
            <td class="px-4 py-2 text-mine truncate max-w-56">{p.courriel}</td>
            <td class="px-4 py-2 text-sm text-mine">{p.groupes.join(', ')}</td>
            <td class="px-4 py-2 text-sm text-mine">{p.sources.map((s) => ref.sources[s]).join(', ')}</td>
            <td class="px-4 py-2 text-sm whitespace-nowrap">
              {#if p.statut === 'linkedin'}<span class="text-mine">LinkedIn seul</span>
              {:else if fusion}<span class="text-[#c4b5fd]">Fusion à réviser</span>
              {:else if p.statut === 'ecarte'}<span class="text-alerte">Mis de côté</span>
              {:else if p.statut === 'verifie'}<span class="text-valide">Vérifié</span>{#if p.brouillon}<span class="block text-xs text-onglet">modifié, à valider</span>{/if}
              {:else if p.doublon}<span class="text-onglet">Doublon à fusionner</span>
              {:else}<span class="text-mine">À relire</span>{/if}
            </td>
          </tr>
        {:else}
          <tr><td colspan="7" class="px-4 py-10 text-center text-mine">
            {tous.length ? 'Aucun contact ne correspond à ces filtres.' : 'Aucun contact : commence par importer un export depuis l’accueil.'}
          </td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
