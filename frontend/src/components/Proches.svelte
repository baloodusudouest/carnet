<script>
  // Révision : noms proches de la fiche en cours dans Immich, Treemich et les autres contacts.
  // Actions : lier la fiche, reprendre la date de naissance, corriger l'orthographe (dans un
  // sens ou dans l'autre), réunir un autre contact dans celui-ci. Rien n'est fait sans clic.
  import { api } from '../lib/api.js'
  import { annoncer } from '../lib/etat.svelte.js'
  import { anniversaireLisible } from '../lib/cles.js'

  let { pid, fiche = $bindable(), reunir } = $props()

  let donnees = $state(null)
  let occupe = $state(false)
  let ouvert = $state(true)

  async function charger() {
    try {
      donnees = await api.get(`/api/personnes/${pid}/proches`)
    } catch (e) {
      donnees = null
      annoncer(e.message, true)
    }
  }
  $effect(() => {
    pid
    donnees = null
    charger()
  })

  const nomFiche = $derived([fiche.prenom, fiche.nom].filter(Boolean).join(' '))
  const cle = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  // Seule la casse diffère (« Martin » / « MARTIN ») : pas une faute, le format est géré dans Liaisons
  const memeOrthographe = (nom) => nom.toLocaleLowerCase('fr') === nomFiche.toLocaleLowerCase('fr')
  const total = $derived(donnees ? donnees.immich.length + donnees.treemich.length + donnees.contacts.length : 0)

  // « Jean-Paul DUPONT » / « Jean Paul Dupont » → prénom, NOM (un mot en majuscules ouvre le
  // nom de famille ; sinon c'est le dernier mot)
  function decouper(nom) {
    const mots = nom.trim().split(/\s+/)
    if (mots.length < 2) return { prenom: mots[0] || '', nom: '' }
    let debut = mots.findIndex((m, i) => i > 0 && m.length > 1 && m === m.toUpperCase() && /\p{L}/u.test(m))
    if (debut < 0) debut = mots.length - 1
    return { prenom: mots.slice(0, debut).join(' '), nom: mots.slice(debut).join(' ').toUpperCase() }
  }

  async function lier(cote, p) {
    occupe = true
    try {
      const r = await api.post(`/api/personnes/${pid}/lier`, { [cote]: p.id })
      annoncer(r.applique ? `Lié à ${p.nom} : photo et relations en cours d'ajout.`
        : `Lié à ${p.nom} : photo et relations seront ajoutées à la validation de la fiche.`)
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }

  async function refuser(p) {
    try {
      await api.post('/api/liaisons/refuser', { pid, immich: p.id })
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  function prendreNom(p) {
    const { prenom, nom } = decouper(p.nom)
    fiche.prenom = prenom
    fiche.nom = nom
    annoncer(`Nom de la fiche : ${[prenom, nom].filter(Boolean).join(' ')} (brouillon).`)
  }

  async function renommer(cote, p) {
    occupe = true
    try {
      const r = await api.post(`/api/personnes/${pid}/renommer-liens`,
        { [cote]: p.id, prenom: fiche.prenom || '', nom: fiche.nom || '' })
      annoncer(`${cote === 'immich' ? 'Immich' : 'Treemich'} : renommé « ${r.nom} ».`)
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }

  function prendreDate(p) {
    fiche.anniversaire = p.naissance
    annoncer(`Anniversaire repris : ${anniversaireLisible(p.naissance)} (brouillon).`)
  }
  // Date reprise seulement si la fiche n'en a pas ; une date différente est signalée
  const dateUtile = (p) => p.naissance?.length === 10 && !fiche.anniversaire
  const dateDiffere = (p) => {
    const a = fiche.anniversaire || ''
    if (p.naissance?.length !== 10 || !a) return false
    return /^\d{4}-/.test(a) ? a.slice(0, 10) !== p.naissance : a.slice(-5) !== p.naissance.slice(-5)
  }
</script>

{#snippet personne(cote, p)}
  <li class="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2">
    {#if cote === 'immich'}
      <img class="w-9 h-9 rounded-full object-cover bg-couture shrink-0" src={`/api/immich/visage/${p.id}?taille=72`} alt="" loading="lazy" />
    {:else}
      <span class="w-9 h-9 rounded-full bg-couture shrink-0 flex items-center justify-center text-xs text-mine" aria-hidden="true">🌳</span>
    {/if}
    <span class="min-w-0 flex-1">
      <span class="block text-papier truncate">{p.nom}
        {#if p.lie}<span class="ml-1 text-xs text-valide">lié ✓</span>{:else if !p.exact}<span class="ml-1 text-xs text-mine tabular-nums">{p.score} %</span>{/if}</span>
      <span class="block text-xs text-mine truncate">
        {p.naissance ? `né(e) ${anniversaireLisible(p.naissance)}` : 'sans date de naissance'}
        {#if dateDiffere(p)}<span class="text-alerte"> · ≠ fiche ({anniversaireLisible(fiche.anniversaire)})</span>{/if}
        {#if p.lie_a} · déjà lié à <a class="underline" href={`#/revision/${p.lie_a.pid}`}>{p.lie_a.nom}</a>{/if}
      </span>
    </span>
    <span class="flex flex-wrap gap-1.5 text-xs">
      {#if !p.lie && !p.lie_a}
        <button class="h-8 pointer-coarse:h-11 px-3 rounded-full bg-onglet text-onglet-sombre font-medium disabled:opacity-50" disabled={occupe}
          onclick={() => lier(cote, p)}>Lier</button>
      {/if}
      {#if dateUtile(p)}
        <button class="h-8 pointer-coarse:h-11 px-3 rounded-full border border-couture text-papier hover:border-onglet" onclick={() => prendreDate(p)}
          title="Reprendre cette date dans la fiche">Prendre la date</button>
      {/if}
      {#if !memeOrthographe(p.nom) && cle(p.nom) !== '' && nomFiche}
        <button class="h-8 pointer-coarse:h-11 px-3 rounded-full border border-couture text-papier hover:border-onglet" onclick={() => prendreNom(p)}
          title="La fiche prend l'orthographe de {cote === 'immich' ? 'Immich' : 'Treemich'}">Nom → fiche</button>
        <button class="h-8 pointer-coarse:h-11 px-3 rounded-full border border-couture text-papier hover:border-onglet disabled:opacity-50" disabled={occupe}
          onclick={() => renommer(cote, p)} title="Renommer dans {cote === 'immich' ? 'Immich' : 'Treemich'} : « {nomFiche} »">
          Fiche → {cote === 'immich' ? 'Immich' : 'Treemich'}</button>
      {/if}
      {#if !p.lie}
        <button class="h-8 pointer-coarse:h-11 px-2 text-mine hover:text-alerte" onclick={() => refuser(p)} title="Pas la même personne : ne plus proposer">✕</button>
      {/if}
    </span>
  </li>
{/snippet}

{#if donnees && total}
  <section class="rounded-xl border border-onglet/40 bg-reliure mb-3 text-sm" aria-label="Noms proches">
    <button class="w-full flex items-center gap-2 px-3 py-2 text-left" onclick={() => (ouvert = !ouvert)} aria-expanded={ouvert}>
      <span class="text-onglet">≈</span>
      <span class="flex-1 text-papier">Noms proches :
        {[donnees.immich.length && `${donnees.immich.length} Immich`, donnees.treemich.length && `${donnees.treemich.length} Treemich`,
          donnees.contacts.length && `${donnees.contacts.length} contact${donnees.contacts.length > 1 ? 's' : ''}`].filter(Boolean).join(' · ')}</span>
      <span class="text-mine text-xs">{ouvert ? 'Masquer' : 'Afficher'}</span>
    </button>
    {#if ouvert}
      <div class="px-3 pb-2 grid gap-x-6 md:grid-cols-2">
        {#if donnees.immich.length}
          <div>
            <h3 class="text-xs uppercase tracking-wide text-mine mt-1">Immich</h3>
            <ul class="divide-y divide-couture">{#each donnees.immich as p (p.id)}{@render personne('immich', p)}{/each}</ul>
          </div>
        {/if}
        {#if donnees.treemich.length}
          <div>
            <h3 class="text-xs uppercase tracking-wide text-mine mt-1">Treemich</h3>
            <ul class="divide-y divide-couture">{#each donnees.treemich as p (p.id)}{@render personne('treemich', p)}{/each}</ul>
          </div>
        {/if}
        {#if donnees.contacts.length}
          <div>
            <h3 class="text-xs uppercase tracking-wide text-mine mt-1">Autres contacts</h3>
            <ul class="divide-y divide-couture">
              {#each donnees.contacts as c (c.id)}
                <li class="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2">
                  <span class="min-w-0 flex-1">
                    <a class="block text-papier truncate hover:underline" href={`#/revision/${c.id}`}>{c.nom}
                      <span class="ml-1 text-xs text-mine tabular-nums">{c.score} %</span></a>
                    <span class="block text-xs text-mine truncate">{[c.statut === 'verifie' ? 'vérifié' : 'à relire',
                      c.telephone, c.anniversaire && anniversaireLisible(c.anniversaire), c.groupes.join(', ')].filter(Boolean).join(' · ')}</span>
                  </span>
                  <button class="h-8 pointer-coarse:h-11 px-3 rounded-full border border-onglet text-onglet text-xs" onclick={() => reunir(c)}
                    title="Même personne : réunir ses fiches dans ce contact">Réunir ici</button>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      </div>
      {#if donnees.lu_le}<p class="px-3 pb-2 text-xs text-mine">Immich et Treemich lus le {new Date(donnees.lu_le).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })} (relecture dans Liaisons).</p>{/if}
    {/if}
  </section>
{/if}
