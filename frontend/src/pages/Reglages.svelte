<script>
  // Réglages (2.9) : la nuit, l'analyse globale, ce que carnet a écrit tout seul, les exceptions,
  // le journal et la session. Les services et les attentes par groupe sont dans Connexion.
  // 2.26 : réglages d'usage (sortis de la stack) et « Restaurer les réglages » (sauvegardes de l'Anneau).
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  import BoutonAnneau from '../components/BoutonAnneau.svelte'
  import { de, occupe, tache } from '../lib/suivi.svelte.js'

  let e = $state(null)
  let auto = $state(null)
  let exceptions = $state(null)
  let attente = $state(false)
  const bloque = $derived(attente || occupe() || etat.accueil?.tache?.etat === 'en_cours')
  const date = (iso) => iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : 'jamais'
  const jour = (iso) => iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) : ''

  async function charger() {
    try { [e, auto, exceptions] = await Promise.all([api.get('/api/etat'), api.get('/api/automatique'), api.get('/api/exceptions')]) }
    catch (err) { erreur(err) }
  }
  async function fond(cle, chemin, corps, nom) {
    try { await tache(cle, chemin, corps, nom); await rafraichirContacts() } catch (err) { erreur(err) }
    charger()
  }
  // Analyse globale ; la remise à zéro des validations se confirme deux fois (bouton, puis mot à taper)
  let zero = $state({ ouvert: false, mot: '' })
  async function analyser(remettre) {
    const corps = remettre ? { remettre_a_zero: true, confirmation: zero.mot } : {}
    zero = { ouvert: false, mot: '' }
    await fond('analyse', '/api/analyse', corps, 'analyse')
  }
  async function defaire(x) {
    attente = true
    try {
      await api.post(`/api/automatique/defaire/${x.id}`)
      dire('Défait.')
      auto = await api.get('/api/automatique'); rafraichirContacts()
    } catch (err) { erreur(err) } finally { attente = false }
  }
  async function retirerException(x) {
    try {
      await api.post(`/api/contacts/${encodeURIComponent(x.uid)}/exception`, { info: x.info, oui: false })
      exceptions = await api.get('/api/exceptions'); rafraichirContacts(); rafraichirAccueil()
    } catch (err) { erreur(err) }
  }
  // ---- 2.26 : réglages d'usage
  const NOMS = {
    veille_heure: 'Heure de la nuit', emoji_groupes: 'Émojis → groupes', synology_carnet: 'Carnet d\'adresses Synology',
    synology_verifier_tls: 'Vérifier le certificat de Synology', auto_fetes: 'Nuit : écrire les fêtes (iCloud)',
    auto_famille: 'Nuit : mariages et décès (Treemich)', nuit_immich: 'Nuit : Immich', nuit_synology: 'Nuit : copie Synology',
    nuit_kit: 'Nuit : kit d\'urgence',
  }
  const lisible = (v) => v === true ? 'oui' : v === false ? 'non' : (v === '' || v == null) ? '(vide)' : String(v)
  let r = $state(null)            // réglages enregistrés
  let f = $state(null)            // formulaire
  let enregistrement = $state(false)
  function remplir(x) {
    r = x
    const active = x.veille_heure && x.veille_heure !== 'off'
    f = { nuit: !!active, heure: active ? x.veille_heure : (f?.heure || '03:00'), emoji_groupes: x.emoji_groupes,
          synology_carnet: x.synology_carnet, synology_verifier_tls: x.synology_verifier_tls }
  }
  const voulus = $derived(f ? { veille_heure: f.nuit ? f.heure : 'off', emoji_groupes: f.emoji_groupes,
                                synology_carnet: f.synology_carnet, synology_verifier_tls: f.synology_verifier_tls } : {})
  const modifie = $derived(!!r && Object.entries(voulus).some(([k, v]) => r[k] !== v))
  async function chargerReglages() {
    try { remplir((await api.get('/api/reglages')).reglages) } catch (err) { erreur(err) }
  }
  async function enregistrer() {
    enregistrement = true
    try {
      remplir((await api.put('/api/reglages', voulus)).reglages)
      dire('Réglages enregistrés.')
      e = await api.get('/api/etat')
    } catch (err) { erreur(err) } finally { enregistrement = false }
  }

  // ---- 2.26 : restaurer depuis une sauvegarde de l'Anneau
  let rest = $state({ ouvert: false, dates: null, le: '', diff: null, message: '', attente: false })
  async function voirSauvegardes() {
    rest = { ouvert: true, dates: null, le: '', diff: null, message: '', attente: true }
    try { rest.dates = (await api.get('/api/restaurer')).dates; if (!rest.dates.length) rest.message = 'L\'Anneau n\'a encore aucune sauvegarde de carnet.' }
    catch (err) { rest.message = err.message }
    finally { rest.attente = false }
  }
  async function choisirDate(le) {
    rest.le = le; rest.diff = null; rest.message = ''
    if (!le) return
    rest.attente = true
    try { rest.diff = await api.get('/api/restaurer?le=' + encodeURIComponent(le)) }
    catch (err) { rest.message = err.message }
    finally { rest.attente = false }
  }
  async function restaurer() {
    rest.attente = true
    try {
      const res = await api.post('/api/restaurer', { le: rest.le })
      remplir(Object.fromEntries(Object.entries(res.reglages)))
      dire(`Réglages restaurés (${res.changes.length} changement(s)).`)
      rest = { ouvert: false, dates: null, le: '', diff: null, message: '', attente: false }
      e = await api.get('/api/etat')
    } catch (err) { rest.message = err.message; rest.attente = false }
  }

  async function deconnecter() { await api.post('/api/deconnexion'); etat.connecte = false }
  const SERVICES_ECRITS = { icloud: 'iCloud', treemich: 'Treemich', immich: 'Immich' }
  onMount(() => { charger(); chargerReglages() })
