<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { etat, erreur, rafraichirAccueil } from '../lib/etat.svelte.js'
  import Point from '../components/Point.svelte'

  let points = $state(null)
  let filtre = $state(null)
  let choisi = $state(null)   // PC : point affiché à droite

  const familles = [
    { nom: 'iPhone', motifs: ['iphone_modifiee', 'iphone_nouvelle', 'iphone_supprimee', 'conflit'] },
    { nom: 'Doublons', motifs: ['doublon'] },
    { nom: 'Liaisons', motifs: ['liaison', 'date', 'nom', 'relations'] },
    { nom: 'Mise en forme', motifs: ['forme', 'emoji'] },
    { nom: 'Imports', motifs: ['import', 'linkedin'] },
  ]
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
          <button class="pastille" aria-pressed={filtre === f} onclick={() => (filtre = f)}>
            {f.nom} ({points.filter((p) => f.motifs.includes(p.motif)).length})
          </button>
        {/each}
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
  .vide { padding: 3rem 0; }
  .vide .titre { font-size: 1.4rem; margin-bottom: 0.3rem; }
</style>
