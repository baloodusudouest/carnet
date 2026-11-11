<script>
  import { onMount } from 'svelte'
  import { api } from './lib/api.js'
  import { etat, aller, annuler, rafraichirAccueil, rafraichirContacts } from './lib/etat.svelte.js'
  import Connexion from './pages/Connexion.svelte'
  import ATraiter from './pages/ATraiter.svelte'
  import Contacts from './pages/Contacts.svelte'
  import Fiche from './pages/Fiche.svelte'
  import Fusion from './pages/Fusion.svelte'
  import Etat from './pages/Etat.svelte'
  import Photos from './pages/Photos.svelte'
  import Reglages from './pages/Reglages.svelte'
  import { ICONES } from './lib/icones.js'
  import Voyant from './components/Voyant.svelte'

  const onglets = [
    { page: 'a-traiter', nom: 'À traiter' },
    { page: 'contacts', nom: 'Contacts' },
    { page: 'photos', nom: 'Photos' },
    { page: 'etat', nom: 'État' },
    { page: 'reglages', nom: 'Réglages' },
  ]
  const actif = $derived(etat.route.page === 'fusion' ? 'a-traiter' : etat.route.page)
  const compte = $derived(etat.accueil?.a_traiter?.total ?? 0)
  const enCours = $derived(etat.accueil?.tache?.etat === 'en_cours')
  const alerte = $derived(etat.accueil?.nuit?.erreur || etat.accueil?.tache?.etat === 'erreur')

  async function demarrer() {
    const s = await api.get('/api/session')
    etat.connecte = s.connecte
    if (s.connecte) { await rafraichirAccueil(); rafraichirContacts() }
  }

  onMount(() => {
    demarrer()
    let id
    const boucle = async () => {
      if (etat.connecte) await rafraichirAccueil()
      id = setTimeout(boucle, etat.accueil?.tache?.etat === 'en_cours' ? 3000 : 60000)
    }
    id = setTimeout(boucle, 3000)
    return () => clearTimeout(id)
  })
</script>

<!-- Un fichier lâché hors d'une zone de dépôt ne doit pas ouvrir le fichier à la place de carnet -->
<svelte:window ondragover={(e) => e.preventDefault()} ondrop={(e) => e.preventDefault()} />

