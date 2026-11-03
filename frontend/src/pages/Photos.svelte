<script>
  // Vue iPhone (et PC) : choisir la photo HD et l'affiche de chaque contact, au toucher.
  // Un toucher ouvre la proposition en grand ; « Choisir » l'applique. L'affiche choisie
  // s'enregistre dans Photos par la feuille de partage de l'iPhone.
  import { api } from '../lib/api.js'
  import { annoncer, ref } from '../lib/etat.svelte.js'
  import { cleTexte, dateCourte } from '../lib/cles.js'
  import Logos from '../components/Logos.svelte'

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
        pid: x.pid, nom: x.nom, choisie: x.choisie, manuel: x.manuel, affiche: x.affiche, posee: x.posee,
        cands: x.propositions, a_choisir: !x.manuel && x.propositions.length,
      }))
    }
    return l.filter((x) => (!q || cleTexte(x.nom).includes(q)) &&
      (filtre === 'tous' || (filtre === 'a_choisir' ? x.a_choisir : filtre === 'a_poser' ? x.affiche && !x.posee
        : filtre === 'posees' ? x.posee : x.manuel)))
  })
  const vignette = (l, c) => mode === 'hd' ? `/api/portraits/apercu/${l.pid}/${c.asset}` : `/api/affiches/proposition/${l.pid}/${c.asset}`
  const grande = (l, c) => mode === 'hd' ? `/api/portraits/apercu/${l.pid}/${c.asset}` : `/api/affiches/proposition/${l.pid}/${c.asset}?grand=true`

  // Recherche de tout (photos HD, affiches, logos) en une fois, avec la progression de chaque étape
  let tache = $state(null)
  let menuRecherche = $state(false)
  let version = $state(0)               // recharge l'onglet Logos après une recherche
  const OPERATIONS = ['photos', 'portraits', 'affiches', 'logos']
  const enCours = $derived(['lecture', 'ecriture'].includes(tache?.etat) && OPERATIONS.includes(tache?.operation))
  const avancement = $derived(tache?.total ? Math.round((100 * tache.fait) / tache.total) : null)
  async function suivre(annoncerFin = false) {
    try {
      tache = (await api.get('/api/icloud')).tache
    } catch {
      return
    }
    if (['lecture', 'ecriture'].includes(tache?.etat)) {
      if (OPERATIONS.includes(tache?.operation)) setTimeout(() => suivre(true), 1000)
    } else if (annoncerFin) {
      if (tache?.message) annoncer(tache.message, tache.etat === 'erreur')
      await charger()
      version += 1
    }
  }
  suivre()   // une recherche lancée avant d'ouvrir la page : sa progression s'affiche
  async function rechercher(mode) {
    menuRecherche = false
    try {
      await api.post('/api/photos/recherche', { mode })
      await suivre(true)
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  const derniereRecherche = $derived(affiches?.journal?.[0]?.le ?? portraits?.journal?.[0]?.le)

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

  // Enregistrer des affiches dans Photos par la feuille de partage de l'iPhone (« Enregistrer N images »).
  // Safari n'ouvre la feuille de partage que juste après un toucher : les images sont d'abord
  // préparées (téléchargées), puis un second toucher ouvre le partage. Par lots de 20.
  // Cet appareil retient ce qui est déjà dans sa pellicule (une affiche changée est reproposée).
  const LOT = 20
  const CLE_DEJA = 'carnet-affiches-enregistrees'
  function lireDeja() {
    try {
      return JSON.parse(localStorage.getItem(CLE_DEJA) || '{}')
    } catch {
      return {}
    }
  }
  let deja = $state(lireDeja())    // pid → identifiant de l'affiche déjà enregistrée sur cet appareil
  function noterDeja(lignesFaites) {
    for (const l of lignesFaites) deja[l.pid] = l.affiche
    try {
      localStorage.setItem(CLE_DEJA, JSON.stringify(deja))
    } catch {
      /* navigation privée : non retenu */
    }
  }
  function toutReproposer() {
    deja = {}
    try {
      localStorage.removeItem(CLE_DEJA)
    } catch {
      /* rien */
    }
  }
  let pret = $state(null)        // { titre, fichiers: File[], lignes } prêt à partager
  const toutes = $derived(affiches ? affiches.lignes.filter((x) => x.affiche) : [])
  // Export : seulement celles pas encore posées sur l'iPhone, ou toutes
  let portee = $state('a_poser')
  const aPoser = $derived(toutes.filter((x) => !x.posee))
  const perimetre = $derived(portee === 'a_poser' ? aPoser : toutes)
  const restantes = $derived(perimetre.filter((x) => deja[x.pid] !== x.affiche))

  // Coche « posée sur l'iPhone » (Apple ne met pas l'affiche dans iCloud : carnet ne peut pas le voir)
  async function marquerPosee(l, posee) {
    try {
      const r = await api.post('/api/affiches/posee', { pid: l.pid, posee })
      const x = affiches.lignes.find((y) => y.pid === l.pid)
      if (x) x.posee = r.posee
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  const lotCourant = $derived(restantes.slice(0, LOT))

  async function preparer(lignesAffiches, titre) {
    occupe = true
    pret = null
    try {
      const fichiers = [], lignesOk = []
      for (const l of lignesAffiches) {
        const r = await fetch(`/api/affiches/image/${l.pid}`, { credentials: 'same-origin' })
        if (!r.ok) continue
        fichiers.push(new File([await r.blob()], `${l.nom.replace(/[\\/:*?"<>|]+/g, ' ').trim()}.jpg`, { type: 'image/jpeg' }))
        lignesOk.push(l)
      }
      if (!fichiers.length) throw new Error('Aucune affiche trouvée dans Immich.')
      pret = { titre, fichiers, lignes: lignesOk }
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }

  async function partager() {
    const { fichiers, lignes: faites } = pret
    try {
      if (navigator.canShare?.({ files: fichiers })) {
        await navigator.share({ files: fichiers })
        noterDeja(faites)
        pret = null
      } else {
        for (const f of fichiers) window.open(URL.createObjectURL(f), '_blank')
        annoncer("Partage indisponible ici : appuie longuement sur chaque image puis « Ajouter à Photos ».")
        noterDeja(faites)
        pret = null
      }
    } catch (e) {
      if (e.name !== 'AbortError') annoncer(e.message, true)
    }
  }

  const pluralAff = (n) => (n > 1 ? `les ${n} affiches` : "l'affiche")
  const enregistrer = (l) => preparer([{ ...l, affiche: affiches.lignes.find((x) => x.pid === l.pid)?.affiche }], `l'affiche de ${l.nom}`)
</script>

<div class="flex items-center gap-2 mb-3">
  <h1 class="titre text-2xl flex-1">Photos</h1>
  <div class="relative">
    <button class="w-11 h-11 rounded-full border border-couture text-onglet grid place-items-center disabled:opacity-50"
      aria-label="Chercher les photos, affiches et logos" aria-expanded={menuRecherche} disabled={enCours}
      onclick={() => (menuRecherche = !menuRecherche)}>
      <svg viewBox="0 0 24 24" class="w-5 h-5 {enCours ? 'animate-spin' : ''}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M20 12a8 8 0 1 1-2.34-5.66" /><path d="M20 4v5h-5" /></svg>
    </button>
    {#if menuRecherche}
      <button class="fixed inset-0 z-30 cursor-default" aria-label="Fermer" onclick={() => (menuRecherche = false)}></button>
      <div class="absolute right-0 top-12 z-40 w-72 rounded-2xl border border-tranche bg-reliure shadow-2xl p-2 text-sm" role="menu">
        <p class="px-2 pt-1 pb-2 text-xs text-mine">Photos HD, affiches et logos de tous les contacts.
          Tes choix ne sont jamais changés.{derniereRecherche ? ` Dernière recherche le ${dateCourte(derniereRecherche)}.` : ''}</p>
        <button role="menuitem" class="w-full text-left rounded-xl px-3 py-2 min-h-12 hover:bg-couture" onclick={() => rechercher('manquants')}>
          <span class="block text-papier">Chercher les manquants</span>
          <span class="block text-xs text-mine">Contacts sans proposition, sites jamais lus</span></button>
        <button role="menuitem" class="w-full text-left rounded-xl px-3 py-2 min-h-12 hover:bg-couture" onclick={() => rechercher('tout')}>
          <span class="block text-papier">Tout régénérer</span>
          <span class="block text-xs text-mine">Toutes les photos réexaminées, tous les sites relus (long)</span></button>
      </div>
    {/if}
  </div>
</div>

{#if enCours}
  <div class="rounded-2xl border border-onglet/50 bg-reliure p-3 mb-3 text-sm" role="status" aria-live="polite">
    <div class="flex items-baseline gap-2 mb-2">
      <span class="flex-1 text-papier">{tache.etape ? `${tache.etape.nom} · étape ${tache.etape.n} sur ${tache.etape.total}` : 'Recherche en cours'}</span>
      {#if avancement != null}<span class="text-mine tabular-nums">{tache.fait} / {tache.total}</span>{/if}
    </div>
    <div class="h-2 rounded-full bg-couture overflow-hidden" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={avancement ?? undefined}>
      <div class="h-full bg-onglet transition-[width] duration-500 {avancement == null ? 'w-1/3 animate-pulse' : ''}"
        style={avancement != null ? `width: ${avancement}%` : undefined}></div>
    </div>
    <p class="text-xs text-mine mt-2 truncate">{tache.message}</p>
  </div>
{/if}

<div class="grid grid-cols-3 p-1 rounded-xl bg-reliure border border-couture text-sm mb-3" role="tablist" aria-label="Type de photo">
  {#each [['hd', 'Photo'], ['affiche', 'Affiche'], ['logo', 'Logos']] as [v, t]}
    <button role="tab" aria-selected={mode === v} class="h-9 pointer-coarse:h-11 rounded-lg {mode === v ? 'bg-couture text-papier' : 'text-mine'}"
      onclick={() => { mode = v; vue = null }}>{t}</button>
  {/each}
</div>

{#if mode === 'logo'}
  {#key version}<Logos />{/key}
{:else}
<input class="w-full h-11 !rounded-xl !px-4 text-base mb-2" type="search" placeholder="Filtrer par nom" bind:value={recherche}
  aria-label="Filtrer par nom" autocomplete="off" />
<div class="flex flex-wrap gap-2 text-sm mb-3" role="group" aria-label="Filtre">
  {#each (mode === 'affiche' ? [['a_choisir', 'À choisir'], ['a_poser', 'À poser'], ['posees', 'Posées'], ['tous', 'Tous']]
    : [['a_choisir', 'À choisir'], ['choisies', 'Choisies'], ['tous', 'Tous']]) as [v, t]}
    <button class="h-8 pointer-coarse:h-11 px-3 rounded-full border {filtre === v ? 'border-onglet text-papier' : 'border-couture text-mine'}"
      aria-pressed={filtre === v} onclick={() => (filtre = v)}>{t}</button>
  {/each}
</div>

{#if mode === 'affiche' && toutes.length}
  <div class="rounded-2xl border {restantes.length ? 'border-onglet/50' : 'border-couture'} bg-reliure p-3 mb-3 text-sm">
    <p class="text-papier">{toutes.length} affiche{toutes.length > 1 ? 's' : ''} choisie{toutes.length > 1 ? 's' : ''}
      <span class="text-mine"> · {toutes.length - aPoser.length} posée{toutes.length - aPoser.length > 1 ? 's' : ''} sur l'iPhone</span></p>
    <div class="grid grid-cols-2 p-1 rounded-lg bg-cuir border border-couture text-xs my-2" role="group" aria-label="Affiches à exporter">
      {#each [['a_poser', `À poser (${aPoser.length})`], ['toutes', `Toutes (${toutes.length})`]] as [v, t]}
        <button class="h-8 pointer-coarse:h-11 rounded-md {portee === v ? 'bg-couture text-papier' : 'text-mine'}" aria-pressed={portee === v}
          onclick={() => { portee = v; pret = null }}>{t}</button>
      {/each}
    </div>
    {#if restantes.length}<p class="text-xs text-mine">{restantes.length} encore à enregistrer sur cet iPhone.</p>{/if}
    {#if restantes.length}
      <p class="text-xs text-mine mb-2">Les mettre dans ta pellicule, puis Contacts › Photo et affiche du contact › Photos.</p>
      <button class="w-full h-11 rounded-xl border border-onglet text-onglet disabled:opacity-50" disabled={occupe}
        onclick={() => preparer(lotCourant, restantes.length > LOT ? `${lotCourant.length} affiches sur les ${restantes.length} restantes` : 'les dernières affiches')}>
        {occupe ? 'Préparation…' : restantes.length > LOT ? `Préparer ${LOT} affiches (sur ${restantes.length})` : `Préparer ${pluralAff(restantes.length)}`}</button>
      <button class="text-xs text-mine underline mt-2" disabled={occupe} onclick={() => noterDeja(restantes)}>
        Déjà dans ma pellicule : ne plus les proposer</button>
    {:else}
      <p class="text-xs text-valide mt-1">{perimetre.length ? '✓ Déjà toutes enregistrées sur cet iPhone.' : '✓ Toutes les affiches sont posées.'}</p>
      <button class="text-xs text-mine underline mt-2" onclick={toutReproposer}>Tout réenregistrer</button>
    {/if}
  </div>
{/if}

{#if pret}
  <div class="fixed inset-x-4 z-40 bottom-[calc(5rem+env(safe-area-inset-bottom))] rounded-2xl border border-onglet bg-reliure shadow-2xl p-4 text-sm"
    role="dialog" aria-label="Enregistrer dans Photos">
    <p class="text-papier mb-3">{pret.fichiers.length} image{pret.fichiers.length > 1 ? 's' : ''} prête{pret.fichiers.length > 1 ? 's' : ''} : {pret.titre}.</p>
    <div class="flex gap-2">
      <button class="flex-1 h-11 rounded-xl bg-onglet text-onglet-sombre font-semibold" onclick={partager}>Enregistrer dans Photos</button>
      <button class="h-11 px-4 rounded-xl border border-couture text-mine" onclick={() => (pret = null)}>Annuler</button>
    </div>
  </div>
{/if}

{#if (mode === 'hd' && !portraits) || (mode === 'affiche' && !affiches)}
  <p class="text-mine">Chargement…</p>
{:else}
  <ul class="space-y-3">
    {#each lignes as l (l.pid)}
      <li class="rounded-2xl border border-couture bg-reliure p-3">
        <div class="flex items-center gap-2 mb-2">
          <span class="flex-1 min-w-0 truncate text-papier">{l.nom}</span>
          {#if mode === 'affiche' && l.affiche}
            <button class="text-xs h-8 pointer-coarse:h-11 px-3 rounded-full border {l.posee ? 'border-valide/60 bg-valide/15 text-valide' : 'border-couture text-mine'}"
              aria-pressed={!!l.posee} onclick={() => marquerPosee(l, !l.posee)}>{l.posee ? 'Posée ✓' : 'Marquer posée'}</button>
          {:else if l.manuel}<span class="text-xs text-valide">choisie ✓</span>{/if}
          {#if mode === 'affiche' && l.affiche}
            <button class="text-xs h-8 pointer-coarse:h-11 px-3 rounded-full border border-onglet text-onglet disabled:opacity-50" disabled={occupe}
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
      <li class="text-sm text-mine py-6 text-center">
        {#if (mode === 'hd' ? portraits.lignes : affiches.lignes).length === 0}
          Aucun contact lié à Immich ici : les liaisons se font dans À traiter (ou seules la nuit), puis la recherche avec le bouton ↻ en haut.
        {:else if filtre === 'a_choisir'}Rien à choisir : tout est fait. Le filtre « Tous » montre chaque contact.
        {:else}Aucun contact dans ce filtre.{/if}
      </li>
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
{/if}
