<script>
  // 2.10 : fenêtre ouverte en touchant la photo d'une fiche en modification.
  // Cinq propositions pour la photo du contact, cinq pour son affiche. Contact relié à Immich :
  // ses visages. Sinon : le logo de sa société, et cinq couleurs de page tirées de ce logo.
  import { api } from '../lib/api.js'
  import { apresEcriture, dire, erreur } from '../lib/etat.svelte.js'
  import DepotLogo from './DepotLogo.svelte'
  let { ouvert = $bindable(false), uid, nom, onchange } = $props()

  let fenetre
  let p = $state(null)          // { mode, photos, affiches, … }
  let attente = $state('')
  let version = $state(0)        // change quand les propositions changent : les aperçus sont rechargés
  const e = $derived(encodeURIComponent(uid))

  async function charger(rafraichir = false) {
    attente = 'chargement'
    try { p = await api.get(`/api/contacts/${e}/propositions${rafraichir ? '?rafraichir=true' : ''}`); version += 1 }
    catch (err) { erreur(err) } finally { attente = '' }
  }
  $effect(() => {
    if (ouvert && fenetre && !fenetre.open) { p = null; fenetre.showModal(); charger() }
    if (!ouvert && fenetre?.open) fenetre.close()
  })
  const image = (sorte, cle) => `/api/contacts/${e}/propositions/${sorte}/${encodeURIComponent(cle)}?v=${version}`

  async function choisirPhoto(x) {
    attente = 'photo' + x.cle
    try {
      const r = p.mode === 'immich' ? await api.post(`/api/contacts/${e}/portrait`, { asset: x.cle })
        : await api.post(`/api/contacts/${e}/logos/${x.cle}`, { sorte: 'photo' })
      await apresEcriture(r, p.mode === 'immich' ? 'Photo posée dans iCloud.' : 'Logo posé en photo dans iCloud.')
      onchange?.(); ouvert = false
    } catch (err) { erreur(err) } finally { attente = '' }
  }
  async function choisirAffiche(x) {
    attente = 'affiche' + x.cle
    try {
      await api.post(`/api/contacts/${e}/affiche`, p.mode === 'immich' ? { asset: x.cle } : { couleur: x.cle })
      dire('Affiche prête dans l\'album Immich « Affiches de contacts ».')
      onchange?.(); ouvert = false
    } catch (err) { erreur(err) } finally { attente = '' }
  }
</script>

