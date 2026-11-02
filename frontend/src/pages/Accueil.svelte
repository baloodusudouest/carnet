<script>
  // À traiter : tout ce qui attend une décision, au même endroit. Les décisions courtes se
  // prennent ici (lier, annuler une liaison faite seule) ; les longues ouvrent la bonne page.
  import { api } from '../lib/api.js'
  import { bilan, ecran, chargerBilan, contacts, chargerContacts, annoncer } from '../lib/etat.svelte.js'
  import { cleTexte, dateCourte, pluriel } from '../lib/cles.js'

  let recherche = $state('')
  let file = $state(null)
  let liaisons = $state(null)
  let auto = $state([])
  let occupe = $state(false)
  const mobile = $derived(ecran.etroit && !ecran.forcerPC)

  async function charger() {
    chargerBilan(api).catch(() => {})
    chargerContacts(api).catch(() => {})
    api.get('/api/file').then((f) => (file = f)).catch((e) => annoncer(e.message, true))
    api.get('/api/liaisons/auto').then((a) => (auto = a)).catch(() => {})
    api.get('/api/liaisons').then((l) => (liaisons = l)).catch(() => (liaisons = { propositions: [], erreurs: [] }))
  }
  charger()

  const resultats = $derived.by(() => {
    const q = cleTexte(recherche)
    const chiffres = recherche.replace(/\D/g, '')
    if (!q || !contacts.liste) return []
    return contacts.liste.filter((p) => p.statut !== 'ecarte' && (cleTexte(`${p.nom} ${p.societe} ${p.courriel}`).includes(q)
      || (chiffres.length >= 3 && (p.telephone ?? '').replace(/\D/g, '').includes(chiffres)))).slice(0, 8)
  })

  // Pourquoi la fiche est à relire : d'où vient le changement
  function genre(p) {
    const m = (p.a_revoir || '').toLowerCase()
    if (m.startsWith('supprimée de l')) return { cle: 'supprimee', libelle: 'Supprimée de l\'iPhone' }
    if (m.includes('iphone') || m.includes('icloud')) return { cle: 'iphone', libelle: 'Modifiée sur l\'iPhone' }
    if (m.startsWith('linkedin') || m.includes('complément linkedin')) return { cle: 'linkedin', libelle: p.a_revoir.replace(/^LinkedIn · /, 'LinkedIn : ') }
    if (p.doublon) return { cle: 'doublon', libelle: 'Doublon à fusionner' }
    if (m) return { cle: 'autre', libelle: p.a_revoir }
    return { cle: 'nouveau', libelle: 'Nouvelle fiche' }
  }
  const ORDRE = ['supprimee', 'iphone', 'linkedin', 'doublon', 'autre', 'nouveau']
  const fiches = $derived(file ? file.map((p) => ({ ...p, g: genre(p) })).sort((a, b) => ORDRE.indexOf(a.g.cle) - ORDRE.indexOf(b.g.cle)) : [])
  const parGenre = $derived(ORDRE.map((k) => [k, fiches.filter((p) => p.g.cle === k).length]).filter(([, n]) => n))
  const LIBELLES = { supprimee: 'supprimées de l\'iPhone', iphone: 'modifiées sur l\'iPhone', linkedin: 'LinkedIn', doublon: 'doublons', autre: 'autres motifs', nouveau: 'nouvelles' }

  const propositions = $derived((liaisons?.propositions ?? []).filter((p) => p.immich.length || p.treemich))

  async function lier(p) {
    occupe = true
    try {
      await api.post('/api/liaisons/valider', { liaisons: [{ pid: p.pid, immich: p.immich[0]?.id ?? null, treemich: p.treemich?.id ?? null }] })
      liaisons = { ...liaisons, propositions: liaisons.propositions.filter((x) => x.pid !== p.pid) }
      annoncer(`${p.nom} lié : photo et relations en cours d'ajout.`)
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }
  async function refuser(p) {
    try {
      await api.post('/api/liaisons/refuser', { pid: p.pid, immich: p.immich[0].id })
      liaisons = { ...liaisons, propositions: liaisons.propositions.filter((x) => x.pid !== p.pid) }
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  async function annulerAuto(x) {
    try {
      await api.post('/api/liaisons/delier', { pid: x.pid, refuser: true })
      auto = auto.filter((y) => y.pid !== x.pid)
      annoncer(`Liaison de ${x.nom} annulée : elle ne sera plus proposée.`)
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  const b = $derived(bilan.donnees)
  const autres = $derived.by(() => {
    if (!b) return []
    const l = b.liaisons, s = b.statut
    const res = []
    if (b.revue) res.push({ n: b.revue, titre: 'Points à compléter', texte: 'Anniversaires, sociétés, numéros sur les contacts vérifiés', lien: '#/revue' })
    if (b.photos?.hd) res.push({ n: b.photos.hd, titre: 'Photos HD à choisir', texte: 'Le visage le plus net trouvé dans Immich', lien: '#/photos' })
    if (b.photos?.affiches) res.push({ n: b.photos.affiches, titre: 'Affiches à choisir', texte: 'Photo plein écran pour l\'appel', lien: '#/photos' })
    if (l?.orthographes) res.push({ n: l.orthographes, titre: 'Orthographes à trancher', texte: 'Nom différent entre carnet et Immich ou Treemich', lien: '#/liaisons' })
    if (l?.noms_immich) res.push({ n: l.noms_immich, titre: 'Noms Immich à mettre en forme', texte: '« Prénom NOM » comme dans carnet', lien: '#/liaisons' })
    if (s?.linkedin_sans_contact) res.push({ n: s.linkedin_sans_contact, titre: 'Relations LinkedIn sans contact', texte: 'À rattacher à un contact, ou à ignorer', lien: '#/contacts', discret: true })
    return res
  })
  const soucis = $derived.by(() => {
    const s = b?.statut
    if (!s) return []
    const res = []
    if (s.synchro && !s.synchro.ok) res.push(s.synchro.alerte ? 'La synchro iCloud de cette nuit n\'a rien écrit (plafond ou veille en erreur).' : 'La synchro iCloud de cette nuit est en erreur.')
    if (s.veille && !s.veille.ok) res.push(`Veille de l'iPhone en erreur : ${s.veille.erreur}`)
    if (s.sauvegarde && !s.sauvegarde.ok) res.push(`Sauvegarde de nuit en erreur : ${s.sauvegarde.erreur}`)
    if (s.synchro?.suppressions_en_attente) res.push(`${pluriel(s.synchro.suppressions_en_attente, 'suppression attend', 'suppressions attendent')} ton accord dans iCloud.`)
    return res
  })
  const tache = $derived(b?.tache)
  const rien = $derived(file && !fiches.length && !propositions.length && !auto.length && !autres.length && !soucis.length)
</script>

{#snippet avatar(p, taille = 40)}
  <span class="relative shrink-0 rounded-full overflow-hidden bg-couture grid place-items-center text-mine text-sm" style="width:{taille}px;height:{taille}px">
    {p.nom?.[0] ?? '?'}
    {#if p.photo}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/photos/${p.photo}?taille=${taille * 2}`} alt=""
      width={taille} height={taille} loading="lazy" onerror={(e) => e.currentTarget.remove()} />{/if}
  </span>
{/snippet}

<div class="max-w-4xl">
  <div class="relative mb-6">
    <input class="w-full h-12 !rounded-xl !px-4" type="search" placeholder="Chercher un contact : nom, société, numéro"
      bind:value={recherche} aria-label="Chercher un contact" autocomplete="off" enterkeyhint="search" />
    {#if resultats.length}
      <ul class="absolute z-20 inset-x-0 mt-1 rounded-xl border border-tranche bg-reliure shadow-2xl divide-y divide-couture overflow-hidden">
        {#each resultats as p (p.id)}
          <li>
            <a href={`#/fiche/${p.id}`} class="flex items-center gap-3 px-3 min-h-14 py-2 hover:bg-couture">
              {@render avatar(p, 36)}
              <span class="flex-1 min-w-0"><span class="block truncate">{p.nom}</span>
                <span class="block truncate text-xs text-mine">{p.societe || p.telephone || p.courriel}</span></span>
              {#if p.statut !== 'verifie'}<span class="text-xs text-onglet">à relire</span>{/if}
            </a>
          </li>
        {/each}
      </ul>
    {:else if recherche.trim() && contacts.liste}
      <p class="text-sm text-mine mt-2">Aucun contact ne correspond.</p>
    {/if}
  </div>

  <h1 class="titre text-2xl mb-1">À traiter</h1>
  {#if tache && ['lecture', 'ecriture'].includes(tache.etat)}
    <p class="text-sm text-mine mb-3" role="status">En cours : {tache.message}{tache.total ? ` (${tache.fait}/${tache.total})` : ''}</p>
  {/if}

  {#if soucis.length}
    <a href="#/etat" class="block rounded-2xl border border-alerte/60 bg-[#2a1b1b] p-4 mt-3 mb-4">
      {#each soucis as t}<p class="text-sm text-papier">{t}</p>{/each}
      <p class="text-sm text-onglet mt-1 underline underline-offset-2">Voir l'état</p>
    </a>
  {/if}

  {#if !file}
    <div class="space-y-3 mt-4" aria-hidden="true">
      <div class="h-24 rounded-2xl bg-reliure animate-pulse"></div><div class="h-40 rounded-2xl bg-reliure animate-pulse"></div>
    </div>
  {:else if rien}
    <div class="rounded-2xl border border-couture bg-reliure p-6 mt-4 text-center">
      <p class="titre text-xl">Rien à traiter</p>
      <p class="text-sm text-mine mt-1">Toutes les fiches sont relues et liées. La synchro de nuit s'occupe du reste.</p>
    </div>
  {:else}
    <p class="text-sm text-mine mb-4">{fiches.length ? `${pluriel(fiches.length, 'fiche', 'fiches')} à relire` : 'Aucune fiche à relire'}{propositions.length ? `, ${pluriel(propositions.length, 'liaison', 'liaisons')} à confirmer` : ''}.</p>

    {#if auto.length}
      <section class="rounded-2xl border border-couture bg-reliure p-4 mb-4" aria-labelledby="t-auto">
        <h2 id="t-auto" class="text-papier mb-1">Liés seuls cette nuit</h2>
        <p class="text-xs text-mine mb-2">Même nom et même date de naissance dans carnet et Immich. Annule si ce n'est pas la même personne.</p>
        <ul class="divide-y divide-couture">
          {#each auto as x (x.pid)}
            <li class="flex items-center gap-3 py-2">
              <img class="w-10 h-10 rounded-full object-cover bg-couture shrink-0" src={`/api/immich/visage/${x.immich}?taille=80`} alt="" loading="lazy" />
              <a class="flex-1 min-w-0 truncate text-papier" href={`#/fiche/${x.pid}`}>{x.nom}</a>
              <button class="min-h-11 px-3 text-sm text-mine hover:text-alerte" onclick={() => annulerAuto(x)}>Annuler</button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if fiches.length}
      <section class="rounded-2xl border border-onglet/40 bg-reliure p-4 mb-4" aria-labelledby="t-fiches">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2 mb-2">
          <h2 id="t-fiches" class="text-papier flex-1">Fiches à relire <span class="text-onglet tabular-nums">{fiches.length}</span></h2>
          <a class="bouton bouton-principal min-h-11" href={`#/revision/${fiches[0].id}`}>Relire{mobile ? '' : ' une à une'}</a>
        </div>
        <p class="text-xs text-mine mb-2">{parGenre.map(([k, n]) => `${n} ${LIBELLES[k]}`).join(', ')}</p>
        <ul class="divide-y divide-couture">
          {#each fiches.slice(0, 6) as p (p.id)}
            <li>
              <a href={`#/revision/${p.id}`} class="flex items-center gap-3 py-2 min-h-14">
                {@render avatar(p)}
                <span class="flex-1 min-w-0">
                  <span class="block truncate text-papier">{p.nom}</span>
                  <span class="block truncate text-xs {p.g.cle === 'supprimee' || p.g.cle === 'iphone' ? 'text-onglet' : 'text-mine'}">{p.g.libelle}</span>
                </span>
                <span class="text-mine" aria-hidden="true">›</span>
              </a>
            </li>
          {/each}
        </ul>
        {#if fiches.length > 6}<a class="block mt-1 min-h-11 leading-[2.75rem] text-sm text-onglet" href="#/revision">Et {fiches.length - 6} autres</a>{/if}
      </section>
    {/if}

    {#if propositions.length}
      <section class="rounded-2xl border border-couture bg-reliure p-4 mb-4" aria-labelledby="t-liaisons">
        <div class="flex items-center gap-3 mb-1">
          <h2 id="t-liaisons" class="text-papier flex-1">Liaisons à confirmer <span class="text-onglet tabular-nums">{propositions.length}</span></h2>
          <a class="min-h-11 flex items-center text-sm text-onglet underline underline-offset-2" href="#/liaisons">Toutes</a>
        </div>
        <p class="text-xs text-mine mb-2">Le visage Immich (et la personne de l'arbre) à relier à ce contact.</p>
        <ul class="divide-y divide-couture">
          {#each propositions.slice(0, 6) as p (p.pid)}
            {@const im = p.immich[0]}
            <li class="flex flex-wrap items-center gap-x-3 gap-y-2 py-2">
              {#if im}<img class="w-10 h-10 rounded-full object-cover bg-couture shrink-0" src={`/api/immich/visage/${im.id}?taille=80`} alt="" loading="lazy" />{/if}
              <span class="flex-1 min-w-0">
                <span class="block truncate text-papier">{p.nom}</span>
                <span class="block truncate text-xs text-mine">{[im && `Immich : ${im.nom}${p.immich.length > 1 ? ` (+${p.immich.length - 1})` : ''}`, p.treemich && `arbre : ${p.treemich.nom}`].filter(Boolean).join(' · ')}</span>
              </span>
              <span class="flex gap-1.5">
                {#if p.immich.length > 1}
                  <a class="min-h-11 px-3 flex items-center rounded-lg border border-couture text-sm" href="#/liaisons">Choisir</a>
                {:else}
                  <button class="min-h-11 px-4 rounded-lg bg-onglet text-onglet-sombre text-sm font-medium disabled:opacity-50" disabled={occupe} onclick={() => lier(p)}>Lier</button>
                {/if}
                {#if im}<button class="min-h-11 px-3 rounded-lg text-sm text-mine hover:text-alerte" onclick={() => refuser(p)}>Pas lui</button>{/if}
              </span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if autres.length}
      <section aria-label="Autres points" class="grid gap-3 sm:grid-cols-2 mb-4">
        {#each autres as c (c.titre)}
          <a href={c.lien} class="flex items-center gap-3 rounded-2xl border border-couture bg-reliure p-4 min-h-16 hover:border-tranche">
            <span class="flex-1 min-w-0">
              <span class="block text-papier">{c.titre}</span>
              <span class="block text-xs text-mine">{c.texte}</span>
            </span>
            <span class="titre text-2xl tabular-nums {c.discret ? 'text-mine' : 'text-onglet'}">{c.n}</span>
          </a>
        {/each}
      </section>
    {/if}
  {/if}
  {#if b?.statut?.synchro && !soucis.length}
    <p class="text-xs text-mine mt-2">Synchro iCloud du {dateCourte(b.statut.synchro.le)} : {b.statut.synchro.mode === 'a_blanc' ? 'à blanc' : 'faite'}. <a class="underline underline-offset-2" href="#/etat">État</a></p>
  {/if}
</div>
