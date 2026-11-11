<script>
  // Réglages (2.9) : la nuit, l'analyse globale, ce que carnet a écrit tout seul, les exceptions,
  // le journal et la session. Les services et les attentes par groupe sont dans Connexion.
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
  async function deconnecter() { await api.post('/api/deconnexion'); etat.connecte = false }
  const SERVICES_ECRITS = { icloud: 'iCloud', treemich: 'Treemich', immich: 'Immich' }
  onMount(charger)
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
  .pied { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
</style>
