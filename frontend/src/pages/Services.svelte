<script>
  // Connexion (2.9) : une icône par service. Chaque service se vérifie (relire et comparer, sans
  // rien écrire) et se synchronise (écrire ce qui est sûr, envoyer les différences dans À traiter).
  import { onMount, tick } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat as global, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  import BoutonAnneau from '../components/BoutonAnneau.svelte'
  import Voyant from '../components/Voyant.svelte'
  import Attentes from '../components/Attentes.svelte'
  import Import from '../components/Import.svelte'
  import Reseaux from '../components/Reseaux.svelte'
  import { ICONES_SERVICES } from '../lib/icones.js'
  import { absents, logoReseau } from '../lib/logos.svelte.js'
  import { de, occupe, tache, telecharger } from '../lib/suivi.svelte.js'

  let cx = $state(null)
  let choisi = $state(null)        // clé du service ouvert, ou « attentes »
  let rapport = $state(null)       // dernier rapport de vérification du service ouvert
  let attente = $state('')
  let importOuvert = $state(false)
  let sauvegardes = $state([])
  let sauvegarde = $state(null)     // { nom, cartes }
  let choisies = $state([])
  let filtreSauvegarde = $state('')

  const RESEAUX = ['linkedin', 'telegram', 'facebook', 'instagram']
  const bloque = $derived(!!attente || occupe() || global.accueil?.tache?.etat === 'en_cours')
  const service = $derived(cx?.services.find((s) => s.cle === choisi))
  const date = (iso) => iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : 'jamais'
  const court = (iso) => iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''

  async function charger() {
    try { cx = await api.get('/api/connexion') } catch (err) { erreur(err) }
  }
  async function ouvrir(cle) {
    choisi = choisi === cle ? null : cle
    rapport = null; sauvegarde = null
    // iPhone : le détail s'ouvre sous treize tuiles, on l'amène à l'écran
    if (choisi) tick().then(() => document.getElementById('detail-service')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    if (choisi === 'sauvegardes') { try { sauvegardes = (await api.get('/api/etat')).sauvegardes } catch (err) { erreur(err) } }
  }
  async function verifier() {
    attente = 'verifier'
    try {
      rapport = await api.post(`/api/connexion/${choisi}/verifier`)
      await Promise.all([charger(), rafraichirAccueil()])
    } catch (err) { erreur(err) } finally { attente = '' }
  }
  async function synchroniser(forcer = false) {
    attente = 'synchroniser'
    try {
      if (choisi === 'synology' && forcer) await tache('synchro', '/api/synology', { forcer: true }, 'synology')
      else await tache('synchro', `/api/connexion/${choisi}/synchroniser`, {}, 'synchro')
      const t = global.accueil?.tache
      if (t?.etat === 'erreur') erreur(new Error(t.message)); else dire(t?.message || 'Synchronisé.')
      rapport = null
      await Promise.all([charger(), rafraichirContacts(), rafraichirAccueil()])
    } catch (err) { erreur(err) } finally { attente = '' }
  }
  async function basculerNuit(actif) {
    try {
      await api.post(`/api/connexion/${choisi}/nuit`, { actif })
      dire(actif ? 'Allumé : fait chaque nuit.' : 'Éteint : seulement quand tu appuies sur Synchroniser.')
      await charger()
    } catch (err) { erreur(err) }
  }
  const chargerFichier = (cle, url, nom) => telecharger(cle, url, nom).catch(erreur)
  async function ouvrirSauvegarde(nom) {
    try { sauvegarde = { nom, cartes: await api.get(`/api/sauvegardes/${encodeURIComponent(nom)}`) }; choisies = [] }
    catch (err) { erreur(err) }
  }
  async function restaurer() {
    attente = 'restauration'
    try {
      const r = await api.post(`/api/sauvegardes/${encodeURIComponent(sauvegarde.nom)}/restaurer`, { uids: choisies })
      dire(`${r.restaurees} fiche(s) remise(s), ${r.recreees} recréée(s)${r.erreurs.length ? `, ${r.erreurs.length} erreur(s)` : ''}.`)
      await rafraichirContacts(); ouvrirSauvegarde(sauvegarde.nom)
    } catch (err) { erreur(err) } finally { attente = '' }
  }
  const cartesVisibles = $derived((sauvegarde?.cartes || []).filter((c) =>
    c.etat !== 'identique' && (!filtreSauvegarde || c.nom.toLowerCase().includes(filtreSauvegarde.toLowerCase()))))
  const voyant = (s) => attente && choisi === s.cle ? 'en_cours' : s.voyant
  const EXPLICATIONS = {
    icloud: 'iCloud est la source : carnet le relit, signale ce qui a changé sur l\'iPhone et n\'y écrit que ce que tu as validé — plus les fêtes, si tu le veux.',
    immich: 'Vérifier compare le nom, la date de naissance et la photo de chaque fiche reliée. Synchroniser fait les liaisons sûres, complète les naissances d\'un côté ou de l\'autre et pose les portraits manquants.',
    treemich: 'Vérifier compare le nom, la naissance, le mariage, le décès et les liens familiaux. Synchroniser remplit le côté vide, sans jamais écraser.',
    synology: 'Copie à l\'identique d\'iCloud vers Synology Contacts.',
    kit: 'Les contacts du groupe Urgence sont envoyés au kit d\'urgence.',
    ha: 'Home Assistant vient lire carnet : contacts, anniversaires et mariages (/ha/anniversaires), fêtes (/ha/fetes), invités, portraits. carnet n\'écrit rien dans Home Assistant.',
    import: 'Cartes de contacts, relations LinkedIn, exports Facebook et Instagram : carnet reconnaît le fichier et annonce ce qu\'il en fera.',
  }
  onMount(charger)
</script>

<section class="page">
  <h1 class="titre">Connexion</h1>
  {#if !cx}
    <p class="discret">Chargement…</p>
  {:else}
    <nav class="tuiles" aria-label="Services">
      {#each cx.services as s (s.cle)}
        <button class="tuile" aria-pressed={choisi === s.cle} onclick={() => ouvrir(s.cle)}>
          <span class="voyant-tuile"><Voyant etat={voyant(s)} /></span>
          {#if RESEAUX.includes(s.cle) && !absents[s.cle]}
            <img class="logo-service" src={logoReseau(s.cle)} alt="" onerror={() => (absents[s.cle] = true)} />
          {:else}
            <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html ICONES_SERVICES[s.cle] || ICONES_SERVICES.defaut}</svg>
          {/if}
          <span class="nom-tuile">{s.nom}{#if s.differences}<span class="ecarts-tuile" title="Différences dans À traiter">{s.differences}</span>{/if}</span>
          <span class="resume">{s.resume}</span>
        </button>
      {/each}
      <button class="tuile" aria-pressed={choisi === 'attentes'} onclick={() => ouvrir('attentes')}>
        <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html ICONES_SERVICES.attentes}</svg>
        <span class="nom-tuile">Attentes</span>
        <span class="resume">Ce que chaque groupe doit avoir</span>
      </button>
    </nav>

    <div id="detail-service"></div>
    {#if !choisi}
      <p class="discret">Touche un service pour le vérifier ou le synchroniser. Le chiffre en couleur est le nombre de différences qui t'attendent dans « À traiter ».</p>
    {:else if choisi === 'attentes'}
      <Attentes />
    {:else if service}
      <div class="feuille bloc" aria-label={service.nom}>
        <div class="entete-service">
          <h2 class="titre">{service.nom}</h2>
          <span class="discret">{service.voyant === 'off' ? 'non configuré' : service.le ? `vu le ${court(service.le)}` : ''}</span>
        </div>
        {#if service.voyant === 'erreur'}<p class="alerte" role="alert">{service.message}</p>{/if}
        {#if EXPLICATIONS[choisi]}<p class="discret">{EXPLICATIONS[choisi]}</p>{/if}
        {#if cx.lecture_seule && service.synchronisable}<p class="discret" role="status">Mode lecture seule : Synchroniser sera refusé.</p>{/if}

        {#if service.verifiable || service.synchronisable}
          <div class="boutons">
            {#if service.verifiable}
              <button class="bouton" disabled={bloque || service.voyant === 'off'} onclick={verifier}>{attente === 'verifier' ? 'Vérification…' : 'Vérifier'}</button>
            {/if}
            {#if service.synchronisable}
              <button class="bouton bouton-principal" disabled={bloque || service.voyant === 'off' || cx.lecture_seule} onclick={() => synchroniser()}>
                {attente === 'synchroniser' ? 'Synchronisation…' : choisi === 'synology' ? 'Copier maintenant' : choisi === 'kit' ? 'Envoyer au kit' : 'Synchroniser'}</button>
            {/if}
            {#if choisi === 'synology' && service.voyant === 'erreur'}
              <button class="bouton bouton-danger" disabled={bloque} onclick={() => synchroniser(true)}>Forcer la copie</button>
            {/if}
            {#if service.differences}<a class="bouton" href="#/a-traiter">{service.differences} différence(s) dans À traiter</a>{/if}
          </div>
        {/if}

        {#if service.nuit}
          <label class="bascule">
            <input type="checkbox" role="switch" checked={service.nuit.actif} onchange={(ev) => basculerNuit(ev.currentTarget.checked)} />
            <span><strong>La nuit{cx.nuit ? ` (${cx.nuit})` : ''}</strong> : {service.nuit.quoi.toLowerCase()}
              <span class="etat-bascule" class:actif={service.nuit.actif}>{service.nuit.actif ? 'allumé' : 'éteint'}</span></span>
          </label>
          {#if !cx.nuit}<p class="discret">La nuit de carnet est désactivée (CARNET_VEILLE_HEURE) : rien ne se fait tout seul.</p>{/if}
        {/if}

        {#if attente === 'verifier' && choisi === 'treemich'}
          <p class="discret" role="status">carnet relit l'arbre personne par personne : compte une minute. Rien n'est écrit.</p>
        {/if}
        {#if rapport && !rapport.ok}
          <p class="alerte" role="alert">{service.nom} n'a pas répondu : {rapport.raison}</p>
        {:else if rapport}
          <div class="rapport" role="status">
            {#if rapport.lignes.some((l) => l.sur)}
              <table class="verif">
                <thead><tr><th scope="col"></th><th scope="col">Vues</th><th scope="col">Égales</th><th scope="col">Vides</th><th scope="col">Écarts</th></tr></thead>
                <tbody>
                  {#each rapport.lignes as l}
                    <tr><th scope="row">{l.libelle}</th><td>{l.sur}</td><td>{l.identiques}</td><td>{l.vides}</td><td class:ecart={l.ecarts}>{l.ecarts}</td></tr>
                  {/each}
                </tbody>
              </table>
            {/if}
            {#if rapport.couples?.length}
              <h3 class="sous-titre">Mariages, couple par couple</h3>
              <div class="defile">
                <table class="verif couples">
                  <thead><tr><th scope="col">Couple</th><th scope="col">carnet</th><th scope="col">Treemich</th><th scope="col"></th></tr></thead>
                  <tbody>
                    {#each rapport.couples as x}
                      <tr><th scope="row"><a href={'#/contacts/' + encodeURIComponent(x.uid)}>{x.couple}</a></th>
                        <td>{x.carnet || '—'}</td><td>{x.treemich || '—'}</td><td class="discret">{x.etat}</td></tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
            {#each rapport.notes as n}<p class="discret">{n}</p>{/each}
            {#if rapport.lignes.some((l) => l.sur) && !rapport.ecarts.length}
              <p class="tout-bon">Aucun écart.</p>
            {:else if rapport.ecarts.length}
              <ul class="ecarts">
                {#each rapport.ecarts as x}
                  <li><span class="discret">{x.libelle} · {x.etat_libelle}</span><br />
                    <a href={'#/contacts/' + encodeURIComponent(x.uid)}>{x.nom}</a> — carnet : {x.carnet || 'rien'} ; {service.nom} : {x.autre || 'rien'}<br />
                    <span class="discret">{x.suite}</span></li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}

        {#if choisi === 'icloud'}
          <div class="boutons">
            <button class="bouton bouton-danger" disabled={bloque} onclick={async () => { try { await tache('relire', '/api/icloud/relire', { forcer: true }, 'relecture'); charger() } catch (err) { erreur(err) } }}>Relire quand même…</button>
          </div>
          <p class="discret petit">« Relire quand même » sert après un arrêt de sécurité : quand plus de 5 % des fiches semblent avoir disparu d'un coup et que tu as vérifié sur l'iPhone que c'est voulu.</p>
        {:else if choisi === 'import'}
          <div class="boutons"><button class="bouton bouton-principal" onclick={() => (importOuvert = true)}>Importer un fichier</button></div>
        {/if}
      </div>

      {#if choisi === 'sauvegardes'}
        <div class="feuille bloc">
          <p class="discret">Une copie complète avant la première écriture de chaque jour et chaque nuit. Gardées 30 jours, puis une par mois pendant un an.</p>
      {#if !sauvegardes.length}
        <p class="discret">Aucune sauvegarde pour l'instant.</p>
      {:else}
        <select aria-label="Sauvegarde" onchange={(ev) => ev.target.value ? ouvrirSauvegarde(ev.target.value) : (sauvegarde = null)}>
          <option value="">Choisir une sauvegarde à comparer</option>
          {#each sauvegardes as s}<option value={s.nom}>{s.nom.replace(/^icloud-|\.vcf$/g, '')} ({Math.round(s.taille / 1024)} Ko)</option>{/each}
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
      {:else if RESEAUX.includes(choisi)}
        {#key choisi}<Reseaux seul={choisi} />{/key}
      {/if}
    {/if}
  {/if}
  <Import bind:ouvert={importOuvert} />
</section>

<style>
  .page { max-width: 60rem; display: grid; gap: 1rem; }
  h1 { font-size: 1.9rem; }
  h2 { font-size: 1.25rem; }
  #detail-service { scroll-margin-top: 0.75rem; }
  .tuiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.6rem; }
  .tuile { position: relative; display: grid; gap: 0.3rem; justify-items: start; text-align: left; padding: 0.85rem 0.95rem; border-radius: 12px;
    border: 1px solid var(--color-couture); background: var(--color-reliure); color: var(--color-papier); min-width: 0; }
  .tuile[aria-pressed='true'] { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 10%, var(--color-reliure)); }
  .nom-tuile { font-weight: 600; font-size: 1.02rem; display: flex; align-items: center; gap: 0.45rem; }
  .resume { color: var(--color-mine); font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .voyant-tuile { position: absolute; top: 0.7rem; right: 0.7rem; display: grid; }
  .ecarts-tuile { min-width: 1.3rem; height: 1.3rem; padding: 0 0.35rem; border-radius: 9999px; font-size: 0.72rem; font-weight: 700;
    line-height: 1.3rem; text-align: center; background: var(--color-onglet); color: var(--color-sur-onglet); }
  .logo-service { width: 26px; height: 26px; border-radius: 6px; background: #f4efe7; object-fit: contain; }
  .bloc { padding: 1rem; display: grid; gap: 0.7rem; }
  .bloc a:not(.bouton) { text-decoration: underline; text-underline-offset: 3px; }
  .entete-service { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .boutons { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .alerte { color: var(--color-alerte); }
  .petit { font-size: 0.82rem; }
  .bascule { display: flex; align-items: center; gap: 0.7rem; min-height: 2.75rem; }
  .bascule input { appearance: none; width: 2.9rem; height: 1.7rem; border-radius: 9999px; background: var(--color-tranche); position: relative;
    border: 0; padding: 0; flex: none; transition: background-color 0.2s ease; cursor: pointer; }
  .bascule input::after { content: ''; position: absolute; top: 3px; left: 3px; width: calc(1.7rem - 6px); height: calc(1.7rem - 6px); border-radius: 50%;
    background: var(--color-papier); transition: transform 0.2s ease; }
  .bascule input:checked { background: var(--color-onglet); }
  .bascule input:checked::after { transform: translateX(1.2rem); }
  .bascule input:focus-visible { outline: 2px solid var(--color-onglet); outline-offset: 2px; }
  .etat-bascule { color: var(--color-mine); font-size: 0.85rem; margin-left: 0.3rem; }
  .etat-bascule.actif { color: var(--color-onglet); }
  .rapport { display: grid; gap: 0.5rem; padding-top: 0.6rem; border-top: 1px solid var(--color-couture); }
  .verif { width: 100%; max-width: 30rem; table-layout: fixed; border-collapse: collapse; font-size: 0.9rem; }
  .verif th, .verif td { padding: 0.3rem 0.25rem; text-align: right; overflow-wrap: anywhere; }
  .verif thead th { color: var(--color-mine); font-size: 0.78rem; font-weight: 600; }
  .verif thead th:first-child, .verif tbody th { width: 34%; text-align: left; }
  .verif tbody tr { border-top: 1px solid var(--color-couture); }
  .verif.couples { max-width: 44rem; table-layout: auto; }
  .verif.couples th, .verif.couples td { text-align: left; }
  .verif.couples tbody th { width: auto; font-weight: 500; }
  .sous-titre { font-size: 0.95rem; font-weight: 600; margin: 0.4rem 0 0; }
  .defile { overflow-x: auto; }
  .verif td.ecart { color: var(--color-onglet); font-weight: 600; }
  .tout-bon { color: var(--color-valide); }
  .ecarts { display: grid; font-size: 0.92rem; max-height: 26rem; overflow-y: auto; }
  .ecarts li { padding: 0.45rem 0; border-top: 1px solid var(--color-couture); }
  .cartes { max-height: 18rem; overflow-y: auto; display: grid; gap: 0.15rem; }
  .cartes label { display: flex; align-items: center; gap: 0.5rem; min-height: 2.5rem; flex-wrap: wrap; }
  @media (min-width: 900px) { .tuiles { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
  @media (prefers-reduced-motion: reduce) { .bascule input, .bascule input::after { transition: none; } }
</style>
