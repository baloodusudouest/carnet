<script>
  // Import unique (2.8) : un seul endroit pour tous les fichiers. carnet dit d'abord ce qu'il a
  // reconnu et ce qu'il va en faire ; rien n'est importé avant « Importer ».
  import { api } from '../lib/api.js'
  import { dire, erreur, rafraichirAccueil } from '../lib/etat.svelte.js'
  import { de, envoyer, resumeImport } from '../lib/suivi.svelte.js'
  let { ouvert = $bindable(false) } = $props()
  let fenetre
  let champ
  let fichier = $state(null)
  let reconnu = $state(null)
  let refus = $state('')
  let attente = $state(false)
  let survol = $state(false)

  $effect(() => {
    if (ouvert && fenetre && !fenetre.open) { fichier = reconnu = null; refus = ''; fenetre.showModal() }
    if (!ouvert && fenetre?.open) fenetre.close()
  })

  async function choisir(f) {
    if (!f) return
    fichier = f; reconnu = null; refus = ''; attente = true
    try {
      const r = await fetch(`/api/import?apercu=true&nom=${encodeURIComponent(f.name)}`, {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/octet-stream' }, body: f })
      const d = await r.json()
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : `Erreur ${r.status}`)
      reconnu = d
    } catch (err) { refus = err.message } finally { attente = false }
  }
  async function importer() {
    attente = true
    try {
      dire(resumeImport(await envoyer('import', fichier, ['facebook', 'instagram'].includes(reconnu.source) ? reconnu.source : '')))
      rafraichirAccueil()
      ouvert = false
    } catch (err) { erreur(err) } finally { attente = false }
  }
  const MODES = [
    ['Cartes de contacts (.vcf)', 'Sur iCloud.com, Contacts : sélectionne des fiches, puis « Exporter une vCard ». Depuis un autre téléphone ou une appli : « Partager le contact » ou « Exporter ».'],
    ['LinkedIn (Connections.csv)', 'LinkedIn, Préférences, Confidentialité des données, « Obtenir une copie de vos données » : coche « Relations ». Le fichier arrive par courriel sous quelques minutes.'],
    ['Facebook', 'Facebook, Paramètres, « Télécharger vos informations » : format JSON, ne coche que « Amis ». Dépose l\'archive .zip telle quelle.'],
    ['Instagram', 'Instagram, Paramètres, Espace Comptes, « Télécharger vos informations » : format JSON, ne coche que « Abonnés et abonnements ».'],
    ['Telegram', 'Pas de fichier : la connexion se fait dans État, section Réseaux.'],
  ]
</script>

<dialog bind:this={fenetre} class="feuille" aria-labelledby="titre-import" onclose={() => (ouvert = false)}
        onclick={(e) => { if (e.target === fenetre) ouvert = false }}>
  <div class="dedans">
    <h2 class="titre" id="titre-import">Importer</h2>
    <div class="zone" class:survol role="group" aria-label="Déposer un fichier"
         ondragover={(e) => { e.preventDefault(); survol = true }} ondragleave={() => (survol = false)}
         ondrop={(e) => { e.preventDefault(); e.stopPropagation(); survol = false; choisir(e.dataTransfer.files[0]) }}>
      <p>{fichier ? fichier.name : 'Dépose un fichier ici, ou choisis-le.'}</p>
      <button class="bouton" disabled={attente} onclick={() => champ.click()}>{fichier ? 'Choisir un autre fichier' : 'Choisir un fichier'}</button>
      <input bind:this={champ} type="file" hidden accept=".vcf,.vcard,.csv,.zip,.json,.html,text/vcard,text/csv,application/zip,application/json"
             onchange={(e) => { const f = e.currentTarget.files[0]; e.currentTarget.value = ''; choisir(f) }} />
    </div>

    {#if attente && !reconnu}<p class="discret" role="status">Lecture du fichier…</p>{/if}
    {#if refus}<p class="refus" role="alert">{refus}</p>{/if}
    {#if reconnu}
      <div class="reconnu" role="status">
        <p><strong>{reconnu.reconnu}</strong> : {reconnu.nombre} {reconnu.source === 'vcf' ? 'fiche(s)' : 'personne(s)'}.</p>
        <p class="discret">{reconnu.suite} Rien n'est écrit dans iCloud par l'import lui-même.</p>
      </div>
    {/if}

    <details>
      <summary>Comment obtenir ce fichier</summary>
      <dl>{#each MODES as [nom, comment]}<dt>{nom}</dt><dd class="discret">{comment}</dd>{/each}</dl>
    </details>

    <div class="boutons">
      <button class="bouton" onclick={() => (ouvert = false)}>Fermer</button>
      <button class="bouton bouton-principal" disabled={!reconnu || attente || de('import').etat === 'en_cours'} onclick={importer}>
        {de('import').etat === 'en_cours' ? 'Import…' : 'Importer'}</button>
    </div>
  </div>
</dialog>

<style>
  dialog { width: min(34rem, calc(100vw - 2rem)); max-height: calc(100dvh - 2rem); padding: 0; color: var(--color-papier);
    border: 1px solid var(--color-couture); border-radius: 14px; background: var(--color-reliure); }
  dialog::backdrop { background: rgb(0 0 0 / 0.55); }
  .dedans { display: grid; gap: 0.9rem; padding: 1.25rem; }
  h2 { font-size: 1.3rem; }
  .zone { display: grid; gap: 0.6rem; justify-items: start; padding: 1rem; border: 1px dashed var(--color-tranche); border-radius: 10px; }
  .zone.survol { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 10%, transparent); }
  .reconnu { display: grid; gap: 0.3rem; padding: 0.75rem 0.9rem; border-left: 3px solid var(--color-onglet); }
  .refus { color: var(--color-alerte); }
  summary { cursor: pointer; color: var(--color-mine); min-height: 2.2rem; display: flex; align-items: center; }
  dl { display: grid; gap: 0.25rem; margin-top: 0.4rem; }
  dt { font-weight: 600; margin-top: 0.45rem; }
  .boutons { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
