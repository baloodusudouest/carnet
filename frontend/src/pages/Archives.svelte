<script>
  import { api } from '../lib/api.js'
  import { ref } from '../lib/etat.svelte.js'
  import { dateCourte } from '../lib/cles.js'

  let archives = $state([])
  let ouverte = $state(null)
  api.get('/api/archives').then((a) => (archives = a))

  const bientot = $derived(archives.filter((a) => a.bientot))
</script>

<h1 class="titre text-3xl mb-2">Archives</h1>
<p class="text-mine max-w-2xl mb-6">
  Chaque export importé est gardé tel quel pendant {ref.archive_jours ?? 365} jours dans
  <code>carnet/archives</code>, puis supprimé automatiquement. Les fiches déjà fusionnées restent dans carnet.
</p>

{#if bientot.length}
  <div class="rounded-xl border border-onglet/60 bg-onglet-sombre/30 px-5 py-4 mb-6">
    <p class="font-medium text-onglet">Suppression dans moins de {ref.alerte_jours ?? 30} jours</p>
    <p class="text-sm text-mine mt-1">Ouvre l'export concerné pour voir les contacts qu'il contient, et récupère le fichier dans
      <code>carnet/archives</code> si tu veux le garder ailleurs.</p>
  </div>
{/if}

<div class="rounded-xl border border-couture overflow-hidden">
  <table class="w-full text-[0.93rem]">
    <thead class="bg-reliure text-mine text-sm">
      <tr>
        <th class="text-left font-normal px-4 py-2.5">Export</th>
        <th class="text-left font-normal px-4 py-2.5 hidden sm:table-cell">Importé le</th>
        <th class="text-left font-normal px-4 py-2.5 hidden sm:table-cell">Fiches</th>
        <th class="text-left font-normal px-4 py-2.5">Suppression</th>
        <th class="px-4 py-2.5"><span class="sr-only">Contacts</span></th>
      </tr>
    </thead>
    <tbody>
      {#each archives as a (a.id)}
        <tr class="border-t border-couture/70 {a.bientot ? 'bg-onglet-sombre/20' : ''}">
          <td class="px-4 py-2.5 break-all">{a.libelle}<span class="block text-xs text-mine">{a.fichier}</span>
            <span class="block text-xs text-mine sm:hidden">importé le {dateCourte(a.importe_le)}</span></td>
          <td class="px-4 py-2.5 text-mine hidden sm:table-cell">{dateCourte(a.importe_le)}</td>
          <td class="px-4 py-2.5 text-mine tabular-nums hidden sm:table-cell">{a.lus} lues, {a.ajoutes} ajoutées</td>
          <td class="px-4 py-2.5 {a.bientot ? 'text-onglet' : 'text-mine'}">
            {#if a.purge_le}supprimée le {dateCourte(a.purge_le)}
            {:else}le {dateCourte(a.expire_le)} <span class="text-xs">(dans {a.jours_restants} j)</span>{/if}
          </td>
          <td class="px-4 py-2.5 text-right">
            <button class="text-sm underline underline-offset-2 text-mine hover:text-papier"
              aria-expanded={ouverte === a.id} onclick={() => (ouverte = ouverte === a.id ? null : a.id)}>
              {ouverte === a.id ? 'Masquer' : `${a.contacts.length} contacts`}
            </button>
          </td>
        </tr>
        {#if ouverte === a.id}
          <tr class="bg-reliure/60">
            <td colspan="5" class="px-4 py-3 text-sm text-mine">
              <ul class="columns-2 md:columns-4 gap-6">{#each a.contacts as nom}<li>{nom}</li>{/each}</ul>
            </td>
          </tr>
        {/if}
      {:else}
        <tr><td colspan="5" class="px-4 py-10 text-center text-mine">Aucun export importé pour l'instant.</td></tr>
      {/each}
    </tbody>
  </table>
</div>
