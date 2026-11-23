<script>
  // 3.1 : le dossier d'une personne en grosses tuiles (choix de Julien du 19/11/2026, maquette A « fiche iPhone et
  // tuiles »). Six tuiles en 2 × 3 ; toucher une tuile affiche son contenu juste dessous. Toucher la photo de la fiche
  // ouvre la tuile Photos (section = 'photos', voulue par Fiche.svelte).
  import { api } from '../lib/api.js'
  import { dire, erreur } from '../lib/etat.svelte.js'
  import Alimentation from './Alimentation.svelte'
  import FicheJournaux from './FicheJournaux.svelte'
  import PhotosFiche from './PhotosFiche.svelte'

  let { uid, donnees, section = $bindable('alimentation'), onchange = () => {}, onpropositions = () => {} } = $props()

  const f = $derived(donnees.fiche)
  const j = $derived(donnees.journaux || {})
  const a = $derived(donnees.alimentation)
  const evts = $derived(donnees.evenements || [])
  const aLimentation = $derived(!!(a && ((a.allergies || []).length || (a.intolerances || []).length)))
  const nbAlim = $derived(a ? ['allergies', 'intolerances', 'non_aimes', 'plaisirs'].reduce((n, k) => n + (a[k] || []).length, 0) : 0)
  const parusGazette = $derived(j.parus || [])
  const sejoursEtSoirees = $derived(evts.filter((e) => ['sejour', 'douze_points', 'gazette', 'recidive', 'autre'].includes(e.type)))
  const proches = $derived((f.noms_associes || []).filter((n) => n.valeur))

  function dateLisible(v) { return v ? `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}` : '' }
  const MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
  function moisAnnee(v) { return v ? `${MOIS[Number(v.slice(5, 7)) - 1]} ${v.slice(0, 4)}` : '' }
  const NOMS = { recidive: 'La Récidive', gazette: 'La Gazette' }
  const TYPES = { sejour: 'Séjour', douze_points: 'Douze points', gazette: 'La Gazette', recidive: 'La Récidive', autre: 'Événement' }

  // Icônes au trait (24 × 24)
  const ICONES = {
    alimentation: '<path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M17 3c-2 0-3 3-3 6s1 4 3 4v8"/>',
    pepites: '<path d="M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z"/>',
    livre: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11"/>',
    gazette: '<path d="M4 5h13v14H6a2 2 0 0 1-2-2zM17 9h3v8a2 2 0 0 1-2 2M8 9h5M8 13h5"/>',
    famille: '<path d="M12 4v5M6 14v-3h12v3M4 14h4v5H4zM10 14h4v5h-4zM16 14h4v5h-4z"/>',
    photos: '<path d="M4 6h16v13H4zM4 15l5-5 4 4 3-3 4 4"/>',
  }
  const tuiles = $derived([
    { cle: 'alimentation', titre: 'Alimentation', nombre: nbAlim, alerte: aLimentation,
      sous: a?.verifiee_le ? `vérifiée le ${dateLisible(a.verifiee_le)}` : 'jamais vérifiée' },
    { cle: 'pepites', titre: 'Pépites', nombre: donnees.pepites ?? '·', sous: 'pour les journaux' },
    { cle: 'livre', titre: "Livre d'or", nombre: (j.livre_or || []).length,
      sous: (j.livre_or || []).length ? `dernier : ${moisAnnee(j.livre_or[0].le)}` : 'aucun mot' },
    { cle: 'gazette', titre: 'Gazette', nombre: donnees.photos_scandale ?? '–',
      sous: `photos scandale · ${parusGazette.length} numéro${parusGazette.length > 1 ? 's' : ''}` },
    { cle: 'famille', titre: 'Famille', nombre: proches.length, sous: 'proches de la fiche' },
    { cle: 'photos', titre: 'Photos', nombre: donnees.liaisons?.immich ? '◉' : '–',
      sous: donnees.liaisons?.immich ? 'contact et affiche' : 'pas liée à Immich' },
  ])

  // 3.5 : supprimer un mot du livre d'or (un essai…) : deux touchers, rien ne part sans le second
  let aSupprimer = $state(null)
  async function supprimerMot(m) {
    if (aSupprimer !== m.id) { aSupprimer = m.id; return }
    try {
      const res = await api.effacer(`/api/livre-or/${m.id}`)
      aSupprimer = null
      dire(res?.message || 'Mot supprimé de carnet.')
      onchange()
    } catch (err) { erreur(err) }
  }
  async function rattacher(m) {
    try {
      await api.put(`/api/livre-or/${m.id}/rattacher`, { uid })
      dire('Mot du livre d\'or rattaché à cette fiche.')
      onchange()
    } catch (err) { erreur(err) }
  }
</script>

