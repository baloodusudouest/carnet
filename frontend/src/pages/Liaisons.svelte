<script>
  import { onDestroy } from 'svelte'
  import { api } from '../lib/api.js'
  import { annoncer } from '../lib/etat.svelte.js'
  import { dateCourte, pluriel, anniversaireLisible } from '../lib/cles.js'

  // Liaisons contact ↔ personne Immich (photo) ↔ personne Treemich (relations familiales).
  let donnees = $state(null)
  let choix = $state({})        // pid → id Immich choisi parmi les candidats
  let tache = $state(null)
  let filtre = $state('')
  let minuteur = null

  const enCours = $derived(['lecture', 'ecriture'].includes(tache?.etat))
  const exactes = $derived(donnees ? donnees.propositions.filter((p) => p.exacte) : [])
  const liees = $derived(donnees ? donnees.liees.filter((p) => !filtre || p.nom.toLowerCase().includes(filtre.toLowerCase())) : [])

  async function charger(rafraichir = false) {
    try {
      donnees = await api.get(`/api/liaisons${rafraichir ? '?rafraichir=true' : ''}`)
      for (const p of donnees.propositions) if (!(p.pid in choix)) choix[p.pid] = p.immich[0]?.id ?? ''
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  charger(true)

  async function suivre() {
    const avant = tache?.etat
    tache = (await api.get('/api/icloud')).tache
    if (['lecture', 'ecriture'].includes(tache.etat)) minuteur = setTimeout(suivre, 800)
    else if (['lecture', 'ecriture'].includes(avant)) {
      annoncer(tache.message, tache.etat === 'erreur')
      if (tache.operation === 'naissances') await chargerNaissances()
      else if (tache.operation === 'portraits') await chargerPortraits()
      else await charger()
    }
  }
  onDestroy(() => clearTimeout(minuteur))

  async function valider(liste) {
    try {
      await api.post('/api/liaisons/valider', { liaisons: liste })
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  const liaisonDe = (p) => ({ pid: p.pid, immich: choix[p.pid] || null, treemich: p.treemich?.id ?? null })

  async function refuser(p) {
    if (choix[p.pid]) await api.post('/api/liaisons/refuser', { pid: p.pid, immich: choix[p.pid] })
    donnees.propositions = donnees.propositions.filter((x) => x.pid !== p.pid)
  }

  async function delier(p) {
    await api.post('/api/liaisons/delier', { pid: p.pid })
    annoncer(`${p.nom} n'est plus lié.`)
    await charger()
  }

  // Orthographe : garder celle de carnet (écrite dans Immich et Treemich) ou celle d'Immich (écrite dans carnet)
  let occupe = $state(null)
  async function corrigerNom(p, garder) {
    occupe = p.pid
    try {
      const r = await api.post('/api/liaisons/nom', { pid: p.pid, garder })
      annoncer(`Nom retenu partout : ${r.nom}.`)
      await charger(true)
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
    }
  }

  // Noms Immich au format « Prénom NOM »
  let noms = $state({})
  async function renommer(liste) {
    occupe = 'renommage'
    let n = 0
    try {
      for (const x of liste) {
        await api.post('/api/immich/renommer', { id: x.id, nom: noms[x.id] ?? x.propose })
        n++
      }
      annoncer(`${pluriel(n, 'personne renommée', 'personnes renommées')} dans Immich.`)
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
      await charger(true)
    }
  }
  const ecarts = $derived(donnees ? donnees.liees.filter((p) => p.ecart_nom) : [])

  // Dates de naissance → Immich et Treemich (étape 5)
  let naissances = $state(null)
  let remplacer = $state(false)
  let confirmeDates = $state(false)
  let essai = $state('')
  async function chargerNaissances() {
    naissances = await api.get('/api/naissances')
  }
  chargerNaissances()
  async function lancerNaissances(chemin, corps) {
    try {
      await api.post(chemin, corps)
      await suivre()
      await chargerNaissances()
      confirmeDates = false
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  const ETATS = { ajouter: 'à ajouter', differente: 'différente', identique: 'identique',
    annee_inconnue: 'année inconnue', rien_dans_carnet: 'absente de carnet' }
  const aEcrire = (l, c) => l[c] && (l[c].etat === 'ajouter' || (remplacer && l[c].etat === 'differente'))

  // Photos HD : le meilleur visage Immich (entier, grand, net) devient la photo du contact
  let portraits = $state(null)
  let ouvert = $state(null)       // pid dont on montre les autres choix
  let filtrePortraits = $state('sans')
  async function chargerPortraits() {
    try {
      portraits = await api.get('/api/portraits')
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  chargerPortraits()
  async function chercherPortraits() {
    try {
      await api.post('/api/portraits/recherche')
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  async function choisirPortrait(l, asset) {
    occupe = l.pid
    try {
      await api.post('/api/portraits/choix', { pid: l.pid, asset })
      annoncer(asset ? `Photo de ${l.nom} changée (aussi dans Immich).` : `carnet choisira la meilleure photo de ${l.nom} au prochain passage.`)
      await chargerPortraits()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
    }
  }
  const lignesPortraits = $derived(portraits ? portraits.lignes.filter((l) =>
    filtrePortraits === 'tous' || (filtrePortraits === 'sans' ? !l.hd : l.hd?.manuel)) : [])
  const netteteLisible = (n) => n == null ? 'netteté inconnue' : n >= 120 ? 'net' : n >= 50 ? 'assez net' : 'un peu flou'

  async function actualiser() {
    try {
      await api.post('/api/liaisons/actualiser')
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }
</script>

{#snippet visage(id, nom)}
  <span class="relative w-11 h-11 shrink-0 rounded-full overflow-hidden bg-couture grid place-items-center text-mine text-sm">
    {nom?.[0] ?? '?'}
    {#if id}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/immich/visage/${id}`} alt=""
      onerror={(e) => e.currentTarget.remove()} loading="lazy" />{/if}
  </span>
{/snippet}

<div class="max-w-5xl">
  <div class="flex flex-wrap items-end gap-4 mb-2">
    <div>
      <h1 class="titre text-3xl">Liaisons Immich et Treemich</h1>
      <p class="text-mine text-sm max-w-3xl">Une fois un contact lié, son visage Immich devient sa photo et ses relations
        Treemich (conjoint, parents, enfants, frères et sœurs) complètent ses noms associés. Tout se met à jour chaque nuit ;
        une relation qui contredit ce que tu as saisi passe par la Revue.</p>
    </div>
    <button class="bouton ml-auto" disabled={enCours} onclick={actualiser}>Mettre à jour maintenant</button>
  </div>

  {#if tache && tache.etat !== 'repos' && ['liens', 'naissances', 'portraits'].includes(tache.operation)}
    <p class="text-sm mb-3 {tache.etat === 'erreur' ? 'text-alerte' : 'text-mine'}">{tache.message}
      {#if enCours && tache.total}<span class="tabular-nums"> ({tache.fait}/{tache.total})</span>{/if}</p>
  {/if}

  {#if donnees}
    {#if !donnees.immich && !donnees.treemich}
      <div class="rounded-xl border border-onglet/60 bg-reliure p-5 mt-4 text-sm">
        Renseigne dans la stack <code>CARNET_IMMICH_CLE</code> (clé d'API Immich) et
        <code>CARNET_TREEMICH_EMAIL</code> / <code>CARNET_TREEMICH_PASSWORD</code>, puis redéploie.
      </div>
    {:else}
      {#each donnees.erreurs as e}<p class="text-sm text-alerte mb-2">{e}</p>{/each}
      <p class="text-sm text-mine mb-6">{pluriel(donnees.nb_immich, 'personne nommée', 'personnes nommées')} dans Immich,
        {pluriel(donnees.nb_treemich, 'personne', 'personnes')} dans Treemich ;
        {pluriel(donnees.liees.length, 'contact lié', 'contacts liés')}.</p>

      <section class="mb-10">
        <div class="flex flex-wrap items-center gap-4 mb-2">
          <h2 class="titre text-xl">À valider <span class="text-mine text-base font-normal">({donnees.propositions.length})</span></h2>
          {#if exactes.length}
            <button class="bouton bouton-principal ml-auto" disabled={enCours}
              onclick={() => valider(exactes.map(liaisonDe))}>
              {exactes.length === 1 ? 'Valider la correspondance exacte' : `Valider les ${exactes.length} correspondances exactes`}</button>
          {/if}
        </div>
        <p class="text-sm text-mine mb-3">Exacte : même nom, une seule personne possible, pas de date de naissance contraire.</p>
        {#if donnees.propositions.length}
          <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
            {#each donnees.propositions as p (p.pid)}
              {@const im = p.immich.find((x) => x.id === choix[p.pid])}
              <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
                <div class="w-52 min-w-0">
                  <a href={`#/revision/${p.pid}`} class="block truncate hover:text-onglet">{p.nom}</a>
                  <span class="block text-xs text-mine truncate">{p.anniversaire ? anniversaireLisible(p.anniversaire) : p.groupes.join(', ')}</span>
                </div>
                <span class="text-mine">→</span>
                {@render visage(im?.id, im?.nom)}
                <div class="w-56 min-w-0 text-sm">
                  {#if p.immich.length > 1}
                    <select class="w-full" bind:value={choix[p.pid]} aria-label={`Personne Immich pour ${p.nom}`}>
                      {#each p.immich as x}<option value={x.id}>{x.nom}{x.naissance ? ` (${x.naissance.slice(0, 4)})` : ''}</option>{/each}
                      <option value="">Aucune</option>
                    </select>
                  {:else if im}
                    <span class="block truncate">{im.nom}</span>
                  {:else}
                    <span class="text-mine">Pas de personne Immich</span>
                  {/if}
                  <span class="block text-xs text-mine truncate">Treemich : {p.treemich?.nom ?? '—'}</span>
                </div>
                {#if p.exacte}<span class="text-xs rounded-full px-2 py-0.5 bg-valide/20 text-valide">exacte</span>{/if}
                <span class="ml-auto flex gap-2">
                  <button class="bouton !py-1" disabled={enCours || (!choix[p.pid] && !p.treemich)} onclick={() => valider([liaisonDe(p)])}>Valider</button>
                  <button class="text-sm text-mine underline underline-offset-2 hover:text-papier" onclick={() => refuser(p)}>Pas lui</button>
                </span>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="text-sm text-mine">Aucune proposition : chaque contact au nom connu d'Immich ou de Treemich est déjà lié.</p>
        {/if}
      </section>

      {#if ecarts.length}
        <section class="mb-10">
          <h2 class="titre text-xl">Orthographes différentes <span class="text-mine text-base font-normal">({ecarts.length})</span></h2>
          <p class="text-sm text-mine mb-3">Choisis l'orthographe juste : elle est écrite dans carnet, Immich et Treemich, au format « Prénom NOM ».
            Pense à corriger aussi une réservation en cours qui utiliserait l'ancien nom.</p>
          <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
            {#each ecarts as p (p.pid)}
              <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 {occupe === p.pid ? 'opacity-60' : ''}">
                {@render visage(p.immich?.id, p.nom)}
                <span class="text-sm text-mine w-64 truncate">Immich : {p.immich?.nom ?? '—'} · Treemich : {p.treemich?.nom ?? '—'}</span>
                <span class="ml-auto flex flex-wrap gap-2">
                  <button class="bouton !py-1" disabled={occupe !== null} onclick={() => corrigerNom(p, 'carnet')}>Garder « {p.nom_immich_propose} »</button>
                  {#if p.immich}<button class="bouton !py-1" disabled={occupe !== null} onclick={() => corrigerNom(p, 'immich')}>Garder « {p.immich.nom} »</button>{/if}
                </span>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if donnees.a_formater?.length}
        {@const lies = donnees.a_formater.filter((x) => x.lie)}
        <section class="mb-10">
          <div class="flex flex-wrap items-center gap-4 mb-2">
            <h2 class="titre text-xl">Noms Immich au format « Prénom NOM » <span class="text-mine text-base font-normal">({donnees.a_formater.length})</span></h2>
            {#if lies.length}
              <button class="bouton bouton-principal ml-auto" disabled={occupe !== null} onclick={() => renommer(lies)}>
                Renommer les {lies.length} personnes liées</button>
            {/if}
          </div>
          <p class="text-sm text-mine mb-3">Pour une personne liée, le nom vient de carnet ; sinon carnet le devine (vérifie les noms composés).
            La personne Treemich correspondante est renommée aussi.</p>
          <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
            {#each donnees.a_formater as x (x.id)}
              <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
                {@render visage(x.id, x.nom)}
                <span class="w-56 truncate">{x.nom}</span>
                <span class="text-mine">→</span>
                <input class="w-64" value={noms[x.id] ?? x.propose} oninput={(e) => (noms[x.id] = e.currentTarget.value)}
                  aria-label={`Nouveau nom de ${x.nom}`} />
                {#if x.lie}<span class="text-xs text-mine">lié</span>{/if}
                <button class="bouton !py-1 ml-auto" disabled={occupe !== null} onclick={() => renommer([x])}>Renommer</button>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if naissances}
        {@const plan = naissances.plan}
        <section class="mb-10">
          <div class="flex flex-wrap items-end gap-4 mb-2">
            <div>
              <h2 class="titre text-xl">Dates de naissance vers Immich et Treemich</h2>
              <p class="text-sm text-mine max-w-3xl">carnet fait foi. Une date sans année ne peut pas être écrite. Une date
                différente n'est remplacée que si tu le demandes ; avant d'écrire dans Treemich, l'arbre est exporté en GEDCOM
                dans carnet/archives, et chaque ancienne valeur est notée dans le journal.</p>
            </div>
            <button class="bouton {plan ? '' : 'bouton-principal'} ml-auto" disabled={enCours}
              onclick={() => lancerNaissances('/api/naissances/simulation')}>{plan ? 'Refaire la simulation' : 'Simuler'}</button>
          </div>
          {#if plan}
            <div class="grid sm:grid-cols-2 gap-3 mb-3 text-sm">
              {#each ['immich', 'treemich'] as c}
                <div class="rounded-xl border border-couture bg-reliure px-4 py-3">
                  <span class="text-papier">{c === 'immich' ? 'Immich' : 'Treemich'}</span> :
                  <span class="text-mine">{plan.resume[c].ajouter} à ajouter, {plan.resume[c].differente} différente(s),
                    {plan.resume[c].identique} identique(s), {plan.resume[c].annee_inconnue} sans année</span>
                </div>
              {/each}
            </div>
            <details class="mb-4">
              <summary class="cursor-pointer text-sm text-mine">Détail par contact</summary>
              <table class="mt-2 w-full text-sm">
                <thead><tr class="text-mine text-xs text-left"><th class="py-1">Contact</th><th>carnet</th><th>Immich</th><th>Treemich</th></tr></thead>
                <tbody>
                  {#each plan.lignes.filter((l) => ['immich', 'treemich'].some((c) => l[c] && l[c].etat !== 'identique' && l[c].etat !== 'rien_dans_carnet')) as l (l.pid)}
                    <tr class="border-t border-couture">
                      <td class="py-1">{l.nom}</td>
                      <td class="tabular-nums">{l.carnet}</td>
                      {#each ['immich', 'treemich'] as c}
                        <td class="tabular-nums {aEcrire(l, c) ? 'text-onglet' : 'text-mine'}">
                          {#if l[c]}{l[c].actuelle || '—'} <span class="text-xs">({ETATS[l[c].etat]})</span>{:else}—{/if}</td>
                      {/each}
                    </tr>
                  {/each}
                </tbody>
              </table>
            </details>
            <label class="flex items-center gap-2 text-sm mb-3">
              <input type="checkbox" bind:checked={remplacer} /> Remplacer aussi les dates différentes (sinon seules les dates absentes sont ajoutées)
            </label>
            <div class="grid gap-4 lg:grid-cols-2">
              <div class="rounded-xl border border-couture bg-reliure p-4 text-sm">
                <p class="mb-2">1. Essai sur une personne</p>
                <div class="flex flex-wrap gap-2">
                  <select class="flex-1" bind:value={essai} aria-label="Personne pour l'essai">
                    <option value="">Choisir…</option>
                    {#each plan.lignes.filter((l) => aEcrire(l, 'immich') || aEcrire(l, 'treemich')) as l}<option value={l.pid}>{l.nom}</option>{/each}
                  </select>
                  <button class="bouton !py-1" disabled={!essai || enCours} onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'immich', essai, remplacer })}>Immich</button>
                  <button class="bouton !py-1" disabled={!essai || enCours} onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'treemich', essai, remplacer })}>Treemich</button>
                </div>
              </div>
              <div class="rounded-xl border border-onglet/60 bg-reliure p-4 text-sm">
                <p class="mb-2">2. Écriture complète</p>
                <label class="flex items-start gap-2 mb-2"><input type="checkbox" class="mt-1" bind:checked={confirmeDates} />
                  <span>J'ai vérifié la simulation.</span></label>
                <div class="flex gap-2">
                  <button class="bouton bouton-principal !py-1" disabled={!confirmeDates || enCours}
                    onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'immich', confirme: true, remplacer })}>Écrire dans Immich</button>
                  <button class="bouton bouton-principal !py-1" disabled={!confirmeDates || enCours}
                    onclick={() => lancerNaissances('/api/naissances/ecriture', { cible: 'treemich', confirme: true, remplacer })}>Écrire dans Treemich</button>
                </div>
              </div>
            </div>
          {/if}
          {#if naissances.journal.length}
            <ul class="mt-4 divide-y divide-couture border-y border-couture text-sm">
              {#each naissances.journal as j}
                <li class="py-2">
                  <span class="text-papier">{dateCourte(j.le)}</span>
                  <span class="text-mine">· {j.essai ? 'Essai' : 'Écriture'} {j.cible} : {j.ecrites.length} date(s){j.sauvegarde ? ` · export ${j.sauvegarde}` : ''}</span>
                  {#if j.ecrites.length}
                    <details class="text-xs text-mine"><summary class="cursor-pointer">Anciennes valeurs</summary>
                      {#each j.ecrites as e}<span class="block">{e.nom} : {e.avant || '—'} → {e.apres}</span>{/each}</details>
                  {/if}
                  {#if j.erreurs.length}<span class="block text-xs text-alerte">{j.erreurs.join(' · ')}</span>{/if}
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}

      {#if portraits?.immich}
        {@const avecHd = portraits.lignes.filter((l) => l.hd).length}
        <section class="mb-10">
          <div class="flex flex-wrap items-end gap-4 mb-2">
            <div>
              <h2 class="titre text-xl">Photos HD depuis Immich <span class="text-mine text-base font-normal">({avecHd}/{portraits.lignes.length})</span></h2>
              <p class="text-sm text-mine max-w-3xl">Pour chaque contact lié sans photo ou avec la vignette Immich, carnet cherche le visage
                entier le plus grand et le plus net, et le découpe en portrait carré depuis la photo d'origine. Il devient la photo du
                contact (iCloud suivra à la prochaine écriture) et la photo de la personne dans Immich. Une photo venue d'iCloud ou de
                Gmail est gardée. Un choix fait ici n'est plus changé automatiquement.</p>
            </div>
            <button class="bouton {portraits.journal.length ? '' : 'bouton-principal'} ml-auto" disabled={enCours}
              onclick={chercherPortraits}>{portraits.journal.length ? 'Relancer la recherche' : 'Chercher les photos HD'}</button>
          </div>
          {#if portraits.journal.length}
            {@const j = portraits.journal[0]}
            <p class="text-xs text-mine mb-3">Dernière recherche le {dateCourte(j.le)} : {j.changees} photo(s) posée(s),
              {j.sans_photo_hd} contact(s) sans visage assez grand{portraits.prochaine ? ` · prochaine recherche automatique vers le ${dateCourte(portraits.prochaine)}` : ''}.
              {#if j.erreurs.length}<span class="block text-alerte">{j.erreurs.join(' · ')}</span>{/if}</p>
            <div class="flex gap-2 text-sm mb-3" role="group" aria-label="Filtrer les photos HD">
              {#each [['sans', 'Sans photo HD'], ['manuel', 'Choisies à la main'], ['tous', 'Tous']] as [v, t]}
                <button class="rounded-full px-3 py-1 border {filtrePortraits === v ? 'border-onglet text-papier' : 'border-couture text-mine'}"
                  onclick={() => (filtrePortraits = v)}>{t}</button>
              {/each}
            </div>
            <ul class="divide-y divide-couture border-y border-couture">
              {#each lignesPortraits as l (l.pid)}
                <li class="py-2 text-sm {occupe === l.pid ? 'opacity-60' : ''}">
                  <div class="flex flex-wrap items-center gap-3">
                    <span class="relative w-14 h-14 shrink-0 rounded-lg overflow-hidden bg-couture grid place-items-center text-mine">
                      {l.nom[0]}
                      {#if l.photo}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/photos/${l.photo}?v=${l.hd?.le ?? ''}`} alt=""
                        onerror={(e) => e.currentTarget.remove()} loading="lazy" />{/if}
                    </span>
                    <span class="flex-1 min-w-0">
                      <a href={`#/revision/${l.pid}`} class="block truncate hover:text-onglet">{l.nom}</a>
                      <span class="block text-xs text-mine">
                        {#if l.hd}visage de {l.hd.taille} px, {netteteLisible(l.hd.nettete)}{l.hd.manuel ? ' · choisie à la main' : ''}
                        {:else if l.candidats.length}pas encore posée{:else}aucune photo où le visage est entier et assez grand{/if}</span>
                    </span>
                    {#if l.candidats.length}
                      <button class="text-xs text-mine underline underline-offset-2 hover:text-papier"
                        onclick={() => (ouvert = ouvert === l.pid ? null : l.pid)}>{ouvert === l.pid ? 'Fermer' : `Autres choix (${l.candidats.length})`}</button>
                    {/if}
                    {#if l.hd?.manuel}
                      <button class="text-xs text-mine underline underline-offset-2 hover:text-papier" disabled={occupe !== null}
                        onclick={() => choisirPortrait(l, null)}>Laisser carnet choisir</button>
                    {/if}
                  </div>
                  {#if ouvert === l.pid}
                    <div class="flex flex-wrap gap-3 mt-3 pl-[4.25rem]">
                      {#each l.candidats as cand (cand.asset)}
                        <button class="w-28 text-left rounded-lg overflow-hidden border-2 {l.hd?.asset === cand.asset ? 'border-onglet' : 'border-transparent hover:border-couture'}"
                          disabled={occupe !== null} onclick={() => choisirPortrait(l, cand.asset)} aria-label={`Choisir cette photo pour ${l.nom}`}>
                          <img class="w-28 h-28 object-cover bg-couture" src={`/api/portraits/apercu/${l.pid}/${cand.asset}`} alt="" loading="lazy" />
                          <span class="block text-[11px] text-mine px-1 py-0.5 leading-tight">{cand.taille} px · {netteteLisible(cand.nettete)}{cand.le ? ` · ${cand.le.slice(0, 4)}` : ''}</span>
                        </button>
                      {/each}
                    </div>
                  {/if}
                </li>
              {:else}
                <li class="py-3 text-sm text-mine">Rien dans ce filtre.</li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}

      <section>
        <div class="flex flex-wrap items-center gap-4 mb-2">
          <h2 class="titre text-xl">Contacts liés <span class="text-mine text-base font-normal">({donnees.liees.length})</span></h2>
          <input class="ml-auto w-56" placeholder="Filtrer" bind:value={filtre} aria-label="Filtrer les contacts liés" />
        </div>
        <ul class="grid sm:grid-cols-2 gap-x-6 divide-y divide-couture border-y border-couture">
          {#each liees as p (p.pid)}
            <li class="flex items-center gap-3 py-2 text-sm">
              {@render visage(p.immich?.id, p.nom)}
              <span class="flex-1 min-w-0">
                <a href={`#/revision/${p.pid}`} class="block truncate hover:text-onglet">{p.nom}</a>
                <span class="block text-xs text-mine truncate">Immich : {p.immich?.nom ?? '—'} · Treemich : {p.treemich?.nom ?? '—'}</span>
              </span>
              <button class="text-xs text-mine underline underline-offset-2 hover:text-papier" onclick={() => delier(p)}>Délier</button>
            </li>
          {/each}
        </ul>
        {#if donnees.dernier_passage}
          <p class="text-xs text-mine mt-3">Dernière mise à jour le {dateCourte(donnees.dernier_passage.le)} :
            {donnees.dernier_passage.photos} photo(s), {donnees.dernier_passage.relations} relation(s),
            {donnees.dernier_passage.a_revoir} à revoir.</p>
        {/if}
      </section>
    {/if}
  {:else}
    <p class="text-mine mt-6">Lecture d'Immich et de Treemich…</p>
  {/if}
</div>
