<script>
  // Onglet Photos (2.8) : quatre files, traitées par lots. Rien n'est écrit dans iCloud sans que
  // l'image ait été vue : on coche, on regarde, puis on pose.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  import { tache } from '../lib/suivi.svelte.js'
  import Avatar from '../components/Avatar.svelte'
  import DepotLogo from '../components/DepotLogo.svelte'

  const FILES = [
    { cle: 'logos', nom: 'Logos', vide: 'Aucune fiche de société sans photo.',
      aide: 'Fiches de société sans photo. Glisse ou colle un logo sur une fiche, ou lance la recherche sur le site de la société pour celles qui en ont un.' },
    { cle: 'portraits', nom: 'Portraits', vide: 'Aucun contact relié à Immich sans photo.',
      aide: 'Contacts reliés à Immich, sans photo. Le portrait est découpé dans la meilleure photo de la personne.' },
    { cle: 'a_preparer', nom: 'Affiches à préparer', vide: 'Aucune affiche à préparer.',
      aide: 'Contacts avec une photo, sans affiche. L\'affiche (image plein écran quand le contact appelle) est déposée dans l\'album Immich « Affiches de contacts ».' },
    { cle: 'a_poser', nom: 'Affiches à poser', vide: 'Aucune affiche en attente.',
      aide: 'Affiches prêtes dans Immich. La pose se fait à la main sur l\'iPhone (Contacts, Modifier, Photo et affiche) ; coche ici celles qui sont faites.' },
  ]
  let donnees = $state(null)
  let file = $state('logos')
  let groupe = $state('')
  let coches = $state(new Set())
  let attente = $state(false)
  let trouves = $state({})    // uid → logos en attente d'un choix : [{ n, depose }]
  let choix = $state({})      // uid → n du logo retenu
  let version = $state(0)

  const courante = $derived(FILES.find((f) => f.cle === file))
  const lignes = $derived((donnees?.files[file] || []).filter((x) => !groupe || x.groupes.includes(groupe)))
  const groupes = $derived([...new Set((donnees?.files[file] || []).flatMap((x) => x.groupes))].sort((a, b) => a.localeCompare(b, 'fr')))
  const lot = $derived(donnees?.lot_max || 20)
  const cochees = $derived(lignes.filter((x) => coches.has(x.uid)).map((x) => x.uid))
  const logosChoisis = $derived(lignes.filter((x) => choix[x.uid] !== undefined).map((x) => ({ uid: x.uid, n: choix[x.uid] })))

  async function charger() {
    try { donnees = await api.get('/api/photos') } catch (e) { erreur(e) }
  }
  function changerFile(cle) { file = cle; groupe = ''; coches = new Set() }
  function basculer(uid) {
    const s = new Set(coches)
    s.has(uid) ? s.delete(uid) : s.add(uid)
    coches = s
  }
  // Jamais « tout cocher » au-delà d'un lot : on avance par paquets que l'on peut regarder
  function cocherLot() { coches = new Set(lignes.slice(0, lot).map((x) => x.uid)) }

  async function enFond(chemin, corps) {
    attente = true
    try {
      await tache('photos', chemin, corps, 'photos')
      dire(etat.accueil?.tache?.message || 'Terminé.')
      coches = new Set(); choix = {}; trouves = {}
      await Promise.all([charger(), rafraichirContacts(), rafraichirAccueil()])
    } catch (e) { erreur(e) } finally { attente = false }
  }
  async function chercherLogos() {
    attente = true
    try {
      const r = await api.post('/api/photos/logos/chercher', { uids: cochees })
      const t = { ...trouves }, c = { ...choix }
      for (const x of r.resultats) { t[x.uid] = x.logos; if (x.logos.length) c[x.uid] = x.logos[0].n; else delete c[x.uid] }
      trouves = t; choix = c; version += 1
      const n = r.resultats.filter((x) => x.logos.length).length
      dire(`${n} logo(s) trouvé(s) sur ${r.resultats.length} société(s)` + (r.restants ? `, ${r.restants} en attente du lot suivant` : '') + '. Regarde-les avant de les poser.')
      await charger()
    } catch (e) { erreur(e) } finally { attente = false }
  }
  function logoDepose(uid, r) {
    trouves = { ...trouves, [uid]: [{ n: r.n, depose: true }] }
    choix = { ...choix, [uid]: r.n }
    version += 1
  }
  async function marquerPosees() {
    attente = true
    try {
      const r = await api.post('/api/photos/posees', { uids: cochees })
      dire(`${r.faits} affiche(s) marquée(s) posée(s).`)
      coches = new Set(); await charger()
    } catch (e) { erreur(e) } finally { attente = false }
  }
  onMount(charger)