<dialog bind:this={fenetre} class="feuille" aria-labelledby="titre-choix-photo" onclose={() => (ouvert = false)}
        onclick={(ev) => { if (ev.target === fenetre) ouvert = false }}>
  {#if ouvert}
  <div class="dedans">
    <h2 class="titre" id="titre-choix-photo">Photo et affiche</h2>
    <p class="discret">{nom}</p>
    {#if !p}
      <p class="discret">Recherche des propositions…</p>
    {:else if p.mode === 'rien'}
      <p>{p.raison}</p>
    {:else}
      <h3>Photo du contact</h3>
      {#if p.photos.length}
        <ul class="propositions photos" aria-label="Propositions de photo">
          {#each p.photos as x (x.cle)}
            <li>
              <button class="proposition" disabled={!!attente} onclick={() => choisirPhoto(x)}
                      aria-label={p.mode === 'immich' ? `Poser la photo ${x.le || ''}` : `Poser le logo ${x.origine}`}>
                <img src={image('photo', x.cle)} alt="" loading="lazy" />
                <span class="legende">{attente === 'photo' + x.cle ? 'Pose…' : p.mode === 'immich' ? (x.le || 'sans date') : x.origine}</span>
              </button>
            </li>
          {/each}
        </ul>
        <p class="discret petit">Toucher une proposition la pose tout de suite dans iCloud ; « Annuler » reste possible 10 secondes.</p>
      {:else if p.mode === 'immich'}
        <p class="discret">Aucun visage assez grand dans Immich pour ce contact.</p>
      {:else}
        <p class="discret">Pas encore de logo pour {p.societe}. Dépose-en un ci-dessous{p.domaine ? ', ou cherche-le sur son site' : ''}.</p>
      {/if}

      <h3>Affiche</h3>
      {#if p.affiches.length}
        <ul class="propositions affiches" aria-label="Propositions d'affiche">
          {#each p.affiches as x (x.cle)}
            <li>
              <button class="proposition" disabled={!!attente} onclick={() => choisirAffiche(x)}
                      aria-label={p.mode === 'immich' ? `Préparer l'affiche ${x.le || ''}` : `Préparer l'affiche, couleur ${Number(x.cle) + 1}`}>
                <img src={image('affiche', x.cle)} alt="" loading="lazy" />
                <span class="legende">{attente === 'affiche' + x.cle ? 'Préparation…' : p.mode === 'immich' ? (x.le || 'sans date') : x.cle === '0' ? 'couleur de la société' : `couleur ${Number(x.cle) + 1}`}</span>
              </button>
            </li>
          {/each}
        </ul>
        <p class="discret petit">L'affiche est rangée dans l'album Immich « Affiches de contacts » ; rien n'est écrit dans iCloud.</p>
      {:else if p.mode === 'immich'}
        <p class="discret">Aucune photo ne laisse assez de place autour du visage pour une affiche.</p>
      {:else}
        <p class="discret">L'affiche se fait à partir du logo : il en faut un d'abord.</p>
      {/if}

      <div class="outils">
        {#if p.mode === 'immich'}
          <button class="bouton" disabled={!!attente} onclick={() => charger(true)}>{attente === 'chargement' ? 'Recherche…' : 'Chercher d\'autres photos dans Immich'}</button>
        {:else}
          <DepotLogo {uid} google={p.google} compact onpret={() => charger()} />
          {#if p.domaine}<button class="bouton" disabled={!!attente} onclick={() => charger(true)}>{attente === 'chargement' ? 'Recherche…' : 'Chercher le logo sur le site'}</button>{/if}
        {/if}
      </div>
    {/if}
    <div class="pied"><button class="bouton" onclick={() => (ouvert = false)}>Fermer</button></div>
  </div>
  {/if}
</dialog>

<style>
  dialog { width: min(44rem, calc(100vw - 1.5rem)); max-height: calc(100dvh - 1.5rem); margin: auto; padding: 0; overflow-y: auto; color: var(--color-papier);
           background: var(--color-reliure); border: 1px solid var(--color-couture); border-radius: 14px; }
  dialog::backdrop { background: rgb(0 0 0 / 0.55); }
  .dedans { display: grid; gap: 0.7rem; padding: 1.2rem; }
  h3 { font-size: 0.95rem; font-weight: 600; margin-top: 0.3rem; }
  .propositions { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0.5rem; list-style: none; padding: 0; margin: 0; }
  .proposition { display: grid; gap: 0.25rem; width: 100%; padding: 0.25rem; border-radius: 10px; border: 1px solid var(--color-couture);
                 background: transparent; color: inherit; cursor: pointer; text-align: center; }
  .proposition:hover:not(:disabled), .proposition:focus-visible { border-color: var(--color-onglet); }
  .proposition:disabled { opacity: 0.5; cursor: wait; }
  .proposition img { width: 100%; border-radius: 7px; display: block; background: var(--color-cuir-2, rgb(127 127 127 / 0.15)); }
  .photos img { aspect-ratio: 1; object-fit: cover; }
  .affiches img { aspect-ratio: 354 / 768; object-fit: cover; }
  .legende { font-size: 0.72rem; color: var(--color-mine); overflow-wrap: anywhere; line-height: 1.2; }
  .petit { font-size: 0.8rem; }
  .outils { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; }
  .pied { display: flex; justify-content: flex-end; }
  @media (max-width: 520px) {
    .propositions { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .dedans { padding: 0.9rem; }
  }
</style>
