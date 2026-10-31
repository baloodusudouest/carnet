<script>
  // Accueil : chercher un contact, et le bilan de tout ce qui attend une action.
  import { api } from '../lib/api.js'
  import { bilan, ecran } from '../lib/etat.svelte.js'
  import { cleTexte, dateCourte, pluriel } from '../lib/cles.js'

  let contacts = $state([])
  let recherche = $state('')
  api.get('/api/contacts').then((l) => (contacts = l.filter((p) => p.statut !== 'ecarte')))
  api.get('/api/bilan').then((b) => (bilan.donnees = b)).catch(() => {})

  const resultats = $derived.by(() => {
    const q = cleTexte(recherche)
    const chiffres = recherche.replace(/\D/g, '')
    if (!q) return []
    return contacts.filter((p) => cleTexte(`${p.nom} ${p.societe} ${p.courriel}`).includes(q)
      || (chiffres.length >= 3 && (p.telephone ?? '').replace(/\D/g, '').includes(chiffres))).slice(0, 8)
  })

  const JOURS_TEST = 90   // un test de restauration de plus de 3 mois est à refaire
  const cartes = $derived.by(() => {
    const b = bilan.donnees
    if (!b) return []
    const s = b.statut
    const c = []
    c.push({ titre: 'Fiches à réviser', n: s.a_reviser, lien: '#/revision',
      texte: s.a_reviser ? `dont ${pluriel(s.doublons_a_reviser, 'doublon', 'doublons')} à fusionner` : 'Tout est relu.' })
    if (b.revue != null) c.push({ titre: 'Points à compléter', n: b.revue, lien: '#/revue',
      texte: b.revue ? 'Anniversaires, sociétés, numéros… sur les contacts vérifiés' : 'Rien à compléter.' })
    if (b.liaisons) {
      const n = b.liaisons.propositions + b.liaisons.orthographes + b.liaisons.noms_immich
      c.push({ titre: 'Liaisons Immich et Treemich', n, lien: '#/liaisons', erreur: b.liaisons.erreurs?.[0],
        texte: n ? [b.liaisons.propositions && `${b.liaisons.propositions} à valider`, b.liaisons.orthographes && `${b.liaisons.orthographes} orthographe(s)`,
          b.liaisons.noms_immich && `${b.liaisons.noms_immich} nom(s) Immich`].filter(Boolean).join(', ') : 'Tout est lié.' })
    }
    if (b.photos) {
      const n = b.photos.hd + b.photos.affiches
      c.push({ titre: 'Photos à choisir', n, lien: '#/photos',
        texte: n ? [b.photos.hd && `${b.photos.hd} photo(s) HD`, b.photos.affiches && `${b.photos.affiches} affiche(s)`].filter(Boolean).join(', ') : 'Rien en attente.' })
    }
    if (s.linkedin_sans_contact) c.push({ titre: 'Relations LinkedIn sans contact', n: s.linkedin_sans_contact, lien: '#/contacts', info: true,
      texte: 'À rattacher à la main (Contacts › LinkedIn uniquement), ou à ignorer' })
    const v = s.veille
    c.push({ titre: 'iCloud', n: v && !v.ok ? 1 : 0, lien: '#/icloud', erreur: v && !v.ok ? v.erreur : null,
      texte: [s.derniere_ecriture_icloud ? `Dernière écriture le ${dateCourte(s.derniere_ecriture_icloud.le)}` : 'Jamais écrit',
        v ? `veille du ${dateCourte(v.le)} : ${v.modifies + v.nouveaux + v.supprimes} écart(s)${v.revision ? '' : ' (journal)'}` : null].filter(Boolean).join(' · ') })
    const sv = s.sauvegarde, r = b.restauration
    const testVieux = !r || !r.ok || (Date.now() - new Date(r.le)) / 864e5 > JOURS_TEST
    c.push({ titre: 'Sauvegarde', n: (sv && !sv.ok ? 1 : 0) + (testVieux ? 1 : 0), lien: '#/export', erreur: sv && !sv.ok ? sv.erreur : null,
      texte: [sv ? `Nuit du ${dateCourte(sv.le)} : ${sv.ok ? 'réussie' : 'échec'}` : 'Aucune sauvegarde',
        r ? `test de restauration ${r.ok ? 'réussi' : 'raté'} le ${dateCourte(r.le)}${testVieux && r.ok ? ' (à refaire)' : ''}` : 'test de restauration jamais fait'].join(' · ') })
    if (s.archives_bientot) c.push({ titre: 'Archives bientôt supprimées', n: s.archives_bientot, lien: '#/archives',
      texte: `${pluriel(s.contacts_archives_bientot, 'contact concerné', 'contacts concernés')}` })
    return c.sort((a, z) => (z.n > 0 && !z.info) - (a.n > 0 && !a.info))
  })
  const enAttente = $derived(cartes.filter((c) => c.n > 0 && !c.info).length)
  const tache = $derived(bilan.donnees?.tache)