</script>

<section class="page">
  <h1 class="titre">Photos</h1>
  {#if !donnees}
    <p class="discret">Chargement…</p>
  {:else}
    <nav class="tuiles" aria-label="Files">
      {#each FILES as f}
        <button class="tuile" aria-pressed={file === f.cle} onclick={() => changerFile(f.cle)}>
          <span class="chiffre">{donnees.nombres[f.cle]}</span>
          <span class="nom-tuile">{f.nom}</span>
        </button>
      {/each}
    </nav>

    <p class="discret aide">{courante.aide}</p>
    {#if etat.accueil?.lecture_seule && file !== 'a_poser'}
      <p class="discret" role="status">Mode lecture seule : les poses seront refusées.</p>
    {/if}

    {#if !(donnees.files[file] || []).length}
      <p class="discret vide">{courante.vide}</p>
    {:else}
      <div class="outils">
        {#if groupes.length > 1}
          <select bind:value={groupe} aria-label="Groupe" onchange={() => (coches = new Set())}>
            <option value="">Tous les groupes ({donnees.files[file].length})</option>
            {#each groupes as g}<option value={g}>{g} ({donnees.files[file].filter((x) => x.groupes.includes(g)).length})</option>{/each}
          </select>
        {/if}
        {#if file !== 'logos' || lignes.some((x) => x.domaine)}
          <button class="bouton" onclick={cocherLot}>Cocher {lignes.length > lot ? `les ${lot} premières` : 'tout'}</button>
        {/if}
        {#if coches.size}<button class="bouton" onclick={() => (coches = new Set())}>Tout décocher</button>{/if}
      </div>

      <div class="actions">
        {#if file === 'logos'}
          <button class="bouton" disabled={attente || !cochees.some((u) => lignes.find((x) => x.uid === u)?.domaine)} onclick={chercherLogos}>
            {attente ? 'Recherche…' : `Chercher les logos (${cochees.length})`}</button>
          <button class="bouton bouton-principal" disabled={attente || !logosChoisis.length}
                  onclick={() => enFond('/api/photos/logos/poser', { choix: logosChoisis })}>Poser les logos ({logosChoisis.length})</button>
        {:else if file === 'portraits'}
          <button class="bouton bouton-principal" disabled={attente || !cochees.length}
                  onclick={() => enFond('/api/photos/portraits', { uids: cochees })}>Poser les portraits ({cochees.length})</button>
        {:else if file === 'a_preparer'}
          <button class="bouton bouton-principal" disabled={attente || !cochees.length}
                  onclick={() => enFond('/api/photos/affiches', { uids: cochees })}>Préparer les affiches ({cochees.length})</button>
        {:else}
          <button class="bouton bouton-principal" disabled={attente || !cochees.length} onclick={marquerPosees}>Marquer comme posées ({cochees.length})</button>
        {/if}
      </div>

      <ul class="liste">
        {#each lignes as x (x.uid)}
          <li class="fiche" class:logo={file === 'logos'}>
            <label class="qui">
              {#if file !== 'logos' || x.domaine}
                <input type="checkbox" checked={coches.has(x.uid)} onchange={() => basculer(x.uid)} aria-label={'Cocher ' + x.nom} />
              {:else}<span class="sans-case" aria-hidden="true"></span>{/if}
              {#if file === 'logos' && trouves[x.uid]?.length}
                <img class="apercu-logo" src={`/api/contacts/${encodeURIComponent(x.uid)}/logos/${choix[x.uid] ?? trouves[x.uid][0].n}?v=${version}`} alt="Logo proposé" />
              {:else if file === 'a_poser'}
                <img class="apercu-affiche" src={`/api/contacts/${encodeURIComponent(x.uid)}/affiche`} alt="" loading="lazy" />
              {:else}
                <Avatar uid={x.uid} nom={x.nom} photo={file !== 'logos' && file !== 'portraits'} taille={40} />
              {/if}
              <span class="texte">
                <a class="nom" href={'#/contacts/' + encodeURIComponent(x.uid)}>{x.nom}</a>
                <span class="discret detail">{[x.societe !== x.nom ? x.societe : '', x.groupes.join(', ')].filter(Boolean).join(' · ')}</span>
                {#if file === 'logos'}
                  {#if trouves[x.uid]?.length}
                    <span class="etat-logo pret">{trouves[x.uid][0].depose ? 'Logo déposé' : `${trouves[x.uid].length} logo(s) trouvé(s)`} : prêt à poser</span>
                  {:else if x.cherche && !x.trouves}<span class="discret etat-logo">Rien trouvé sur le site</span>
                  {:else if !x.domaine}<span class="discret etat-logo">Ni site ni courriel professionnel : à déposer</span>{/if}
                {/if}
              </span>
            </label>
            {#if file === 'logos'}
              {#if trouves[x.uid]?.length > 1}
                <div class="candidats">
                  {#each trouves[x.uid] as l (l.n)}
                    <button class="candidat" aria-pressed={choix[x.uid] === l.n} onclick={() => (choix = { ...choix, [x.uid]: l.n })} aria-label={'Logo ' + (l.n + 1)}>
                      <img src={`/api/contacts/${encodeURIComponent(x.uid)}/logos/${l.n}?v=${version}`} alt="" /></button>
                  {/each}
                </div>
              {/if}
              <DepotLogo uid={x.uid} google={x.google} compact onpret={(r) => logoDepose(x.uid, r)} />
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .page { display: grid; gap: 1rem; max-width: 56rem; }
  h1 { font-size: 1.9rem; }
  .tuiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.6rem; }
  .tuile { display: grid; gap: 0.15rem; text-align: left; padding: 0.85rem 1rem; border-radius: 12px;
    border: 1px solid var(--color-couture); background: var(--color-reliure); }
  .tuile[aria-pressed='true'] { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 10%, var(--color-reliure)); }
  .chiffre { font-size: 1.9rem; font-weight: 300; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .nom-tuile { color: var(--color-mine); font-size: 0.88rem; }
  .aide { max-width: 44rem; }
  .outils, .actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
  .liste { display: grid; gap: 0.5rem; }
  .fiche { display: grid; gap: 0.6rem; padding: 0.7rem 0.85rem; border: 1px solid var(--color-couture); border-radius: 12px; }
  .qui { display: flex; align-items: center; gap: 0.7rem; min-width: 0; }
  .qui input { width: 1.25rem; height: 1.25rem; accent-color: var(--color-onglet); flex: none; }
  .sans-case { width: 1.25rem; flex: none; }
  .texte { display: grid; min-width: 0; }
  .nom { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nom:hover { text-decoration: underline; text-underline-offset: 3px; }
  .detail { font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .etat-logo { font-size: 0.82rem; }
  .etat-logo.pret { color: var(--color-onglet); }
  .apercu-logo { width: 48px; height: 48px; border-radius: 10px; object-fit: contain; background: #fff; flex: none; }
  .apercu-affiche { width: 36px; height: 78px; border-radius: 6px; object-fit: cover; flex: none; background: var(--color-couture); }
  .candidats { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .candidat { width: 52px; height: 52px; padding: 2px; border-radius: 10px; border: 2px solid transparent; background: #fff; }
  .candidat[aria-pressed='true'] { border-color: var(--color-onglet); }
  .candidat img { width: 100%; height: 100%; object-fit: contain; }
  .vide { padding: 2rem 0; }
  @media (min-width: 900px) {
    .tuiles { grid-template-columns: repeat(4, 1fr); }
    .fiche.logo { grid-template-columns: minmax(0, 1fr) minmax(16rem, 22rem); align-items: center; }
    .fiche.logo .candidats { grid-column: 1; }
  }
</style>
