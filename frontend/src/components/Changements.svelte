<script>
  // Liste des champs qui changent : ancienne valeur barrée, nouvelle surlignée
  let { champs = [] } = $props()
</script>

{#if champs.length}
  <dl class="changements">
    {#each champs as ch}
      <dt class="discret">{ch.libelle}</dt>
      <dd>
        {#each ch.avant.filter((v) => !ch.apres.includes(v)) as v}<span class="avant">{v}</span>{/each}
        {#each ch.apres.filter((v) => !ch.avant.includes(v)) as v}<span class="apres">{v}</span>{/each}
        {#if !ch.apres.length}<span class="discret">(vide)</span>{/if}
      </dd>
    {/each}
  </dl>
{:else}
  <p class="discret">Aucun changement.</p>
{/if}

<style>
  .changements { display: grid; grid-template-columns: minmax(6rem, auto) 1fr; gap: 0.3rem 0.9rem; }
  dd { display: flex; flex-wrap: wrap; gap: 0.25rem 0.6rem; min-width: 0; overflow-wrap: anywhere; }
</style>
