<script>
  // Plateformes reliées à une fiche : icône officielle du réseau, ou ses deux lettres si
  // l'icône n'a pas pu être récupérée. En mode « toutes », les réseaux absents sont estompés.
  import { PLATEFORMES, ORDRE as ordre } from '../lib/plateformes.js'
  import { absents, logoReseau } from '../lib/logos.svelte.js'
  let { liste = [], toutes = false, taille = 'petit' } = $props()
  const affichees = $derived(toutes ? ordre : ordre.filter((p) => liste.includes(p) && p !== 'icloud'))
</script>

{#if affichees.length}
  <span class="plateformes" class:grand={taille === 'grand'} aria-label={'Plateformes : ' + affichees.filter((p) => liste.includes(p)).map((p) => PLATEFORMES[p].nom).join(', ')}>
    {#each affichees as p}
      <span class="pf" class:absente={!liste.includes(p)} class:lettres={absents[p]} style:--teinte={PLATEFORMES[p].teinte}
            title={PLATEFORMES[p].nom + (liste.includes(p) ? '' : ' (pas lié)')}>
        {#if absents[p]}{PLATEFORMES[p].court}
        {:else}<img src={logoReseau(p)} alt="" loading="lazy" decoding="async" onerror={() => (absents[p] = true)} />{/if}
      </span>
    {/each}
  </span>
{/if}

<style>
  .plateformes { display: inline-flex; flex-wrap: wrap; gap: 4px; }
  .pf {
    display: inline-grid; place-items: center; width: 1.25rem; height: 1.25rem; border-radius: 5px; overflow: hidden;
    background: #f4efe7; box-shadow: 0 0 0 1px rgb(0 0 0 / 0.25);
  }
  .pf img { width: 100%; height: 100%; object-fit: contain; }
  .lettres {
    width: auto; min-width: 1.35rem; padding: 0 0.2rem; background: var(--teinte); color: #1c1715;
    font-size: 0.62rem; font-weight: 700; letter-spacing: 0.02em;
  }
  .grand .pf { width: 2rem; height: 2rem; border-radius: 8px; }
  .grand .lettres { width: auto; min-width: 2rem; font-size: 0.8rem; }
  .pf.absente { opacity: 0.35; filter: grayscale(1); box-shadow: inset 0 0 0 1px var(--color-couture); }
  .pf.absente.lettres { background: transparent; color: var(--color-tranche); filter: none; opacity: 1; }
</style>
