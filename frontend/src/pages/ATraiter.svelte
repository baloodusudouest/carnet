<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { etat, erreur, dire, rafraichirAccueil } from '../lib/etat.svelte.js'
  import Point from '../components/Point.svelte'

  let points = $state(null)
  let filtre = $state(null)
  let choisi = $state(null)   // PC : point affiché à droite

  const familles = [
    { nom: 'iPhone', motifs: ['iphone_modifiee', 'iphone_nouvelle', 'iphone_supprimee', 'conflit'] },
    { nom: 'Doublons', motifs: ['doublon'] },
    { nom: 'Liaisons', motifs: ['liaison', 'date', 'nom', 'relations'] },
    { nom: 'Mise en forme', motifs: ['forme', 'emoji'] },
    { nom: 'Réseaux', motifs: ['reseau'] },
    { nom: 'Imports', motifs: ['import', 'linkedin'] },
  ]
  // Actions groupées : seulement sur une famille filtrée, avec une seule réponse possible pour tous
  const LOTS = {
    'Réseaux': [{ action: 'lier', libelle: 'Tout lier' }, { action: 'ignorer', libelle: 'Tout ignorer' }],
    'Mise en forme': [{ action: 'appliquer', libelle: 'Tout appliquer' }, { action: 'ignorer', libelle: 'Tout ignorer' }],
    'Liaisons': [{ action: 'ignorer', libelle: 'Tout ignorer' }],
    'Imports': [{ action: 'ignorer', libelle: 'Tout ignorer' }],
  }
  let lotEnCours = $state(false)
  let aConfirmer = $state(null)   // action groupée en attente de confirmation, avec son aperçu
  // Avant « Confirmer » : carnet dit ce que le lot fera (écritures dans iCloud, plafond, lecture seule)
  async function annoncer(l) {
    try {
      const apercu = await api.post('/api/a-traiter-lot/apercu', { ids: visibles.map((p) => p.id), action: l.action })
      aConfirmer = { ...l, apercu }
    } catch (e) { erreur(e) }
  }
  function annonce(a) {
    const n = a.points
    if (!a.ecrit) return `${n} point(s) seront écartés et ne seront plus proposés. Rien n'est écrit dans iCloud.`
    if (a.lecture_seule) return `Mode lecture seule : ces ${n} écriture(s) dans iCloud seront refusées.`
    return `${a.a_ecrire} fiche(s) seront modifiées dans iCloud`
      + (a.reportes ? `, les ${a.reportes} autres attendront le lot suivant (${a.plafond} écritures au plus par lot)` : '')
      + `. Une copie d'iCloud est faite avant la première écriture du jour.`
  }
  async function lot(action) {
    const ids = visibles.map((p) => p.id)
    aConfirmer = null
    if (!ids.length) return
    lotEnCours = true
    try {
      const r = await api.post('/api/a-traiter-lot', { ids, action })
      dire(`${r.faits} point(s) traité(s)` + (r.reportes ? `, ${r.reportes} remis au prochain lot (plafond d'écritures)` : '')
           + (r.erreurs.length ? `, ${r.erreurs.length} erreur(s) : ${r.erreurs[0]}` : '') + '.')
      await charger(); rafraichirAccueil()
    } catch (e) { erreur(e) } finally { lotEnCours = false }
  }
  const presentes = $derived(familles.filter((f) => points?.some((p) => f.motifs.includes(p.motif))))
  const visibles = $derived(points ? (filtre ? points.filter((p) => filtre.motifs.includes(p.motif)) : points) : [])

  async function charger() {
    try { points = await api.get('/api/a-traiter') } catch (e) { erreur(e) }
  }
  const affiche = $derived(visibles.find((p) => p.id === choisi) || visibles[0])
  function traite(p) {
    const i = visibles.findIndex((x) => x.id === p.id)
    points = points.filter((x) => x.id !== p.id)
    choisi = visibles[Math.min(i, visibles.length - 1)]?.id ?? null   // PC : le suivant s'affiche
    rafraichirAccueil()
  }
  onMount(charger)
</script>

