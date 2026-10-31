<script>
  // Vue iPhone : les autres pages de carnet (celles du PC), la bascule vers la vue PC et la déconnexion.
  import { statut, choisirVue } from '../lib/etat.svelte.js'

  let { deconnecter } = $props()
  const PAGES = [
    { cle: 'importer', nom: 'Importer des exports', aide: 'Dépôt des fichiers iCloud, Gmail, Outlook, LinkedIn' },
    { cle: 'revision', nom: 'Révision', aide: 'Fusion champ par champ — à faire sur PC' },
    { cle: 'revue', nom: 'Revue', aide: 'Points à compléter sur les contacts vérifiés' },
    { cle: 'liaisons', nom: 'Liaisons Immich et Treemich', aide: 'Visages, arbre, dates de naissance' },
    { cle: 'icloud', nom: 'iCloud', aide: 'Simulation, écriture, veille de nuit' },
    { cle: 'groupes', nom: 'Groupes', aide: 'Créer, renommer, supprimer' },
    { cle: 'export', nom: 'Export, kit et sauvegardes', aide: 'Fichiers .vcf, kit d\u2019urgence, restauration' },
    { cle: 'archives', nom: 'Archives', aide: 'Exports déposés et leur expiration' },
  ]
</script>

<h1 class="titre text-2xl mb-3">Plus</h1>
<ul class="rounded-2xl border border-couture divide-y divide-couture overflow-hidden bg-reliure">
  {#each PAGES as p}
    <li>
      <a href={`#/${p.cle}`} class="flex items-center gap-3 px-4 min-h-14 py-2 active:bg-couture">
        <span class="flex-1 min-w-0">
          <span class="block text-papier">{p.nom}
            {#if p.cle === 'revision' && statut.a_reviser}<span class="ml-1 rounded-full bg-onglet-sombre text-onglet text-xs px-1.5 tabular-nums">{statut.a_reviser}</span>{/if}</span>
          <span class="block text-xs text-mine truncate">{p.aide}</span>
        </span>
        <span class="text-mine" aria-hidden="true">›</span>
      </a>
    </li>
  {/each}
</ul>

<ul class="mt-6 rounded-2xl border border-couture divide-y divide-couture overflow-hidden bg-reliure">
  <li><button class="w-full text-left px-4 min-h-12 text-papier active:bg-couture" onclick={() => choisirVue(true)}>Afficher la vue PC</button></li>
  <li><button class="w-full text-left px-4 min-h-12 text-alerte active:bg-couture" onclick={deconnecter}>Se déconnecter</button></li>
</ul>
