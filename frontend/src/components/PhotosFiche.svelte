<script>
  // Photo, affiche et logo d'une fiche
  import { api } from '../lib/api.js'
  import { apresEcriture, dire, erreur } from '../lib/etat.svelte.js'
  let { uid, nom, lieImmich, portraits = null, affiche = null, societe = '', onchange } = $props()

  let candidats = $state(portraits?.candidats ?? null)
  let attente = $state('')
  let logos = $state(null)
  let fichierAffiche = $state(null)
  const e = encodeURIComponent(uid)

  async function chercher(rafraichir = false) {
    attente = 'portraits'
    try { candidats = await api.get(`/api/contacts/${e}/portraits${rafraichir ? '?rafraichir=true' : ''}`) }
    catch (err) { erreur(err) } finally { attente = '' }
  }
  async function poser(asset) {
    attente = asset
    try { await apresEcriture(await api.post(`/api/contacts/${e}/portrait`, { asset }), 'Photo posée dans iCloud.'); onchange?.() }
    catch (err) { erreur(err) } finally { attente = '' }
  }
  async function preparerAffiche(asset) {
    attente = 'affiche'
    try { await api.post(`/api/contacts/${e}/affiche`, asset ? { asset } : {}); dire('Affiche prête dans l\'album Immich.'); onchange?.() }
    catch (err) { erreur(err) } finally { attente = '' }
  }
  // Web Share exige un geste : on prépare d'abord le fichier, puis un second toucher l'enregistre
  async function preparerEnvoi() {
    attente = 'envoi'
    try {
      const r = await fetch(`/api/contacts/${e}/affiche`)
      if (!r.ok) throw new Error((await r.json()).detail)
      fichierAffiche = new File([await r.blob()], `${nom}.jpg`, { type: 'image/jpeg' })
    } catch (err) { erreur(err) } finally { attente = '' }
  }
  async function enregistrer() {
    try {
      if (navigator.canShare?.({ files: [fichierAffiche] })) await navigator.share({ files: [fichierAffiche] })
      else {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(fichierAffiche); a.download = fichierAffiche.name; a.click()
      }
      fichierAffiche = null
    } catch (err) { if (err.name !== 'AbortError') erreur(err) }
  }
  async function posee(valeur) {
    try { await api.post(`/api/contacts/${e}/affiche/posee`, { posee: valeur }); onchange?.() } catch (err) { erreur(err) }
  }
  async function chercherLogos() {
    attente = 'logos'
    try { logos = await api.get(`/api/contacts/${e}/logos`) } catch (err) { erreur(err) } finally { attente = '' }
  }
  async function choisirLogo(n, sorte) {
    attente = 'logo' + n
    try {
      const r = await api.post(`/api/contacts/${e}/logos/${n}`, { sorte })
      if (sorte === 'photo') await apresEcriture(r, 'Logo posé en photo.')
      else dire('Affiche du logo prête dans l\'album Immich.')
      onchange?.()
    } catch (err) { erreur(err) } finally { attente = '' }
  }
</script>

<div class="photos">
  {#if lieImmich}
    <div>
      <div class="ligne-titre">
        <h3>Photo depuis Immich</h3>
        <button class="bouton" disabled={!!attente} onclick={() => chercher(candidats !== null)}>
          {attente === 'portraits' ? 'Recherche…' : candidats === null ? 'Chercher les photos' : 'Chercher à nouveau'}</button>
      </div>
      {#if candidats?.length}
        <div class="grille">
          {#each candidats as cand (cand.asset)}
            <figure class:choisi={portraits?.asset === cand.asset}>
              <img src={`/api/immich/${cand.asset}/apercu`} alt="" loading="lazy" />
              <figcaption class="actions">
                <button class="bouton" disabled={!!attente} onclick={() => poser(cand.asset)}>{attente === cand.asset ? 'Pose…' : 'Photo'}</button>
                <button class="bouton" disabled={!!attente} onclick={() => preparerAffiche(cand.asset)}>Affiche</button>
              </figcaption>
            </figure>
          {/each}
        </div>
      {:else if candidats}
        <p class="discret">Aucun visage assez grand et entier dans les photos de cette personne.</p>
      {/if}
    </div>
  {:else}
    <p class="discret">Lie ce contact à une personne Immich pour choisir sa photo et son affiche.</p>
  {/if}

  {#if affiche}
    <div class="affiche">
      <h3>Affiche</h3>
      <p class="discret">{affiche.posee ? `Posée sur l'iPhone le ${affiche.posee.slice(0, 10)}.` : 'Pas encore posée sur l\'iPhone.'}</p>
      <div class="actions">
        {#if fichierAffiche}
          <button class="bouton bouton-principal" onclick={enregistrer}>Enregistrer dans Photos</button>
        {:else}
          <button class="bouton" disabled={!!attente} onclick={preparerEnvoi}>{attente === 'envoi' ? 'Préparation…' : 'Préparer l\'envoi'}</button>
        {/if}
        <button class="bouton" onclick={() => posee(!affiche.posee)}>{affiche.posee ? 'Pas encore posée' : 'Marquer posée'}</button>
      </div>
    </div>
  {/if}

  {#if societe}
    <div>
      <div class="ligne-titre">
        <h3>Logo de la société</h3>
        <button class="bouton" disabled={!!attente} onclick={chercherLogos}>{attente === 'logos' ? 'Recherche…' : 'Chercher le logo'}</button>
      </div>
      {#if logos?.length}
        <div class="grille">
          {#each logos as l (l.n)}
            <figure>
              <img class="logo" src={`/api/contacts/${e}/logos/${l.n}`} alt="" />
              <figcaption class="actions">
                <button class="bouton" disabled={!!attente} onclick={() => choisirLogo(l.n, 'photo')}>Photo</button>
                <button class="bouton" disabled={!!attente} onclick={() => choisirLogo(l.n, 'affiche')}>Affiche</button>
              </figcaption>
            </figure>
          {/each}
        </div>
      {:else if logos}
        <p class="discret">Aucun logo trouvé sur le site de la société.</p>
      {/if}
    </div>
  {/if}
</div>

<style>
  .photos { display: grid; gap: 1.2rem; }
  h3 { font-weight: 600; }
  .ligne-titre { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; margin-bottom: 0.6rem; }
  .grille { display: grid; grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr)); gap: 0.6rem; }
  figure { display: grid; gap: 0.35rem; }
  figure img { aspect-ratio: 1; width: 100%; object-fit: cover; border-radius: 8px; background: var(--color-reliure); }
  figure.choisi img { outline: 2px solid var(--color-onglet); outline-offset: 2px; }
  img.logo { object-fit: contain; padding: 0.75rem; background: #efe6d8; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  figcaption .bouton { flex: 1; padding: 0.3rem 0.5rem; }
</style>