</script>

<div class="max-w-5xl mx-auto">
  <h1 class="titre text-3xl {ecran.etroit && !ecran.forcerPC ? 'text-2xl' : ''} mb-4">Bonjour</h1>

  <div class="relative mb-8">
    <input class="w-full h-12 !rounded-xl !px-4 text-base" type="search" placeholder="Chercher : nom, société, numéro…"
      bind:value={recherche} aria-label="Chercher un contact" autocomplete="off" />
    {#if resultats.length}
      <ul class="absolute z-20 inset-x-0 mt-1 rounded-xl border border-tranche bg-reliure shadow-2xl divide-y divide-couture overflow-hidden">
        {#each resultats as p (p.id)}
          <li>
            <a href={`#/fiche/${p.id}`} class="flex items-center gap-3 px-3 py-2 hover:bg-couture">
              <span class="relative w-9 h-9 shrink-0 rounded-full overflow-hidden bg-couture grid place-items-center text-mine text-sm">
                {p.nom?.[0] ?? '?'}
                {#if p.photo}<img class="absolute inset-0 w-full h-full object-cover" src={`/api/photos/${p.photo}?taille=72`} alt=""
                  width="36" height="36" onerror={(e) => e.currentTarget.remove()} />{/if}
              </span>
              <span class="flex-1 min-w-0"><span class="block truncate">{p.nom}</span>
                <span class="block truncate text-xs text-mine">{p.societe || p.telephone || p.courriel}</span></span>
              {#if p.statut !== 'verifie'}<span class="text-xs text-onglet">à relire</span>{/if}
            </a>
          </li>
        {/each}
      </ul>
    {:else if recherche.trim()}
      <p class="text-sm text-mine mt-2">Aucun contact ne correspond.</p>
    {/if}
  </div>

  <div class="flex items-baseline gap-3 mb-3">
    <h2 class="titre text-xl">En attente</h2>
    {#if bilan.donnees}<span class="text-sm text-mine">{enAttente ? pluriel(enAttente, 'point demande', 'points demandent') + ' ton attention' : 'Tout est à jour.'}</span>{/if}
  </div>
  {#if tache && ['lecture', 'ecriture'].includes(tache.etat)}
    <p class="text-sm text-mine mb-3">En cours : {tache.message}{tache.total ? ` (${tache.fait}/${tache.total})` : ''}</p>
  {/if}
  {#if !bilan.donnees}
    <p class="text-mine">Chargement du bilan…</p>
  {:else}
    <ul class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each cartes as c (c.titre)}
        {@const actif = c.n > 0 && !c.info}
        <li>
          <a href={c.lien} class="flex h-full flex-col rounded-2xl border p-4 transition-colors
            {c.erreur ? 'border-alerte/70 bg-[#2a1b1b]' : actif ? 'border-onglet/50 bg-reliure hover:border-onglet' : 'border-couture bg-reliure/50 hover:border-tranche'}">
            <span class="flex items-start gap-3">
              <span class="flex-1 text-sm {actif || c.erreur ? 'text-papier' : 'text-mine'}">{c.titre}</span>
              {#if c.n > 0 && c.titre !== 'iCloud' && c.titre !== 'Sauvegarde'}
                <span class="titre text-2xl leading-none tabular-nums {c.info ? 'text-mine' : 'text-onglet'}">{c.n}</span>
              {:else if !c.n}<span class="text-valide" aria-label="à jour">✓</span>{/if}
            </span>
            <span class="mt-2 text-xs {c.erreur ? 'text-alerte' : 'text-mine'}">{c.erreur ?? c.texte}</span>
            {#if c.erreur}<span class="mt-1 text-xs text-mine">{c.texte}</span>{/if}
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</div>
