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
  let section = $state(null)

  const court = (iso) => iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'jamais'
  // Une tuile par section : icône, résumé d'une ligne, pastille rouge en cas de problème
  const SECTIONS = [
    { cle: 'icloud', nom: 'iCloud et la nuit', icone: '<path d="M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.1 9.5 4.3 4.3 0 0 0 7 18z"/>',
      resume: (e) => `Nuit : ${court(e.nuit?.le)}`, alerte: (e) => !!e.nuit?.erreur },
    { cle: 'sauvegardes', nom: 'Sauvegardes', icone: '<path d="M4 7h16v12H4z"/><path d="M4 7l2-3h12l2 3"/><path d="M10 12h4"/>',
      resume: (e) => `${e.sauvegardes.length} copie(s)`, alerte: () => false },
    { cle: 'copies', nom: 'Copies', icone: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
      resume: (e) => `Synology : ${e.synology ? court(e.synology.le) : 'jamais'}`, alerte: (e) => !!e.synology?.erreur },
    { cle: 'linkedin', nom: 'LinkedIn', icone: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 11v5M8 8v.01M12 16v-5M12 13a2 2 0 0 1 4 0v3"/>',
      resume: (e) => `${e.linkedin.sans_contact.length} sans fiche`, alerte: () => false },
    { cle: 'reseaux', nom: 'Réseaux', icone: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 10.9l7.6-3.8M8.2 13.1l7.6 3.8"/>',
      resume: (e) => `${Object.values(e.reseaux).reduce((n, r) => n + r.liees, 0)} fiche(s) liée(s)`, alerte: () => false },
    { cle: 'completude', nom: 'Complétude', icone: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 8 8h-8z"/>',
      resume: (e) => `${e.statut.completude?.validees ?? 0} validée(s), ${e.statut.completude?.a_revoir ?? 0} à revoir`,
      alerte: (e) => !!e.statut.completude?.a_revoir },
    { cle: 'services', nom: 'Services', icone: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
      resume: (e) => `${Object.entries(e.services).filter(([k, v]) => k !== 'nuit' && v).length} sur 6 configurés`,
      alerte: (e) => !!e.reprise?.erreur },
    { cle: 'journal', nom: 'Journal', icone: '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
      resume: (e) => `${e.journal.length} lignes`, alerte: () => false },
  ]

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
  // Telegram : numéro → code reçu dans Telegram → mot de passe si la double vérification est active.
  // La session n'existe qu'en mémoire le temps de l'import, puis carnet se déconnecte.
  let tg = $state({ telephone: '', code: '', mdp: '', etape: 'telephone' })
  async function telegramCode() {
    const r = await lancer('telegram', '/api/telegram/code', { telephone: tg.telephone }, 'Code envoyé dans Telegram.')
    if (r) tg.etape = 'code'
  }
  async function telegramImport() {
    const r = await lancer('telegram', '/api/telegram/import', { code: tg.code, mot_de_passe: tg.mdp })
    if (!r) return
    if (r.mot_de_passe) { tg.etape = 'mdp'; dire('Telegram demande ton mot de passe de double vérification.'); return }
    dire(`Telegram : ${r.lues} contact(s) lu(s), ${r.proposees} rattachement(s) proposé(s) dans « À traiter ».`)
    tg = { telephone: '', code: '', mdp: '', etape: 'telephone' }
  }
  async function telegramAbandon() {
    await lancer('telegram', '/api/telegram/abandon', {}, 'Connexion à Telegram abandonnée.')
    tg = { telephone: '', code: '', mdp: '', etape: 'telephone' }
  }
  async function importerInstagram(ev) {
    const fichier = ev.target.files?.[0]
    if (!fichier) return
    const fd = new FormData()
    fd.append('fichier', fichier)
    await lancer('instagram', '/api/import', fd, (r) => `Instagram : ${r.lues} compte(s) lu(s), ${r.proposees} rattachement(s) proposé(s). L'archive n'est pas gardée.`)
    ev.target.value = ''
  }
  // Analyse globale ; la remise à zéro des validations se confirme deux fois (bouton, puis mot à taper)
  let zero = $state({ ouvert: false, mot: '' })
  async function analyser(remettre) {
    await lancer('analyse', '/api/analyse', remettre ? { remettre_a_zero: true, confirmation: zero.mot } : {},
      remettre ? 'Validations remises à zéro, analyse globale lancée.' : 'Analyse globale lancée.')
    zero = { ouvert: false, mot: '' }
    setTimeout(async () => { await rafraichirContacts(); charger() }, 4000)
  }
  const NOMS_RESEAUX = { telegram: 'Telegram', instagram: 'Instagram', facebook: 'Facebook', whatsapp: 'WhatsApp' }

  async function deconnecter() { await api.post('/api/deconnexion'); global.connecte = false }

  onMount(charger)
