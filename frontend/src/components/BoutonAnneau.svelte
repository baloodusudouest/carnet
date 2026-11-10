<script>
  // Bouton à anneau : l'anneau est le bord du bouton lui-même.
  //  repos    : icône de l'action dans l'anneau éteint
  //  en_cours : l'anneau se remplit d'or (progression 0…1) ou tourne s'il n'y a pas de mesure
  //  succes   : anneau vert plein, une coche se trace
  //  echec    : tout le disque passe au rouge, une croix remplace l'icône
  import { ICONES } from '../lib/icones.js'

  let {
    etat = 'repos', progression = null, icone = 'telecharger', libelle, enCours = null,
    detail = '', principal = false, compact = false, disabled = false, onclick, fichier = null, onfichier,
  } = $props()

  const R = 17
  const TOUR = 2 * Math.PI * R
  const mesure = $derived(etat === 'en_cours' && typeof progression === 'number')
  const remplissage = $derived(etat === 'succes' ? 1 : mesure ? Math.max(0.03, Math.min(1, progression)) : 0)
  const pourcent = $derived(mesure ? Math.round(progression * 100) : null)
  const texte = $derived(etat === 'en_cours' ? (enCours || libelle) : libelle)
  const annonce = $derived(etat === 'en_cours' ? `${texte}${pourcent !== null ? ` ${pourcent} %` : ''}`
    : etat === 'succes' ? `${libelle} : terminé` : etat === 'echec' ? `${libelle} : échec` : '')
</script>

{#snippet contenu()}
  <span class="anneau" aria-hidden="true">
    <svg viewBox="-20 -20 40 40">
      <circle class="champ" r="15.4" />
      <circle class="rail" r={R} />
      {#if etat === 'en_cours' && !mesure}
        <circle class="arc tourne" r={R} stroke-dasharray="{TOUR * 0.28} {TOUR}" />
      {:else}
        <circle class="arc" r={R} stroke-dasharray={TOUR} stroke-dashoffset={TOUR * (1 - remplissage)} />
      {/if}
      <g class="dessin" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
        {#if etat === 'succes'}
          <path class="coche" d="M-6.2 0.4 -1.9 4.6 6.4 -4.2" pathLength="1" />
        {:else if etat === 'echec'}
          <path d="M-5 -5 5 5M5 -5 -5 5" />
        {:else if etat === 'en_cours'}
          {#if pourcent !== null}<text class="pct" y="3.6" text-anchor="middle">{pourcent}</text>
          {:else}<path class="trait" d="M-5.5 0h11" />{/if}
        {:else}
          <g transform="translate(-12 -12)" stroke-width="1.9">{@html ICONES[icone]}</g>
        {/if}
      </g>
    </svg>
  </span>
  <span class="texte">
    <span class="nom">{texte}</span>
    {#if detail}<span class="detail">{detail}</span>{/if}
  </span>
{/snippet}

{#if fichier}
  <!-- Variante « choisir un fichier » : le libellé ouvre le sélecteur -->
  <label class="bouton-anneau" class:principal class:compact data-etat={etat} aria-disabled={disabled || etat === 'en_cours'}>
    {@render contenu()}
    <input type="file" accept={fichier} hidden disabled={disabled || etat === 'en_cours'}
           onchange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onfichier?.(f) }} />
  </label>
{:else}
  <button type="button" class="bouton-anneau" class:principal class:compact data-etat={etat}
          disabled={disabled || etat === 'en_cours'} aria-busy={etat === 'en_cours'} {onclick}>
    {@render contenu()}
  </button>
{/if}
<span class="sr" role="status" aria-live="polite">{annonce}</span>

<style>
  .bouton-anneau {
    --encre: var(--color-papier); --or: var(--color-onglet);
    display: inline-flex; align-items: center; gap: 0.7rem; min-height: 3rem; padding: 0.3rem 1.1rem 0.3rem 0.35rem;
    border-radius: 9999px; border: 1px solid var(--color-tranche); color: var(--encre); font-weight: 500;
    text-align: left; cursor: pointer; transition: border-color 0.2s ease;
  }
  .bouton-anneau:hover:not(:disabled):not([aria-disabled='true']) { border-color: var(--color-mine); }
  .bouton-anneau:focus-visible, .bouton-anneau:focus-within { outline: 2px solid var(--or); outline-offset: 2px; }
  .bouton-anneau:disabled, .bouton-anneau[aria-disabled='true'] { cursor: default; }
  .bouton-anneau:disabled[data-etat='repos'] { opacity: 0.45; }
  .compact { min-height: 2.5rem; gap: 0.5rem; padding: 0.2rem 0.85rem 0.2rem 0.25rem; font-size: 0.92rem; }
  .compact .anneau { width: 2rem; height: 2rem; }
  .compact .detail { display: none; }
  .principal { border-color: color-mix(in srgb, var(--or) 55%, transparent); }

  .anneau { flex: none; width: 2.5rem; height: 2.5rem; display: grid; }
  svg { width: 100%; height: 100%; overflow: visible; }
  .champ { fill: color-mix(in srgb, var(--color-papier) 4%, transparent); transition: fill 0.32s ease; }
  .rail { fill: none; stroke: var(--color-couture); stroke-width: 2.6; }
  .arc {
    fill: none; stroke: var(--or); stroke-width: 2.6; stroke-linecap: round;
    transform: rotate(-90deg); transition: stroke-dashoffset 0.45s ease, stroke 0.3s ease;
  }
  .principal .arc { stroke: var(--or); }
  .arc { transform-origin: 0 0; }
  .tourne { animation: tourne 1.1s linear infinite; }
  @keyframes tourne { from { transform: rotate(-90deg); } to { transform: rotate(270deg); } }
  .dessin { color: var(--encre); }
  .pct { fill: currentColor; stroke: none; font: 600 9.5px var(--font-ui, inherit); font-variant-numeric: tabular-nums; }
  .trait { animation: respire 1.2s ease-in-out infinite; }
  @keyframes respire { 50% { opacity: 0.35; } }

  [data-etat='succes'] { border-color: color-mix(in srgb, var(--color-valide) 60%, transparent); }
  [data-etat='succes'] .arc { stroke: var(--color-valide); }
  [data-etat='succes'] .dessin { color: var(--color-valide); }
  .coche { stroke-dasharray: 1; stroke-dashoffset: 1; animation: trace 0.42s 0.12s ease-out forwards; }
  @keyframes trace { to { stroke-dashoffset: 0; } }

  [data-etat='echec'] { border-color: color-mix(in srgb, var(--color-alerte) 70%, transparent); }
  [data-etat='echec'] .champ { fill: var(--color-alerte); }
  [data-etat='echec'] .rail, [data-etat='echec'] .arc { stroke: var(--color-alerte); }
  [data-etat='echec'] .dessin { color: #2a1514; }

  .texte { display: grid; line-height: 1.25; }
  .detail { font-size: 0.8rem; color: var(--color-mine); }
  [data-etat='echec'] .detail { color: var(--color-alerte); }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

  @media (prefers-reduced-motion: reduce) {
    .tourne, .trait { animation: none; }
    .coche { animation: none; stroke-dashoffset: 0; }
    .arc, .champ { transition: none; }
  }
</style>
