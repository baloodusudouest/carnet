<script>
  import { api } from '../lib/api.js'
  import { ref, statut, annoncer, aller } from '../lib/etat.svelte.js'
  import { dateCourte, pluriel } from '../lib/cles.js'

  let depot = $state([])
  let choix = $state({})
  let enCours = $state(null)
  let bilan = $state(null)
  let survol = $state(false)

  async function rafraichir() {
    depot = await api.get('/api/depot')
    for (const f of depot) if (!(f.nom in choix)) choix[f.nom] = f.source ?? ''
    Object.assign(statut, await api.get('/api/statut'))
  }
  rafraichir()

  async function envoyer(fichiers) {
    if (!fichiers?.length) return
    const fd = new FormData()
    for (const f of fichiers) fd.append('fichiers', f)
    try {
      await api.post('/api/depot', fd)
      await rafraichir()
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  async function importer(nom) {
    if (!choix[nom]) return annoncer('Choisis la source de ce fichier.', true)
    enCours = nom
    try {
      bilan = { nom, ...(await api.post('/api/importer', { nom, source: choix[nom] })) }
      await rafraichir()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      enCours = null
    }
  }

  function deposer(e) {
    e.preventDefault()
    survol = false
    envoyer(e.dataTransfer.files)
  }
</script>

<div class="grid gap-10 lg:grid-cols-[1fr_340px]">
  <section>
    <h1 class="titre text-3xl mb-2">Rassembler les carnets</h1>
    <p class="text-mine max-w-2xl mb-6">
      Dépose ici les exports d'iCloud, Gmail, Outlook et LinkedIn. Chaque fichier est archivé
      avant d'être lu, puis les doublons sont regroupés pour la révision.
    </p>

    <label
      class="block rounded-xl border border-dashed px-6 py-8 text-center cursor-pointer transition-colors
        {survol ? 'border-onglet bg-onglet-sombre/40' : 'border-tranche hover:border-mine'}"
      ondragover={(e) => { e.preventDefault(); survol = true }}
      ondragleave={() => (survol = false)}
      ondrop={deposer}
    >
      <input type="file" class="sr-only" accept=".vcf,.vcard,.csv" multiple
        onchange={(e) => envoyer(e.currentTarget.files)} />
      <span class="block text-papier">Glisse les fichiers .vcf ou .csv ici, ou clique pour les choisir</span>
      <span class="block text-sm text-mine mt-1">Tu peux aussi les copier dans le dossier <code>carnet/depot</code> du NAS.</span>
    </label>

    {#if depot.length}
      <ul class="mt-6 divide-y divide-couture border-y border-couture">
        {#each depot as f (f.nom)}
          <li class="flex items-center gap-4 py-3">
            <span class="flex-1 truncate">{f.nom}
              <span class="text-mine text-sm ml-2">{Math.max(1, Math.round(f.taille / 1024))} Ko</span>
            </span>
            <select bind:value={choix[f.nom]} aria-label={`Source de ${f.nom}`}>
              <option value="" disabled>Source…</option>
              {#each Object.entries(ref.sources) as [cle, nom]}
                <option value={cle}>{nom}</option>
              {/each}
            </select>
            <button class="bouton bouton-principal" disabled={enCours !== null} onclick={() => importer(f.nom)}>
              {enCours === f.nom ? 'Import…' : 'Importer'}
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if bilan}
      <div class="mt-6 rounded-lg border border-couture bg-reliure px-5 py-4" role="status">
        <p class="font-medium">{bilan.nom} importé ({ref.sources[bilan.source]})</p>
        <p class="text-mine text-sm mt-1">
          {pluriel(bilan.lus, 'fiche lue', 'fiches lues')}, {pluriel(bilan.ajoutes, 'ajoutée', 'ajoutées')}{bilan.identiques ? `, ${pluriel(bilan.identiques, 'déjà connue', 'déjà connues')}` : ''}.
          {#if bilan.source === 'linkedin'}
            {pluriel(bilan.enrichies, 'contact complété', 'contacts complétés')} ; les autres relations LinkedIn ne créent pas de contact.
          {:else}
            {pluriel(bilan.personnes_creees, 'nouveau contact', 'nouveaux contacts')}, {pluriel(bilan.personnes_completees, 'fiche rapprochée', 'fiches rapprochées')} d'un contact existant.
          {/if}
        </p>
        {#if bilan.avertissements?.length}
          <details class="mt-2 text-sm text-mine">
            <summary class="cursor-pointer">{bilan.avertissements.length} avertissement(s)</summary>
            <ul class="mt-1 list-disc pl-5">{#each bilan.avertissements as a}<li>{a}</li>{/each}</ul>
          </details>
        {/if}
      </div>
    {/if}
  </section>

  <aside class="space-y-6">
    <div class="rounded-xl border border-couture bg-reliure p-6">
      <h2 class="titre text-xl mb-4">Où tu en es</h2>
      <dl class="space-y-3">
        <div class="flex justify-between"><dt class="text-mine">Contacts</dt><dd class="tabular-nums">{statut.total}</dd></div>
        <div class="flex justify-between"><dt class="text-mine">Vérifiés</dt><dd class="tabular-nums text-valide">{statut.verifies}</dd></div>
        <div class="flex justify-between"><dt class="text-mine">À relire</dt><dd class="tabular-nums">{statut.a_reviser}</dd></div>
        <div class="flex justify-between"><dt class="text-mine">dont doublons à fusionner</dt><dd class="tabular-nums">{statut.doublons_a_reviser ?? 0}</dd></div>
        {#if statut.linkedin_sans_contact}
          <div class="flex justify-between"><dt class="text-mine">Relations LinkedIn sans contact</dt><dd class="tabular-nums">{statut.linkedin_sans_contact}</dd></div>
        {/if}
      </dl>
      <button class="bouton bouton-principal w-full justify-center mt-6" disabled={!statut.a_reviser}
        onclick={() => aller('revision')}>
        {statut.a_reviser ? 'Reprendre la révision' : 'Rien à relire'}
      </button>
    </div>

    {#if statut.archives_bientot}
      <a href="#/archives" class="block rounded-xl border border-onglet/60 bg-onglet-sombre/30 p-5">
        <p class="font-medium text-onglet">Archives bientôt supprimées</p>
        <p class="text-sm text-mine mt-1">
          {statut.archives_bientot} export(s), soit {statut.contacts_archives_bientot} fiches,
          seront effacés à partir du {dateCourte(statut.prochaine_suppression)}.
        </p>
      </a>
    {/if}
  </aside>
</div>
