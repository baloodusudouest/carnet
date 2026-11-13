<script>
  // Onglet Photos (2.8) : quatre files, traitées par lots. Rien n'est écrit dans iCloud sans que
  // l'image ait été vue : on coche, on regarde, puis on pose.
  // 2.11 : « Portraits » et « Affiches » montrent TOUS les contacts qui peuvent en recevoir une, avec
  // cinq propositions chacun. La première est le choix de carnet ; on peut en toucher une autre.
  // Une photo déjà en place n'est jamais cochée d'office.
  // 2.13 : « Cocher tous ceux que carnet propose » coche d'un geste tous les contacts de la liste qui
  // ont une proposition, au-delà des lignes affichées. La pose reste par lots : les suivants restent cochés.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  import { tache } from '../lib/suivi.svelte.js'
  import Avatar from '../components/Avatar.svelte'
  import DepotLogo from '../components/DepotLogo.svelte'

  const FILES = [
    { cle: 'logos', nom: 'Logos', vide: 'Aucune fiche de société sans photo.',
      aide: 'Une ligne par société. Glisse ou colle son logo, ou lance la recherche sur son site quand elle en a un : il est posé sur toutes ses fiches sans photo, et gardé pour les suivantes. Une fiche qui a déjà une photo la garde.' },
    { cle: 'portraits', nom: 'Portraits', vide: 'Aucun contact relié à Immich, ni société avec un logo gardé.',
      aide: 'Tous les contacts reliés à Immich ou dont la société a un logo. Le nombre de la tuile compte ceux qui n\'ont pas de photo. Carnet propose d\'abord la photo où le visage est entier, grand, la personne seule et au centre si possible ; touche une autre proposition pour la préférer. La photo posée devient aussi le visage de la personne dans Immich.' },
    { cle: 'affiches', nom: 'Affiches', vide: 'Aucun contact relié à Immich, ni société avec un logo gardé.',
      aide: 'Les mêmes contacts. Le nombre de la tuile compte ceux qui n\'ont pas d\'affiche. L\'affiche (image plein écran quand le contact appelle) est déposée dans l\'album Immich « Affiches de contacts » ; elle se pose ensuite à la main sur l\'iPhone.' },
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
  // 2.11
  let voirChoisis = $state(false)   // 2.12 : les contacts dont le choix est fait sont repliés ; l'œil les remontre
  const nbChoisis = $derived((donnees?.files[file] || []).filter((x) => x.choisi && (!groupe || x.groupes.includes(groupe))).length)
  let manque = $state(false)   // ne montrer que ce qui manque
  let montrees = $state(20)    // lignes affichées (on avance par paquets)
  let props = $state({})       // uid → propositions lues ({ photos, affiches }), null pendant la lecture
  let retenu = $state({})      // uid → clé de la proposition retenue (par défaut : la première, celle de carnet)
  // 2.16 : une proposition dont l'image ne s'affiche plus (la photo a quitté Immich : migration, suppression).
  // La personne est retirée de la liste, comptée dans un message, et on propose de refaire sa recherche.
  let casses = $state(new Set())      // « file:uid »
  let voirCasses = $state(false)
  const cassee = (x) => casses.has(file + ':' + x.uid)
  const lesCasses = $derived(aChoix ? (donnees?.files[file] || []).filter(cassee) : [])
  function imageCassee(x) { if (!cassee(x)) casses = new Set([...casses, file + ':' + x.uid]) }
  async function reparer() {
    const uids = lesCasses.map((x) => x.uid)
    await enFond('/api/photos/propositions', { uids })
    casses = new Set([...casses].filter((k) => !k.startsWith(file + ':')))
    voirCasses = false
  }
  let relance = $state(false)   // 2.12 : confirmation avant de relancer la recherche pour tout le monde
  const relies = $derived((donnees?.files[file] || []).filter((x) => x.mode === 'immich').length)
  const aChoix = $derived(file === 'portraits' || file === 'affiches')
  const sorte = $derived(file === 'affiches' ? 'affiche' : 'photo')
  const fait = (x) => (file === 'affiches' ? x.affiche !== null : x.a_photo)

  const courante = $derived(FILES.find((f) => f.cle === file))
  const filtrees = $derived((donnees?.files[file] || []).filter((x) => (!groupe || x.groupes.includes(groupe)) && (!aChoix || !manque || !fait(x)) && (!aChoix || voirChoisis || !x.choisi) && (voirCasses || !cassee(x))))
  // Logos : une ligne par société. Le logo choisi est posé sur toutes ses fiches sans photo ;
  // une fiche qui a déjà une photo n'est pas dans la file et n'est jamais touchée.
  const lignes = $derived.by(() => {
    if (file !== 'logos') return filtrees
    const par = new Map()
    for (const x of filtrees) {
      const g = par.get(x.cle) || par.set(x.cle, []).get(x.cle)
      g.push(x)
    }
    return [...par.values()].map((g) => {
      const rep = g.find((x) => x.domaine) || g[0]
      return { ...rep, nom: rep.societe, nb: g.length, noms: g.map((x) => x.nom).filter((n) => n !== rep.societe),
               groupes: [...new Set(g.flatMap((x) => x.groupes))], cherche: g.some((x) => x.cherche), trouves: Math.max(...g.map((x) => x.trouves)) }
    }).sort((a, b) => a.nom.localeCompare(b.nom, 'fr'))
  })
  const groupes = $derived([...new Set((donnees?.files[file] || []).flatMap((x) => x.groupes))].sort((a, b) => a.localeCompare(b, 'fr')))
  const lot = $derived(donnees?.lot_max || 20)
  const cochees = $derived(lignes.filter((x) => coches.has(x.uid)).map((x) => x.uid))
  const visibles = $derived(aChoix ? lignes.slice(0, montrees) : lignes)
  const liste = (x) => (props[x.uid] ? (file === 'affiches' ? props[x.uid].affiches : props[x.uid].photos) : [])
  const cleDe = (x) => retenu[file + ':' + x.uid] ?? liste(x)[0]?.cle
  // Cochés et pas encore relus dans Immich : à chercher. Cochés avec une proposition : prêts.
  const aChercher = $derived(lignes.filter((x) => coches.has(x.uid) && x.mode === 'immich' && !x.cherche).map((x) => x.uid))
  const prets = $derived(lignes.filter((x) => coches.has(x.uid) && cleDe(x) !== undefined).map((x) => ({ uid: x.uid, cle: cleDe(x) })))
  const remplacees = $derived(lignes.filter((x) => coches.has(x.uid) && cleDe(x) !== undefined && fait(x)).length)

  // 2.13 : tous les contacts de la liste pour qui carnet a une proposition, affichés ou non
  const proposables = $derived(aChoix ? lignes.filter((x) => x.cherche && !x.aucune) : [])
  const enLecture = $derived(proposables.filter((x) => coches.has(x.uid) && !props[x.uid]).length)
  function cocherProposes() { coches = new Set(proposables.map((x) => x.uid)) }

  // Les propositions des lignes affichées, puis celles des contacts cochés plus bas, sont lues une à une
  // (les images, elles, à la demande)
  $effect(() => {
    if (!aChoix) return
    const aLire = (x) => x.cherche && !x.aucune && props[x.uid] === undefined
    const suivant = visibles.find(aLire) || proposables.find((x) => coches.has(x.uid) && aLire(x))
    if (!suivant) return
    props[suivant.uid] = null
    api.get(`/api/contacts/${encodeURIComponent(suivant.uid)}/propositions`)
      .then((r) => { props[suivant.uid] = r })
      .catch(() => { props[suivant.uid] = { photos: [], affiches: [] } })
  })
  // Prêtes à poser : un logo trouvé ou déposé à l'instant, ou le logo déjà gardé pour la société
  const logosChoisis = $derived(lignes.filter((x) => choix[x.uid] !== undefined || x.connu).map((x) => ({ uid: x.uid, n: choix[x.uid] ?? 0 })))

  async function charger() {
    try { donnees = await api.get('/api/photos') } catch (e) { erreur(e) }
  }
  function changerFile(cle) { relance = false; voirChoisis = false; file = cle; groupe = ''; coches = new Set(); montrees = 20 }
  function basculer(uid) {
    const s = new Set(coches)
    s.has(uid) ? s.delete(uid) : s.add(uid)
    coches = s
  }
  // Jamais « tout cocher » au-delà d'un lot : on avance par paquets que l'on peut regarder
  // 2.11 : dans Portraits et Affiches, on ne coche d'office que ce qui manque — jamais un remplacement
  function cocherLot() { coches = new Set((aChoix ? visibles.filter((x) => !fait(x) && !x.aucune) : lignes).slice(0, lot).map((x) => x.uid)) }

  async function enFond(chemin, corps, garder = []) {
    attente = true
    try {
      await tache('photos', chemin, corps, 'photos')
      dire(etat.accueil?.tache?.message || 'Terminé.')
      coches = new Set(garder); choix = {}; trouves = {}; props = {}; retenu = {}; version += 1
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
  // Un lot à la fois : les contacts cochés au-delà du lot le restent pour le suivant
  function poserLeLot() {
    const envoi = prets.slice(0, lot), partis = new Set(envoi.map((x) => x.uid))
    enFond(file === 'affiches' ? '/api/photos/affiches/choix' : '/api/photos/portraits/choix', { choix: envoi },
           cochees.length > lot ? cochees.filter((uid) => !partis.has(uid)) : [])
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
            <option value="">Tous les groupes</option>
            {#each groupes as g}<option value={g}>{g} ({donnees.files[file].filter((x) => x.groupes.includes(g)).length} fiches)</option>{/each}
          </select>
        {/if}
        {#if aChoix}
          <label class="bascule"><input type="checkbox" bind:checked={manque} onchange={() => { coches = new Set(); montrees = 20 }} />
            Seulement {file === 'affiches' ? 'sans affiche' : 'sans photo'}</label>
          <button class="bouton" onclick={cocherLot}>Cocher ce qui manque ici</button>
          {#if proposables.length}
            <button class="bouton" onclick={cocherProposes} title="Tous les contacts de cette liste pour qui carnet a une proposition, affichés ou non">
              Cocher tous ceux que carnet propose ({proposables.length})</button>
          {/if}
          {#if nbChoisis}
            <button class="bouton oeil" aria-pressed={voirChoisis} onclick={() => { voirChoisis = !voirChoisis; coches = new Set(); montrees = 20 }}
                    title="Contacts dont tu as déjà choisi {file === 'affiches' ? 'l\'affiche' : 'la photo'} ici">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />{#if !voirChoisis}<path d="M4 4l16 16" />{/if}</svg>
              {voirChoisis ? 'Masquer' : 'Afficher'} les {nbChoisis} déjà choisi{nbChoisis > 1 ? 's' : ''}</button>
          {/if}
        {:else if file !== 'logos' || lignes.some((x) => x.domaine)}
          <button class="bouton" onclick={cocherLot}>Cocher {lignes.length > lot ? `les ${lot} premières` : 'tout'}</button>
        {/if}
        {#if coches.size}<button class="bouton" onclick={() => (coches = new Set())}>Tout décocher</button>{/if}
      </div>

      <div class="actions">
        {#if file === 'logos'}
          {#if lignes.some((x) => x.domaine)}
            <button class="bouton" disabled={attente || !cochees.length} onclick={chercherLogos}>
              {attente ? 'Recherche…' : `Chercher les logos (${cochees.length})`}</button>
          {/if}
          <button class="bouton bouton-principal" disabled={attente || !logosChoisis.length}
                  onclick={() => enFond('/api/photos/logos/poser', { choix: logosChoisis })}>Poser les logos ({logosChoisis.length} société{logosChoisis.length > 1 ? 's' : ''})</button>
        {:else if aChoix}
          {#if aChercher.length}
            <button class="bouton" disabled={attente} onclick={() => enFond('/api/photos/propositions', { uids: aChercher })}>
              {attente ? 'Recherche…' : `Chercher les propositions (${aChercher.length})`}</button>
          {/if}
          <button class="bouton bouton-principal" disabled={attente || !prets.length} onclick={poserLeLot}>
            {file === 'affiches' ? 'Préparer les affiches cochées' : 'Poser les photos cochées'} ({prets.length > lot ? `${lot} sur ${prets.length}` : prets.length})</button>
          {#if enLecture}<span class="discret" role="status">Lecture des propositions : encore {enLecture}…</span>{/if}
          {#if remplacees}<span class="discret">dont {remplacees} en remplacement de {file === 'affiches' ? 'l\'affiche' : 'la photo'} actuelle</span>{/if}
          {#if cochees.length > lot}<span class="discret">Par lots de {lot} : les suivants restent cochés.</span>{/if}
          {#if relies}
            {#if relance}
              <span class="relance" role="group" aria-label="Relancer la recherche">
                <span>Relire Immich pour {relies} contact(s) ? Cela peut durer plusieurs minutes. Rien n'est posé : seules les propositions changent, pour les photos et les affiches.</span>
                <button class="bouton bouton-principal" disabled={attente} onclick={() => { relance = false; enFond('/api/photos/propositions', { tous: true }) }}>Oui, relancer</button>
                <button class="bouton" onclick={() => (relance = false)}>Non</button>
              </span>
            {:else}
              <button class="bouton" disabled={attente} onclick={() => (relance = true)}>{attente ? 'Recherche…' : `Relancer la recherche pour tous (${relies})`}</button>
            {/if}
          {/if}
        {:else}
          <button class="bouton bouton-principal" disabled={attente || !cochees.length} onclick={marquerPosees}>Marquer comme posées ({cochees.length})</button>
        {/if}
      </div>

      {#if lesCasses.length}
        <div class="casses" role="status" aria-label="Propositions qui ne s'affichent plus">
          <p><strong>{lesCasses.length} personne{lesCasses.length > 1 ? 's ont' : ' a'} un problème d'affichage</strong> : une photo proposée n'est plus dans Immich (remplacée par une migration, ou supprimée). {voirCasses ? '' : (lesCasses.length > 1 ? 'Elles sont retirées' : 'Elle est retirée') + ' de la liste en attendant.'}</p>
          <p class="discret">La solution : refaire leur recherche. Carnet relit Immich pour {lesCasses.length > 1 ? 'ces personnes' : 'cette personne'} et propose les photos d'aujourd'hui. Rien n'est posé, et une photo déjà en place n'est pas touchée.</p>
          <div class="actions">
            <button class="bouton bouton-principal" disabled={attente} onclick={reparer}>{attente ? 'Recherche…' : `Refaire la recherche pour ${lesCasses.length > 1 ? 'ces ' + lesCasses.length + ' personnes' : 'cette personne'}`}</button>
            <button class="bouton" aria-pressed={voirCasses} onclick={() => (voirCasses = !voirCasses)}>{voirCasses ? 'Les cacher' : 'Les afficher quand même'}</button>
          </div>
        </div>
      {/if}

      <ul class="liste">
        {#each visibles as x (x.uid)}
          <li class="fiche" class:logo={file === 'logos'} class:choix={aChoix}>
            <label class="qui">
              {#if file !== 'logos' || x.domaine}
                <input type="checkbox" checked={coches.has(x.uid)} onchange={() => basculer(x.uid)} aria-label={'Cocher ' + x.nom} />
              {:else}<span class="sans-case" aria-hidden="true"></span>{/if}
              {#if file === 'logos' && trouves[x.uid]?.length}
                <img class="apercu-logo" src={`/api/contacts/${encodeURIComponent(x.uid)}/logos/${choix[x.uid] ?? trouves[x.uid][0].n}?v=${version}`} alt="Logo proposé" />
              {:else if file === 'logos' && x.connu}
                <img class="apercu-logo" src={`/api/photos/logos/connu/${encodeURIComponent(x.uid)}`} alt="Logo de la société" />
              {:else if file === 'a_poser'}
                <img class="apercu-affiche" src={`/api/contacts/${encodeURIComponent(x.uid)}/affiche`} alt="" loading="lazy" />
              {:else}
                {#key version}<Avatar uid={x.uid} nom={x.nom} photo={file === 'a_poser' || (aChoix && x.a_photo)} taille={40} />{/key}
              {/if}
              <span class="texte">
                <a class="nom" href={'#/contacts/' + encodeURIComponent(x.uid)}>{x.nom}</a>
                {#if file === 'logos'}
                  <span class="discret detail">{x.nb} fiche(s) sans photo{x.noms.length ? ' : ' + x.noms.slice(0, 4).join(', ') + (x.noms.length > 4 ? '…' : '') : ''}</span>
                {:else if aChoix}
                  <span class="discret detail">{[file === 'affiches' ? (x.affiche === null ? 'sans affiche' : 'affiche ' + x.affiche) : (x.a_photo ? 'a déjà une photo' : 'sans photo'),
                    x.societe !== x.nom ? x.societe : '', x.groupes.join(', ')].filter(Boolean).join(' · ')}</span>
                {:else}
                  <span class="discret detail">{[x.societe !== x.nom ? x.societe : '', x.groupes.join(', ')].filter(Boolean).join(' · ')}</span>
                {/if}
                {#if file === 'logos'}
                  {#if trouves[x.uid]?.length}
                    <span class="etat-logo pret">{trouves[x.uid][0].depose ? 'Logo déposé' : `${trouves[x.uid].length} logo(s) trouvé(s)`} : prêt à poser</span>
                  {:else if x.connu}<span class="etat-logo pret">Logo de la société déjà choisi : prêt à poser</span>
                  {:else if x.cherche && !x.trouves}<span class="discret etat-logo">Rien trouvé sur le site</span>
                  {:else if !x.domaine}<span class="discret etat-logo">Ni site ni courriel professionnel : à déposer</span>{/if}
                {/if}
              </span>
            </label>
            {#if aChoix}
              {#if x.aucune}
                <span class="discret etat-logo">Aucune photo utilisable dans Immich (visage entier et assez grand).</span>
              {:else if !x.cherche}
                <span class="discret etat-logo">Pas encore cherché dans Immich : coche puis « Chercher les propositions ».</span>
              {:else if !props[x.uid]}
                <span class="discret etat-logo">Lecture des propositions…</span>
              {:else if !liste(x).length}
                <span class="discret etat-logo">{file === 'affiches' ? 'Aucune photo ne laisse assez de place autour du visage pour une affiche.' : 'Aucune proposition.'}</span>
              {:else}
                <div class="propositions" role="group" aria-label={'Propositions pour ' + x.nom}>
                  {#each liste(x) as pr, i (pr.cle)}
                    <button class="proposition" class:affiche={file === 'affiches'} aria-pressed={cleDe(x) === pr.cle}
                            aria-label={`Proposition ${i + 1}` + (i === 0 ? ', choix de carnet' : '') + (pr.seul ? ', seul sur la photo' : '')}
                            onclick={() => { retenu = { ...retenu, [file + ':' + x.uid]: pr.cle }; if (!coches.has(x.uid)) basculer(x.uid) }}>
                      {#if pr.couleur}<span class="teinte" style:background={pr.couleur}></span>{/if}
                      <img src={`/api/contacts/${encodeURIComponent(x.uid)}/propositions/${sorte}/${encodeURIComponent(pr.cle)}?v=${version}`} alt="" loading="lazy" onerror={() => imageCassee(x)} />
                      {#if i === 0}<span class="marque">carnet</span>{/if}
                    </button>
                  {/each}
                </div>
              {/if}
            {/if}
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
      {#if aChoix && lignes.length > montrees}
        <button class="bouton" onclick={() => (montrees += 20)}>Voir les 20 suivants ({lignes.length - montrees} restants)</button>
      {/if}
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
  .bascule { display: inline-flex; align-items: center; gap: 0.45rem; min-height: 2.75rem; font-size: 0.9rem; }
  .bascule input { width: 1.15rem; height: 1.15rem; accent-color: var(--color-onglet); }
  .oeil { display: inline-flex; align-items: center; gap: 0.4rem; }
  .relance { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; flex-basis: 100%; }
  .casses { margin: 0.6rem 0 0.9rem; padding: 0.8rem 1rem; border: 1px solid var(--attention, #c9a227); border-radius: 12px; display: grid; gap: 0.45rem; }
  .casses p { margin: 0; }
  .propositions { display: flex; gap: 0.45rem; flex-wrap: wrap; }
  .proposition { position: relative; width: 64px; height: 64px; padding: 0; border-radius: 12px; overflow: hidden;
    border: 2px solid transparent; outline: 1px solid var(--color-couture); background: var(--color-reliure); }
  .proposition.affiche { width: 54px; height: 117px; border-radius: 9px; }
  .proposition[aria-pressed='true'] { border-color: var(--color-onglet); outline-color: var(--color-onglet); }
  .proposition img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .proposition .teinte { position: absolute; inset: 0; }
  .proposition .teinte + img { position: relative; }
  .marque { position: absolute; left: 0; right: 0; bottom: 0; font-size: 0.6rem; line-height: 1.5; text-align: center;
    background: var(--color-onglet); color: var(--color-sur-onglet); font-weight: 600; }
  @media (min-width: 900px) {
    .tuiles { grid-template-columns: repeat(4, 1fr); }
    .fiche.logo { grid-template-columns: minmax(0, 1fr) minmax(16rem, 22rem); align-items: center; }
    .fiche.logo .candidats { grid-column: 1; }
  }
</style>
