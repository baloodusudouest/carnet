<script>
  // 2.33 : « Fiche complète » pour les journaux (Gazette, La Récidive) — toutes les rubriques en amorces repliables,
  // des suggestions à toucher, une ligne « vrac » rangée par mots-clés (côté carnet, sans IA), une jauge en nombre
  // de pépites (5, 15, 30) et les sujets interdits masqués. Chaque détail est une pépite écrite une par une, avec
  // son `le` : si Gazette l'a changée entre-temps, carnet répond 409 et la fiche est relue. Même logique dans Gazette.
  // Ce que carnet sait déjà (métier, conjoint, enfants, animaux, alimentation) et les anciennes Récidives sont
  // proposés en gris : rien n'est recopié tant que « Ajouter » n'est pas touché. Reste dans carnet : jamais dans iCloud.
  import { api } from '../lib/api.js'
  import { dire, erreur } from '../lib/etat.svelte.js'
  import { SUGGESTIONS } from '../lib/suggestions_journaux.js'

  let { uid } = $props()
  let fiche = $state(null)
  let echec = $state('')
  let attente = $state(false)
  let vrac = $state('')
  let rangee = $state(null)            // dernière pépite du vrac : « rangée dans … », modifiable
  let saisies = $state({})             // rubrique → texte en cours
  let edition = $state(null)           // { id, texte }
  let voirInterdits = $state(false)

  const chemin = $derived(`/api/contacts/${encodeURIComponent(uid)}/fiche-journaux`)
  const PALIERS = [[5, 'de quoi rire'], [15, 'bien fournie'], [30, 'inépuisable']]
  const SOURCES = { carnet: 'carnet', recidive: 'Récidive', sillage: 'Sillage' }

  async function charger() {
    try {
      fiche = await api.get(chemin)
      echec = ''
    } catch (err) { echec = err.message }
  }
  $effect(() => { if (uid) charger() })

  const familles = $derived(fiche?.rubriques?.familles ?? [])
  const interditCle = $derived(fiche?.rubriques?.interdits?.cle ?? 'interdits')
  const titres = $derived(Object.fromEntries([
    ...familles.flatMap((f) => f.rubriques.map((r) => [r.cle, r.titre])),
    [interditCle, fiche?.rubriques?.interdits?.titre ?? 'Sujets interdits'],
  ]))
  const pepites = $derived(fiche?.pepites ?? [])
  const interdits = $derived(pepites.filter((p) => p.interdit))
  const nombre = $derived(fiche?.jauge?.nombre ?? 0)
  function dans(cle) { return pepites.filter((p) => !p.interdit && p.rubrique === cle) }
  const plier = (t) => (t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim()
  // suggestions génériques déjà devenues pépites dans la rubrique : plus proposées
  function exemples(cle) { const deja = new Set(pepites.filter((p) => p.rubrique === cle).map((p) => plier(p.texte))); return (SUGGESTIONS[cle] ?? []).filter((s) => !deja.has(plier(s))) }
  function proposees(cle) { return (fiche?.suggestions ?? []).filter((s) => s.rubrique === cle) }
  function compte(f) { return f.rubriques.reduce((n, r) => n + dans(r.cle).length, 0) }
  function dateLisible(v) { return v ? `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}` : '' }

  // Écriture refusée parce que la fiche a bougé (409 : changée ailleurs, 404 : effacée) : on relit.
  async function rate(err) {
    erreur(err)
    if (err?.statut === 409 || err?.statut === 404) await charger()
  }

  async function ajouter(rubrique, texte, source = 'julien') {
    texte = (texte || '').trim()
    if (!texte) return null
    attente = true
    try {
      const p = await api.post(`${chemin}/pepites`, { rubrique, texte, source })
      dire(p.deja ? 'Déjà dans la fiche.' : `Ajouté dans « ${titres[p.rubrique] ?? p.rubrique} ».`)
      await charger()
      return p
    } catch (err) { await rate(err); return null } finally { attente = false }
  }
  async function ajouterSaisie(cle) {
    if (await ajouter(cle, saisies[cle])) saisies[cle] = ''
  }
  async function ajouterVrac() {
    const p = await ajouter('vrac', vrac)
    if (p) { vrac = ''; rangee = p }
  }
  async function deplacer(p, rubrique) {
    if (!rubrique || rubrique === p.rubrique) return
    attente = true
    try {
      const n = await api.put(`${chemin}/pepites/${encodeURIComponent(p.id)}`, { le: p.le, rubrique })
      if (rangee?.id === p.id) rangee = n
      dire(`Déplacé dans « ${titres[n.rubrique] ?? n.rubrique} ».`)
      await charger()
    } catch (err) { await rate(err) } finally { attente = false }
  }
  async function enregistrer(p) {
    attente = true
    try {
      await api.put(`${chemin}/pepites/${encodeURIComponent(p.id)}`, { le: p.le, texte: edition.texte })
      edition = null
      await charger()
    } catch (err) { await rate(err) } finally { attente = false }
  }
  async function effacer(p) {
    if (!confirm(`Effacer « ${p.texte} » ?`)) return
    attente = true
    try {
      await api.effacer(`${chemin}/pepites/${encodeURIComponent(p.id)}`, { le: p.le })
      if (rangee?.id === p.id) rangee = null
      await charger()
    } catch (err) { await rate(err) } finally { attente = false }
  }
</script>

{#snippet choixRubrique(p)}
  <select class="deplacer" aria-label="Déplacer dans une autre rubrique" disabled={attente} value={p.rubrique}
          onchange={(ev) => deplacer(p, ev.currentTarget.value)}>
    {#each familles as f}
      <optgroup label={f.titre}>{#each f.rubriques as r}<option value={r.cle}>{r.titre}</option>{/each}</optgroup>
    {/each}
    <option value={interditCle}>{titres[interditCle]}</option>
  </select>
{/snippet}

{#snippet pepite(p)}
  <li class="pepite">
    {#if edition?.id === p.id}
      <form class="ligne" onsubmit={(ev) => { ev.preventDefault(); enregistrer(p) }}>
        <input type="text" maxlength="200" bind:value={edition.texte} aria-label="Texte de la pépite" />
        <button type="submit" class="bouton bouton-principal petit" disabled={attente || !edition.texte.trim()}>OK</button>
        <button type="button" class="bouton petit" onclick={() => (edition = null)}>Annuler</button>
      </form>
    {:else}
      <span class="texte">{p.texte}</span>
      {#if SOURCES[p.source]}<span class="marque">{SOURCES[p.source]}</span>{/if}
      {#if p.parue_le}<span class="marque parue" title="Déjà utilisée dans un numéro approuvé">parue le {dateLisible(p.parue_le)}</span>{/if}
      <span class="actions">
        <button class="bouton petit" disabled={attente} onclick={() => (edition = { id: p.id, texte: p.texte })}>Modifier</button>
        {@render choixRubrique(p)}
        <button class="bouton bouton-danger petit" disabled={attente} onclick={() => effacer(p)} aria-label="Effacer">Effacer</button>
      </span>
    {/if}
  </li>
{/snippet}

<section class="fiche-journaux" aria-label="Fiche complète pour les journaux">
  {#if echec && !fiche}
    <p class="discret">Fiche complète illisible : {echec}</p>
    <button class="bouton" onclick={charger}>Réessayer</button>
  {:else if !fiche}
    <p class="discret">Lecture de la fiche…</p>
  {:else}
    <!-- Jauge : un nombre de pépites et des paliers, pas un pourcentage -->
    <div class="jauge" aria-label="Jauge de la fiche">
      <p><b>{nombre} pépite{nombre > 1 ? 's' : ''}</b>{fiche.jauge.palier ? ` · ${fiche.jauge.palier}` : ''}
        {#if fiche.jauge.prochain}<span class="discret petit"> — encore {fiche.jauge.prochain - nombre} pour « {PALIERS.find(([s]) => s === fiche.jauge.prochain)?.[1]} »</span>{/if}</p>
      <div class="barre" aria-hidden="true">
        <span class="plein" style:width="{Math.min(nombre, 30) / 30 * 100}%"></span>
        {#each PALIERS as [s]}<span class="cran" class:atteint={nombre >= s} style:left="{s / 30 * 100}%"></span>{/each}
      </div>
    </div>

    <!-- Vrac : texte libre, rangé dans la rubrique la plus probable (modifiable juste après) -->
    <form class="ligne vrac" onsubmit={(ev) => { ev.preventDefault(); ajouterVrac() }}>
      <input type="text" maxlength="200" placeholder="En vrac : un détail, carnet le range" bind:value={vrac} aria-label="Détail en vrac" />
      <button type="submit" class="bouton bouton-principal" disabled={attente || !vrac.trim()}>Ranger</button>
    </form>
    {#if rangee}
      <p class="petit rangee">« {rangee.texte} » rangé dans <b>{titres[rangee.rubrique] ?? rangee.rubrique}</b>.
        <span class="discret">Pas là ?</span> {@render choixRubrique(rangee)}</p>
    {/if}

    {#each familles as f (f.cle)}
      <details class="famille">
        <summary><span class="titre">{f.titre}</span> <span class="discret petit">{compte(f) || ''}</span></summary>
        {#each f.rubriques as r (r.cle)}
          {@const liste = dans(r.cle)}
          {@const carnet = proposees(r.cle)}
          <details class="rubrique">
            <summary>{r.titre} {#if liste.length}<span class="nombre">{liste.length}</span>{/if}
              {#if carnet.length}<span class="discret petit">· {carnet.length} à valider</span>{/if}</summary>
            {#if liste.length}<ul class="pepites">{#each liste as p (p.id)}{@render pepite(p)}{/each}</ul>{/if}
            {#if carnet.length}
              <ul class="proposees">
                {#each carnet as s}
                  <li><span class="texte">{s.texte}</span> <span class="marque">{SOURCES[s.source] ?? s.source}</span>
                    <button class="bouton petit" disabled={attente} onclick={() => ajouter(s.rubrique, s.texte, s.source)}>Ajouter</button></li>
                {/each}
              </ul>
            {/if}
            {#if exemples(r.cle).length}
              <div class="suggestions" role="group" aria-label="Suggestions">
                {#each exemples(r.cle) as s}
                  <button type="button" class="pastille petit" onclick={() => (saisies[r.cle] = s)}>{s}</button>
                {/each}
              </div>
            {/if}
            <form class="ligne" onsubmit={(ev) => { ev.preventDefault(); ajouterSaisie(r.cle) }}>
              <input type="text" maxlength="200" placeholder="Un détail…" bind:value={saisies[r.cle]} aria-label={`Ajouter dans ${r.titre}`} />
              <button type="submit" class="bouton" disabled={attente || !(saisies[r.cle] || '').trim()}>Ajouter</button>
            </form>
          </details>
        {/each}
      </details>
    {/each}

    <!-- Sujets interdits : jamais envoyés à l'IA par Gazette ; masqués par défaut -->
    <div class="interdits">
      <div class="ligne-titre">
        <h3 class="titre">{titres[interditCle]} <span class="discret petit">({interdits.length})</span></h3>
        <button class="bouton petit" aria-expanded={voirInterdits} onclick={() => (voirInterdits = !voirInterdits)}>{voirInterdits ? 'Masquer' : 'Afficher'}</button>
      </div>
      <p class="discret petit">Jamais envoyés à l'IA ; une proposition qui en parle est écartée. Un détail à ne pas utiliser se déplace ici.</p>
      {#if voirInterdits}
        {#if interdits.length}<ul class="pepites">{#each interdits as p (p.id)}{@render pepite(p)}{/each}</ul>{/if}
        <form class="ligne" onsubmit={(ev) => { ev.preventDefault(); ajouterSaisie(interditCle) }}>
          <input type="text" maxlength="200" placeholder="Un sujet à ne jamais aborder" bind:value={saisies[interditCle]} aria-label="Ajouter un sujet interdit" />
          <button type="submit" class="bouton" disabled={attente || !(saisies[interditCle] || '').trim()}>Ajouter</button>
        </form>
      {/if}
    </div>
  {/if}
</section>

<style>
  .fiche-journaux { display: grid; gap: 0.7rem; margin-top: 0.8rem; }
  .jauge p { margin: 0 0 0.35rem; }
  .barre { position: relative; height: 0.45rem; border-radius: 999px; background: var(--color-couture); }
  .plein { position: absolute; inset: 0 auto 0 0; border-radius: 999px; background: var(--color-onglet); }
  .cran { position: absolute; top: -0.2rem; width: 2px; height: 0.85rem; margin-left: -1px; background: var(--color-tranche); }
  .cran.atteint { background: var(--color-valide); }
  .ligne { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
  .ligne input { flex: 1 1 12rem; min-width: 0; }
  .rangee { margin: 0; overflow-wrap: anywhere; }
  .famille { border-top: 1px solid var(--color-couture); padding-top: 0.5rem; }
  .famille > summary { cursor: pointer; padding: 0.35rem 0; }
  .rubrique { margin: 0.2rem 0 0.2rem 0.6rem; padding: 0.3rem 0 0.3rem 0.6rem; border-left: 2px solid var(--color-couture); }
  .rubrique[open] { border-left-color: var(--color-tranche); }
  .rubrique > summary { cursor: pointer; padding: 0.3rem 0; }
  .rubrique > * + * { margin-top: 0.5rem; }
  .nombre { display: inline-block; min-width: 1.4rem; padding: 0 0.35rem; border-radius: 999px; text-align: center;
            font-size: 0.8rem; background: var(--color-reliure); color: var(--color-onglet); }
  .pepites, .proposees { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.4rem; }
  .pepite { display: flex; flex-wrap: wrap; gap: 0.35rem 0.5rem; align-items: center; }
  .pepite .texte { flex: 1 1 12rem; overflow-wrap: anywhere; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }
  .marque { font-size: 0.75rem; padding: 0.05rem 0.4rem; border-radius: 999px; border: 1px solid var(--color-couture); color: var(--color-mine); }
  .parue { border-color: color-mix(in srgb, var(--color-valide) 50%, transparent); }
  .proposees li { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; color: var(--color-mine); font-style: italic; }
  .proposees .bouton { font-style: normal; }
  .suggestions { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .deplacer { max-width: 11rem; }
  .interdits { border-top: 1px solid var(--color-couture); padding-top: 0.6rem; }
  .interdits h3 { font-size: 0.95rem; margin: 0; }
  .interdits p { margin: 0.3rem 0; }
</style>
