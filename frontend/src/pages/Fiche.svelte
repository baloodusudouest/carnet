<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { aller, apresEcriture, erreur, dire, etat, rafraichirContacts } from '../lib/etat.svelte.js'
  import Dossier from '../components/Dossier.svelte'
  import Avatar from '../components/Avatar.svelte'
  import ChoixPhoto from '../components/ChoixPhoto.svelte'
  import Changements from '../components/Changements.svelte'
  import Editeur from '../components/Editeur.svelte'
  import Point from '../components/Point.svelte'
  import PhotosFiche from '../components/PhotosFiche.svelte'
  import Plateformes from '../components/Plateformes.svelte'
  import { PLATEFORMES, RESEAUX } from '../lib/plateformes.js'

  let { uid, panneau = false } = $props()   // panneau : à droite de la liste, sur PC
  const e = encodeURIComponent(uid)
  let donnees = $state(null)
  let brouillon = $state(null)    // fiche en cours de modification
  let choixPhoto = $state(false)  // 2.10 : fenêtre des propositions de photo et d'affiche
  let section = $state('alimentation')   // 3.1 : tuile ouverte du dossier
  let dossier = $state(null)
  // 3.1 : toucher la photo ouvre la tuile Photos (choix de la photo du contact et de l'affiche)
  function ouvrirPhotos() {
    section = 'photos'
    requestAnimationFrame(() => dossier?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  let apercu = $state(null)       // { fiche, champs } avant d'écrire
  let conjoint = $state('')       // 3.5 : uid du conjoint choisi sous la date de mariage
  let raisons = $state([])        // 3.5 : pourquoi la date de mariage ne part pas vers Treemich (après l'écriture)
  let attente = $state(false)
  let proches = $state(null)
  let reunir = $state('')

  async function charger() {
    try { donnees = await api.get(`/api/contacts/${e}`) } catch (err) { erreur(err) }
  }
  // Dates : saisies en JJ/MM/AAAA ; une année inconnue s'écrit 1900 (iCloud ne reçoit que le jour et le mois)
  const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
  function dateSaisie(v) {
    if (!v) return ''
    if (v.startsWith('--')) return `${v.slice(5, 7)}/${v.slice(2, 4)}/1900`
    return v.length === 10 ? `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)}` : v
  }
  function dateLecture(v) {
    if (v.startsWith('--')) return `${Number(v.slice(5, 7))} ${MOIS[Number(v.slice(2, 4)) - 1]}`
    return dateSaisie(v)
  }
  // 2.24 : champs de la fiche de l'iPhone, montrés en lecture quand ils sont remplis
  const CHAMPS_224 = [['titre', 'Titre'], ['second_prenom', 'Second prénom'], ['suffixe', 'Suffixe'], ['nom_naissance', 'Nom de naissance'],
                      ['phonetique_second_prenom', 'Second prénom phonétique'], ['dire_prenom', 'Prononciation du prénom'],
                      ['dire_nom', 'Prononciation du nom'], ['phonetique_societe', 'Nom de société phonétique']]
  function modifier() {
    brouillon = JSON.parse(JSON.stringify(donnees.fiche))
    brouillon.anniversaire = dateSaisie(brouillon.anniversaire)
    aSupprimer = false
    for (const k of ['mariage', 'deces']) brouillon[k] = dateSaisie(brouillon[k] || '')
    brouillon.fete = (brouillon.fete || '').startsWith('--') ? `${brouillon.fete.slice(5, 7)}/${brouillon.fete.slice(2, 4)}` : ''
    for (const k of ['service', 'prononciation_prenom', 'prononciation_nom', ...CHAMPS_224.map(([k]) => k)]) brouillon[k] = brouillon[k] || ''
    // 2.24 : dates libres saisies comme les autres (JJ/MM/AAAA, ou JJ/MM sans année)
    brouillon.dates_autres = (brouillon.dates_autres || []).map((d) => ({ ...d, valeur: d.valeur.startsWith('--') ? `${d.valeur.slice(5, 7)}/${d.valeur.slice(2, 4)}` : dateSaisie(d.valeur) }))
    brouillon.messageries = brouillon.messageries || []
    conjoint = donnees.famille?.conjoint || ''
    raisons = []
    apercu = null
  }
  async function verifier() {
    attente = true
    try { apercu = await api.post(`/api/contacts/${e}/apercu`, { fiche: brouillon }) } catch (err) { erreur(err) } finally { attente = false }
  }
  async function ecrire() {
    attente = true
    try {
      const res = await api.put(`/api/contacts/${e}`, { fiche: apercu.fiche, etag: donnees.etag,
                                                         conjoint: apercu.fiche.mariage ? conjoint : '' })
      brouillon = apercu = null
      raisons = res.raisons || []
      await apresEcriture(res, res.famille ? `Fiche écrite dans iCloud. ${res.famille}` : 'Fiche écrite dans iCloud.')
      await charger()
    } catch (err) { erreur(err) } finally { attente = false }
  }
  // Suppression : seulement depuis la modification, et toujours après une confirmation
  let aSupprimer = $state(false)
  async function supprimer() {
    attente = true
    try {
      const res = await api.post(`/api/contacts/${e}/supprimer`, { etag: donnees.etag, confirmation: true })
      brouillon = apercu = null
      aSupprimer = false
      aller('contacts')
      await apresEcriture(res, `${res.nom} : fiche supprimée d'iCloud.`)
    } catch (err) { erreur(err) } finally { attente = false }
  }
  async function chercherProches() {
    try { proches = await api.get(`/api/contacts/${e}/proches`) } catch (err) { erreur(err) }
  }
  async function lier(service, id) {
    try { await api.post(`/api/contacts/${e}/lier`, { service, id }); dire('Lié.'); proches = null; await charger() } catch (err) { erreur(err) }
  }
  async function delier(service) {
    try { await api.post(`/api/contacts/${e}/delier`, { service }); dire('Délié : cette personne ne sera plus proposée.'); await charger() }
    catch (err) { erreur(err) }
  }

  // Complétude et réseaux
  let reseau = $state('')        // réseau en cours d'ajout
  let profil = $state('')        // adresse, pseudo ou numéro
  let aDelier = $state(null)      // réseau dont le retrait attend confirmation
  async function poster(chemin, corps, messageOk) {
    attente = true
    try {
      // La version affichée part avec la demande : si la fiche a changé depuis, rien n'est fait
      const res = await api.post(`/api/contacts/${e}/${chemin}`, { ...corps, etag: donnees.etag })
      if (res?.jeton) await apresEcriture(res, messageOk)
      else { dire(messageOk); await rafraichirContacts() }
      reseau = profil = ''
      aDelier = null
      await charger()
    } catch (err) { erreur(err) } finally { attente = false }
  }
  const ajouterProfil = () => poster('profil', { service: reseau, valeur: profil }, `Profil ${PLATEFORMES[reseau].nom} ajouté.`)
  const delierReseau = (s) => poster('delier-reseau', { service: s }, `${PLATEFORMES[s].nom} délié : plus proposé pour cette fiche.`)
  // Adresse qui sera retirée de la carte (la confirmation la montre)
  const adresseReseau = (s) => (f?.sites || []).filter((x) => x.type === s).map((x) => x.valeur).join(', ')
  const AIDE = { facebook: 'facebook.com/…', instagram: 'Pseudo ou instagram.com/…', telegram: 'Pseudo ou t.me/…',
                 x: '@pseudo ou x.com/…' }

  const SERVICE = { immich: 'Immich', treemich: 'Treemich' }
  const candidatsReunir = $derived.by(() => {
    const q = reunir.trim().toLowerCase()
    if (q.length < 2) return []
    return (etat.contacts || []).filter((c) => c.uid !== uid && c.nom.toLowerCase().includes(q)).slice(0, 6)
  })
  const f = $derived(donnees?.fiche)
  const comp = $derived(donnees?.completude || {})
  const liees = $derived(comp.plateformes || [])
  const decede = $derived(!!donnees?.deces?.decede)
  const anneau = $derived(comp.total ? Math.round((comp.score / comp.total) * 100) : null)
  const alim = $derived(donnees?.alimentation)
  const tel = $derived(f?.telephones?.[0]?.valeur || '')
  const courriel = $derived(f?.courriels?.[0]?.valeur || '')
  const prononciation = $derived([f?.prononciation_prenom, f?.prononciation_nom].filter(Boolean).join(' '))
  const ORIGINE_FETE = { calendrier: 'd\'après le calendrier, pas encore écrite dans iCloud', main: 'saisie à la main', carte: '' }
  async function excepter(info, oui) {
    try {
      await api.post(`/api/contacts/${e}/exception`, { info, oui })
      dire(oui ? 'Noté : ce manque ne sera plus signalé pour ce contact.' : 'Ce manque est de nouveau signalé.')
      await Promise.all([charger(), rafraichirContacts()])
    } catch (err) { erreur(err) }
  }
  async function marquerDecede(oui) {
    try {
      await api.post(`/api/contacts/${e}/decede`, { oui })
      dire(oui ? 'Noté. Cette personne ne sera plus annoncée par Home Assistant.' : 'Marque retirée.')
      await Promise.all([charger(), rafraichirContacts()])
    } catch (err) { erreur(err) }
  }
  // 2.22 : genre (femme, homme, autre). Reste dans carnet ; écrit dans Treemich s'il y est inconnu.
  // Toucher le genre déjà choisi le retire.
  const genre = $derived(donnees?.genre || { valeur: '', origine: '', treemich: '', choix: {} })
  let genreEnCours = $state(false)
  async function choisirGenre(g) {
    genreEnCours = true
    try {
      const r = await api.post(`/api/contacts/${e}/genre`, { genre: genre.valeur === g && genre.origine === 'main' ? '' : g })
      dire(r.message)
      await charger()
    } catch (err) { erreur(err) } finally { genreEnCours = false }
  }
  // 3.6 : arbre de Sillage : cette personne n'est jamais montrée aux invités (visage, nom et dates masqués)
  async function masquerArbre(oui) {
    try {
      await api.put(`/api/arbre/masques/${encodeURIComponent(donnees.arbre.treemich)}`, { masque: oui })
      dire(oui ? 'Noté : jamais montrée aux invités dans l\'arbre de Sillage.' : 'De nouveau montrée aux invités (selon les règles).')
      await charger()
    } catch (err) { erreur(err) }
  }
  onMount(charger)
</script>

<section class="page">
  {#if !panneau}<a class="retour discret" href="#/contacts">Contacts</a>{/if}
  {#if !donnees}
    <p class="discret">Chargement…</p>
  {:else}
    <header class="entete" class:lecture-seule={!brouillon}>
      {#if brouillon}
        <!-- 2.10 : en modification, toucher la photo ouvre les propositions de photo et d'affiche -->
        <button class="changer-photo" onclick={() => (choixPhoto = true)} aria-label="Changer la photo ou l'affiche" title="Changer la photo ou l'affiche">
          <Avatar {uid} nom={donnees.nom} photo={f.a_photo} taille={84} />
          <span class="pastille-photo" aria-hidden="true">✎</span>
        </button>
      {:else}
        <!-- 3.1 (maquette A) : photo ronde avec l'anneau de complétude ; la toucher ouvre la tuile Photos -->
        <button class="photo-anneau" onclick={ouvrirPhotos} aria-label="Photos : choisir la photo du contact et l'affiche"
                title={anneau !== null ? `Fiche complète à ${anneau} %` : 'Photos'}>
          <svg class="anneau" viewBox="0 0 132 132" aria-hidden="true">
            <circle cx="66" cy="66" r="62" fill="none" stroke="var(--color-couture)" stroke-width="4" />
            {#if anneau !== null}
              <circle cx="66" cy="66" r="62" fill="none" stroke="var(--color-onglet)" stroke-width="4" stroke-linecap="round"
                      stroke-dasharray="389.6" stroke-dashoffset={389.6 * (1 - anneau / 100)} transform="rotate(-90 66 66)" />
            {/if}
          </svg>
          <span class="photo-dedans"><Avatar {uid} nom={donnees.nom} photo={f.a_photo} taille={112} /></span>
          <span class="pastille-appareil" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
          </span>
        </button>
      {/if}
      <div class="identite">
        <h1 class="titre">{#if decede}<span class="croix" title="Décédé(e)" aria-label="Décédé(e)">†</span>{' '}{/if}{donnees.nom}</h1>
        {#if prononciation}<p class="discret prononciation">{prononciation}</p>{/if}
        {#if f.societe || f.fonction || f.service}<p class="discret">{[f.fonction, f.service, f.societe].filter(Boolean).join(', ')}</p>{/if}
        {#if !brouillon && anneau !== null}<p class="discret petit">Fiche complète à {anneau} %</p>{/if}
        {#if f.groupes.length}<p class="groupes">{#each f.groupes as g}<span class="pastille">{g}</span>{/each}</p>{/if}
        {#if !brouillon && alim}
          <p class="badges">
            {#if alim.allergies?.length}<span class="badge-allergie">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 3l10 18H2z"/><path d="M12 10v5"/><path d="M12 18h.01"/></svg>
              Allergie : {alim.allergies.join(', ')}</span>{/if}
            {#if alim.intolerances?.length}<span class="pastille">Intolérance : {alim.intolerances.join(', ')}</span>{/if}
            {#if !alim.allergies?.length && !alim.intolerances?.length}<span class="pastille">{alim.aucune ? 'Aucune allergie connue' : 'Allergies : à demander'}</span>{/if}
          </p>
        {/if}
      </div>
      {#if !brouillon}
        <!-- Stylo : modifier les informations de la fiche -->
        <button class="stylo" onclick={modifier} aria-label="Modifier les informations" title="Modifier">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M16.9 3.6a2.1 2.1 0 0 1 3 3L8.4 18.1 4 19.5l1.4-4.4z" /><path d="M14.8 5.7l3 3" />
          </svg>
        </button>
      {/if}
    </header>

    {#if !brouillon && (tel || courriel)}
      <!-- 3.1 : actions comme sur l'iPhone -->
      <div class="actions">
        {#if tel}<a class="action" href={'tel:' + tel}>
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>Appeler</a>
        <a class="action" href={'sms:' + tel}>
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v11H8l-4 4z"/></svg>Message</a>{/if}
        {#if courriel}<a class="action" href={'mailto:' + courriel}>
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>Courriel</a>{/if}
      </div>
    {/if}

    {#if donnees.a_traiter.length}
      <div class="points">
        {#each donnees.a_traiter as p (p.id)}<Point point={p} ontraite={charger} />{/each}
      </div>
    {/if}

    {#if brouillon}
      <div class="feuille bloc">
        <Editeur bind:fiche={brouillon} bind:conjoint groupesConnus={donnees.groupes_connus} {uid} />
      </div>
      <div class="barre">
        {#if apercu}
          <div class="apercu">
            <h2 class="titre">Ce qui part dans iCloud</h2>
            <Changements champs={apercu.champs} />
            {#each apercu.notes || [] as n}<p class="note-saisie" role="note">{n}</p>{/each}
          </div>
          <div class="boutons">
            <button class="bouton" onclick={() => (apercu = null)}>Continuer à modifier</button>
            <button class="bouton bouton-principal" disabled={attente || !apercu.champs.length} onclick={ecrire}>
              {attente ? 'Écriture…' : 'Écrire dans iCloud'}</button>
          </div>
        {:else}
          <div class="boutons">
            <button class="bouton" onclick={() => (brouillon = null)}>Abandonner</button>
            <button class="bouton bouton-principal" disabled={attente} onclick={verifier}>{attente ? 'Vérification…' : 'Voir les changements'}</button>
          </div>
        {/if}
      </div>
      <div class="feuille bloc suppression">
        {#if !aSupprimer}
          <button class="bouton bouton-danger" disabled={attente} onclick={() => (aSupprimer = true)}>Supprimer cette fiche…</button>
        {:else}
          <div class="confirmer-suppression" role="alertdialog" aria-label="Confirmer la suppression">
            <p><strong>Supprimer {donnees.nom} ?</strong></p>
            <p class="discret">La fiche sera retirée d'iCloud, donc de l'iPhone et de tes autres appareils. Ses liaisons avec Immich et Treemich
              sont oubliées ; rien n'est supprimé dans Immich ni dans Treemich. Tu auras 10 secondes pour annuler ; ensuite, la sauvegarde
              du jour permet de la remettre (État, Sauvegardes).</p>
            <span class="boutons-gauche">
              <button class="bouton bouton-danger" disabled={attente} onclick={supprimer}>{attente ? 'Suppression…' : 'Supprimer définitivement'}</button>
              <button class="bouton" disabled={attente} onclick={() => (aSupprimer = false)}>Garder la fiche</button>
            </span>
          </div>
        {/if}
      </div>
    {:else}
      <div class="feuille bloc lecture">
        <div class="raccourcis">
          {#each f.telephones as t}<a class="bouton" href={'tel:' + t.valeur}>{t.affichage || t.valeur} <span class="discret">{t.type}</span></a>{/each}
          {#each f.courriels as c}<a class="bouton" href={'mailto:' + c.valeur}>{c.valeur}</a>{/each}
        </div>
        <dl>
          {#if f.anniversaire}<dt>Anniversaire</dt><dd>{dateLecture(f.anniversaire)}</dd>{/if}
          {#if donnees.fete?.date && !decede && (donnees.fete.attendue || donnees.fete.origine !== 'calendrier')}<dt>Fête</dt><dd>{dateLecture(donnees.fete.date)}{#if ORIGINE_FETE[donnees.fete.origine]}{' '}<span class="discret">({ORIGINE_FETE[donnees.fete.origine]})</span>{/if}</dd>{/if}
          {#if f.mariage}<dt>Mariage</dt><dd>{dateLecture(f.mariage)}
            <!-- 3.5 : pourquoi la date ne part pas vers Treemich, dit sur la fiche -->
            {#each (raisons.length ? raisons : donnees.famille?.raisons || []) as r}<span class="raison-famille">{r}</span>{/each}</dd>{/if}
          {#if decede}<dt>Décès</dt><dd>{donnees.deces.date ? dateLecture(donnees.deces.date) : 'date inconnue'}</dd>{/if}
          {#each f.dates_autres || [] as d}<dt>{d.type}</dt><dd>{dateLecture(d.valeur)}</dd>{/each}
          {#if f.surnom}<dt>Surnom</dt><dd>{f.surnom}</dd>{/if}
          {#each CHAMPS_224 as [cle, nom]}{#if f[cle]}<dt>{nom}</dt><dd>{f[cle]}</dd>{/if}{/each}
          {#each f.adresses as a}<dt>Adresse {a.type}</dt><dd>{[a.rue, `${a.cp} ${a.ville}`.trim(), a.pays].filter(Boolean).join(', ')}</dd>{/each}
          {#each f.noms_associes as n, i}<dt>{n.type}</dt><dd>{#if donnees.associes?.[i]}<a class="proche" href={'#/contacts/' + encodeURIComponent(donnees.associes[i])}>{n.valeur}</a>{:else}{n.valeur}{/if}</dd>{/each}
          {#each f.sites as s}<dt>{s.type}</dt><dd><a href={s.valeur} target="_blank" rel="noreferrer">{s.valeur}</a></dd>{/each}
          {#each f.messageries || [] as m}<dt>{m.type}</dt><dd>{m.valeur}</dd>{/each}
          {#if f.sonnerie}<dt>Sonnerie</dt><dd>{f.sonnerie} <span class="discret">(réglée sur l'iPhone)</span></dd>{/if}
          {#if f.son_sms}<dt>Son SMS</dt><dd>{f.son_sms} <span class="discret">(réglé sur l'iPhone)</span></dd>{/if}
          {#if f.notes}<dt>Notes</dt><dd class="notes">{f.notes}</dd>{/if}
        </dl>
        {#if f.prenom || f.nom}
          <div class="genre" role="group" aria-label="Genre">
            <span class="discret">Genre</span>
            {#each Object.entries(genre.choix) as [cle, nom]}
              <button class={'pastille genre-' + cle} aria-pressed={genre.valeur === cle} disabled={genreEnCours} onclick={() => choisirGenre(cle)}>{nom}</button>
            {/each}
            {#if genre.valeur && genre.origine === 'treemich'}<span class="discret petit">d'après Treemich</span>{/if}
            {#if genre.treemich}<span class="discret petit">Treemich dit « {genre.treemich} » : rien n'y est écrasé</span>{/if}
          </div>
        {/if}
      </div>

      {#if f.prenom || f.nom}
        <!-- 3.1 : dossier de la personne en grosses tuiles (Alimentation, Pépites, Livre d'or, Gazette, Famille, Photos) -->
        <div class="dossier" bind:this={dossier}>
          <Dossier {uid} {donnees} bind:section onchange={charger} onpropositions={() => (choixPhoto = true)} />
        </div>
      {/if}

      <div class="feuille bloc completude">
        <div class="ligne-titre">
          <h2 class="titre">Complétude</h2>
          {#if comp.statut === 'valide'}<span class="etat valide">Fiche validée</span>
          {:else if comp.statut === 'a_revoir'}<span class="etat revoir">Modifiée depuis la validation</span>{/if}
        </div>
        {#if decede}
          <p class="discret">Personne décédée : rien n'est attendu, rien n'est annoncé.</p>
        {:else if !comp.total}
          <p class="discret">{f.groupes.length ? "Les groupes de ce contact n'attendent aucune information." : "Ce contact n'est dans aucun groupe : rien n'est attendu de sa fiche."}</p>
        {:else}
          <p class="discret">Informations attendues par {f.groupes.length > 1 ? 'ses groupes' : 'son groupe'} : {comp.score} sur {comp.total}.</p>
          {#if comp.manques?.length}
            <ul class="manques">
              {#each comp.manques as m}
                <li><span class="pastille">{donnees.criteres[m]}</span>
                  <button class="bouton petit-bouton" onclick={() => excepter(m, true)}>Normal pour ce contact</button></li>
              {/each}
            </ul>
          {:else}
            <p class="discret">Rien ne manque.</p>
          {/if}
          {#if comp.exceptees?.length}
            <ul class="manques exceptees">
              {#each comp.exceptees as m}
                <li><span class="pastille exceptee">{donnees.criteres[m]}</span>
                  <button class="bouton petit-bouton" onclick={() => excepter(m, false)}>Signaler de nouveau</button></li>
              {/each}
            </ul>
          {/if}
        {/if}
        <div class="boutons-gauche">
          {#if comp.statut === 'valide'}
            <button class="bouton" disabled={attente} onclick={() => poster('devalider', {}, 'Validation retirée.')}>Retirer la validation</button>
          {:else}
            <button class="bouton bouton-principal" disabled={attente} onclick={() => poster('valider', {}, 'Fiche validée.')}>
              {comp.statut === 'a_revoir' ? 'Revalider' : 'Valider la fiche'}</button>
            {#if comp.statut === 'a_revoir'}
              <button class="bouton" disabled={attente} onclick={() => poster('devalider', {}, 'Validation retirée.')}>Retirer la validation</button>
            {/if}
          {/if}
        </div>
        {#if comp.statut !== 'valide' && comp.manques?.length}
          <p class="discret petit">Valider dit que la fiche est complète telle quelle : elle sort des filtres « Sans … ».</p>
        {/if}
        {#if !f.deces}
          <label class="case-deces"><input type="checkbox" checked={donnees.deces?.coche} onchange={(ev) => marquerDecede(ev.currentTarget.checked)} />
            <span>Personne décédée, date inconnue <span class="discret">(si tu connais la date, saisis-la dans la fiche)</span></span></label>
        {/if}
      </div>

      <div class="feuille bloc">
        <h2 class="titre">Plateformes</h2>
        <Plateformes liste={liees} toutes taille="grand" />
        <ul class="reseaux">
          {#each RESEAUX.filter((r) => liees.includes(r)) as r}
            <li class="liaison"><span>{PLATEFORMES[r].nom} <span class="discret">{adresseReseau(r)}</span></span>
              {#if aDelier !== r}
                <button class="bouton" disabled={attente} onclick={() => (aDelier = r)}>Délier</button>
              {/if}</li>
            {#if aDelier === r}
              <li class="confirmer">
                <p>{adresseReseau(r) ? `${adresseReseau(r)} sera retiré de la carte iCloud` : 'La liaison sera retirée'}, et cette personne ne sera plus proposée pour cette fiche.</p>
                <span class="boutons-gauche">
                  <button class="bouton bouton-danger" disabled={attente} onclick={() => delierReseau(r)}>Délier {PLATEFORMES[r].nom}</button>
                  <button class="bouton" onclick={() => (aDelier = null)}>Garder</button></span>
              </li>
            {/if}
          {/each}
        </ul>
        {#if RESEAUX.some((r) => !liees.includes(r))}
          <div class="ajout">
            <select bind:value={reseau} aria-label="Réseau à ajouter" onchange={() => (profil = reseau === 'whatsapp' ? (f.telephones[0]?.valeur || '') : '')}>
              <option value="">Ajouter un profil…</option>
              {#each RESEAUX.filter((r) => !liees.includes(r)) as r}<option value={r}>{PLATEFORMES[r].nom}</option>{/each}
            </select>
            {#if reseau === 'whatsapp'}
              {#if f.telephones.length}
                <select bind:value={profil} aria-label="Numéro WhatsApp">
                  {#each f.telephones as t}<option value={t.valeur}>{t.affichage || t.valeur}</option>{/each}
                </select>
              {:else}
                <p class="discret">Ajoute d'abord un numéro à la fiche.</p>
              {/if}
            {:else if reseau}
              <input type="text" bind:value={profil} placeholder={AIDE[reseau]} aria-label={'Profil ' + PLATEFORMES[reseau].nom}
                     autocapitalize="off" autocomplete="off" spellcheck="false" />
            {/if}
            {#if reseau}
              <button class="bouton bouton-principal" disabled={attente || !profil.trim()} onclick={ajouterProfil}>Ajouter</button>
            {/if}
          </div>
          {#if reseau}<p class="discret petit">Le profil est écrit dans la fiche iCloud (champ site), visible sur l'iPhone.</p>{/if}
        {/if}
      </div>

      <div class="feuille bloc">
        <h2 class="titre">Liaisons</h2>
        {#each Object.entries(donnees.liaisons) as [service, l]}
          <p class="liaison"><span>{SERVICE[service]} : {l.nom || l.id}{l.statut === 'auto' ? ' (liée seule la nuit)' : ''}</span>
            <button class="bouton" onclick={() => delier(service)}>Délier</button></p>
        {/each}
        {#if !donnees.liaisons.immich || !donnees.liaisons.treemich}
          {#if proches === null}
            <button class="bouton" onclick={chercherProches}>Chercher dans Immich et Treemich</button>
          {:else if !proches.length}
            <p class="discret">Aucune personne au nom proche.</p>
          {:else}
            {#each proches.filter((p) => !donnees.liaisons[p.service]) as p}
              <p class="liaison"><span>{SERVICE[p.service]} : {p.nom} <span class="discret">({p.score} %{p.naissance ? `, ${p.naissance.slice(0, 10)}` : ''})</span></span>
                <button class="bouton" onclick={() => lier(p.service, p.id)}>Lier</button></p>
            {/each}
          {/if}
        {/if}
        {#if donnees.arbre}
          <label class="liaison masque-arbre"><span>Jamais montrée aux invités dans l'arbre de Sillage</span>
            <input type="checkbox" checked={donnees.arbre.masque} onchange={(ev) => masquerArbre(ev.currentTarget.checked)} /></label>
        {/if}
        {#if donnees.sillage}<p class="liaison"><span>Son chemin de vie en photos</span>
          <a class="bouton" href={donnees.sillage} target="_blank" rel="noopener">Ouvrir dans Sillage</a></p>{/if}
        {#if donnees.linkedin}<p class="discret">LinkedIn : {[donnees.linkedin.fonction, donnees.linkedin.societe].filter(Boolean).join(', ') || donnees.linkedin.url}</p>{/if}
      </div>

      {#if !(f.prenom || f.nom)}
        <div class="feuille bloc">
          <h2 class="titre">Photo et affiche</h2>
          <PhotosFiche {uid} nom={donnees.nom} lieImmich={!!donnees.liaisons.immich} portraits={donnees.portraits}
                       affiche={donnees.affiche} societe={f.societe} google={donnees.google_logo} onchange={charger} />
        </div>
      {/if}

      <div class="feuille bloc">
        <h2 class="titre">Réunir avec une autre fiche</h2>
        <input type="search" bind:value={reunir} placeholder="Nom de l'autre fiche" aria-label="Autre fiche" />
        {#each candidatsReunir as c (c.uid)}
          <button class="bouton choix" onclick={() => aller('fusion', uid, c.uid)}>{c.nom}</button>
        {/each}
      </div>
    {/if}
  {/if}
  {#if donnees}<ChoixPhoto bind:ouvert={choixPhoto} {uid} nom={donnees.nom} onchange={charger} />{/if}
</section>

<style>
  .raison-famille { display: block; margin-top: 0.25rem; font-size: 0.85rem; color: var(--color-alerte); overflow-wrap: anywhere; }
  .page { max-width: 46rem; display: grid; gap: 1rem; }
  .retour { justify-self: start; min-height: 2.75rem; display: inline-flex; align-items: center; }
  .entete { display: flex; gap: 1rem; align-items: center; }
  .changer-photo { position: relative; padding: 0; border: 0; background: none; border-radius: 50%; cursor: pointer; flex: none; }
  .changer-photo:focus-visible { outline: 2px solid var(--color-onglet); outline-offset: 3px; }
  .pastille-photo { position: absolute; right: -2px; bottom: -2px; width: 1.7rem; height: 1.7rem; display: grid; place-items: center;
                    border-radius: 50%; background: var(--color-onglet); color: var(--color-reliure); font-size: 0.85rem; border: 2px solid var(--color-reliure); }
  .entete > div { flex: 1; min-width: 0; }
  /* 3.1 (maquette A) : en lecture, en-tête centré comme la fiche de l'iPhone */
  .entete.lecture-seule { flex-direction: column; text-align: center; position: relative; gap: 0.6rem; }
  .entete.lecture-seule .stylo { position: absolute; top: 0; right: 0; }
  .entete.lecture-seule .groupes, .entete.lecture-seule .badges { justify-content: center; }
  .photo-anneau { position: relative; width: 132px; height: 132px; padding: 0; border: 0; background: none; border-radius: 50%; cursor: pointer; flex: none; }
  .photo-anneau:focus-visible { outline: 2px solid var(--color-onglet); outline-offset: 3px; }
  .anneau { position: absolute; inset: 0; width: 100%; height: 100%; }
  .photo-dedans { position: absolute; inset: 10px; display: grid; place-items: center; }
  .pastille-appareil { position: absolute; right: 4px; bottom: 4px; width: 2.1rem; height: 2.1rem; display: grid; place-items: center;
                       border-radius: 50%; background: var(--color-onglet); color: var(--color-sur-onglet); border: 2px solid var(--color-cuir); }
  .identite h1 { font-weight: 300; }
  .badges { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
  .badge-allergie { display: inline-flex; align-items: center; gap: 0.35rem; min-height: 1.9rem; padding: 0 0.75rem; border-radius: 9999px;
                    font-size: 0.85rem; font-weight: 600; color: var(--color-alerte);
                    background: color-mix(in srgb, var(--color-alerte) 14%, transparent); border: 1px solid color-mix(in srgb, var(--color-alerte) 45%, transparent); }
  .actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(0, 1fr)); gap: 0.5rem; }
  .action { display: flex; flex-direction: column; align-items: center; gap: 0.3rem; padding: 0.7rem 0.4rem; min-height: 2.75rem;
            border-radius: 14px; background: var(--color-reliure); color: var(--color-onglet); text-decoration: none; font-size: 0.82rem; }
  .action:hover { background: color-mix(in srgb, var(--color-onglet) 10%, var(--color-reliure)); }
  .dossier { scroll-margin-top: 1rem; display: grid; gap: 0.75rem; }
  .stylo {
    flex: none; align-self: flex-start; display: grid; place-items: center; width: 2.75rem; height: 2.75rem;
    border-radius: 50%; border: 1px solid var(--color-tranche); color: var(--color-onglet);
  }
  .stylo:hover { border-color: var(--color-onglet); background: color-mix(in srgb, var(--color-onglet) 10%, transparent); }
  h1 { font-size: 1.9rem; line-height: 1.15; }
  h2 { font-size: 1.2rem; margin-bottom: 0.6rem; }
  .groupes { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.4rem; }
  .groupes .pastille { min-height: 1.6rem; font-size: 0.8rem; }
  .points { display: grid; gap: 0.6rem; }
  .bloc { padding: 1rem; }
  .lecture { display: grid; gap: 0.9rem; }
  .lecture > .bouton { justify-self: start; }
  .raccourcis { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  dl { display: grid; grid-template-columns: minmax(7rem, auto) 1fr; gap: 0.35rem 1rem; }
  dt { color: var(--color-mine); }
  dd { min-width: 0; overflow-wrap: anywhere; }
  .proche { color: inherit; text-decoration: underline; text-decoration-color: var(--color-onglet); text-underline-offset: 3px; display: inline-block; min-height: 1.75rem; }
  .proche:hover { color: var(--color-onglet); }
  .notes { white-space: pre-line; }
  .liaison { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; min-height: 2.75rem; }
  .ligne-titre { display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
  .completude { display: grid; gap: 0.7rem; }
  .completude h2 { margin-bottom: 0; }
  .etat { font-size: 0.85rem; font-weight: 600; }
  .etat.valide { color: var(--color-valide); }
  .etat.revoir { color: var(--color-alerte); }
  .manques { display: grid; gap: 0.35rem; }
  .manques li { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; flex-wrap: wrap; }
  .petit-bouton { min-height: 2rem; padding: 0 0.7rem; font-size: 0.82rem; }
  .exceptee { color: var(--color-champ); text-decoration: line-through; text-decoration-color: var(--color-tranche); }
  .croix { color: var(--color-mine); font-weight: 400; }
  .suppression { border-style: dashed; }
  .confirmer-suppression { display: grid; gap: 0.6rem; }
  .prononciation { font-style: italic; }
  .genre { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 0.5rem; margin-top: 0.8rem; }
  .case-deces { display: flex; align-items: flex-start; gap: 0.5rem; font-size: 0.9rem; }
  .manques .pastille { min-height: 1.8rem; font-size: 0.82rem; }
  .boutons-gauche { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .petit { font-size: 0.82rem; }
  .reseaux { margin-top: 0.4rem; }
  .reseaux .discret { font-size: 0.85rem; overflow-wrap: anywhere; }
  .confirmer { display: grid; gap: 0.5rem; padding: 0.75rem; margin: 0.25rem 0 0.5rem;
    border: 1px solid color-mix(in srgb, var(--color-alerte) 50%, transparent); border-radius: 8px; }
  .ajout { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; align-items: center; }
  .ajout select, .ajout input { flex: 1 1 12rem; width: auto; min-height: 2.75rem; }
  .choix { margin-top: 0.4rem; margin-right: 0.4rem; }
  .barre {
    position: sticky; bottom: calc(3.5rem + env(safe-area-inset-bottom)); z-index: 5; display: grid; gap: 0.7rem;
    padding: 0.8rem 1rem; background: var(--color-reliure); border: 1px solid var(--color-tranche); border-radius: 10px;
    box-shadow: 0 -6px 18px rgb(0 0 0 / 0.35);
  }
  .apercu { max-height: 45dvh; overflow-y: auto; }
  .boutons { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 0.5rem; }
  @media (min-width: 900px) { .barre { bottom: 1rem; } }
  .note-saisie { margin: 0.5rem 0 0; font-size: 0.9rem; color: var(--avertissement, #e9b54a); }
</style>
