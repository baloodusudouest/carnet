<script>
  // Vue iPhone (et PC) : choisir la photo HD et l'affiche de chaque contact, au toucher.
  // Un toucher ouvre la proposition en grand ; « Choisir » l'applique. L'affiche choisie
  // s'enregistre dans Photos par la feuille de partage de l'iPhone.
  import { api } from '../lib/api.js'
  import { annoncer } from '../lib/etat.svelte.js'
  import { cleTexte } from '../lib/cles.js'

  let mode = $state('hd')                 // hd | affiche
  let filtre = $state('a_choisir')
  let recherche = $state('')
  let portraits = $state(null)
  let affiches = $state(null)
  let vue = $state(null)                  // { ligne, cand, src } : proposition ouverte en grand
  let occupe = $state(false)

  async function charger() {
    try {
      ;[portraits, affiches] = await Promise.all([api.get('/api/portraits'), api.get('/api/affiches')])
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  charger()

  const netteLisible = (c) => (c.ecran >= 0.5 ? 'pixélisé' : c.nettete == null ? '' : c.nettete >= 110 ? 'net' : c.nettete >= 70 ? 'assez net' : 'flou')
  const faceLisible = (f) => (f == null ? '' : f >= 0.7 ? 'de face' : f >= 0.4 ? 'trois quarts' : 'profil')

  // Lignes normalisées : { pid, nom, choisie, manuel, cands[], vignette(c), grande(c) }
  const lignes = $derived.by(() => {
    const q = cleTexte(recherche)
    let l = []
    if (mode === 'hd' && portraits) {
      l = portraits.lignes.map((x) => ({
        pid: x.pid, nom: x.nom, choisie: x.hd?.asset, manuel: !!x.hd?.manuel, photo: x.photo, le: x.hd?.le,
        cands: x.candidats, a_choisir: !x.hd && x.candidats.length,
      }))
    } else if (mode === 'affiche' && affiches) {
      l = affiches.lignes.map((x) => ({
        pid: x.pid, nom: x.nom, choisie: x.choisie, manuel: x.manuel, affiche: x.affiche,
        cands: x.propositions, a_choisir: !x.manuel && x.propositions.length,
      }))
    }
    return l.filter((x) => (!q || cleTexte(x.nom).includes(q)) &&
      (filtre === 'tous' || (filtre === 'a_choisir' ? x.a_choisir : x.manuel)))
  })
  const vignette = (l, c) => mode === 'hd' ? `/api/portraits/apercu/${l.pid}/${c.asset}` : `/api/affiches/proposition/${l.pid}/${c.asset}`
  const grande = (l, c) => mode === 'hd' ? `/api/portraits/apercu/${l.pid}/${c.asset}` : `/api/affiches/proposition/${l.pid}/${c.asset}?grand=true`

  async function choisir() {
    const { ligne, cand } = vue
    occupe = true
    try {
      await api.post(mode === 'hd' ? '/api/portraits/choix' : '/api/affiches/choix', { pid: ligne.pid, asset: cand.asset })
      annoncer(mode === 'hd' ? `Photo de ${ligne.nom} changée.` : `Affiche de ${ligne.nom} rangée dans l'album Immich.`)
      vue = null
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }

  // Enregistrer l'affiche choisie dans Photos : feuille de partage (« Enregistrer l'image »)
  async function enregistrer(l) {
    occupe = true
    try {
      const r = await fetch(`/api/affiches/image/${l.pid}`, { credentials: 'same-origin' })
      if (!r.ok) throw new Error("Affiche introuvable dans Immich.")
      const fichier = new File([await r.blob()], `affiche-${l.nom.replace(/[^\p{L}\p{N}]+/gu, '-')}.jpg`, { type: 'image/jpeg' })
      if (navigator.canShare?.({ files: [fichier] })) {
        await navigator.share({ files: [fichier] })
      } else {
        window.open(URL.createObjectURL(fichier), '_blank')
        annoncer("Appuie longuement sur l'image puis « Ajouter à Photos ».")
      }
    } catch (e) {
      if (e.name !== 'AbortError') annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }
</script>

<h1 class="titre text-2xl mb-3">Photos</h1>

<div class="grid grid-cols-2 p-1 rounded-xl bg-reliure border border-couture text-sm mb-3" role="tablist" aria-label="Type de photo">
  {#each [['hd', 'Photo du contact'], ['affiche', 'Affiche iPhone']] as [v, t]}
    <button role="tab" aria-selected={mode === v} class="h-9 rounded-lg {mode === v ? 'bg-couture text-papier' : 'text-mine'}"
      onclick={() => { mode = v; vue = null }}>{t}</button>
  {/each}
</div>

<input class="w-full h-11 !rounded-xl !px-4 text-base mb-2" type="search" placeholder="Filtrer par nom" bind:value={recherche}
  aria-label="Filtrer par nom" autocomplete="off" />
<div class="flex gap-2 text-sm mb-3" role="group" aria-label="Filtre">
  {#each [['a_choisir', 'À choisir'], ['choisies', 'Choisies'], ['tous', 'Tous']] as [v, t]}
    <button class="h-8 px-3 rounded-full border {filtre === v ? 'border-onglet text-papier' : 'border-couture text-mine'}"
      aria-pressed={filtre === v} onclick={() => (filtre = v)}>{t}</button>
  {/each}
</div>

{#if (mode === 'hd' && !portraits) || (mode === 'affiche' && !affiches)}
  <p class="text-mine">Chargement…</p>
{:else}
  {#if mode === 'affiche' && !affiches.groupes.length}
    <p class="text-sm text-mine mb-3">Aucun groupe choisi pour les affiches : coche-les sur PC, onglet Liaisons › Affiches iPhone.</p>
  {/if}
  <ul class="space-y-3">
    {#each lignes as l (l.pid)}
      <li class="rounded-2xl border border-couture bg-reliure p-3">
        <div class="flex items-center gap-2 mb-2">
          <span class="flex-1 min-w-0 truncate text-papier">{l.nom}</span>
          {#if l.manuel}<span class="text-xs text-valide">choisie ✓</span>{/if}
          {#if mode === 'affiche' && l.affiche}
            <button class="text-xs h-8 px-3 rounded-full border border-onglet text-onglet disabled:opacity-50" disabled={occupe}
              onclick={() => enregistrer(l)}>Enregistrer dans Photos</button>
          {/if}
        </div>
        {#if l.cands.length}
          <div class="flex gap-2 overflow-x-auto snap-x -mx-3 px-3 pb-1" data-defile>
            {#each l.cands as c (c.asset)}
              <button class="snap-start shrink-0 rounded-xl overflow-hidden border-2 {l.choisie === c.asset ? 'border-onglet' : 'border-transparent'}
                {mode === 'hd' ? 'w-20 h-20' : 'w-20 aspect-[9/19.5]'}" onclick={() => (vue = { ligne: l, cand: c })}
                aria-label={`Voir la photo de ${l.nom} en grand`}>
                <img class="w-full h-full object-cover bg-couture" src={vignette(l, c)} alt="" loading="lazy" />
              </button>
            {/each}
          </div>
        {:else}
          <p class="text-xs text-mine">Aucune photo qui convienne dans Immich.</p>
        {/if}
      </li>
    {:else}
      <li class="text-sm text-mine py-6 text-center">Rien dans ce filtre.</li>
    {/each}
  </ul>
{/if}

{#if vue}
  <div class="fixed inset-0 z-40 bg-black/90 flex flex-col pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]"
    role="dialog" aria-modal="true" aria-label={`Photo de ${vue.ligne.nom}`}>
    <div class="flex items-center px-4 h-12">
      <span class="flex-1 truncate text-papier">{vue.ligne.nom}</span>
      <button class="h-10 px-2 text-onglet" onclick={() => (vue = null)}>Fermer</button>
    </div>
    <div class="flex-1 min-h-0 grid place-items-center px-4">
      <img class="max-w-full max-h-full rounded-2xl object-contain {mode === 'hd' ? 'aspect-square w-full' : ''}"
        src={grande(vue.ligne, vue.cand)} alt="" />
    </div>
    <p class="text-center text-xs text-mine mt-2">{[netteLisible(vue.cand), faceLisible(vue.cand.face), vue.cand.le?.slice(0, 4)].filter(Boolean).join(' · ')}</p>
    <div class="p-4">
      <button class="w-full h-12 rounded-xl bg-onglet text-onglet-sombre font-semibold disabled:opacity-50"
        disabled={occupe || vue.ligne.choisie === vue.cand.asset && vue.ligne.manuel} onclick={choisir}>
        {vue.ligne.choisie === vue.cand.asset && vue.ligne.manuel ? 'Déjà choisie' : 'Choisir cette photo'}</button>
    </div>
  </div>
{/if}
