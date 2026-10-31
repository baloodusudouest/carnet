<script>
  // Vue iPhone : fiche d'un contact en lecture, avec les actions de l'iPhone
  // (appeler, message, courriel, Plans). La modification se fait sur PC, dans la Révision.
  import { api } from '../lib/api.js'
  import { route, annoncer } from '../lib/etat.svelte.js'
  import { anniversaireLisible, texteItem } from '../lib/cles.js'

  let dossier = $state(null)
  $effect(() => {
    const id = route.id
    dossier = null
    if (id) api.get(`/api/personnes/${id}`).then((d) => (dossier = d)).catch((e) => annoncer(e.message, true))
  })
  const f = $derived(dossier?.fiche)
  const nom = $derived(f ? [f.prenom, f.nom].filter(Boolean).join(' ') || f.societe || f.surnom || '(sans nom)' : '')
  const mobile = $derived(f?.telephones.find((t) => t.type === 'mobile' || t.type === 'travail') ?? f?.telephones[0])
  const lienPlans = (a) => `https://maps.apple.com/?q=${encodeURIComponent(texteItem('adresses', a))}`
  const lienSite = (v) => (/^[a-z]+:/i.test(v) ? v : `https://${v}`)
</script>

{#snippet action(href, libelle, chemin)}
  <a {href} class="flex-1 flex flex-col items-center gap-1 rounded-2xl bg-reliure border border-couture py-2.5 text-xs text-papier active:bg-couture
    {href ? '' : 'pointer-events-none opacity-40'}" aria-disabled={!href}>
    <svg viewBox="0 0 24 24" class="w-5 h-5 text-onglet" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html chemin}</svg>
    {libelle}
  </a>
{/snippet}

{#snippet section(titre, champ, items)}
  {#if items?.length}
    <section class="mt-4">
      <h2 class="text-xs uppercase tracking-wide text-mine mb-1.5 px-1">{titre}</h2>
      <ul class="rounded-2xl border border-couture divide-y divide-couture overflow-hidden bg-reliure">
        {#each items as it}
          {@const href = champ === 'telephones' ? `tel:${it.valeur}` : champ === 'courriels' ? `mailto:${it.valeur}`
            : champ === 'adresses' ? lienPlans(it) : lienSite(it.valeur)}
          <li>
            <a {href} class="flex items-center gap-3 px-4 min-h-12 py-2 active:bg-couture">
              <span class="flex-1 min-w-0">
                <span class="block text-[11px] text-mine">{it.type || ''}</span>
                <span class="block text-onglet break-words">{texteItem(champ, it)}</span>
              </span>
            </a>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
{/snippet}

<a href="#/chercher" onclick={(e) => { if (history.length > 1) { e.preventDefault(); history.back() } }}
  class="inline-flex items-center gap-1 text-onglet text-sm h-10">‹ Chercher</a>

{#if !f}
  <p class="text-mine mt-6">Chargement…</p>
{:else}
  <div class="flex flex-col items-center text-center mt-1">
    <span class="relative w-28 h-28 rounded-full overflow-hidden bg-couture grid place-items-center text-4xl text-mine">
      {nom[0]}
      {#if f.photo}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/photos/${f.photo}?taille=240`} alt=""
        width="112" height="112" onerror={(e) => e.currentTarget.remove()} />{/if}
    </span>
    <h1 class="titre text-2xl mt-3 leading-tight">{nom}</h1>
    {#if f.surnom}<p class="text-mine text-sm">« {f.surnom} »</p>{/if}
    {#if f.fonction || f.societe}<p class="text-mine text-sm">{[f.fonction, f.societe].filter(Boolean).join(' · ')}</p>{/if}
  </div>

  <div class="flex gap-2 mt-4">
    {@render action(mobile ? `tel:${mobile.valeur}` : null, 'Appeler',
      '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>')}
    {@render action(mobile ? `sms:${mobile.valeur}` : null, 'Message',
      '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>')}
    {@render action(f.courriels[0] ? `mailto:${f.courriels[0].valeur}` : null, 'Courriel',
      '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>')}
  </div>

  {@render section('Téléphones', 'telephones', f.telephones)}
  {@render section('Courriels', 'courriels', f.courriels)}
  {@render section('Adresses', 'adresses', f.adresses)}
  {@render section('Sites et réseaux', 'sites', f.sites)}

  {#if f.anniversaire}
    <section class="mt-4 rounded-2xl border border-couture bg-reliure px-4 py-2.5">
      <span class="block text-[11px] text-mine">anniversaire</span>{anniversaireLisible(f.anniversaire)}
    </section>
  {/if}
  {#if f.noms_associes?.length}
    <section class="mt-4">
      <h2 class="text-xs uppercase tracking-wide text-mine mb-1.5 px-1">Proches</h2>
      <ul class="rounded-2xl border border-couture divide-y divide-couture bg-reliure">
        {#each f.noms_associes as n}<li class="px-4 py-2.5"><span class="block text-[11px] text-mine">{n.type}</span>{n.valeur}</li>{/each}
      </ul>
    </section>
  {/if}
  {#if f.notes}
    <section class="mt-4 rounded-2xl border border-couture bg-reliure px-4 py-2.5 whitespace-pre-line break-words">
      <span class="block text-[11px] text-mine">notes</span>{f.notes}
    </section>
  {/if}
  {#if f.groupes.length}
    <div class="flex flex-wrap gap-1.5 mt-4">
      {#each f.groupes as g}<span class="text-xs rounded-full px-2.5 py-1 border border-couture text-mine">{g}</span>{/each}
    </div>
  {/if}
  <p class="text-xs text-mine mt-6 text-center">Pour modifier ce contact, ouvre carnet sur ton PC (onglet Révision).</p>
{/if}
