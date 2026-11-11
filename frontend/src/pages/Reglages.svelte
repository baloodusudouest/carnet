<script>
  // Réglages (2.8) : ce que chaque groupe doit avoir, ce que carnet écrit tout seul, les exceptions.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'

  let tableau = $state(null)
  let auto = $state(null)
  let exceptions = $state(null)
  let enAttente = $state(null)   // case en cours de confirmation : { groupe, info, attendue, apercu }
  let attente = $state(false)

  async function charger() {
    try {
      [tableau, auto, exceptions] = await Promise.all([api.get('/api/attentes'), api.get('/api/automatique'), api.get('/api/exceptions')])
    } catch (e) { erreur(e) }
  }
  // Une case : carnet dit d'abord ce que ça change, puis on enregistre
  async function proposer(groupe, info, attendue) {
    try { enAttente = { groupe, info, attendue, apercu: await api.post('/api/attentes/apercu', { groupe, info, attendue }) } }
    catch (e) { erreur(e) }
  }
  async function enregistrer() {
    attente = true
    try {
      const r = await api.post('/api/attentes', { groupe: enAttente.groupe, info: enAttente.info, attendue: enAttente.attendue })
      tableau = r.tableau
      dire('Enregistré.')
      enAttente = null
      rafraichirContacts(); rafraichirAccueil()
    } catch (e) { erreur(e) } finally { attente = false }
  }
  const coche = (g, info) => enAttente?.groupe === g.nom && enAttente?.info === info ? enAttente.attendue : g.attentes.includes(info)
  const nomInfo = (cle) => tableau.infos.find((i) => i.cle === cle)?.nom

  async function basculer(quoi, actif) {
    attente = true
    try {
      await api.post(`/api/automatique/${quoi}`, { actif })
      dire(actif ? 'Allumé : carnet écrira dès la prochaine nuit.' : 'Éteint : carnet n\'écrit plus rien de lui-même pour cela.')
      auto = await api.get('/api/automatique')
    } catch (e) { erreur(e) } finally { attente = false }
  }
  async function accorder() {
    attente = true
    try {
      const r = await api.post('/api/automatique/accorder')
      dire(r.message)
      auto = await api.get('/api/automatique'); rafraichirContacts(); rafraichirAccueil()
    } catch (e) { erreur(e) } finally { attente = false }
  }
  async function defaire(x) {
    attente = true
    try {
      await api.post(`/api/automatique/defaire/${x.id}`)
      dire('Défait. L\'interrupteur correspondant est éteint, sinon carnet le réécrirait.')
      auto = await api.get('/api/automatique'); rafraichirContacts()
    } catch (e) { erreur(e) } finally { attente = false }
  }
  async function retirerException(x) {
    try {
      await api.post(`/api/contacts/${encodeURIComponent(x.uid)}/exception`, { info: x.info, oui: false })
      exceptions = await api.get('/api/exceptions'); tableau = await api.get('/api/attentes'); rafraichirContacts()
    } catch (e) { erreur(e) }
  }
  async function deconnecter() { await api.post('/api/deconnexion'); etat.connecte = false }
  const jour = (iso) => iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) : ''
  const BLOCS = [
    ['fetes', 'La fête de chaque contact dont un groupe attend la fête (colonne « Fête » du tableau) est écrite sur sa fiche iCloud, sans année. Une fête saisie à la main n\'est jamais remplacée. Home Assistant annonce les fêtes dans tous les cas.'],
    ['famille', 'Mariages et décès : carnet remplit le côté vide, entre iCloud et Treemich, et n\'écrase jamais. Deux dates différentes vont dans « À traiter ».'],
  ]
  onMount(charger)
</script>