</script>

<section class="page">
  <h1 class="titre">Réglages</h1>
  {#if !e || !auto}
    <p class="discret">Chargement…</p>
  {:else}
    <div class="feuille bloc">
      <h2 class="titre">La nuit</h2>
      <dl>
        <dt>Heure</dt><dd>{e.services.nuit || 'désactivée'}</dd>
        <dt>Dernière nuit</dt>
        <dd>{date(e.nuit?.le)}{e.nuit ? `, ${e.nuit.ecrites} écriture(s), ${e.nuit.liaisons} liaison(s)` : ''}
          {#if e.nuit?.reportees}, {e.nuit.reportees} reportée(s) à la nuit suivante{/if}</dd>
      </dl>
      <p class="discret">Chaque nuit : sauvegarde d'iCloud, relecture, puis la synchronisation des services dont l'interrupteur « la nuit » est allumé dans <a href="#/connexion">Connexion</a>.</p>
      {#if e.nuit?.erreur}<p class="alerte" role="alert">{e.nuit.erreur}</p>{/if}
      {#each e.nuit?.details || [] as d}<p class="discret">{d}</p>{/each}
      <div class="boutons">
        <BoutonAnneau icone="nuit" libelle="Lancer la nuit maintenant" enCours="Nuit en cours…" {...de('nuit')}
                      disabled={bloque} onclick={() => fond('nuit', '/api/nuit', {}, 'nuit')} />
      </div>
    </div>

    {#if f}
      <div class="feuille bloc" id="reglages-usage">
        <h2 class="titre">Réglages d'usage</h2>
        <p class="discret">Ils se changent ici (avant la 2.26, dans la stack). L'Anneau les sauvegarde chaque nuit.</p>
        <label class="bascule">
          <input type="checkbox" role="switch" bind:checked={f.nuit} aria-label="La nuit chaque jour" />
          <span><strong>La nuit chaque jour</strong>
            <span class="etat-bascule" class:actif={f.nuit}>{f.nuit ? 'allumée' : 'désactivée'}</span></span>
        </label>
        {#if f.nuit}
          <label class="champ"><span>Heure de la nuit</span>
            <input type="time" bind:value={f.heure} aria-label="Heure de la nuit" required /></label>
        {/if}
        <label class="champ"><span>Émojis → groupes</span>
          <input bind:value={f.emoji_groupes} aria-label="Émojis vers groupes" placeholder="🍕:Amis;🔧:Artisans et services" autocomplete="off" />
          <small class="discret">Un contact qui contient l'émoji rejoint le groupe. Règles « émoji:groupe » séparées par « ; ».</small></label>
        <label class="champ"><span>Carnet d'adresses Synology</span>
          <input bind:value={f.synology_carnet} aria-label="Carnet d'adresses Synology" autocomplete="off" />
          <small class="discret">Nom du carnet de Synology Contacts qui reçoit la copie ; plusieurs noms possibles, séparés par « | ».</small></label>
        <label class="bascule">
          <input type="checkbox" role="switch" bind:checked={f.synology_verifier_tls} aria-label="Vérifier le certificat de Synology" />
          <span><strong>Vérifier le certificat de Synology</strong>
            <span class="etat-bascule" class:actif={f.synology_verifier_tls}>{f.synology_verifier_tls ? 'oui' : 'non'}</span></span>
        </label>
        <p class="discret">Les interrupteurs « la nuit » de chaque service restent dans <a href="#/connexion">Connexion</a>.</p>
        <div class="boutons">
          <button class="bouton bouton-principal" disabled={!modifie || enregistrement} onclick={enregistrer}>Enregistrer les réglages</button>
          {#if modifie}<button class="bouton" onclick={() => remplir(r)}>Annuler</button>{/if}
        </div>
      </div>
    {/if}

    <div class="feuille bloc" id="restaurer">
      <h2 class="titre">Restaurer les réglages</h2>
      <p class="discret">Reprend les réglages d'une sauvegarde de l'Anneau (seulement les réglages : ni fiches, ni contacts).</p>
      {#if !rest.ouvert}
        <div class="boutons"><button class="bouton" onclick={voirSauvegardes}>Voir les sauvegardes</button></div>
      {:else}
        {#if rest.dates?.length}
          <label class="champ"><span>Sauvegarde du</span>
            <select aria-label="Date de la sauvegarde" value={rest.le} onchange={(ev) => choisirDate(ev.currentTarget.value)} disabled={rest.attente}>
              <option value="">Choisir une date…</option>
              {#each rest.dates as d}<option value={d}>{d}</option>{/each}
            </select></label>
        {/if}
        {#if rest.attente}<p class="discret">Lecture de l'Anneau…</p>{/if}
        {#if rest.message}<p class="alerte" role="alert">{rest.message}</p>{/if}
        {#if rest.diff}
          {#if !rest.diff.differences.length}
            <p class="discret">Rien à restaurer : les réglages sont déjà ceux du {rest.le}.</p>
          {:else}
            <table class="diff">
              <thead><tr><th scope="col">Réglage</th><th scope="col">Avant</th><th scope="col">Sauvegardé</th></tr></thead>
              <tbody>
                {#each rest.diff.differences as d (d.cle)}
                  <tr><th scope="row">{NOMS[d.cle] || d.cle}</th><td>{lisible(d.actuel)}</td><td>{lisible(d.sauve)}</td></tr>
                {/each}
              </tbody>
            </table>
            <div class="boutons">
              <button class="bouton bouton-principal" disabled={rest.attente} onclick={restaurer}>Restaurer ces réglages</button>
            </div>
          {/if}
        {/if}
        <div class="boutons"><button class="bouton" onclick={() => (rest = { ouvert: false, dates: null, le: '', diff: null, message: '', attente: false })}>Fermer</button></div>
      {/if}
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Analyse globale</h2>
      <p class="discret">Relit Immich et Treemich, recalcule doublons, manques et rapprochements des réseaux. Elle n'écrit rien dans iCloud.
        {e.statut.completude.validees} fiche(s) validée(s), {e.statut.completude.a_revoir} à revoir.</p>
      <div class="boutons">
        <BoutonAnneau icone="analyse" libelle="Relancer l'analyse globale" enCours="Analyse en cours…" {...de('analyse')}
                      disabled={bloque} onclick={() => analyser(false)} />
        {#if !zero.ouvert}
          <button class="bouton bouton-danger" disabled={bloque} onclick={() => (zero.ouvert = true)}>Remettre les validations à zéro…</button>
        {/if}
      </div>
      {#if zero.ouvert}
        <div class="zero">
          <p>Les {e.statut.completude.validees + e.statut.completude.a_revoir} validation(s) seront effacées : chaque fiche devra être revalidée. Tape <strong>REMETTRE</strong> pour confirmer.</p>
          <span class="rangee"><input bind:value={zero.mot} aria-label="Confirmation" autocapitalize="characters" autocomplete="off" />
            <button class="bouton bouton-danger" disabled={zero.mot !== 'REMETTRE' || bloque} onclick={() => analyser(true)}>Remettre à zéro et analyser</button>
            <button class="bouton" onclick={() => (zero = { ouvert: false, mot: '' })}>Annuler</button></span>
        </div>
      {/if}
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Écrit par carnet tout seul</h2>
      <p class="discret">Ce que la synchronisation a écrit sans te demander (fêtes, mariages, décès, naissances), avec la valeur d'avant. « Défaire » la remet.</p>
      {#if !auto.journal.length}
        <p class="discret">Rien encore.</p>
      {:else}
        <ul class="journal">
          {#each auto.journal as x (x.id)}
            <li class:defaite={x.defaite}>
              <span><span class="discret">{jour(x.le)} · {SERVICES_ECRITS[x.service] || x.service}</span> {x.nom} — {x.texte}{x.defaite ? ' (défait)' : ''}</span>
              {#if !x.defaite}<button class="bouton petit" disabled={attente} onclick={() => defaire(x)}>Défaire</button>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Exceptions</h2>
      <p class="discret">Les manques déclarés « normal pour ce contact » sur une fiche. Retirer une exception fait de nouveau signaler le manque.</p>
      {#if !exceptions?.length}
        <p class="discret">Aucune exception.</p>
      {:else}
        <ul class="journal">
          {#each exceptions as x (x.uid + x.info)}
            <li><span><a href={'#/contacts/' + encodeURIComponent(x.uid)}>{x.nom}</a> <span class="discret">— {x.libelle}</span></span>
              <button class="bouton petit" onclick={() => retirerException(x)}>Retirer</button></li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Journal</h2>
      <ol class="journal lignes">
        {#each e.journal as j}<li><span><span class="discret">{date(j.le)}</span> {j.message}</span></li>{/each}
      </ol>
    </div>

    <p class="pied discret"><span>carnet {e.version}</span> <button class="bouton" onclick={deconnecter}>Se déconnecter</button></p>
  {/if}
</section>

<style>
  .page { display: grid; gap: 1rem; max-width: 46rem; }
  h1 { font-size: 1.9rem; }
  h2 { font-size: 1.2rem; }
  .bloc { padding: 1rem; display: grid; gap: 0.7rem; }
  .bloc a { text-decoration: underline; text-underline-offset: 3px; }
  dl { display: grid; grid-template-columns: minmax(7rem, auto) 1fr; gap: 0.3rem 1rem; }
  dt { color: var(--color-mine); }
  .boutons { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .alerte { color: var(--color-alerte); }
  .journal { display: grid; font-size: 0.92rem; max-height: 22rem; overflow-y: auto; }
  .journal li { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; padding: 0.4rem 0; border-top: 1px solid var(--color-couture); }
  .journal li.defaite { color: var(--color-champ); }
  .petit { min-height: 2rem; padding: 0 0.7rem; font-size: 0.82rem; flex: none; }
  .zero { display: grid; gap: 0.5rem; padding: 0.75rem; border: 1px solid color-mix(in srgb, var(--color-alerte) 50%, transparent); border-radius: 8px; }
  .rangee { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .rangee input { flex: 1; min-width: 12rem; }
  .champ { display: grid; gap: 0.3rem; }
  .champ > span { color: var(--color-mine); font-size: 0.9rem; }
  .champ input, .champ select { max-width: 100%; min-width: 0; }
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
  .diff { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.9rem; }
  .diff th, .diff td { padding: 0.35rem 0.3rem; text-align: left; overflow-wrap: anywhere; border-top: 1px solid var(--color-couture); }
  .diff thead th { color: var(--color-mine); font-weight: 500; border-top: 0; }
  @media (prefers-reduced-motion: reduce) { .bascule input, .bascule input::after { transition: none; } }
  .pied { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
</style>
