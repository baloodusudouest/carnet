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

  // LinkedIn par l'API de portabilité : le jeton sert une fois, il n'est pas enregistré
  let jetonLinkedin = $state('')
  let adresseRetour = $state('')
  let linkedin = $state({ oauth: false, retour: '' })
  api.get('/api/linkedin/etat').then((r) => (linkedin = r))

  async function connecterLinkedin() {
    try {
      const { url } = await api.post('/api/linkedin/autorisation')
      window.open(url, '_blank', 'noopener')
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  async function importerLinkedin(parCode = false) {
    enCours = 'linkedin'
    try {
      const r = parCode === 'reessayer'
        ? await api.post('/api/linkedin/reessayer')
        : parCode
          ? await api.post('/api/linkedin/code', { adresse: adresseRetour })
          : await api.post('/api/linkedin', { jeton: jetonLinkedin })
      adresseRetour = ''
      bilan = { nom: 'Relations LinkedIn (API)', ...r }
      jetonLinkedin = ''
      await rafraichir()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      enCours = null
      linkedin = await api.get('/api/linkedin/etat')
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

    <details class="mt-4 rounded-xl border border-couture bg-reliure px-5 py-3">
      <summary class="cursor-pointer text-sm">LinkedIn sans archive : relations lues par l'API de portabilité</summary>
      {#if linkedin.en_attente}
        <p class="text-sm mt-2 rounded-md border border-onglet/60 px-3 py-2">Connexion LinkedIn faite : les données
          sont en préparation chez LinkedIn (environ 30 minutes après la première autorisation).
          <button class="bouton !py-1 ml-2" disabled={enCours !== null} onclick={() => importerLinkedin('reessayer')}>
            {enCours === 'linkedin' ? 'Lecture…' : 'Réessayer'}</button></p>
      {/if}
      {#if linkedin.oauth}
        <ol class="text-sm text-mine mt-2 list-decimal pl-5 space-y-2">
          <li><button class="bouton !py-1" onclick={connecterLinkedin}>Se connecter à LinkedIn</button>
            <span class="block mt-1">Un onglet s'ouvre : accepte l'accès. LinkedIn renvoie ensuite vers
              <code>{linkedin.retour}</code>, une page qui ne s'affiche pas : c'est normal.</span></li>
          <li>Copie l'adresse complète de cette page (elle contient <code>?code=</code>) et colle-la ici :
            <div class="flex flex-wrap gap-2 mt-1">
              <input class="flex-1 min-w-64" bind:value={adresseRetour} placeholder={`${linkedin.retour}?code=…&state=…`} autocomplete="off" />
              <button class="bouton bouton-principal" disabled={!adresseRetour.trim() || enCours !== null} onclick={() => importerLinkedin(true)}>
                {enCours === 'linkedin' ? 'Lecture…' : 'Importer les relations'}</button>
            </div></li>
        </ol>
      {:else}
        <p class="text-sm text-mine mt-2">Pour un bouton de connexion, ajoute <code>CARNET_LINKEDIN_CLIENT_ID</code> et
          <code>CARNET_LINKEDIN_CLIENT_SECRET</code> (onglet Auth de l'app LinkedIn) dans les variables de la stack.</p>
      {/if}
      <p class="text-sm text-mine mt-3">Ou colle un jeton créé dans l'outil OAuth de LinkedIn (portée <code>r_dma_portability_self_serve</code>).
        Rien n'est enregistré.</p>
      <div class="flex flex-wrap gap-2 mt-2">
        <input type="password" class="flex-1 min-w-64" bind:value={jetonLinkedin} placeholder="Jeton d'accès LinkedIn" autocomplete="off" />
        <button class="bouton" disabled={!jetonLinkedin.trim() || enCours !== null} onclick={() => importerLinkedin(false)}>
          Importer avec ce jeton</button>
      </div>
    </details>

    {#if depot.length}
      <ul class="mt-6 divide-y divide-couture border-y border-couture">
        {#each depot as f (f.nom)}
          <li class="flex items-center gap-4 py-3">
            <span class="flex-1 truncate">{f.nom}
              <span class="text-mine text-sm ml-2">{Math.max(1, Math.round(f.taille / 1024))} Ko</span>
            </span>
            <select bind:value={choix[f.nom]} aria-label={`Source de ${f.nom}`}>
              <option value="" disabled>Source…</option>
              {#each Object.entries(ref.sources).filter(([cle]) => cle !== 'immich') as [cle, nom]}
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