</script>

<section class="page">
  <h1 class="titre">État</h1>
  {#if !e}
    <p class="discret">Chargement…</p>
  {:else}
    <nav class="tuiles" aria-label="Sections">
      {#each SECTIONS as s}
        <button class="tuile" aria-pressed={section === s.cle} onclick={() => (section = section === s.cle ? null : s.cle)}>
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html s.icone}</svg>
          <span class="nom-tuile">{s.nom}</span>
          <span class="resume">{s.resume(e)}</span>
          {#if s.alerte(e)}<span class="alerte-point" aria-label="Problème à voir"></span>{/if}
        </button>
      {/each}
    </nav>
    {#if !section}<p class="discret">Choisis une section pour l'afficher.</p>{/if}
    {#if section === 'icloud'}
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
    {/if}

    {#if section === 'sauvegardes'}
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
    {/if}

    {#if section === 'copies'}
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
    {/if}

    {#if section === 'linkedin'}
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
    {/if}

    {#if section === 'reseaux'}
    <div class="feuille bloc">
      <h2 class="titre">Réseaux</h2>
      <dl>
        {#each Object.entries(e.reseaux) as [s, r]}
          <dt>{NOMS_RESEAUX[s]}</dt>
          <dd>{r.liees} fiche(s) liée(s){#if r.lues}, {r.lues} personne(s) lue(s){/if}{#if r.importe_le}{" "}<span class="discret">(import du {date(r.importe_le)})</span>{/if}</dd>
        {/each}
      </dl>
      <p class="discret">Chaque rapprochement arrive dans « À traiter » (Réseaux) : rien n'est lié sans toi. Les personnes lues mais jamais liées sont effacées au bout de 90 jours.</p>

      <h3>Telegram</h3>
      {#if !e.telegram.configure}
        <p class="discret">Ajoute CARNET_TELEGRAM_API_ID et CARNET_TELEGRAM_API_HASH dans la stack (my.telegram.org, « API development tools »).</p>
      {:else if tg.etape === 'telephone'}
        <span class="rangee"><input type="tel" bind:value={tg.telephone} placeholder="+33 6 12 34 56 78" aria-label="Ton numéro Telegram" autocomplete="tel" />
          <button class="bouton" disabled={!tg.telephone || !!attente} onclick={telegramCode}>Recevoir le code</button></span>
      {:else}
        <span class="rangee"><input inputmode="numeric" bind:value={tg.code} placeholder="Code reçu dans Telegram" aria-label="Code Telegram" autocomplete="one-time-code" />
          {#if tg.etape === 'mdp'}<input type="password" bind:value={tg.mdp} placeholder="Mot de passe Telegram" aria-label="Mot de passe Telegram" autocomplete="off" />{/if}
          <button class="bouton bouton-principal" disabled={!tg.code || (tg.etape === 'mdp' && !tg.mdp) || !!attente} onclick={telegramImport}>Importer</button>
          <button class="bouton" disabled={!!attente} onclick={telegramAbandon}>Abandonner</button></span>
      {/if}
      {#if e.telegram.configure}<p class="discret">Import ponctuel : carnet lit tes contacts Telegram puis se déconnecte. La session n'est ni gardée ni sauvegardée.</p>{/if}

      <h3>Instagram</h3>
      <p class="discret">Dans Instagram : Paramètres, Espace Comptes, Télécharger tes informations, format JSON, « Abonnés et abonnements ». Dépose l'archive .zip ici : seuls les pseudos sont lus, l'archive n'est pas gardée.</p>
      <label class="bouton fichier">{attente === 'instagram' ? 'Lecture…' : 'Déposer l\'export Instagram'}
        <input type="file" accept=".zip,.json,application/zip,application/json" onchange={importerInstagram} hidden /></label>

      <h3>Facebook et WhatsApp</h3>
      <p class="discret">Pas d'import possible : sur la fiche, colle l'adresse du profil Facebook ou choisis le numéro WhatsApp (section Plateformes).</p>
    </div>
    {/if}

    {#if section === 'completude'}
    <div class="feuille bloc">
      <h2 class="titre">Complétude</h2>
      <dl>
        <dt>Sans année</dt><dd>{e.statut.completude.annee}</dd>
        <dt>Sans adresse</dt><dd>{e.statut.completude.adresse}</dd>
        <dt>Sans téléphone</dt><dd>{e.statut.completude.telephone}</dd>
        <dt>Sans moyen de contact</dt><dd>{e.statut.completude.contact}</dd>
        <dt>Validées</dt><dd>{e.statut.completude.validees}</dd>
        <dt>À revoir</dt><dd>{e.statut.completude.a_revoir}</dd>
      </dl>
      <p class="discret">L'analyse globale relit Immich et Treemich, recalcule doublons, complétude et rapprochements réseaux. Elle n'écrit rien dans iCloud.</p>
      <div class="boutons">
        <button class="bouton bouton-principal" disabled={!!attente} onclick={() => analyser(false)}>Relancer l'analyse globale</button>
        {#if !zero.ouvert}
          <button class="bouton bouton-danger" disabled={!!attente} onclick={() => (zero.ouvert = true)}>Remettre les validations à zéro…</button>
        {/if}
      </div>
      {#if zero.ouvert}
        <div class="zero">
          <p>Les {e.statut.completude.validees + e.statut.completude.a_revoir} validation(s) seront effacées : chaque fiche devra être revalidée. Tape <strong>REMETTRE</strong> pour confirmer.</p>
          <span class="rangee"><input bind:value={zero.mot} aria-label="Confirmation" autocapitalize="characters" autocomplete="off" />
            <button class="bouton bouton-danger" disabled={zero.mot !== 'REMETTRE' || !!attente} onclick={() => analyser(true)}>Remettre à zéro et analyser</button>
            <button class="bouton" onclick={() => (zero = { ouvert: false, mot: '' })}>Annuler</button></span>
        </div>
      {/if}
    </div>
    {/if}

    {#if section === 'services'}
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
    {/if}

    {#if section === 'journal'}
    <div class="feuille bloc">
      <h2 class="titre">Journal</h2>
      <ol class="journal">
        {#each e.journal as j}<li><span class="discret">{date(j.le)}</span> {j.message}</li>{/each}
      </ol>
    </div>
    {/if}

    <p class="pied discret">carnet {e.version} <button class="bouton" onclick={deconnecter}>Se déconnecter</button></p>
  {/if}
</section>

<style>
  .tuiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr)); gap: 0.6rem; }
  .tuile {
    position: relative; display: grid; gap: 0.2rem; justify-items: start; text-align: left; padding: 0.9rem;
    border: 1px solid var(--color-couture); border-radius: 10px; background: var(--color-reliure); min-height: 6.5rem;
  }
  .tuile svg { color: var(--color-onglet); margin-bottom: 0.2rem; }
  .tuile[aria-pressed='true'] { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 10%, var(--color-reliure)); }
  .nom-tuile { font-family: var(--font-livre); font-weight: 600; font-size: 1.05rem; }
  .resume { color: var(--color-mine); font-size: 0.82rem; }
  .alerte-point { position: absolute; top: 0.7rem; right: 0.7rem; width: 0.6rem; height: 0.6rem; border-radius: 50%; background: var(--color-alerte); }
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
  .fichier { justify-self: start; cursor: pointer; }
  .zero { display: grid; gap: 0.5rem; padding: 0.75rem; border: 1px solid color-mix(in srgb, var(--color-alerte) 50%, transparent); border-radius: 8px; }
  .pied { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
</style>
