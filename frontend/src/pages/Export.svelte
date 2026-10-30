<script>
  import { api } from '../lib/api.js'
  import { statut, annoncer } from '../lib/etat.svelte.js'
  import { dateCourte, pluriel } from '../lib/cles.js'

  let exports = $state([])
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
</div>