<div class="tuiles" role="tablist" aria-label="Dossier de la personne">
  {#each tuiles as t (t.cle)}
    <button type="button" role="tab" class="tuile" class:actif={section === t.cle} aria-selected={section === t.cle}
            aria-controls="dossier-panneau" onclick={() => (section = t.cle)}>
      <span class="haut">
        <span class="nombre" class:alerte={t.alerte}>{t.nombre}</span>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html ICONES[t.cle]}</svg>
      </span>
      <span class="nom">{t.titre}</span>
      <span class="sous discret">{t.sous}</span>
    </button>
  {/each}
</div>

<div id="dossier-panneau" class="panneau" role="tabpanel">
  {#if section === 'alimentation'}
    {#if a}
      <Alimentation {uid} alimentation={a} {onchange} />
    {:else}
      <p class="discret">Alimentation : seulement pour une personne (prénom ou nom).</p>
    {/if}

  {:else if section === 'pepites'}
    <div class="feuille bloc">
      <h2 class="titre">Pépites</h2>
      <p class="discret petit">Pour La Récidive et la Gazette : plus la fiche est fournie, plus l'IA du PC écrit juste.
        Rangé dans carnet seulement, modifiable aussi depuis Gazette ; rien n'est écrit dans iCloud.</p>
      <FicheJournaux {uid} />
    </div>

  {:else if section === 'livre'}
    <div class="feuille bloc">
      <h2 class="titre">Livre d'or</h2>
      {#if j.livre_or?.length}
        <ul class="liste">
          {#each j.livre_or as m (m.id)}
            <li class="carte"><p class="discret petit">{dateLisible(m.le)}{m.chambre ? ` · ${m.chambre}` : ''}{m.nom ? ` · signé ${m.nom}` : ''}</p>
              <p class="mot">« {m.message} »</p>
              <p><button class="bouton petit" class:bouton-danger={aSupprimer === m.id} onclick={() => supprimerMot(m)}>
                {aSupprimer === m.id ? 'Confirmer : supprimer ce mot' : 'Supprimer…'}</button>
                {#if aSupprimer === m.id}<button class="bouton petit" onclick={() => (aSupprimer = null)}>Garder</button>{/if}</p></li>
          {/each}
        </ul>
      {:else}<p class="discret">Aucun mot : ceux qu'elle ou il laissera dans le livre d'or de la chambre arriveront ici.</p>{/if}
      {#if j.orphelins?.length}
        <details class="orphelins">
          <summary class="petit">Mots non rattachés ({j.orphelins.length}) : signataire que carnet n'a pas reconnu</summary>
          <ul class="liste">
            {#each j.orphelins as m (m.id)}
              <li class="carte"><p class="mot">« {m.message} »</p>
                <p class="discret petit">{dateLisible(m.le)} · signé « {m.nom} »{m.chambre ? ` · ${m.chambre}` : ''}
                  <button class="bouton petit" onclick={() => rattacher(m)}>C'est cette personne</button>
                  <button class="bouton petit" class:bouton-danger={aSupprimer === m.id} onclick={() => supprimerMot(m)}>
                    {aSupprimer === m.id ? 'Confirmer : supprimer ce mot' : 'Supprimer…'}</button>
                  {#if aSupprimer === m.id}<button class="bouton petit" onclick={() => (aSupprimer = null)}>Garder</button>{/if}</p></li>
            {/each}
          </ul>
        </details>
      {/if}
    </div>

  {:else if section === 'gazette'}
    <div class="feuille bloc">
      <div class="ligne-titre"><h2 class="titre">Gazette</h2>
        <span class="discret petit">{donnees.photos_scandale ?? 'pas encore envoyé'} photo{donnees.photos_scandale > 1 ? 's' : ''} scandale</span></div>
      <div class="carte scandale">
        <span class="grand-nombre">{donnees.photos_scandale ?? '–'}</span>
        <span>photos scandale pour la prochaine Gazette<br>
          <span class="discret petit">{donnees.photos_scandale === 0 ? 'Aucune : la Gazette le signale dans son À traiter.' : 'Nombre envoyé par Gazette.'}</span></span>
      </div>
      <h3 class="sous-titre">Numéros parus</h3>
      {#if parusGazette.length}
        <ul class="liste">
          {#each parusGazette as p (p.cle)}
            <li>
              {#if p.lien}
                <a class="carte ligne" href={p.lien} target="_blank" rel="noopener"><span>{NOMS[p.journal] ?? p.journal}{p.numero ? ` N° ${p.numero}` : ''}{p.titre ? ` — « ${p.titre} »` : ''}</span><span class="discret">{dateLisible(p.le)} ›</span></a>
              {:else}
                <details class="carte">
                  <summary class="ligne"><span>{NOMS[p.journal] ?? p.journal}{p.numero ? ` N° ${p.numero}` : ''}{p.titre ? ` — « ${p.titre} »` : ''}</span><span class="discret">{dateLisible(p.le)}</span></summary>
                  {#if p.evenement}<p class="petit"><span class="discret">Événement :</span> {p.evenement}</p>{/if}
                  {#if p.descriptions?.length}<ul class="petit">{#each p.descriptions as x}<li>Photo : {x}</li>{/each}</ul>{/if}
                </details>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}<p class="discret petit">Aucun numéro encore.</p>{/if}
      <h3 class="sous-titre">Séjours et soirées</h3>
      {#if sejoursEtSoirees.length}
        <ul class="liste">
          {#each sejoursEtSoirees as e (e.appli + e.cle)}
            <li>
              <svelte:element this={e.lien ? 'a' : 'div'} class="carte ligne" href={e.lien || undefined} target={e.lien ? '_blank' : undefined} rel={e.lien ? 'noopener' : undefined}>
                <span>{e.titre || TYPES[e.type]}{#if e.type === 'douze_points' && (e.donnees?.moyenne != null || e.donnees?.classement != null)}<span class="discret"> · {e.donnees.moyenne != null ? `note ${e.donnees.moyenne}` : ''}{e.donnees.moyenne != null && e.donnees.classement != null ? ', ' : ''}{e.donnees.classement != null ? `classement ${e.donnees.classement}` : ''}</span>{/if}</span>
                <span class="discret">{dateLisible(e.date)}{e.lien ? ' ›' : ''}</span>
              </svelte:element>
            </li>
          {/each}
        </ul>
      {:else}<p class="discret petit">Rien encore : Gazette et Douze points envoient séjours et soirées à carnet.</p>{/if}
    </div>

  {:else if section === 'famille'}
    <div class="feuille bloc">
      <h2 class="titre">Famille et proches</h2>
      {#if proches.length}
        <ul class="liste">
          {#each f.noms_associes as n, i}
            {#if n.valeur}
              <li>
                {#if donnees.associes?.[i]}
                  <a class="carte ligne" href={'#/contacts/' + encodeURIComponent(donnees.associes[i])}><span>{n.valeur}</span><span class="discret">{n.type} ›</span></a>
                {:else}
                  <div class="carte ligne"><span>{n.valeur}</span><span class="discret">{n.type}</span></div>
                {/if}
              </li>
            {/if}
          {/each}
        </ul>
      {:else}<p class="discret">Aucun proche sur la fiche. Les liens de Treemich arrivent dans À traiter (Liens familiaux).</p>{/if}
    </div>

  {:else if section === 'photos'}
    <div class="feuille bloc">
      <div class="ligne-titre"><h2 class="titre">Photos</h2>
        <button class="bouton bouton-principal" onclick={onpropositions}>Choisir la photo et l'affiche</button></div>
      <PhotosFiche {uid} nom={donnees.nom} lieImmich={!!donnees.liaisons.immich} portraits={donnees.portraits}
                   affiche={donnees.affiche} societe={f.societe} google={donnees.google_logo} {onchange} />
    </div>
  {/if}
</div>

<style>
  .tuiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.6rem; }
  @media (min-width: 700px) { .tuiles { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
  .tuile {
    min-height: 6.5rem; border-radius: 16px; padding: 0.85rem; display: flex; flex-direction: column; align-items: flex-start;
    gap: 0.2rem; text-align: left; background: var(--color-reliure); border: 2px solid transparent; color: var(--color-papier); cursor: pointer;
  }
  .tuile:hover { border-color: var(--color-tranche); }
  .tuile.actif { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 8%, var(--color-reliure)); }
  .haut { display: flex; align-items: center; justify-content: space-between; width: 100%; color: var(--color-mine); }
  .nombre { font-size: 1.6rem; font-weight: 300; color: var(--color-papier); line-height: 1.1; }
  .nombre.alerte { color: var(--color-alerte); font-weight: 500; }
  .nom { font-size: 0.95rem; font-weight: 600; }
  .sous { font-size: 0.78rem; }
  .panneau { display: grid; gap: 0.75rem; }
  .bloc { padding: 1rem; display: grid; gap: 0.7rem; }
  .ligne-titre { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
  .titre { font-size: 1.15rem; margin: 0; }
  .sous-titre { font-size: 0.95rem; margin: 0.6rem 0 0; }
  .liste { display: grid; gap: 0.5rem; padding: 0; margin: 0; list-style: none; }
  .carte { border-radius: 10px; background: var(--color-cuir); border: 1px solid var(--color-couture); padding: 0.7rem 0.8rem; }
  .ligne { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; min-height: 2.75rem;
           color: var(--color-papier); text-decoration: none; overflow-wrap: anywhere; }
  a.ligne:hover { border-color: var(--color-onglet); }
  summary.ligne { cursor: pointer; padding: 0; min-height: 2rem; }
  .mot { font-style: italic; white-space: pre-line; margin: 0.2rem 0 0; overflow-wrap: anywhere; }
  .scandale { display: flex; align-items: center; gap: 0.9rem; }
  .grand-nombre { font-size: 2.4rem; font-weight: 300; line-height: 1; }
  .orphelins summary { cursor: pointer; }
  .petit { font-size: 0.82rem; }
</style>
