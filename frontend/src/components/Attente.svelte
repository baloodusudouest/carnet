<script>
  // Changements en attente pour iCloud, tous sur une liste : un résumé, un toucher l'ouvre ;
  // chaque fiche se valide (écrite dans iCloud tout de suite) ou se revoit (retour en Révision).
  import { api } from '../lib/api.js'
  import { annoncer, chargerBilan } from '../lib/etat.svelte.js'

  let donnees = $state(null)
  let ouvert = $state(false)
  let choix = $state({})            // id → 'valider' | 'revoir'
  let tache = $state(null)
  let occupe = $state(false)

  const enCours = $derived(['lecture', 'ecriture'].includes(tache?.etat))

  async function charger(auto = false) {
    try {
      donnees = await api.get('/api/synchro/attente')
      tache = donnees.tache
      if (['lecture', 'ecriture'].includes(tache?.etat)) return setTimeout(() => charger(false), 1200)
      if (auto && !donnees.plan && donnees.configure) await actualiser()
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  charger(true)

  async function actualiser() {
    try {
      await api.post('/api/synchro/attente/actualiser')
      tache = { etat: 'lecture', message: 'Lecture d\'iCloud…' }
      setTimeout(() => charger(false), 1200)
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  const lignes = $derived(donnees?.plan?.lignes ?? [])
  const compte = (cible, action) => lignes.filter((l) => l.cible === cible && l.action === action).length
  const resume = $derived.by(() => {
    const p = []
    const m = compte('contact', 'modifier'), c = compte('contact', 'creer'), s = compte('contact', 'supprimer')
    const g = lignes.filter((l) => l.cible === 'groupe').length
    if (m) p.push(`${m} modification${m > 1 ? 's' : ''}`)
    if (c) p.push(`${c} création${c > 1 ? 's' : ''}`)
    if (s) p.push(`${s} suppression${s > 1 ? 's' : ''}`)
    if (g) p.push(`${g} groupe${g > 1 ? 's' : ''}`)
    return p.join(' · ')
  })
  const SECTIONS = [
    ['contact', 'modifier', 'Modifications'], ['contact', 'creer', 'Créations'],
    ['contact', 'supprimer', 'Suppressions'], ['groupe', null, 'Groupes'],
  ]
  const CHAMPS = { prenom: 'Prénom', nom: 'Nom', surnom: 'Surnom', societe: 'Société', fonction: 'Fonction', anniversaire: 'Anniversaire',
    notes: 'Notes', telephones: 'Téléphones', courriels: 'Courriels', adresses: 'Adresses', sites: 'Sites', noms_associes: 'Noms associés',
    groupes: 'Groupes', forme: 'Mise en forme seulement', carte: 'Carte' }
  const nbChoix = $derived(Object.values(choix).filter(Boolean).length)

  function basculer(id, valeur) {
    choix = { ...choix, [id]: choix[id] === valeur ? null : valeur }
  }
  function toutValider() {
    choix = Object.fromEntries(lignes.map((l) => [l.id, 'valider']))
  }
  async function appliquer() {
    const valider = Object.keys(choix).filter((k) => choix[k] === 'valider')
    const revoir = Object.keys(choix).filter((k) => choix[k] === 'revoir')
    occupe = true
    try {
      const r = await api.post('/api/synchro/attente/decision', { valider, revoir })
      choix = {}
      annoncer([r.ecrites && `${r.ecrites} écrite(s) dans iCloud`, r.revues && `${r.revues} remise(s) en révision`].filter(Boolean).join(', ') + '.')
      tache = r.ecrites ? { etat: 'ecriture', message: 'Écriture dans iCloud…' } : tache
      setTimeout(() => { charger(false); chargerBilan(api).catch(() => {}) }, r.ecrites ? 1200 : 0)
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }
  const minutes = $derived(donnees?.plan ? Math.max(0, Math.round((30 * 60 - donnees.plan.valable_encore) / 60)) : null)
</script>

<section class="rounded-2xl border {lignes.length ? 'border-onglet/60' : 'border-couture'} bg-reliure mb-4" aria-labelledby="t-attente">
  <div class="flex items-center gap-2 p-2 pl-4">
    <button class="flex-1 min-h-14 text-left" aria-expanded={ouvert} disabled={!lignes.length} onclick={() => (ouvert = !ouvert)}>
      <h2 id="t-attente" class="text-papier">Changements pour iCloud
        {#if lignes.length}<span class="text-onglet tabular-nums">{lignes.length}</span>{/if}</h2>
      <span class="block text-sm text-mine">
        {#if enCours}{tache.message}{:else if !donnees}Chargement…{:else if !donnees.configure}Identifiants iCloud absents de la stack.
        {:else if !donnees.plan}Pas encore lu.{:else if lignes.length}{resume} · lu il y a {minutes} min{:else}iCloud est à jour (lu il y a {minutes} min).{/if}
      </span>
    </button>
    {#if lignes.length}<span class="text-mine px-1" aria-hidden="true">{ouvert ? '▾' : '▸'}</span>{/if}
    <button class="w-11 h-11 rounded-full border border-couture text-onglet grid place-items-center disabled:opacity-50" disabled={enCours || !donnees?.configure}
      onclick={actualiser} aria-label="Relire iCloud pour mettre la liste à jour">
      <svg viewBox="0 0 24 24" class="w-5 h-5 {enCours ? 'animate-spin' : ''}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M20 12a8 8 0 1 1-2.34-5.66" /><path d="M20 4v5h-5" /></svg>
    </button>
  </div>

  {#if ouvert && lignes.length}
    <div class="border-t border-couture px-3 pb-3">
      <p class="text-xs text-mine py-2">Valider : écrit dans iCloud tout de suite. Revoir : la fiche repasse en Révision, rien n'est écrit.</p>
      {#each SECTIONS as [cible, action, titre]}
        {@const liste = lignes.filter((l) => l.cible === cible && (!action || l.action === action))}
        {#if liste.length}
          <h3 class="text-xs text-mine mt-3 mb-1">{titre} ({liste.length})</h3>
          <ul class="grid gap-2">
            {#each liste as l (l.id)}
              <li class="rounded-xl border p-2.5 {choix[l.id] === 'valider' ? 'border-valide/60' : choix[l.id] === 'revoir' ? 'border-onglet/70' : 'border-couture'}">
                <div class="flex flex-wrap items-start gap-2">
                  <div class="flex-1 min-w-40">
                    {#if l.pid}<a class="text-papier hover:underline" href={`#/fiche/${l.pid}`}>{l.nom}</a>{:else}<span class="text-papier">{l.nom}</span>{/if}
                    {#if l.motif}<span class="block text-xs text-mine">{l.motif}</span>{/if}
                    {#if l.cible === 'groupe' && l.action !== 'supprimer'}<span class="block text-xs text-mine">{[l.ajoutes && `+${l.ajoutes} membre(s)`, l.retires && `−${l.retires} membre(s)`].filter(Boolean).join(', ')}</span>{/if}
                    {#each l.ecarts as e}
                      <span class="block text-xs mt-0.5"><span class="text-mine">{CHAMPS[e.champ] ?? e.champ}</span>
                        {#if e.avant || e.apres}<span class="text-mine/80 line-through decoration-mine/60"> {e.avant || '—'}</span> <span class="text-papier">→ {e.apres || 'vide'}</span>{/if}</span>
                    {/each}
                  </div>
                  <div class="flex gap-1.5">
                    <button class="min-h-11 px-3 rounded-lg border text-sm {choix[l.id] === 'valider' ? 'bg-valide/20 border-valide text-valide' : 'border-couture text-papier'}"
                      aria-pressed={choix[l.id] === 'valider'} onclick={() => basculer(l.id, 'valider')}>Valider</button>
                    {#if l.pid}
                      <button class="min-h-11 px-3 rounded-lg border text-sm {choix[l.id] === 'revoir' ? 'bg-onglet/20 border-onglet text-onglet' : 'border-couture text-papier'}"
                        aria-pressed={choix[l.id] === 'revoir'} onclick={() => basculer(l.id, 'revoir')}>Revoir</button>
                    {/if}
                  </div>
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      {/each}
      <div class="sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] md:bottom-2 mt-3 flex flex-wrap gap-2 rounded-xl bg-reliure/95 backdrop-blur-md py-2">
        <button class="bouton min-h-11" onclick={toutValider} disabled={occupe || enCours}>Tout valider</button>
        <button class="bouton bouton-principal min-h-11 flex-1 justify-center" disabled={!nbChoix || occupe || enCours} onclick={appliquer}>
          Appliquer {nbChoix ? `(${nbChoix})` : ''}</button>
      </div>
    </div>
  {/if}
</section>
