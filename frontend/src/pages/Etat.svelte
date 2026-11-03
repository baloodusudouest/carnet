<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat as global, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'

  let e = $state(null)
  let attente = $state('')
  let sauvegarde = $state(null)     // { nom, cartes }
  let choisies = $state([])
  let filtreSauvegarde = $state('')
  let adresseLinkedin = $state('')
  let rattache = $state({})

  const date = (iso) => iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : 'jamais'
  async function charger() { try { e = await api.get('/api/etat') } catch (err) { erreur(err) } }

  async function lancer(nom, chemin, corps, message) {
    attente = nom
    try {
      const r = await api.post(chemin, corps)
      if (message) dire(typeof message === 'function' ? message(r) : message)
      await rafraichirAccueil()
      setTimeout(charger, 1500)
      return r
    } catch (err) { erreur(err) } finally { attente = '' }
  }

  async function ouvrirSauvegarde(nom) {
    try { sauvegarde = { nom, cartes: await api.get(`/api/sauvegardes/${encodeURIComponent(nom)}`) }; choisies = [] }
    catch (err) { erreur(err) }
  }
  async function restaurer() {
    const r = await lancer('restauration', `/api/sauvegardes/${encodeURIComponent(sauvegarde.nom)}/restaurer`, { uids: choisies },
      (r) => `${r.restaurees} fiche(s) remise(s), ${r.recreees} recréée(s)${r.erreurs.length ? `, ${r.erreurs.length} erreur(s)` : ''}.`)
    if (r) { await rafraichirContacts(); ouvrirSauvegarde(sauvegarde.nom) }
  }
  const cartesVisibles = $derived((sauvegarde?.cartes || []).filter((c) =>
    c.etat !== 'identique' && (!filtreSauvegarde || c.nom.toLowerCase().includes(filtreSauvegarde.toLowerCase()))))

  async function linkedinConnecter() {
    const r = await lancer('linkedin', '/api/linkedin/autorisation', {})
    if (r) window.open(r.url, '_blank', 'noopener')
  }
  async function linkedinCode() {
    await lancer('linkedin', '/api/linkedin/code', { adresse: adresseLinkedin },
      (r) => `LinkedIn : ${r.rattachees} relations reconnues, ${r.proposees} changement(s) à traiter.`)
    adresseLinkedin = ''
  }
  async function linkedinRattacher(url, uid) {
    try { await api.post('/api/linkedin/rattacher', { url, uid }); dire(uid ? 'Relation rattachée.' : 'Relation détachée.'); charger() }
    catch (err) { erreur(err) }
  }
  async function deconnecter() { await api.post('/api/deconnexion'); global.connecte = false }

  onMount(charger)
</script>

