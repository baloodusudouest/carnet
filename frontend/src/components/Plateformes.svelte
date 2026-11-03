<script>
  import { PLATEFORMES, ORDRE as ordre } from '../lib/plateformes.js'
  // Plateformes reliées à une fiche : pastilles à deux lettres, une couleur par réseau.
  // (Pas de logos de marque : des abréviations, lisibles en petit.)
  let { liste = [], toutes = false, taille = 'petit' } = $props()
  const affichees = $derived(toutes ? ordre : ordre.filter((p) => liste.includes(p) && p !== 'icloud'))
</script>

{#if affichees.length}
  <span class="plateformes" class:grand={taille === 'grand'} aria-label={'Plateformes : ' + affichees.filter((p) => liste.includes(p)).map((p) => PLATEFORMES[p].nom).join(', ')}>
    {#each affichees as p}
      <span class="pf" class:absente={!liste.includes(p)} style:--teinte={PLATEFORMES[p].teinte} title={PLATEFORMES[p].nom}>{PLATEFORMES[p].court}</span>
    {/each}
  </span>
{/if}

<style>
  .plateformes { display: inline-flex; flex-wrap: wrap; gap: 3px; }
  .pf {
    display: inline-grid; place-items: center; min-width: 1.35rem; height: 1.1rem; padding: 0 0.2rem; border-radius: 4px;
    font-size: 0.62rem; font-weight: 700; letter-spacing: 0.02em; color: #1c1715; background: var(--teinte);
  }
  .grand .pf { min-width: 2rem; height: 1.6rem; font-size: 0.8rem; border-radius: 6px; }
  .pf.absente { background: transparent; color: var(--color-tranche); box-shadow: inset 0 0 0 1px var(--color-couture); }
</style>
