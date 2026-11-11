<script>
  // Logo fourni à la main : glissé depuis une autre fenêtre (image ou adresse), fichier glissé,
  // image collée, ou choisie dans les fichiers ou les photos de l'iPhone. Rien n'est écrit ici :
  // le logo devient un candidat que l'on voit avant de le poser.
  import { api } from '../lib/api.js'
  import { erreur } from '../lib/etat.svelte.js'
  let { uid, google = '', compact = false, onpret } = $props()
  let survol = $state(false)
  let attente = $state(false)
  let champ

  async function envoyer(corps) {
    attente = true
    try { onpret?.(await api.post(`/api/contacts/${encodeURIComponent(uid)}/logo-depose`, corps)) }
    catch (err) { erreur(err) } finally { attente = false }
  }
  const texte = (t) => new Blob([t], { type: 'text/plain' })
  // Ce que le navigateur donne quand on glisse une image d'une page : parfois le fichier,
  // souvent seulement son adresse (ou le morceau de page qui la contient)
  function adresseDe(dt) {
    const html = dt.getData('text/html')
    const src = html && /<img[^>]+src=["']([^"']+)["']/i.exec(html)?.[1]
    const brut = src || dt.getData('text/uri-list') || dt.getData('text/plain') || ''
    const ligne = brut.split('\n').map((l) => l.trim()).find((l) => l && !l.startsWith('#')) || ''
    return ligne.replaceAll('&amp;', '&')
  }
  function recevoir(dt) {
    const fichier = [...(dt.files || [])].find((f) => f.type.startsWith('image/'))
    if (fichier) return envoyer(fichier)
    const adresse = adresseDe(dt)
    if (/^(https?:|data:image\/)/i.test(adresse)) return envoyer(texte(adresse))
    erreur(new Error('Ce qui a été déposé n\'est pas une image : glisse l\'image elle-même, ou enregistre-la puis dépose le fichier.'))
  }
  function lacher(e) { e.preventDefault(); e.stopPropagation(); survol = false; recevoir(e.dataTransfer) }
  function coller(e) {
    const dt = e.clipboardData
    if (!dt) return
    e.preventDefault()
    recevoir(dt)
  }
</script>

<div class="depot" class:survol class:compact role="group" aria-label="Déposer un logo" tabindex="0"
     ondragover={(e) => { e.preventDefault(); survol = true }} ondragleave={() => (survol = false)} ondrop={lacher} onpaste={coller}>
  <p class="consigne">{attente ? 'Lecture de l\'image…' : compact ? 'Glisse ou colle un logo ici' : 'Glisse un logo ici depuis une autre fenêtre, ou colle une image.'}</p>
  <div class="actions">
    <button class="bouton" disabled={attente} onclick={() => champ.click()}>Choisir une image</button>
    {#if google}<a class="bouton" href={google} target="_blank" rel="noreferrer">Chercher sur Google Images</a>{/if}
  </div>
  <input bind:this={champ} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden
         onchange={(e) => { const f = e.currentTarget.files[0]; e.currentTarget.value = ''; if (f) envoyer(f) }} />
</div>

<style>
  .depot { display: grid; gap: 0.55rem; padding: 0.85rem; border: 1px dashed var(--color-tranche); border-radius: 10px;
    transition: border-color 0.15s ease, background-color 0.15s ease; }
  .depot:focus-visible { outline: 2px solid var(--color-onglet); outline-offset: 2px; }
  .depot.survol { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 10%, transparent); }
  .depot.compact { padding: 0.6rem; gap: 0.4rem; }
  .consigne { color: var(--color-mine); font-size: 0.9rem; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .compact .bouton { min-height: 2.1rem; padding: 0 0.7rem; font-size: 0.85rem; }
</style>