<section class="page">
  <h1 class="titre">Réglages</h1>
  {#if !tableau || !auto}
    <p class="discret">Chargement…</p>
  {:else}
    <div class="feuille bloc attentes">
      <h2 class="titre">Ce que chaque groupe doit avoir</h2>
      <p class="discret">Une case cochée : l'information est attendue pour les contacts du groupe. Les attentes de plusieurs groupes s'additionnent.
        Aujourd'hui, {tableau.total.incompletes} fiche(s) sur {tableau.total.fiches} ont au moins un manque.</p>

      {#if enAttente}
        <div class="confirmer" role="status">
          <p><strong>{enAttente.groupe}</strong> {enAttente.attendue ? 'attendra' : 'n\'attendra plus'} « {nomInfo(enAttente.info)} » :
            « {enAttente.apercu.libelle} » passera de {enAttente.apercu.avant} à {enAttente.apercu.apres} fiche(s).</p>
          <span class="boutons">
            <button class="bouton bouton-principal" disabled={attente} onclick={enregistrer}>Enregistrer</button>
            <button class="bouton" onclick={() => (enAttente = null)}>Annuler</button></span>
        </div>
      {/if}

      {#if etat.large}
        <div class="defile">
          <table>
            <thead><tr><th scope="col">Groupe</th>{#each tableau.infos as i}<th scope="col"><span>{i.nom}</span></th>{/each}</tr></thead>
            <tbody>
              {#each tableau.groupes as g (g.nom)}
                <tr>
                  <th scope="row">{g.nom} <span class="discret">{g.nombre}</span></th>
                  {#each tableau.infos as i}
                    <td><input type="checkbox" checked={coche(g, i.cle)} aria-label={`${g.nom} : ${i.nom}`}
                               onchange={(ev) => { ev.currentTarget.checked = g.attentes.includes(i.cle); proposer(g.nom, i.cle, !g.attentes.includes(i.cle)) }} /></td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <!-- iPhone : un groupe à la fois, sa liste de cases -->
        {#each tableau.groupes as g (g.nom)}
          <details class="groupe">
            <summary><span>{g.nom} <span class="discret">{g.nombre}</span></span><span class="discret resume">{g.attentes.length ? `${g.attentes.length} attendue(s)` : 'rien'}</span></summary>
            <div class="cases">
              {#each tableau.infos as i}
                <label><input type="checkbox" checked={coche(g, i.cle)}
                              onchange={(ev) => { ev.currentTarget.checked = g.attentes.includes(i.cle); proposer(g.nom, i.cle, !g.attentes.includes(i.cle)) }} /> {i.nom}</label>
              {/each}
            </div>
          </details>
        {/each}
      {/if}
    </div>

    <div class="feuille bloc">
      <h2 class="titre">Ce que carnet écrit tout seul</h2>
      <p class="discret">Deux écritures se font sans te demander, la nuit. Elles sont éteintes tant que tu ne les allumes pas ; éteintes, carnet montre ce qu'il écrirait.</p>
      {#if auto.lecture_seule}<p class="discret" role="status">Mode lecture seule : même allumé, rien n'est écrit.</p>{/if}
      {#each BLOCS as [quoi, explication]}
        {@const b = auto[quoi]}
        <div class="interrupteur">
          <label class="bascule">
            <input type="checkbox" role="switch" checked={b.actif} disabled={attente} onchange={(ev) => basculer(quoi, ev.currentTarget.checked)} />
            <span><strong>{b.nom}</strong> <span class="etat-bascule" class:actif={b.actif}>{b.actif ? 'allumé' : 'éteint'}</span></span>
          </label>
          <p class="discret">{explication}</p>
          {#if quoi === 'famille' && !b.treemich}
            <p class="discret">Treemich n'a pas encore été relu, ou ne répond pas : rien à montrer pour l'instant.</p>
          {:else if b.actions.length}
            <details class="prevu">
              <summary>{b.actif ? 'Sera écrit la prochaine nuit' : 'Ce que carnet écrirait'} : {b.actions.length} écriture(s)</summary>
              <ul>{#each b.actions.slice(0, 60) as a}<li>{a.texte}</li>{/each}
                {#if b.actions.length > 60}<li class="discret">… et {b.actions.length - 60} autre(s), au rythme de 20 fiches par nuit.</li>{/if}</ul>
            </details>
          {:else}
            <p class="discret">Rien à écrire pour l'instant.</p>
          {/if}
          {#if quoi === 'famille'}
            {#if b.actif && b.actions.length}
              <span><button class="bouton" disabled={attente || auto.lecture_seule} onclick={accorder}>{attente ? 'Accord en cours…' : 'Accorder maintenant'}</button></span>
            {/if}
            {#if b.points}<p class="discret">{b.points} point(s) attendent ta réponse dans <a href="#/a-traiter">À traiter</a> (date manquante ou dates différentes).</p>{/if}
            {#if b.raisons?.length}
              <div class="raisons" role="status">
                <p><strong>Ce qui empêche une date de partir vers Treemich</strong></p>
                <ul>{#each b.raisons as raison}<li>{raison}</li>{/each}</ul>
              </div>
            {/if}
          {/if}
        </div>
      {/each}

      <h3 class="titre">Écrit par carnet tout seul</h3>
      {#if !auto.journal.length}
        <p class="discret">Rien encore.</p>
      {:else}
        <ul class="journal">
          {#each auto.journal as x (x.id)}
            <li class:defaite={x.defaite}>
              <span><span class="discret">{jour(x.le)} · {x.service === 'icloud' ? 'iCloud' : 'Treemich'}</span> {x.nom} — {x.texte}{x.defaite ? ' (défait)' : ''}</span>
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
      <h2 class="titre">Réseaux</h2>
      <p class="discret">Les fichiers (cartes, LinkedIn, Facebook, Instagram) se déposent par « Importer », dans Contacts. Les connexions LinkedIn et Telegram et les personnes sans fiche sont dans <a href="#/etat">État</a>, section Réseaux.</p>
    </div>

    <p class="pied discret"><span>Session ouverte sur cet appareil.</span> <button class="bouton" onclick={deconnecter}>Se déconnecter</button></p>
  {/if}
</section>

<style>
  .page { display: grid; gap: 1rem; max-width: 64rem; }
  h1 { font-size: 1.9rem; }
  h2 { font-size: 1.2rem; }
  h3 { font-size: 1rem; margin-top: 0.6rem; }
  .bloc { padding: 1rem; display: grid; gap: 0.7rem; }
  .bloc a { text-decoration: underline; text-underline-offset: 3px; }
  .defile { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
  thead th { position: sticky; top: 0; background: var(--color-cuir); vertical-align: bottom; padding: 0.35rem 0.3rem; font-weight: 600;
    color: var(--color-mine); font-size: 0.78rem; text-align: center; min-width: 4.6rem; }
  thead th:first-child, tbody th { text-align: left; min-width: 11rem; }
  tbody th { font-weight: 600; padding: 0.3rem 0.5rem 0.3rem 0; white-space: nowrap; }
  tbody tr { border-top: 1px solid var(--color-couture); }
  td { text-align: center; padding: 0.3rem; }
  input[type='checkbox'] { accent-color: var(--color-onglet); width: 1.15rem; height: 1.15rem; }
  .confirmer { position: sticky; top: calc(0.5rem + env(safe-area-inset-top)); z-index: 2; display: grid; gap: 0.5rem; padding: 0.75rem 0.9rem;
    border: 1px solid var(--color-onglet); border-radius: 10px; background: var(--color-reliure); }
  .boutons { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .groupe { border-top: 1px solid var(--color-couture); }
  .groupe summary { display: flex; justify-content: space-between; align-items: center; min-height: 3rem; cursor: pointer; font-weight: 600; }
  .groupe .resume { font-weight: 400; font-size: 0.85rem; }
  .cases { display: grid; gap: 0.1rem; padding-bottom: 0.6rem; }
  .cases label { display: flex; align-items: center; gap: 0.6rem; min-height: 2.6rem; }
  .interrupteur { display: grid; gap: 0.4rem; padding-top: 0.7rem; border-top: 1px solid var(--color-couture); }
  .bascule { display: flex; align-items: center; gap: 0.7rem; min-height: 2.75rem; }
  .bascule input { appearance: none; width: 2.9rem; height: 1.7rem; border-radius: 9999px; background: var(--color-tranche); position: relative;
    border: 0; padding: 0; flex: none; transition: background-color 0.2s ease; cursor: pointer; }
  .bascule input::after { content: ''; position: absolute; top: 3px; left: 3px; width: calc(1.7rem - 6px); height: calc(1.7rem - 6px); border-radius: 50%;
    background: var(--color-papier); transition: transform 0.2s ease; }
  .bascule input:checked { background: var(--color-onglet); }
  .bascule input:checked::after { transform: translateX(1.2rem); }
  .bascule input:focus-visible { outline: 2px solid var(--color-onglet); outline-offset: 2px; }
  .raisons { display: grid; gap: 0.35rem; padding: 0.7rem 0.9rem; border-left: 3px solid var(--color-onglet); font-size: 0.92rem; }
  .raisons ul { display: grid; gap: 0.25rem; padding-left: 1.1rem; list-style: disc; color: var(--color-mine); }
  .etat-bascule { color: var(--color-mine); font-size: 0.85rem; margin-left: 0.3rem; }
  .etat-bascule.actif { color: var(--color-onglet); }
  .prevu summary { cursor: pointer; min-height: 2.4rem; display: flex; align-items: center; }
  .prevu ul { display: grid; gap: 0.2rem; max-height: 16rem; overflow-y: auto; font-size: 0.9rem; padding: 0.3rem 0 0.3rem 0.2rem; }
  .journal { display: grid; font-size: 0.92rem; max-height: 22rem; overflow-y: auto; }
  .journal li { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; padding: 0.4rem 0; border-top: 1px solid var(--color-couture); }
  .journal li.defaite { color: var(--color-champ); }
  .petit { min-height: 2rem; padding: 0 0.7rem; font-size: 0.82rem; flex: none; }
  .pied { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  @media (prefers-reduced-motion: reduce) { .bascule input, .bascule input::after { transition: none; } }
</style>
