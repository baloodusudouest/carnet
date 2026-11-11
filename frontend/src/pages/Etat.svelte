<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat as global, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  import BoutonAnneau from '../components/BoutonAnneau.svelte'
  import Voyant from '../components/Voyant.svelte'
  import ListeNonLies from '../components/ListeNonLies.svelte'
  import { absents, logoReseau } from '../lib/logos.svelte.js'
  import { appel, de, envoyer, occupe, resumeImport, tache, telecharger } from '../lib/suivi.svelte.js'

  let e = $state(null)
  let attente = $state('')
  let sauvegarde = $state(null)     // { nom, cartes }
  let choisies = $state([])
  let filtreSauvegarde = $state('')
  let adresseLinkedin = $state('')
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
    { cle: 'reseaux', nom: 'Réseaux', icone: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 10.9l7.6-3.8M8.2 13.1l7.6 3.8"/>',
      resume: (e) => `${Object.values(e.reseaux).reduce((n, r) => n + r.liees, 0)} fiche(s) liée(s)`,
      alerte: (e) => ['telegram', 'linkedin'].some((k) => e.sante?.[k]?.etat === 'erreur') },
    { cle: 'completude', nom: 'Complétude', icone: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 8 8h-8z"/>',
      resume: (e) => `${e.statut.completude?.validees ?? 0} validée(s), ${e.statut.completude?.a_revoir ?? 0} à revoir`,
      alerte: (e) => !!e.statut.completude?.a_revoir },
    { cle: 'services', nom: 'Services', icone: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
      resume: (e) => {
        const v = Object.values(e.sante || {}).filter((x) => x.etat !== 'off')
        const ko = v.filter((x) => x.etat === 'erreur').length
        return ko ? `${ko} en erreur sur ${v.length}` : `${v.length} sur ${v.length} OK`
      },
      alerte: (e) => !!e.reprise?.erreur || Object.values(e.sante || {}).some((x) => x.etat === 'erreur') },
    { cle: 'journal', nom: 'Journal', icone: '<path d="M6 4h12v16H6z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
      resume: (e) => `${e.journal.length} lignes`, alerte: () => false },
  ]

  // Voyants : roue pendant l'opération qui concerne la tuile, coche si tout va bien, croix sinon
  const TACHES = { icloud: ['relecture', 'nuit', 'demarrage'], completude: ['analyse'], services: ['liens'],
                   reseaux: [], sauvegardes: [], copies: ['synology'] }
  const tacheEnCours = $derived(global.accueil?.tache?.etat === 'en_cours' ? global.accueil.tache : null)
  function voyantTuile(s) {
    if (tacheEnCours && (TACHES[s.cle] || []).includes(tacheEnCours.nom)) return 'en_cours'
    return s.alerte(e) ? 'erreur' : 'ok'
  }
  const NOMS_TACHES = { relecture: 'Lecture d\'iCloud', nuit: 'Nuit', analyse: 'Analyse globale', liens: 'Lecture d\'Immich et de Treemich',
                        demarrage: 'Démarrage', synology: 'Copie vers Synology Contacts' }
  // Bandeau du haut : une opération en cours, sinon tout va bien, sinon ce qui ne va pas
  const SERVICES = [['icloud', 'iCloud'], ['immich', 'Immich'], ['treemich', 'Treemich'], ['synology', 'Synology Contacts'],
                    ['kit', 'Kit d\'urgence'], ['ha', 'Home Assistant'], ['linkedin', 'LinkedIn (API)'], ['telegram', 'Telegram']]
  const enErreur = $derived(e ? SECTIONS.filter((x) => x.cle !== 'journal' && x.alerte(e)).map((x) => x.nom) : [])

  const date = (iso) => iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : 'jamais'
  async function charger() { try { e = await api.get('/api/etat') } catch (err) { erreur(err) } }

  async function lancer(nom, chemin, corps, message) {
    attente = nom
    try {
      const r = chemin ? await api.post(chemin, corps) : await api.envoyer(corps)
      if (message) dire(typeof message === 'function' ? message(r) : message)
      await rafraichirAccueil()
      setTimeout(charger, 1500)
      return r
    } catch (err) { erreur(err) } finally { attente = '' }
  }

  // Boutons à anneau
  const bloque = $derived(!!attente || occupe() || global.accueil?.tache?.etat === 'en_cours')
  async function fond(cle, chemin, corps, nom) {
    try { await tache(cle, chemin, corps, nom); await rafraichirContacts() } catch (err) { erreur(err) }
    charger()
  }
  async function action(cle, chemin, corps, message) {
    try {
      const r = await appel(cle, async () => {
        const r = await api.post(chemin, corps)
        if (r?.erreur) throw new Error(r.erreur)
        return r
      })
      if (message) dire(typeof message === 'function' ? message(r) : message)
    } catch (err) { erreur(err) }
    charger()
  }
  async function importerFichier(cle, f) {
    try { dire(resumeImport(await envoyer(cle, f, cle))); rafraichirAccueil(); charger() } catch (err) { erreur(err) }
  }
  // Copie vers Synology : tâche de fond, l'anneau suit les fiches copiées
  async function copierSynology(cle, forcer) {
    await fond(cle, '/api/synology', forcer ? { forcer: true } : {}, 'synology')
    const t = global.accueil?.tache
    if (t?.nom === 'synology') (t.etat === 'erreur' ? erreur(t.message) : dire(t.message))
  }
  const chargerFichier = (cle, url, nom) => telecharger(cle, url, nom).catch(erreur)

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
  // Bilan des réseaux : un clic amène à la partie du réseau
  function allerReseau(s) {
    const cible = document.getElementById(`reseau-${s}`)
    cible?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
    cible?.classList.add('repere'); setTimeout(() => cible?.classList.remove('repere'), 1600)
  }
  async function rattacherReseau(service, x, uid) {
    try {
      const r = await api.post(`/api/reseaux/${service}/rattacher`, { ext_id: x.ext_id, uid })
      dire(`${x.nom} rattaché.`, { jeton: r?.jeton || null }); charger(); rafraichirContacts()
    } catch (err) { erreur(err); throw err }
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
  // Analyse globale ; la remise à zéro des validations se confirme deux fois (bouton, puis mot à taper)
  let zero = $state({ ouvert: false, mot: '' })
  async function analyser(remettre) {
    const corps = remettre ? { remettre_a_zero: true, confirmation: zero.mot } : {}
    zero = { ouvert: false, mot: '' }
    await fond('analyse', '/api/analyse', corps, 'analyse')
  }
  const NOMS_RESEAUX = { linkedin: 'LinkedIn', telegram: 'Telegram', instagram: 'Instagram', facebook: 'Facebook',
                         x: 'X (Twitter)', whatsapp: 'WhatsApp' }

  async function deconnecter() { await api.post('/api/deconnexion'); global.connecte = false }

  onMount(charger)
</script>

<section class="page">
  <h1 class="titre">État</h1>
  {#if !e}
    <p class="discret">Chargement…</p>
  {:else}
    <p class="bilan" data-etat={tacheEnCours ? 'en_cours' : enErreur.length ? 'erreur' : 'ok'} role="status">
      {#if tacheEnCours}
        <Voyant etat="en_cours" taille="1.4rem" />
        <span><strong>{NOMS_TACHES[tacheEnCours.nom] || 'Opération'} en cours</strong> <span class="discret">{tacheEnCours.message}</span></span>
      {:else if enErreur.length}
        <Voyant etat="erreur" taille="1.4rem" />
        <span><strong>À voir :</strong> {enErreur.join(', ')}</span>
      {:else}
        <Voyant etat="ok" taille="1.4rem" />
        <span><strong>Tout fonctionne</strong> <span class="discret">dernière nuit {court(e.nuit?.le)}</span></span>
      {/if}
    </p>
    <nav class="tuiles" aria-label="Sections">
      {#each SECTIONS as s}
        <button class="tuile" aria-pressed={section === s.cle} onclick={() => (section = section === s.cle ? null : s.cle)}>
          {#if s.cle !== 'journal'}<span class="voyant-tuile"><Voyant etat={voyantTuile(s)} /></span>{/if}
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html s.icone}</svg>
          <span class="nom-tuile">{s.nom}</span>
          <span class="resume">{s.resume(e)}</span>
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
        <BoutonAnneau icone="relire" libelle="Relire iCloud" enCours="Lecture d'iCloud…" {...de('relire')}
                      disabled={bloque} onclick={() => fond('relire', '/api/icloud/relire', {}, 'relecture')} />
        <BoutonAnneau icone="nuit" libelle="Lancer la nuit maintenant" enCours="Nuit en cours…" {...de('nuit')}
                      disabled={bloque} onclick={() => fond('nuit', '/api/nuit', {}, 'nuit')} />
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
        <select aria-label="Sauvegarde" onchange={(ev) => ev.target.value ? ouvrirSauvegarde(ev.target.value) : (sauvegarde = null)}>
          <option value="">Choisir une sauvegarde à comparer</option>
          {#each e.sauvegardes as s}<option value={s.nom}>{s.nom.replace(/^icloud-|\.vcf$/g, '')} ({Math.round(s.taille / 1024)} Ko)</option>{/each}
        </select>
      {/if}
      <div class="boutons">
        {#if sauvegarde}
          <BoutonAnneau icone="telecharger" libelle="Télécharger cette sauvegarde" enCours="Téléchargement…" {...de('sauvegarde')}
                        disabled={bloque} onclick={() => chargerFichier('sauvegarde', `/api/sauvegardes/${encodeURIComponent(sauvegarde.nom)}/fichier`, sauvegarde.nom)} />
        {/if}
        <BoutonAnneau icone="telecharger" libelle="Exporter tout le carnet (.vcf)" enCours="Export…" {...de('export')}
                      disabled={bloque} onclick={() => chargerFichier('export', '/api/export.vcf', 'carnet.vcf')} />
      </div>
      <p class="discret">L'export reprend les cartes d'iCloud telles qu'à la dernière lecture, photos comprises : un seul fichier à ouvrir dans Contacts ou à garder ailleurs.</p>
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
          <BoutonAnneau icone="copier" libelle="Copier maintenant" enCours="Copie vers Synology…" {...de('syno')}
                        disabled={bloque} onclick={() => copierSynology('syno', false)} />
          {#if e.synology?.erreur || de('syno_force').etat !== 'repos'}
            <BoutonAnneau icone="copier" danger libelle="Forcer la copie" enCours="Copie forcée…" {...de('syno_force')}
                          disabled={bloque} onclick={() => copierSynology('syno_force', true)} />
          {/if}
        {/if}
        {#if e.services.kit}
          <BoutonAnneau icone="envoyer" libelle="Envoyer au kit" enCours="Envoi au kit…" {...de('kit')}
                        disabled={bloque} onclick={() => action('kit', '/api/kit', {}, (r) => `${r.nb} contact(s) envoyé(s) au kit.`)} />
        {/if}
      </div>
    </div>
    {/if}

    {#if section === 'reseaux'}
    <div class="feuille bloc">
      <h2 class="titre">Réseaux</h2>
      <dl>
        {#each Object.entries(e.reseaux) as [s, r]}
          <dt><button class="reseau" onclick={() => allerReseau(s)} title={'Aller à ' + NOMS_RESEAUX[s]}>
            {#if !absents[s]}<img class="logo-reseau" src={logoReseau(s)} alt="" onerror={() => (absents[s] = true)} />{/if}{NOMS_RESEAUX[s]}</button></dt>
          <dd>{r.liees} fiche(s) liée(s){#if r.lues}, {r.lues} personne(s) lue(s){/if}{#if r.importe_le}{" "}<span class="discret">(import du {date(r.importe_le)})</span>{/if}</dd>
        {/each}
      </dl>
      <p class="discret">Chaque rapprochement arrive dans « À traiter » (Réseaux) : rien n'est lié sans toi. Les personnes lues mais jamais liées sont effacées au bout de 90 jours.</p>

      <h3 class="titre-reseau" id="reseau-linkedin">{#if !absents.linkedin}<img class="logo-reseau" src={logoReseau('linkedin')} alt="" onerror={() => (absents.linkedin = true)} />{/if}LinkedIn</h3>
      <p class="discret">Tes relations par l'API de portabilité, ou le fichier Connections.csv de l'export LinkedIn. Seuls les changements de poste ou de société remontent dans « À traiter ».</p>
      <BoutonAnneau icone="envoyer" libelle="Déposer Connections.csv" enCours="Envoi du fichier…" {...de('linkedin_csv')}
                    fichier=".csv,text/csv" disabled={bloque} onfichier={(f) => importerFichier('linkedin_csv', f)} />
      {#if e.linkedin.api}
        <div class="boutons">
          <button class="bouton" disabled={!!attente} onclick={linkedinConnecter}>Se connecter à LinkedIn</button>
          {#if e.linkedin.en_attente}<button class="bouton" disabled={!!attente} onclick={() => lancer('linkedin', '/api/linkedin/reessayer', {}, (r) => `${r.rattachees} relations reconnues.`)}>Réessayer</button>{/if}
        </div>
        <label class="colle"><span class="discret">Adresse de retour de LinkedIn, collée ici</span>
          <span class="rangee"><input bind:value={adresseLinkedin} placeholder="https://localhost/carnet-linkedin?code=…" />
            <button class="bouton" disabled={!adresseLinkedin || !!attente} onclick={linkedinCode}>Importer</button></span></label>
      {/if}
      <ListeNonLies titre="Relations sans fiche" items={e.linkedin.sans_contact} cle={(r) => r.url}
                    detail={(r) => [r.fonction, r.societe].filter(Boolean).join(', ')}
                    rattacher={(r, uid) => linkedinRattacher(r.url, uid)} detacher={(r) => linkedinRattacher(r.url, null)} />

      <h3 class="titre-reseau" id="reseau-telegram">{#if !absents.telegram}<img class="logo-reseau" src={logoReseau('telegram')} alt="" onerror={() => (absents.telegram = true)} />{/if}Telegram</h3>
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

      <ListeNonLies titre="Importés de Telegram sans fiche" charger={() => api.get('/api/reseaux/telegram/non-lies')}
                    detail={(x) => [x.pseudo && x.pseudo !== x.nom && '@' + x.pseudo, x.telephone].filter(Boolean).join(', ')}
                    rattacher={(x, uid) => rattacherReseau('telegram', x, uid)} />

      <h3 class="titre-reseau" id="reseau-facebook">{#if !absents.facebook}<img class="logo-reseau" src={logoReseau('facebook')} alt="" onerror={() => (absents.facebook = true)} />{/if}Facebook</h3>
      <p class="discret">Compte Meta › Vos informations et autorisations › Exporter vos informations : choisis seulement Contacts › <strong>Ami(e)s</strong> (et Followers si tu veux), format <strong>JSON</strong>. Dépose le .zip tel quel, ou seulement <strong>your_friends.json</strong> si tu l'as décompressé (les autres fichiers sont des suggestions ou des demandes, ils ne sont pas lus). Facebook ne donne que les noms : un ami est proposé quand son nom désigne une seule fiche. « Lier » pose la pastille Facebook ; pour écrire le lien du profil dans iCloud, colle son adresse sur la fiche.</p>
      <BoutonAnneau icone="envoyer" libelle="Déposer l'export Facebook" enCours="Envoi de l'archive…" {...de('facebook')}
                    fichier=".zip,.json,application/zip,application/json" disabled={bloque}
                    onfichier={(f) => importerFichier('facebook', f)} />

      <ListeNonLies titre="Importés de Facebook sans fiche" charger={() => api.get('/api/reseaux/facebook/non-lies')}
                    detail={(x) => [x.pseudo && x.pseudo !== x.nom && '@' + x.pseudo, x.telephone].filter(Boolean).join(', ')}
                    rattacher={(x, uid) => rattacherReseau('facebook', x, uid)} />

      <h3 class="titre-reseau" id="reseau-instagram">{#if !absents.instagram}<img class="logo-reseau" src={logoReseau('instagram')} alt="" onerror={() => (absents.instagram = true)} />{/if}Instagram</h3>
      <p class="discret">Dans Instagram : Paramètres, Espace Comptes, Télécharger tes informations, format JSON, « Abonnés et abonnements ». Seuls les pseudos sont lus.</p>
      <BoutonAnneau icone="envoyer" libelle="Déposer l'export Instagram" enCours="Envoi de l'archive…" {...de('instagram')}
                    fichier=".zip,.json,application/zip,application/json" disabled={bloque}
                    onfichier={(f) => importerFichier('instagram', f)} />
      <p class="discret">Les archives sont lues en mémoire puis oubliées : rien n'est gardé sur le NAS.</p>
      <ListeNonLies titre="Importés d'Instagram sans fiche" charger={() => api.get('/api/reseaux/instagram/non-lies')}
                    detail={(x) => [x.pseudo && x.pseudo !== x.nom && '@' + x.pseudo, x.telephone].filter(Boolean).join(', ')}
                    rattacher={(x, uid) => rattacherReseau('instagram', x, uid)} />

      <h3 class="titre-reseau" id="reseau-x">{#if !absents.x}<img class="logo-reseau" src={logoReseau('x')} alt="" onerror={() => (absents.x = true)} />{/if}X (Twitter)</h3>
      <p class="discret">L'archive de X ne donne que des numéros de compte, sans pseudo ni nom : rien à rapprocher. Sur la fiche, colle le pseudo (@…) ou l'adresse x.com dans Plateformes ; les profils Twitter déjà présents sur tes cartes iCloud sont reconnus.</p>

      <h3 class="titre-reseau" id="reseau-whatsapp">{#if !absents.whatsapp}<img class="logo-reseau" src={logoReseau('whatsapp')} alt="" onerror={() => (absents.whatsapp = true)} />{/if}WhatsApp</h3>
      <p class="discret">Pas d'export des contacts : sur la fiche, choisis le numéro WhatsApp (section Plateformes).</p>
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
        <BoutonAnneau icone="analyse" principal libelle="Relancer l'analyse globale" enCours="Analyse en cours…" {...de('analyse')}
                      disabled={bloque} onclick={() => analyser(false)} />
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
        {#each SERVICES as [k, nom]}
          {@const v = e.sante?.[k] || { etat: 'off', message: '' }}
          <li>
            <Voyant etat={tacheEnCours?.nom === 'liens' && (k === 'immich' || k === 'treemich') ? 'en_cours' : v.etat} />
            <span>{nom} <span class="discret">{v.etat === 'ok' ? 'OK' : v.etat === 'off' ? 'non configuré' : ''}</span>
              {#if v.etat === 'erreur'}<span class="alerte petit">{v.message}</span>{/if}</span>
          </li>
        {/each}
      </ul>
      {#if e.reprise}
        <p class="discret">Reprise de la 1.3 le {date(e.reprise.le)} : {e.reprise.liaisons} liaison(s), {e.reprise.portraits} photo(s) choisie(s), {e.reprise.affiches} affiche(s), {e.reprise.linkedin} relation(s) LinkedIn.</p>
        {#if e.reprise.erreur}<p class="alerte">{e.reprise.erreur}</p>{/if}
      {/if}
      <BoutonAnneau icone="relire" libelle="Relire Immich et Treemich" enCours="Lecture d'Immich et de Treemich…" {...de('liens')}
                    disabled={bloque} onclick={() => fond('liens', '/api/liens/rafraichir', {}, 'liens')} />
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
  /* Tuiles bento : la taille dit l'importance. « iCloud et la nuit » occupe deux colonnes. */
  .tuiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.6rem; }
  .tuiles .tuile:first-child { grid-column: span 2; }
  @media (min-width: 900px) { .tuiles { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.75rem; } }
  .tuile {
    position: relative; display: grid; gap: 0.2rem; justify-items: start; text-align: left; padding: 0.9rem;
    border: 1px solid var(--color-couture); border-radius: 14px; background: var(--color-reliure); min-height: 6.5rem;
  }
  .tuile svg { color: var(--color-onglet); margin-bottom: 0.2rem; }
  .tuile[aria-pressed='true'] { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 10%, var(--color-reliure)); }
  .nom-tuile { font-family: var(--font-livre); font-weight: 600; font-size: 1.05rem; }
  .resume { color: var(--color-mine); font-size: 0.82rem; }
  .voyant-tuile { position: absolute; top: 0.75rem; right: 0.75rem; display: grid; }
  .bilan { display: flex; align-items: center; gap: 0.7rem; padding: 0.75rem 0.9rem; border-radius: 10px;
    border: 1px solid var(--color-couture); background: var(--color-reliure); }
  .bilan[data-etat='erreur'] { border-color: color-mix(in srgb, var(--color-alerte) 60%, transparent); }
  .bilan[data-etat='ok'] { border-color: color-mix(in srgb, var(--color-valide) 40%, transparent); }
  .bilan[data-etat='en_cours'] { border-color: color-mix(in srgb, var(--color-onglet) 50%, transparent); }
  /* Logos des réseaux */
  .logo-reseau { width: 1.35rem; height: 1.35rem; border-radius: 5px; background: #f4efe7; object-fit: contain;
    box-shadow: 0 0 0 1px rgb(0 0 0 / 0.25); flex: none; }
  .titre-reseau { display: flex; align-items: center; gap: 0.5rem; }
  button.reseau { display: flex; align-items: center; gap: 0.45rem; color: var(--color-mine); text-align: left; min-height: 1.8rem; }
  button.reseau:hover { color: var(--color-papier); text-decoration: underline; text-underline-offset: 3px; }
  .titre-reseau { scroll-margin-top: calc(1rem + env(safe-area-inset-top)); border-radius: 6px; transition: background-color 0.6s ease; }
  :global(.titre-reseau.repere) { background: color-mix(in srgb, var(--color-onglet) 18%, transparent); }
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
  .services { display: grid; gap: 0.3rem; }
  .services li { display: flex; align-items: center; gap: 0.5rem; }
  .services li { align-items: flex-start; min-height: 1.8rem; }
  .services li > span .alerte { display: block; }
  .petit { font-size: 0.82rem; }
  .journal { display: grid; gap: 0.35rem; max-height: 22rem; overflow-y: auto; font-size: 0.9rem; }
  .zero { display: grid; gap: 0.5rem; padding: 0.75rem; border: 1px solid color-mix(in srgb, var(--color-alerte) 50%, transparent); border-radius: 8px; }
  .pied { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
</style>