<section class="page">
  <h1 class="titre">État</h1>
  {#if !e}
    <p class="discret">Chargement…</p>
  {:else}
    <div class="feuille bloc">
      <h2 class="titre">iCloud et la nuit</h2>
      <dl>
        <dt>Dernière lecture</dt><dd>{date(e.lecture?.le)}{e.lecture ? `, ${e.lecture.contacts} fiches` : ''}</dd>
        <dt>Dernière nuit</dt>
        <dd>{date(e.nuit?.le)}{e.nuit ? `, ${e.nuit.ecrites} écriture(s), ${e.nuit.liaisons} liaison(s)` : ''}
          {#if e.nuit?.reportees}, {e.nuit.reportees} reportée(s) à la nuit suivante{/if}</dd>
        <dt>Heure de la nuit</dt><dd>{e.services.nuit || 'désactivée'}</dd>
      </dl>
      {#if e.nuit?.erreur}<p class="alerte" role="alert">{e.nuit.erreur}</p>{/if}
      {#each e.nuit?.details || [] as d}<p class="discret">{d}</p>{/each}
      <div class="boutons">
        <button class="bouton" disabled={!!attente} onclick={() => lancer('relire', '/api/icloud/relire', {}, 'Lecture d\'iCloud lancée.')}>Relire iCloud</button>
        <button class="bouton" disabled={!!attente} onclick={() => lancer('nuit', '/api/nuit', {}, 'Passage de nuit lancé.')}>Lancer la nuit maintenant</button>
        {#if e.nuit?.erreur?.includes('5 %')}
          <button class="bouton bouton-danger" disabled={!!attente} onclick={() => lancer('relire', '/api/icloud/relire', { forcer: true }, 'Lecture acceptée malgré les disparitions.')}>Relire quand même</button>
        {/if}
      </div>
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Sauvegardes d'iCloud</h2>
      <p class="discret">Une copie complète avant la première écriture de chaque jour et chaque nuit. Gardées 30 jours, puis une par mois pendant un an.</p>
      {#if !e.sauvegardes.length}
        <p class="discret">Aucune sauvegarde pour l'instant.</p>
      {:else}
        <select aria-label="Sauvegarde" onchange={(ev) => ev.target.value && ouvrirSauvegarde(ev.target.value)}>
          <option value="">Choisir une sauvegarde à comparer</option>
          {#each e.sauvegardes as s}<option value={s.nom}>{s.nom.replace(/^icloud-|\.vcf$/g, '')} ({Math.round(s.taille / 1024)} Ko)</option>{/each}
        </select>
      {/if}
      {#if sauvegarde}
        {#if !sauvegarde.cartes.some((c) => c.etat !== 'identique')}
          <p class="discret">Toutes les fiches de cette sauvegarde sont identiques à iCloud.</p>
        {:else}
          <input type="search" bind:value={filtreSauvegarde} placeholder="Filtrer par nom" aria-label="Filtrer" />
          <ul class="cartes">
            {#each cartesVisibles as c (c.uid)}
              <li><label><input type="checkbox" value={c.uid} bind:group={choisies} /> {c.nom}
                <span class="discret">{c.etat === 'absente' ? 'supprimée depuis' : 'différente aujourd\'hui'}</span></label></li>
            {/each}
          </ul>
          <button class="bouton bouton-principal" disabled={!choisies.length || !!attente} onclick={restaurer}>
            Remettre {choisies.length || ''} fiche(s) comme dans la sauvegarde</button>
        {/if}
      {/if}
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Copies</h2>
      <dl>
        <dt>Synology Contacts</dt>
        <dd>{e.services.synology ? (e.synology ? `${date(e.synology.le)}${e.synology.erreur ? '' : `, ${e.synology.crees} créée(s), ${e.synology.modifies} mise(s) à jour, ${e.synology.supprimes} retirée(s)`}` : 'pas encore copiée') : 'non configurée'}</dd>
        <dt>Kit d'urgence</dt><dd>{e.kit ? `${date(e.kit.le)}, ${e.kit.nb} contact(s), régénération ${e.kit.regeneration}` : e.services.kit ? 'pas encore envoyé' : 'dossier du kit non monté'}</dd>
      </dl>
      {#if e.synology?.erreur}<p class="alerte">{e.synology.erreur}</p>{/if}
      <div class="boutons">
        {#if e.services.synology}
          <button class="bouton" disabled={!!attente} onclick={() => lancer('syno', '/api/synology', {}, (r) => r.erreur || 'Synology Contacts à jour.')}>Copier maintenant</button>
          {#if e.synology?.erreur}<button class="bouton bouton-danger" disabled={!!attente} onclick={() => lancer('syno', '/api/synology', { forcer: true }, 'Copie forcée.')}>Forcer la copie</button>{/if}
        {/if}
        {#if e.services.kit}<button class="bouton" disabled={!!attente} onclick={() => lancer('kit', '/api/kit', {}, (r) => `${r.nb} contact(s) envoyé(s) au kit.`)}>Envoyer au kit</button>{/if}
      </div>
    </div>

    <div class="feuille bloc">
      <h2 class="titre">LinkedIn</h2>
      <p class="discret">Importe tes relations par l'API de portabilité, ou dépose Connections.csv avec « Importer » dans Contacts. Seuls les changements remontent.</p>
      {#if e.linkedin.api}
        <div class="boutons">
          <button class="bouton" disabled={!!attente} onclick={linkedinConnecter}>Se connecter à LinkedIn</button>
          {#if e.linkedin.en_attente}<button class="bouton" disabled={!!attente} onclick={() => lancer('linkedin', '/api/linkedin/reessayer', {}, (r) => `${r.rattachees} relations reconnues.`)}>Réessayer</button>{/if}
        </div>
        <label class="colle"><span class="discret">Adresse de retour de LinkedIn, collée ici</span>
          <span class="rangee"><input bind:value={adresseLinkedin} placeholder="https://localhost/carnet-linkedin?code=…" />
            <button class="bouton" disabled={!adresseLinkedin || !!attente} onclick={linkedinCode}>Importer</button></span></label>
      {/if}
      {#if e.linkedin.sans_contact.length}
        <h3>Relations sans fiche ({e.linkedin.sans_contact.length})</h3>
        <ul class="relations">
          {#each e.linkedin.sans_contact.slice(0, 50) as r (r.url)}
            <li>
              <span>{r.nom} <span class="discret">{[r.fonction, r.societe].filter(Boolean).join(', ')}</span></span>
              <span class="rangee">
                <select bind:value={rattache[r.url]} aria-label="Fiche à rattacher">
                  <option value="">Rattacher à…</option>
                  {#each (global.contacts || []) as c (c.uid)}<option value={c.uid}>{c.nom}</option>{/each}
                </select>
                <button class="bouton" disabled={!rattache[r.url]} onclick={() => linkedinRattacher(r.url, rattache[r.url])}>Rattacher</button>
                <button class="bouton" onclick={() => linkedinRattacher(r.url, null)}>Détacher</button>
              </span>
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Services</h2>
      <ul class="services">
        {#each [['icloud', 'iCloud'], ['immich', 'Immich'], ['treemich', 'Treemich'], ['synology', 'Synology Contacts'], ['kit', 'Kit d\'urgence'], ['ha', 'Home Assistant']] as [k, nom]}
          <li><span class="voyant" class:ok={e.services[k]}></span>{nom} <span class="discret">{e.services[k] ? 'configuré' : 'non configuré'}</span></li>
        {/each}
      </ul>
      {#if e.reprise}
        <p class="discret">Reprise de la 1.3 le {date(e.reprise.le)} : {e.reprise.liaisons} liaison(s), {e.reprise.portraits} photo(s) choisie(s), {e.reprise.affiches} affiche(s), {e.reprise.linkedin} relation(s) LinkedIn.</p>
        {#if e.reprise.erreur}<p class="alerte">{e.reprise.erreur}</p>{/if}
      {/if}
      <button class="bouton" disabled={!!attente} onclick={() => lancer('liens', '/api/liens/rafraichir', {}, 'Lecture d\'Immich et de Treemich lancée.')}>Relire Immich et Treemich</button>
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Journal</h2>
      <ol class="journal">
        {#each e.journal as j}<li><span class="discret">{date(j.le)}</span> {j.message}</li>{/each}
      </ol>
    </div>

    <p class="pied discret">carnet {e.version} <button class="bouton" onclick={deconnecter}>Se déconnecter</button></p>
  {/if}
</section>

<style>
  .page { max-width: 46rem; display: grid; gap: 1rem; }
  h1 { font-size: 1.9rem; }
  h2 { font-size: 1.2rem; margin-bottom: 0.6rem; }
  h3 { font-weight: 600; margin: 0.9rem 0 0.4rem; }
  .bloc { padding: 1rem; display: grid; gap: 0.6rem; }
  dl { display: grid; grid-template-columns: minmax(8rem, auto) 1fr; gap: 0.3rem 1rem; }
  dt { color: var(--color-mine); }
  .boutons { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .alerte { color: var(--color-alerte); }
  .cartes { max-height: 18rem; overflow-y: auto; display: grid; gap: 0.15rem; }
  .cartes label { display: flex; align-items: center; gap: 0.5rem; min-height: 2.5rem; flex-wrap: wrap; }
  .colle { display: grid; gap: 0.3rem; }
  .rangee { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .rangee input { flex: 1; min-width: 12rem; }
  .rangee select { width: auto; max-width: 12rem; }
  .relations { display: grid; gap: 0.5rem; }
  .relations li { display: grid; gap: 0.3rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--color-couture); }
  .services { display: grid; gap: 0.3rem; }
  .services li { display: flex; align-items: center; gap: 0.5rem; }
  .voyant { width: 0.55rem; height: 0.55rem; border-radius: 50%; background: var(--color-tranche); }
  .voyant.ok { background: var(--color-valide); }
  .journal { display: grid; gap: 0.35rem; max-height: 22rem; overflow-y: auto; font-size: 0.9rem; }
  .pied { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
</style>