{#if etat.connecte === false}
  <Connexion onconnecte={demarrer} />
{:else if etat.connecte}
  <!-- iPhone : bande opaque sous l'heure et la batterie, rien ne défile dessous -->
  <div class="haut-securise" aria-hidden="true"></div>
  <div class="cadre">
    <nav class="onglets" aria-label="Sections">
      <span class="marque titre">carnet</span>
      {#each onglets as o}
        <!-- iPhone : icônes seules, l'onglet actif s'élargit avec son libellé. PC : rail, même pastille. -->
        <a href={'#/' + o.page} class="onglet" aria-current={actif === o.page ? 'page' : undefined} aria-label={o.nom}>
          <span class="icone-onglet">
            <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round">{@html ICONES[o.page]}</svg>
            {#if o.page === 'a-traiter' && compte}<span class="badge">{compte > 99 ? '99+' : compte}</span>{/if}
            {#if o.page === 'etat' && enCours}<span class="roue"><Voyant etat="en_cours" taille="0.85rem" titre="Opération en cours" /></span>
            {:else if o.page === 'etat' && alerte}<span class="point" aria-label="Problème à voir"></span>{/if}
          </span>
          <span class="libelle">{o.nom}</span>
        </a>
      {/each}
    </nav>

    <main class="contenu">
      {#if etat.accueil?.lecture_seule}
        <p class="lecture-seule" role="status"><strong>Mode lecture seule.</strong> carnet lit et calcule, mais n'écrit ni dans iCloud, ni dans Immich, Treemich, Synology ou le kit.</p>
      {/if}
      {#if etat.accueil?.tache?.etat === 'en_cours'}
        <p class="tache" role="status">{etat.accueil.tache.message}</p>
      {/if}
      {#if etat.route.page === 'contacts' && etat.large}
        <Contacts selection={etat.route.args[0] || null} />
      {:else if etat.route.page === 'contacts' && etat.route.args[0]}
        {#key etat.route.args[0]}<Fiche uid={etat.route.args[0]} />{/key}
      {:else if etat.route.page === 'contacts'}
        <Contacts />
      {:else if etat.route.page === 'fusion'}
        <Fusion a={etat.route.args[0]} b={etat.route.args[1]} />
      {:else if etat.route.page === 'photos'}
        <Photos />
      {:else if etat.route.page === 'reglages'}
        <Reglages />
      {:else if etat.route.page === 'etat'}
        <Etat />
      {:else}
        <ATraiter />
      {/if}
    </main>
  </div>

  {#if etat.message}
    <div class="message" class:erreur={etat.message.erreur} role={etat.message.erreur ? 'alert' : 'status'}>
      <span>{etat.message.texte}</span>
      {#if etat.message.jeton}
        <button class="bouton" onclick={() => { const j = etat.message.jeton; etat.message = null; annuler(j) }}>Annuler</button>
      {/if}
    </div>
  {/if}
{/if}

<style>
  .cadre { min-height: 100dvh; }
  .contenu {
    padding: calc(0.75rem + env(safe-area-inset-top)) max(1rem, env(safe-area-inset-right)) calc(5.5rem + env(safe-area-inset-bottom))
             max(1rem, env(safe-area-inset-left));
    max-width: 72rem; margin: 0 auto;
  }
  .haut-securise { position: fixed; z-index: 25; top: 0; left: 0; right: 0; height: env(safe-area-inset-top); background: var(--color-cuir); }
  /* iPhone : pilule sombre flottante (reliure), l'onglet actif en pastille papier avec son libellé */
  .onglets {
    position: fixed; z-index: 20; left: 50%; transform: translateX(-50%);
    bottom: calc(0.6rem + env(safe-area-inset-bottom)); display: flex; align-items: center; gap: 0.25rem;
    padding: 0.35rem; border-radius: 9999px;
    background: color-mix(in srgb, var(--color-cuir) 82%, transparent); border: 1px solid var(--color-couture);
    box-shadow: 0 10px 30px var(--color-ombre);
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  }
  .marque { display: none; }
  .onglet {
    display: flex; align-items: center; gap: 0.5rem; height: 3rem; padding: 0 1.05rem; border-radius: 9999px;
    color: var(--color-mine); font-weight: 600; font-size: 0.95rem; white-space: nowrap;
    transition: background-color 0.28s ease, color 0.28s ease, padding 0.28s ease;
  }
  .onglet:focus-visible { outline: 2px solid var(--color-onglet); outline-offset: 2px; }
  .libelle { max-width: 0; overflow: hidden; opacity: 0; transition: max-width 0.32s ease, opacity 0.2s ease; }
  .onglet[aria-current='page'] { background: var(--color-papier); color: var(--color-cuir); padding: 0 1.15rem 0 0.95rem; }
  .onglet[aria-current='page'] .libelle { max-width: 7rem; opacity: 1; }
  .icone-onglet { position: relative; display: grid; place-items: center; }
  .icone-onglet svg { width: 1.45rem; height: 1.45rem; }
  .badge {
    position: absolute; top: -0.45rem; left: 0.85rem; min-width: 1.15rem; height: 1.15rem; padding: 0 0.3rem;
    border-radius: 9999px; font-size: 0.68rem; font-weight: 700; line-height: 1.15rem; text-align: center;
    background: var(--color-onglet); color: var(--color-sur-onglet); box-shadow: 0 0 0 2px var(--color-cuir);
  }
  .onglet[aria-current='page'] .badge { box-shadow: 0 0 0 2px var(--color-papier); }
  .point { position: absolute; top: -0.15rem; right: -0.2rem; width: 0.55rem; height: 0.55rem; border-radius: 50%;
    background: var(--color-alerte); box-shadow: 0 0 0 2px var(--color-cuir); }
  .roue { position: absolute; top: -0.4rem; right: -0.45rem; display: grid; border-radius: 50%; background: var(--color-cuir); padding: 1px; }
  .onglet[aria-current='page'] .roue { background: var(--color-papier); }
  /* Cinq onglets : sur un iPhone étroit, les icônes se resserrent pour que la pilule tienne */
  @media (max-width: 26rem) {
    .onglets { gap: 0.1rem; }
    .onglet { padding: 0 0.72rem; }
    .onglet[aria-current='page'] { padding: 0 0.9rem 0 0.75rem; }
  }
  @media (prefers-reduced-motion: reduce) { .onglet, .libelle { transition: none; } }
  .lecture-seule { margin-bottom: 0.75rem; padding: 0.5rem 0.8rem; border: 1px solid var(--color-onglet); border-radius: 8px; color: var(--color-papier); }
  .tache { margin-bottom: 0.75rem; padding: 0.5rem 0.8rem; border-left: 3px solid var(--color-onglet); color: var(--color-mine); }
  .message {
    position: fixed; z-index: 30; left: 1rem; right: 1rem; bottom: calc(4.9rem + env(safe-area-inset-bottom));
    display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    max-width: 34rem; margin: 0 auto; padding: 0.6rem 0.6rem 0.6rem 1rem; border-radius: 10px;
    background: var(--color-reliure); border: 1px solid var(--color-tranche); box-shadow: 0 8px 24px var(--color-ombre);
  }
  .message.erreur { border-color: var(--color-alerte); }
  @media (min-width: 900px) {
    /* PC : rail latéral conservé ; l'onglet actif prend la même pastille papier */
    .onglets {
      top: 0; bottom: 0; left: 0; transform: none; width: 13rem; flex-direction: column; align-items: stretch; gap: 0.25rem;
      padding: 1.25rem 0.75rem; border-radius: 0; border: 0; border-right: 1px solid var(--color-couture);
      background: var(--color-cuir); box-shadow: none; backdrop-filter: none; -webkit-backdrop-filter: none;
    }
    .marque { display: block; font-size: 1.5rem; font-weight: 300; letter-spacing: -0.03em; padding: 0 0.85rem 1.25rem; color: var(--color-papier); }
    .onglet { height: 2.75rem; padding: 0 0.85rem; gap: 0.7rem; font-size: 0.95rem; }
    .onglet[aria-current='page'] { padding: 0 0.85rem; background: var(--color-reliure); color: var(--color-papier); }
    .onglet[aria-current='page'] .roue { background: none; }
    .libelle, .onglet .libelle { max-width: none; opacity: 1; overflow: visible; }
    .onglet { position: relative; }
    .icone-onglet { position: static; }
    .badge { left: auto; right: 0.75rem; top: 50%; transform: translateY(-50%); box-shadow: none; min-width: 1.4rem; }
    .point { top: 50%; right: 0.9rem; transform: translateY(-50%); box-shadow: none; }
    .roue { top: 50%; right: 0.8rem; transform: translateY(-50%); background: none; }
    .onglet:hover:not([aria-current='page']) { color: var(--color-papier); background: color-mix(in srgb, var(--color-papier) 5%, transparent); }
    .contenu { margin-left: 13rem; padding: 1.75rem 2.5rem 3rem; max-width: none; }
    .message { bottom: 1.5rem; left: 14rem; }
  }
</style>
