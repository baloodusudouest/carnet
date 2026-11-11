<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { aller, etat, erreur, dire, rafraichirAccueil } from '../lib/etat.svelte.js'
  import Point from '../components/Point.svelte'
  import { ICONES_TUILES } from '../lib/icones.js'

  let points = $state(null)
  let choisi = $state(null)   // PC : point affiché à droite
  // Manques (2.8) : des informations attendues et absentes. Ce ne sont pas des décisions : ils ne
  // comptent pas dans le compteur de l'onglet, et chaque ligne mène à la liste des fiches.
  let manques = $state(null)
  function ouvrirManque(cle) { etat.manque = cle; aller('contacts') }

  // 2.9 : une tuile par type de chose à traiter ; toucher une tuile ouvre sa liste
  let tuiles = $state([])
  let tuile = $state(null)    // clé de la tuile ouverte, ou null : la grille
  // Actions groupées : seulement dans une tuile, avec une seule réponse possible pour tous
  const LOTS = {
    reseaux: [{ action: 'lier', libelle: 'Tout lier' }, { action: 'ignorer', libelle: 'Tout ignorer' }],
    forme: [{ action: 'appliquer', libelle: 'Tout appliquer' }, { action: 'ignorer', libelle: 'Tout ignorer' }],
    immich: [{ action: 'ignorer', libelle: 'Tout ignorer' }],
    imports: [{ action: 'ignorer', libelle: 'Tout ignorer' }],
  }
  const AIDES = {
    icloud: 'Fiches modifiées, créées ou supprimées sur l\'iPhone, et conflits d\'écriture.',
    immich: 'Liaisons proposées, noms et dates de naissance qui diffèrent d\'Immich.',
    treemich: 'Mariages, décès, noms, naissances et liens familiaux qui diffèrent de l\'arbre.',
  }
  function ouvrir(t) {
    if (t.cle === 'sans_groupe') { etat.manque = 'sans_groupe'; aller('contacts'); return }
    tuile = t.cle; aConfirmer = null; choisi = null
  }
  const ouverte = $derived(tuiles.find((t) => t.cle === tuile))
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
  const visibles = $derived(points && tuile ? points.filter((p) => p.tuile === tuile) : [])

  async function charger() {
    try { points = await api.get('/api/a-traiter') } catch (e) { erreur(e) }
    try { manques = await api.get('/api/manques') } catch { manques = null }
    try { tuiles = await api.get('/api/a-traiter-tuiles') } catch { tuiles = [] }
  }
  const affiche = $derived(visibles.find((p) => p.id === choisi) || visibles[0])
  function traite(p) {
    const i = visibles.findIndex((x) => x.id === p.id)
    points = points.filter((x) => x.id !== p.id)
    choisi = visibles[Math.min(i, visibles.length - 1)]?.id ?? null   // PC : le suivant s'affiche
    tuiles = tuiles.map((t) => t.cle === p.tuile ? { ...t, nombre: Math.max(0, t.nombre - 1) } : t)
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
  {:else if !tuile}
    {#if !tuiles.some((t) => t.nombre)}
      <div class="vide">
        <p class="titre">Rien à traiter.</p>
        <p class="discret">Les changements faits sur l'iPhone, les différences avec Immich et Treemich, les doublons et les fiches incomplètes arriveront ici.</p>
      </div>
    {:else}
      <nav class="tuiles" aria-label="Types de choses à traiter">
        {#each tuiles.filter((t) => t.nombre) as t (t.cle)}
          <button class="tuile" class:secondaire={!t.compte} onclick={() => ouvrir(t)}>
            <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7"
                 stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html ICONES_TUILES[t.cle] || ''}</svg>
            <span class="chiffre">{t.nombre}</span>
            <span class="nom-tuile">{t.nom}</span>
          </button>
        {/each}
      </nav>
      <p class="discret">Le chiffre de l'onglet compte ce qui attend une décision. « Contact incomplet » n'en fait pas partie : ce sont des informations à compléter, à ton rythme.</p>
    {/if}
  {:else}
    <div class="retour-tuiles">
      <button class="bouton" onclick={() => { tuile = null; aConfirmer = null; charger() }}>‹ Toutes les tuiles</button>
      <h2 class="titre">{ouverte?.nom} <span class="discret">{ouverte?.nombre ?? ''}</span></h2>
    </div>
    {#if AIDES[tuile]}<p class="discret">{AIDES[tuile]}</p>{/if}
    {#if tuile === 'incomplet'}
      <div class="manques feuille">
        <p class="discret">Ce que les groupes attendent et qui n'est pas sur la fiche. Rien à décider ici : chaque ligne ouvre la liste des fiches. Les attentes se règlent dans <a href="#/connexion">Connexion</a>, icône Attentes.</p>
        <ul>
          {#each manques.lignes as l (l.cle)}
            <li>
              <button class="ligne-manque" onclick={() => ouvrirManque(l.cle)}><span>{l.libelle}</span><span class="nombre">{l.nombre}</span></button>
              {#if l.cle === 'photo'}<a class="bouton" href="#/photos">Traiter dans Photos</a>{/if}
            </li>
          {/each}
        </ul>
      </div>
    {:else if !visibles.length}
      <p class="discret">Plus rien dans cette tuile.</p>
    {:else}
    {#if LOTS[tuile] && visibles.length > 1}
      <div class="lot">
        {#if aConfirmer}
          <span class="discret annonce" role="status">{aConfirmer.libelle} : {annonce(aConfirmer.apercu)}</span>
          <button class="bouton bouton-principal" disabled={lotEnCours || (aConfirmer.apercu.ecrit && aConfirmer.apercu.lecture_seule)}
                  onclick={() => lot(aConfirmer.action)}>Confirmer</button>
          <button class="bouton" onclick={() => (aConfirmer = null)}>Annuler</button>
        {:else}
          {#each LOTS[tuile] as l}
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
  {/if}
</section>

<style>
  .tuiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.6rem; margin-bottom: 0.9rem; }
  .tuile { display: grid; gap: 0.15rem; justify-items: start; text-align: left; padding: 0.9rem 1rem; border-radius: 12px;
    border: 1px solid var(--color-couture); background: var(--color-reliure); color: var(--color-papier); }
  .tuile:hover { border-color: var(--color-onglet); }
  .tuile svg { color: var(--color-onglet); }
  .tuile.secondaire svg { color: var(--color-mine); }
  .tuile.secondaire { background: transparent; }
  .chiffre { font-size: 1.9rem; font-weight: 300; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; line-height: 1.15; }
  .nom-tuile { color: var(--color-mine); font-size: 0.9rem; }
  .retour-tuiles { display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap; }
  .retour-tuiles h2 { font-size: 1.25rem; }
  @media (min-width: 900px) { .tuiles { grid-template-columns: repeat(4, minmax(0, 1fr)); max-width: 60rem; } }
  .manques { padding: 1rem; display: grid; gap: 0.75rem; max-width: 40rem; }
  .manques ul { display: grid; }
  .manques li { display: flex; align-items: center; gap: 0.6rem; border-top: 1px solid var(--color-couture); }
  .ligne-manque { flex: 1; display: flex; justify-content: space-between; align-items: center; gap: 1rem; min-height: 3rem; text-align: left; }
  .ligne-manque:hover span:first-child { text-decoration: underline; text-underline-offset: 3px; }
  .ligne-manque .nombre { font-variant-numeric: tabular-nums; font-weight: 600; }
  .manques a:not(.bouton) { text-decoration: underline; text-underline-offset: 3px; }
  .page { max-width: 46rem; }
  .page:has(.deux-volets) { max-width: none; }
  .deux-volets { display: grid; grid-template-columns: minmax(18rem, 24rem) minmax(0, 46rem); gap: 1.5rem; align-items: start; }
  .sommaire { position: sticky; top: 1rem; max-height: calc(100dvh - 9rem); overflow-y: auto; display: grid; gap: 2px; }
  .sommaire button { width: 100%; display: grid; text-align: left; padding: 0.5rem 0.75rem; border-radius: 8px; }
  .sommaire button:hover { background: var(--color-reliure); }
  .sommaire button[aria-current] { background: var(--color-reliure); box-shadow: inset 3px 0 0 var(--color-onglet); }
  .sommaire .titre { font-size: 0.95rem; }
  .sommaire .motif { color: var(--color-mine); font-size: 0.82rem; }
  .detail { position: sticky; top: 1rem; }
  h1 { font-size: 2.1rem; line-height: 1.1; margin-bottom: 1rem; }
  .filtres { display: flex; gap: 0.4rem; overflow-x: auto; padding-bottom: 0.4rem; margin-bottom: 0.75rem; scrollbar-width: none; }
  .filtres .pastille { flex: none; }
  .liste { display: grid; gap: 0.75rem; }
  .annonce { flex-basis: 100%; }
  .lot { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
  .vide { padding: 3rem 0; }
  .vide .titre { font-size: 1.3rem; font-weight: 500; margin-bottom: 0.3rem; }
</style>