<section class="page">
  <h1 class="titre">À traiter</h1>
  {#if !etat.accueil?.reference && etat.accueil?.icloud}
    <p class="discret">Première lecture d'iCloud en cours : elle sert de point de départ, rien n'est signalé avant.</p>
  {/if}

  {#if points === null}
    <p class="discret">Chargement…</p>
  {:else if !points.length}
    <div class="vide">
      <p class="titre">Rien à traiter.</p>
      <p class="discret">Les fiches modifiées sur l'iPhone, les doublons et les liaisons à confirmer arriveront ici.</p>
    </div>
  {:else}
    {#if presentes.length > 1}
      <div class="filtres" role="group" aria-label="Filtrer">
        <button class="pastille" aria-pressed={!filtre} onclick={() => (filtre = null)}>Tout ({points.length})</button>
        {#each presentes as f}
          <button class="pastille" aria-pressed={filtre === f} onclick={() => { filtre = f; aConfirmer = null }}>
            {f.nom} ({points.filter((p) => f.motifs.includes(p.motif)).length})
          </button>
        {/each}
      </div>
    {/if}
    {#if filtre && LOTS[filtre.nom] && visibles.length > 1}
      <div class="lot">
        {#if aConfirmer}
          <span class="discret annonce" role="status">{aConfirmer.libelle} : {annonce(aConfirmer.apercu)}</span>
          <button class="bouton bouton-principal" disabled={lotEnCours || (aConfirmer.apercu.ecrit && aConfirmer.apercu.lecture_seule)}
                  onclick={() => lot(aConfirmer.action)}>Confirmer</button>
          <button class="bouton" onclick={() => (aConfirmer = null)}>Annuler</button>
        {:else}
          {#each LOTS[filtre.nom] as l}
            <button class="bouton" disabled={lotEnCours} onclick={() => annoncer(l)}>{l.libelle} ({visibles.length})</button>
          {/each}
        {/if}
      </div>
    {/if}
    {#if etat.large}
      <div class="deux-volets">
        <ul class="sommaire" aria-label="Points à traiter">
          {#each visibles as p (p.id)}
            <li><button aria-current={affiche?.id === p.id ? 'true' : undefined} onclick={() => (choisi = p.id)}>
              <span class="titre">{p.nom}</span><span class="motif">{p.titre}</span></button></li>
          {/each}
        </ul>
        <div class="detail">
          {#if affiche}{#key affiche.id}<Point point={affiche} ontraite={traite} />{/key}{/if}
        </div>
      </div>
    {:else}
      <div class="liste">
        {#each visibles as p (p.id)}
          <Point point={p} ontraite={traite} />
        {/each}
      </div>
    {/if}
  {/if}
</section>

<style>
  .page { max-width: 46rem; }
  .page:has(.deux-volets) { max-width: none; }
  .deux-volets { display: grid; grid-template-columns: minmax(18rem, 24rem) minmax(0, 46rem); gap: 1.5rem; align-items: start; }
  .sommaire { position: sticky; top: 1rem; max-height: calc(100dvh - 9rem); overflow-y: auto; display: grid; gap: 2px; }
  .sommaire button { width: 100%; display: grid; text-align: left; padding: 0.5rem 0.75rem; border-radius: 8px; }
  .sommaire button:hover { background: var(--color-reliure); }
  .sommaire button[aria-current] { background: var(--color-reliure); box-shadow: inset 3px 0 0 var(--color-onglet); }
  .sommaire .titre { font-size: 1rem; }
  .sommaire .motif { color: var(--color-mine); font-size: 0.82rem; }
  .detail { position: sticky; top: 1rem; }
  h1 { font-size: 1.9rem; margin-bottom: 0.75rem; }
  .filtres { display: flex; gap: 0.4rem; overflow-x: auto; padding-bottom: 0.4rem; margin-bottom: 0.75rem; scrollbar-width: none; }
  .filtres .pastille { flex: none; }
  .liste { display: grid; gap: 0.75rem; }
  .lot { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
  .vide { padding: 3rem 0; }
  .vide .titre { font-size: 1.4rem; margin-bottom: 0.3rem; }
</style>
