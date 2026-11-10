<script>
  // Voyant d'état : roue qui tourne (en cours), coche verte (OK), croix rouge (erreur),
  // trait gris (non configuré). Même dessin que l'anneau des boutons, en petit.
  let { etat = 'ok', taille = '1.15rem', titre = '' } = $props()
  const NOMS = { en_cours: 'En cours', ok: 'OK', erreur: 'En erreur', off: 'Non configuré' }
</script>

<span class="voyant" data-etat={etat} style:--taille={taille} role="img" aria-label={titre || NOMS[etat]} title={titre || NOMS[etat]}>
  <svg viewBox="-12 -12 24 24" aria-hidden="true">
    {#if etat === 'en_cours'}
      <circle class="rail" r="9.5" />
      <circle class="arc" r="9.5" stroke-dasharray="17 60" />
    {:else if etat === 'ok'}
      <circle class="disque" r="10.5" />
      <path d="M-4.6 0.3-1.4 3.4 4.8-3.2" />
    {:else if etat === 'erreur'}
      <circle class="disque" r="10.5" />
      <path d="M-3.8-3.8 3.8 3.8M3.8-3.8-3.8 3.8" />
    {:else}
      <circle class="rail" r="9.5" />
      <path d="M-3.8 0h7.6" />
    {/if}
  </svg>
</span>

<style>
  .voyant { display: inline-grid; flex: none; width: var(--taille); height: var(--taille); vertical-align: -0.2em; }
  svg { width: 100%; height: 100%; overflow: visible; fill: none; stroke-linecap: round; stroke-linejoin: round; }
  path { stroke-width: 2.4; }
  .rail { stroke: var(--color-couture); stroke-width: 2.4; }
  .arc { stroke: var(--color-onglet); stroke-width: 2.4; transform-origin: 0 0; animation: tourne 0.9s linear infinite; }
  @keyframes tourne { to { transform: rotate(360deg); } }
  [data-etat='ok'] .disque { fill: color-mix(in srgb, var(--color-valide) 22%, transparent); }
  [data-etat='ok'] path { stroke: var(--color-valide); }
  [data-etat='erreur'] .disque { fill: var(--color-alerte); }
  [data-etat='erreur'] path { stroke: #2a1514; }
  [data-etat='off'] path { stroke: var(--color-tranche); }
  @media (prefers-reduced-motion: reduce) { .arc { animation: none; } }
</style>
