<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { aller, apresEcriture, erreur } from '../lib/etat.svelte.js'
  import Avatar from '../components/Avatar.svelte'
  import Editeur from '../components/Editeur.svelte'

  let { a, b } = $props()
  let prop = $state(null)
  let garder = $state(a)
  let fiche = $state(null)
  let attente = $state(false)
  let groupes = $state([])

  const resume = (f) => [f.societe, ...f.telephones.map((t) => t.affichage || t.valeur), ...f.courriels.map((c) => c.valeur),
                         f.anniversaire].filter(Boolean)

  async function reunir() {
    attente = true
    try {
      const absorber = garder === a ? b : a
      const res = await api.post('/api/fusion', { garder, absorber, fiche })
      await apresEcriture(null, 'Fiches réunies : l\'autre carte a été retirée d\'iCloud.')
      aller('contacts', garder)
    } catch (e) { erreur(e) } finally { attente = false }
  }

  onMount(async () => {
    try {
      prop = await api.get(`/api/fusion?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`)
      fiche = prop.proposee
      groupes = (await api.get('/api/groupes')).map((g) => g.nom)
    } catch (e) { erreur(e) }
  })
</script>

<section class="page">
  <a class="retour discret" href="#/a-traiter">À traiter</a>
  <h1 class="titre">Réunir deux fiches</h1>
  {#if prop}
    <div class="deux">
      {#each [prop.a, prop.b] as x}
        <label class="feuille carte" class:gardee={garder === x.uid}>
          <input type="radio" name="garder" value={x.uid} bind:group={garder} />
          <Avatar uid={x.uid} nom={x.nom} photo={x.fiche.a_photo} />
          <span class="texte"><span class="titre">{x.nom}</span>
            <span class="discret">{resume(x.fiche).join(', ')}</span>
            <span class="role">{garder === x.uid ? 'Carte gardée' : 'Carte retirée d\'iCloud'}</span></span>
        </label>
      {/each}
    </div>
    <p class="discret">La fiche gardée reçoit ce qui suit. Liaisons, photo choisie, affiche et relation LinkedIn de l'autre passent sur elle.</p>
    <div class="feuille bloc"><Editeur bind:fiche groupesConnus={groupes} /></div>
    <div class="boutons">
      <a class="bouton" href="#/a-traiter">Abandonner</a>
      <button class="bouton bouton-principal" disabled={attente} onclick={reunir}>{attente ? 'Réunion…' : 'Réunir en une fiche'}</button>
    </div>
  {:else}
    <p class="discret">Chargement…</p>
  {/if}
</section>

<style>
  .page { max-width: 46rem; display: grid; gap: 1rem; }
  .retour { justify-self: start; min-height: 2.75rem; display: inline-flex; align-items: center; }
  h1 { font-size: 1.9rem; }
  .deux { display: grid; gap: 0.6rem; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }
  .carte { display: flex; gap: 0.7rem; align-items: flex-start; padding: 0.8rem; cursor: pointer; }
  .carte.gardee { border-color: var(--color-onglet); }
  .texte { display: grid; gap: 0.15rem; min-width: 0; overflow-wrap: anywhere; }
  .role { font-size: 0.85rem; color: var(--color-onglet); }
  .bloc { padding: 1rem; }
  .boutons { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
