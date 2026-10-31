<script>
  import { api } from '../lib/api.js'
  import { statut, annoncer } from '../lib/etat.svelte.js'
  import { dateCourte, pluriel } from '../lib/cles.js'

  let exports = $state([])
  let sauvegardes = $state(null)
  let tache = $state(null)

  async function chargerSauvegardes() {
    sauvegardes = await api.get('/api/sauvegardes')
    tache = (await api.get('/api/icloud')).tache
    if (['lecture', 'ecriture'].includes(tache?.etat)) setTimeout(chargerSauvegardes, 1000)
  }
  chargerSauvegardes()

  async function sauvegarder(forcer = false) {
    try {
      await api.post(forcer ? '/api/sauvegardes/forcer' : '/api/sauvegardes')
      await chargerSauvegardes()
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  // Test de restauration : la clé saisie (celle d'Enpass) sert une fois et n'est jamais enregistrée
  let cleEnpass = $state('')
  let restauration = $state(null)
  let testEnCours = $state(false)
  async function testerRestauration(avecCle) {
    testEnCours = true
    try {
      restauration = await api.post('/api/sauvegardes/restauration', { cle: avecCle ? cleEnpass : null })
      cleEnpass = ''
      annoncer(restauration.ok ? 'La sauvegarde s\'ouvre et elle est intacte.' : `Échec : ${restauration.motif ?? 'voir le détail'}.`, !restauration.ok)
      await chargerSauvegardes()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      testEnCours = false
    }
  }

  let kit = $state(null)
  let occupe = $state('')

  async function charger() {
    exports = await api.get('/api/exports')
    kit = await api.get('/api/kit')
    Object.assign(statut, await api.get('/api/statut'))
  }
  charger()

  async function exporter() {
    occupe = 'export'
    try {
      const r = await api.post('/api/export')
      annoncer(`${pluriel(r.nb, 'contact exporté', 'contacts exportés')} dans ${r.fichier}.`)
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = ''
    }
  }

  async function envoyerKit() {
    occupe = 'kit'
    try {
      const r = await api.post('/api/kit')
      annoncer(`${pluriel(r.nb, 'contact envoyé', 'contacts envoyés')} au kit. Régénération : ${r.regeneration}.`, !String(r.regeneration).startsWith('ok'))
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = ''
    }
  }
</script>

<div class="grid gap-10 lg:grid-cols-2">
  <section>
    <h1 class="titre text-3xl mb-2">Export propre</h1>
    <p class="text-mine mb-5">
      Un fichier .vcf avec tous les contacts vérifiés, aux formats retenus. Importe-le d'abord sur un
      compte iCloud de test pour contrôler le résultat.
    </p>
    {#if statut.a_reviser}
      <p class="text-sm text-onglet mb-4">{pluriel(statut.a_reviser, 'contact n\'est pas encore vérifié : il ne sera', 'contacts ne sont pas encore vérifiés : ils ne seront')} pas dans l'export.</p>
    {/if}
    <button class="bouton bouton-principal" onclick={exporter} disabled={occupe !== '' || !statut.verifies}>
      {occupe === 'export' ? 'Export…' : `Exporter ${pluriel(statut.verifies, 'contact vérifié', 'contacts vérifiés')}`}
    </button>
    {#if exports.length}
      <h2 class="text-sm text-mine mt-8 mb-2">Exports enregistrés dans carnet/export</h2>
      <ul class="divide-y divide-couture border-y border-couture">
        {#each exports as e}
          <li class="flex items-center py-2.5">
            <span class="flex-1">{e.nom}</span>
            <span class="text-sm text-mine mr-4">{Math.max(1, Math.round(e.taille / 1024))} Ko</span>
            <a class="text-sm underline underline-offset-2 hover:text-onglet" href={`/api/exports/${encodeURIComponent(e.nom)}`} download>Télécharger</a>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section>
    <h2 class="titre text-3xl mb-2">Kit d'urgence</h2>
    <p class="text-mine mb-5">
      Les contacts vérifiés du groupe Urgence remplacent <code>contacts-urgence.vcf</code> dans le kit,
      qui se régénère aussitôt.
    </p>
    {#if kit}
      <div class="rounded-xl border border-couture bg-reliure p-5 mb-5">
        {#if kit.verifies.length}
          <p class="text-sm text-mine mb-2">{pluriel(kit.verifies.length, 'contact sera envoyé', 'contacts seront envoyés')} :</p>
          <ul class="columns-2 text-sm">{#each kit.verifies as nom}<li>{nom}</li>{/each}</ul>
        {:else}
          <p class="text-sm text-mine">Aucun contact vérifié dans le groupe Urgence. Ajoute-le pendant la révision (touche U).</p>
        {/if}
        {#if kit.a_reviser.length}
          <p class="text-sm text-onglet mt-3">Pas encore vérifiés, donc pas envoyés : {kit.a_reviser.join(', ')}.</p>
        {/if}
      </div>
      <button class="bouton bouton-principal" onclick={envoyerKit} disabled={occupe !== '' || !kit.verifies.length}>
        {occupe === 'kit' ? 'Envoi…' : 'Envoyer au kit'}
      </button>
      {#if kit.dernier_envoi}
        <p class="text-sm text-mine mt-3">
          Dernier envoi le {dateCourte(kit.dernier_envoi.le)} : {pluriel(kit.dernier_envoi.nb, 'contact', 'contacts')},
          régénération {kit.dernier_envoi.regeneration}.
        </p>
      {/if}
    {/if}
  </section>

  {#if sauvegardes}
    <section class="lg:col-span-2">
      <div class="flex flex-wrap items-end gap-4 mb-2">
        <div>
          <h2 class="titre text-3xl">Sauvegarde de nuit</h2>
          <p class="text-mine text-sm max-w-3xl">Chaque nuit, après la veille iCloud : un fichier .vcf daté (sans photos, gardé
            {sauvegardes.jours} jours) {sauvegardes.synology ? 'et une copie à l\'identique dans Synology Contacts, bloquée si plus de 5 % des fiches changent d\'un coup' : '— copie Synology non configurée (CARNET_SYNOLOGY_URL)'}.</p>
        </div>
        <button class="bouton ml-auto" disabled={['lecture', 'ecriture'].includes(tache?.etat)} onclick={() => sauvegarder()}>Sauvegarder maintenant</button>
      </div>
      {#if tache && tache.etat !== 'repos' && ['sauvegarde', 'veille'].includes(tache.operation)}
        <p class="text-sm mb-3 {tache.etat === 'erreur' ? 'text-alerte' : 'text-mine'}">{tache.message}
          {#if tache.etat === 'erreur' && tache.message.includes('bloquée')}
            <button class="bouton !py-1 ml-2 !border-alerte !text-alerte" onclick={() => sauvegarder(true)}>Forcer la copie</button>
          {/if}
        </p>
      {/if}
      <div class="grid gap-6 lg:grid-cols-2">
        <ul class="divide-y divide-couture border-y border-couture text-sm">
          {#each sauvegardes.journal as j}
            <li class="py-2 flex flex-wrap gap-x-3">
              <span class="text-papier">{dateCourte(j.le)}</span>
              {#if j.erreur}<span class="text-alerte">{j.erreur}</span>
              {:else}
                <span class="text-mine">{pluriel(j.contacts, 'contact', 'contacts')}{j.synology ? ` ; Synology : ${j.synology.crees} créé(s), ${j.synology.modifies} mis à jour, ${j.synology.supprimes} supprimé(s)` : ''}</span>
                {#if j.synology?.erreurs?.length}<span class="text-alerte text-xs basis-full">{j.synology.erreurs.join(' · ')}</span>{/if}
              {/if}
            </li>
          {:else}
            <li class="py-2 text-mine">Aucune sauvegarde pour l'instant.</li>
          {/each}
        </ul>
        <ul class="divide-y divide-couture border-y border-couture text-sm">
          {#each sauvegardes.fichiers as f}
            <li class="py-2 flex"><span class="flex-1">{f.nom}</span>
              <span class="text-mine mr-4">{Math.max(1, Math.round(f.taille / 1024))} Ko</span>
              <a class="underline underline-offset-2 hover:text-onglet" href={`/api/sauvegardes/${f.nom}`} download>Télécharger</a></li>
          {/each}
        </ul>
      </div>

      <div class="grid gap-6 lg:grid-cols-2 mt-8">
        <div>
          <h3 class="titre text-xl mb-1">Copies de la base</h3>
          <p class="text-mine text-sm mb-3">Chaque nuit, la base entière (fiches, photos, liaisons, historique) est copiée, chiffrée avec
            la même clé, dans <code>archives/sauvegardes</code> ; gardée {sauvegardes.jours_base} jours. Sans la clé, la copie est illisible.</p>
          <ul class="divide-y divide-couture border-y border-couture text-sm">
            {#each sauvegardes.bases as f}
              <li class="py-2 flex"><span class="flex-1">{f.nom}</span>
                <span class="text-mine">{(f.taille / 1048576).toFixed(1)} Mo</span></li>
            {:else}
              <li class="py-2 text-mine">Pas encore de copie : « Sauvegarder maintenant » en crée une.</li>
            {/each}
          </ul>
        </div>
        <div class="rounded-xl border border-couture bg-reliure p-4 text-sm">
          <h3 class="titre text-xl mb-1">Test de restauration</h3>
          <p class="text-mine mb-3">Colle la clé notée dans Enpass : carnet ouvre la dernière copie avec, vérifie qu'elle est intacte,
            la compare à la base en service et relit le dernier .vcf. La clé n'est ni enregistrée ni notée dans le journal.</p>
          <form class="flex flex-wrap gap-2" onsubmit={(e) => { e.preventDefault(); testerRestauration(true) }}>
            <input type="password" class="flex-1 min-w-48" bind:value={cleEnpass} autocomplete="off" spellcheck="false"
              placeholder="Clé de la base (Enpass)" aria-label="Clé de la base notée dans Enpass" />
            <button class="bouton bouton-principal !py-1" type="submit" disabled={!cleEnpass || testEnCours || !sauvegardes.bases.length}>Tester avec cette clé</button>
          </form>
          <button class="text-xs text-mine underline underline-offset-2 hover:text-papier mt-2" disabled={testEnCours || !sauvegardes.bases.length}
            onclick={() => testerRestauration(false)}>Tester avec la clé de la stack</button>
          {#if sauvegardes.restaurations.length}
            <ul class="mt-4 divide-y divide-couture border-y border-couture">
              {#each sauvegardes.restaurations as r}
                <li class="py-2">
                  <span class="text-papier">{dateCourte(r.le)}</span>
                  <span class={r.ok ? 'text-valide' : 'text-alerte'}> · {r.ok ? 'réussi' : 'échec'}</span>
                  <span class="text-mine"> · clé {r.cle === 'Enpass' ? "d'Enpass" : 'de la stack'} · {r.fichier}</span>
                  {#if r.motif}<span class="block text-xs text-alerte">{r.motif}</span>{/if}
                  {#if r.comptes}<span class="block text-xs text-mine">{r.comptes.verifies} contacts vérifiés, {r.comptes.photos} photos,
                    {r.comptes.etat} réglages et journaux{r.vcf?.contacts != null ? ` ; ${r.vcf.fichier} : ${r.vcf.contacts} contacts lisibles` : ''}</span>{/if}
                  {#each r.ecarts as e}<span class="block text-xs text-mine">Écart (normal si des fiches ont changé depuis la copie) : {e}</span>{/each}
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      </div>
    </section>
  {/if}
</div>
