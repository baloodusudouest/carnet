<script>
  import { api } from '../lib/api.js'
  import { ref, annoncer, aller } from '../lib/etat.svelte.js'
  import { pluriel } from '../lib/cles.js'

  // Contrôles sur les contacts déjà vérifiés. Les corrections faites ici sont enregistrées
  // directement dans la fiche validée.
  const SECTIONS = [
    { cle: 'anniversaires', titre: 'Famille et amis sans anniversaire',
      aide: 'Saisis la date : 15/03/1985, 15 mars 1985, ou 15 mars si l’année est inconnue.' },
    { cle: 'societes', titre: 'Collègues et clients sans société',
      aide: 'Rajoute le nom de la société. Une proposition est faite d’après l’adresse e-mail professionnelle.' },
    { cle: 'travail_a_classer', titre: 'Ancien groupe Travail à classer',
      aide: 'Le groupe Travail est remplacé par Collègues et Clients.' },
    { cle: 'urgence_sans_mobile', titre: 'Urgence sans mobile',
      aide: 'Un contact d’urgence doit pouvoir être appelé sur un mobile.' },
    { cle: 'sans_groupe', titre: 'Sans aucun groupe', aide: 'Clique sur les groupes à ajouter.' },
    { cle: 'numeros_non_reconnus', titre: 'Numéros non reconnus',
      aide: 'Numéros que carnet n’a pas pu mettre au format international : ouvre la fiche pour les corriger.' },
    { cle: 'injoignables', titre: 'Sans téléphone ni courriel', aide: 'Ces fiches ne permettent de joindre personne.' },
  ]

  let revue = $state(null)
  let saisies = $state({})      // société saisie ou proposée, par contact
  let annifs = $state({})       // anniversaire saisi, par contact
  let occupe = $state(null)

  async function charger() {
    revue = await api.get('/api/revue')
    for (const p of revue.societes) if (!(p.id in saisies)) saisies[p.id] = p.proposition
  }
  charger()

  async function retoucher(p, corps, message) {
    occupe = p.id
    try {
      await api.post(`/api/personnes/${p.id}/retoucher`, corps)
      annoncer(message)
      delete saisies[p.id]
      delete annifs[p.id]
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = null
    }
  }

  function touche(e, action) {
    if (e.key === 'Enter') { e.preventDefault(); action() }
  }

  const total = $derived(revue ? SECTIONS.reduce((n, s) => n + revue[s.cle].length, 0) : 0)
</script>

<div class="flex flex-wrap items-end gap-4 mb-6">
  <div>
    <h1 class="titre text-3xl">Revue des contacts vérifiés</h1>
    <p class="text-mine text-sm">{revue ? (total ? `${pluriel(total, 'point', 'points')} à compléter` : 'Tout est complet.') : ''}</p>
  </div>
</div>

{#if revue}
  <div class="flex gap-8">
    <!-- Sommaire, façon onglets de carnet -->
    <nav class="sticky top-6 self-start w-72 shrink-0 hidden lg:flex flex-col gap-0.5" aria-label="Sections">
      {#each SECTIONS as s}
        {@const n = revue[s.cle].length}
        <a href={`#/revue`} onclick={(e) => { e.preventDefault(); document.getElementById(s.cle)?.scrollIntoView({ behavior: 'smooth' }) }}
          class="flex items-center gap-2 px-3 py-1.5 rounded-l-md text-sm {n ? 'text-papier hover:bg-couture' : 'text-mine/60'}">
          <span class="flex-1 truncate">{s.titre}</span>
          <span class="tabular-nums text-xs rounded-full px-1.5 {n ? 'bg-onglet text-onglet-sombre font-semibold' : ''}">{n}</span>
        </a>
      {/each}
    </nav>

    <div class="flex-1 min-w-0 space-y-8">
      {#each SECTIONS as s}
        {@const liste = revue[s.cle]}
        <section id={s.cle} class="scroll-mt-6">
          <h2 class="titre text-xl">{s.titre} <span class="text-mine text-base font-normal tabular-nums">({liste.length})</span></h2>
          <p class="text-sm text-mine mb-2">{liste.length ? s.aide : 'Rien à signaler.'}</p>
          {#if liste.length}
            <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
              {#each liste as p (p.id)}
                <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 {occupe === p.id ? 'opacity-60' : ''}">
                  <div class="w-56 min-w-0">
                    <a href={`#/revision/${p.id}`} class="block truncate hover:text-onglet" title="Ouvrir la fiche">{p.nom}</a>
                    <span class="block text-xs text-mine truncate">{[p.courriel, p.telephone].filter(Boolean).join(', ') || p.groupes.join(', ')}</span>
                  </div>

                  {#if s.cle === 'anniversaires'}
                    <input class="w-44" placeholder="15/03/1985 ou 15 mars" bind:value={annifs[p.id]}
                      aria-label={`Anniversaire de ${p.nom}`}
                      onkeydown={(e) => touche(e, () => retoucher(p, { anniversaire: annifs[p.id] ?? '' }, `Anniversaire de ${p.nom} enregistré.`))} />
                    <button class="bouton !py-1" disabled={!annifs[p.id] || occupe === p.id}
                      onclick={() => retoucher(p, { anniversaire: annifs[p.id] }, `Anniversaire de ${p.nom} enregistré.`)}>Enregistrer</button>

                  {:else if s.cle === 'societes'}
                    <input class="w-64" placeholder="Nom de la société" bind:value={saisies[p.id]}
                      aria-label={`Société de ${p.nom}`}
                      onkeydown={(e) => touche(e, () => retoucher(p, { societe: saisies[p.id] ?? '' }, `Société de ${p.nom} enregistrée.`))} />
                    <button class="bouton !py-1" disabled={!saisies[p.id] || occupe === p.id}
                      onclick={() => retoucher(p, { societe: saisies[p.id] }, `Société de ${p.nom} enregistrée.`)}>Enregistrer</button>
                    {#if p.proposition}<span class="text-xs text-mine">proposition {p.origine}</span>{/if}

                  {:else if s.cle === 'travail_a_classer'}
                    {#if p.societe}<span class="text-sm text-mine">{p.societe}</span>{/if}
                    <span class="ml-auto flex gap-2">
                      <button class="bouton !py-1" disabled={occupe === p.id}
                        onclick={() => retoucher(p, { ajouter: ['Collègues'], retirer: ['Travail'] }, `${p.nom} classé dans Collègues.`)}>Collègue</button>
                      <button class="bouton !py-1" disabled={occupe === p.id}
                        onclick={() => retoucher(p, { ajouter: ['Clients'], retirer: ['Travail'] }, `${p.nom} classé dans Clients.`)}>Client</button>
                    </span>

                  {:else if s.cle === 'sans_groupe'}
                    <span class="flex flex-wrap gap-1">
                      {#each ref.groupes as g}
                        <button class="text-xs rounded-full px-2 py-0.5 border border-tranche text-mine hover:text-papier hover:border-mine"
                          disabled={occupe === p.id}
                          onclick={() => retoucher(p, { ajouter: [g] }, `${p.nom} ajouté à ${g}.`)}>{g}</button>
                      {/each}
                    </span>

                  {:else}
                    {#if p.numeros}<span class="text-sm text-onglet">{p.numeros.join(', ')}</span>{/if}
                    <a class="bouton !py-1 ml-auto" href={`#/revision/${p.id}`}>Ouvrir la fiche</a>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/each}
    </div>
  </div>
{/if}
