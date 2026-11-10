<script>
  // Liste des contacts. iPhone : en-tête fixé en haut (recherche, tri, groupes) et index fin des
  // lettres sur le bord droit, qu'on peut parcourir du pouce. PC : liste à gauche, fiche à droite.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { etat, erreur, rafraichirAccueil, rafraichirContacts, dire, choisirTri } from '../lib/etat.svelte.js'
  import Avatar from '../components/Avatar.svelte'
  import BoutonAnneau from '../components/BoutonAnneau.svelte'
  import { de, envoyer, resumeImport } from '../lib/suivi.svelte.js'
  import Jauge from '../components/Jauge.svelte'
  import Plateformes from '../components/Plateformes.svelte'
  import Fiche from './Fiche.svelte'

  let { selection = null } = $props()
  let recherche = $state('')
  let groupe = $state(null)
  let manque = $state(null)   // filtre de complétude
  let groupes = $state([])
  let menuGroupes = $state(false)
  let hautEntete = $state(0)
  let liste = $state(null)

  const ALPHABET = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '#']
  const sansAccent = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  // Clé de tri : prénom puis nom, ou nom puis prénom ; une fiche d'entreprise se range à sa société
  const cle = (c) => sansAccent(etat.tri === 'nom'
    ? `${c.nom_famille || c.prenom || c.societe || c.nom} ${c.prenom}`
    : `${c.prenom || c.nom_famille || c.societe || c.nom} ${c.nom_famille}`).trim()
  const lettre = (c) => {
    const l = cle(c).charAt(0).toUpperCase()
    return /[A-Z]/.test(l) ? l : '#'
  }
  // Filtres de complétude : une fiche validée ne compte plus dans les « Sans … »
  const MANQUES = [
    { cle: 'annee', libelle: 'Sans année' }, { cle: 'adresse', libelle: 'Sans adresse' },
    { cle: 'telephone', libelle: 'Sans téléphone' }, { cle: 'contact', libelle: 'Sans moyen de contact' },
    { cle: 'a_revoir', libelle: 'À revoir' }, { cle: 'valide', libelle: 'Validées' },
  ]
  const correspond = (c, m) => m === 'a_revoir' ? c.statut === 'a_revoir' : m === 'valide' ? c.statut === 'valide'
    : (c.manques || []).includes(m) && c.statut !== 'valide'
  const nombres = $derived(Object.fromEntries(MANQUES.map((m) => [m.cle, (etat.contacts || []).filter((c) => correspond(c, m.cle)).length])))
  const filtres = $derived.by(() => {
    const q = sansAccent(recherche.trim())
    const chiffres = recherche.replace(/\D/g, '')
    return (etat.contacts || []).filter((c) => (!groupe || c.groupes.includes(groupe)) && (!manque || correspond(c, manque)) && (!q ||
      sansAccent(`${c.nom} ${c.societe} ${c.fonction} ${c.courriel}`).includes(q) ||
      (chiffres.length >= 3 && c.valeur_tel.replace(/\D/g, '').includes(chiffres.replace(/^0/, '')))))
  })
  const sections = $derived.by(() => {
    const res = new Map()
    for (const c of [...filtres].sort((a, b) => cle(a).localeCompare(cle(b), 'fr'))) {
      const l = lettre(c)
      if (!res.has(l)) res.set(l, [])
      res.get(l).push(c)
    }
    return [...res.entries()].sort(([a], [b]) => (a === '#') - (b === '#') || a.localeCompare(b))
  })
  const presentes = $derived(new Set(sections.map(([l]) => l)))

  function sauter(l) {
    // Lettre absente : la suivante présente
    const cible = ALPHABET.slice(ALPHABET.indexOf(l)).find((x) => presentes.has(x))
    const el = cible && document.getElementById('lettre-' + cible)
    if (!el) return
    if (etat.large && liste) liste.scrollTo({ top: el.offsetTop - liste.offsetTop })
    else el.scrollIntoView({ block: 'start' })
  }
  // Index du pouce : glisser le long des lettres fait défiler la liste
  function parcourir(e) {
    const el = document.elementFromPoint(e.clientX, e.clientY)
    if (el?.dataset?.lettre) sauter(el.dataset.lettre)
  }

  async function importer(fichier) {
    try { dire(resumeImport(await envoyer('import', fichier))); rafraichirAccueil() } catch (err) { erreur(err) }
  }

  onMount(async () => {
    try {
      if (!etat.contacts) await rafraichirContacts()
      groupes = (await api.get('/api/groupes')).filter((g) => g.nombre)
    } catch (e) { erreur(e) }
  })
</script>

<svelte:window onclick={(e) => { if (menuGroupes && !e.target.closest?.('.menu')) menuGroupes = false }} />

<div class="contacts" class:large={etat.large} style:--haut-entete="{hautEntete}px">
  <section class="volet-liste">
    <div class="entete" bind:clientHeight={hautEntete}>
      <div class="ligne-titre">
        <h1 class="titre">Contacts <span class="discret nombre">{filtres.length !== (etat.contacts?.length ?? 0) ? `${filtres.length} / ` : ''}{etat.contacts?.length ?? ''}</span></h1>
        <BoutonAnneau compact icone="envoyer" libelle="Importer" enCours="Envoi…" {...de('import')}
                      fichier=".vcf,.vcard,.csv,.zip,.json,text/vcard,text/csv,application/zip,application/json" onfichier={importer} />
      </div>
      <input class="recherche" type="search" placeholder="Nom, société, numéro…" bind:value={recherche} aria-label="Chercher un contact" />
      <div class="outils">
        <div class="tri" role="group" aria-label="Trier par">
          <button aria-pressed={etat.tri === 'prenom'} onclick={() => choisirTri('prenom')}>Prénom</button>
          <button aria-pressed={etat.tri === 'nom'} onclick={() => choisirTri('nom')}>Nom</button>
        </div>
        {#if groupes.length}
          <div class="menu">
            <button class="pastille" aria-pressed={!!groupe} aria-expanded={menuGroupes} onclick={() => (menuGroupes = !menuGroupes)}>
              {groupe || 'Groupes'} <span aria-hidden="true">▾</span>
            </button>
            {#if menuGroupes}
              <div class="panneau-groupes feuille" role="menu">
                <button role="menuitemradio" aria-checked={!groupe} onclick={() => { groupe = null; menuGroupes = false }}>
                  Tous les contacts <span class="discret">{etat.contacts?.length}</span></button>
                {#each groupes as g}
                  <button role="menuitemradio" aria-checked={groupe === g.nom} onclick={() => { groupe = g.nom; menuGroupes = false }}>
                    {g.nom} <span class="discret">{g.nombre}</span></button>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
      </div>
      {#if etat.contacts?.length}
        <div class="manques" role="group" aria-label="Filtrer par complétude">
          {#each MANQUES.filter((m) => nombres[m.cle] || manque === m.cle) as m}
            <button class="pastille" aria-pressed={manque === m.cle} onclick={() => (manque = manque === m.cle ? null : m.cle)}>
              {m.libelle} <span class="discret">{nombres[m.cle]}</span></button>
          {/each}
        </div>
      {/if}
    </div>

    {#if !etat.contacts}
      <p class="discret">Chargement…</p>
    {:else if !filtres.length}
      <p class="discret vide">Aucun contact ne correspond{recherche ? ` à « ${recherche} »` : ''}.</p>
    {:else}
      <div class="carnet">
        <div class="liste" bind:this={liste}>
          {#each sections as [l, membres] (l)}
            <!-- Une section par lettre : son titre reste collé en haut jusqu'à la lettre suivante -->
            <section class="groupe-lettre">
            <h2 id={'lettre-' + l} class="lettre titre">{l}</h2>
            <ul>
              {#each membres as c (c.uid)}
                <li>
                  <a class="ligne" href={'#/contacts/' + encodeURIComponent(c.uid)} aria-current={selection === c.uid ? 'true' : undefined}>
                    <Jauge score={c.score} statut={c.statut}><Avatar uid={c.uid} nom={c.nom} photo={c.a_photo} /></Jauge>
                    <span class="texte">
                      <span class="nom">{c.nom}{#if c.a_traiter}<span class="marque" aria-label="À traiter"></span>{/if}</span>
                      <span class="discret detail">{[c.societe, c.telephone].filter(Boolean).join(', ')}</span>
                    </span>
                    <Plateformes liste={c.plateformes} />
                  </a>
                </li>
              {/each}
            </ul>
            </section>
          {/each}
        </div>
        {#if etat.large}
          <!-- PC : la tranche du carnet, une lettre par onglet -->
          <nav class="tranche" aria-label="Aller à la lettre">
            {#each sections as [l]}<button onclick={() => sauter(l)}>{l}</button>{/each}
          </nav>
        {:else}
          <!-- iPhone : index fin, à parcourir du pouce comme dans Contacts -->
          <nav class="index" aria-label="Aller à la lettre"
               onpointerdown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); parcourir(e) }}
               onpointermove={(e) => e.buttons && parcourir(e)}>
            {#each ALPHABET as l}
              <button data-lettre={l} class:absente={!presentes.has(l)} onclick={() => sauter(l)} tabindex={presentes.has(l) ? 0 : -1}>{l}</button>
            {/each}
          </nav>
        {/if}
      </div>
    {/if}
  </section>

  {#if etat.large}
    <section class="volet-fiche">
      {#if selection}
        {#key selection}<Fiche uid={selection} panneau />{/key}
      {:else}
        <p class="discret vide">Choisis un contact dans la liste.</p>
      {/if}
    </section>
  {/if}
</div>

<style>
  .contacts { max-width: 46rem; }
  .entete {
    position: sticky; z-index: 6; top: env(safe-area-inset-top); background: var(--color-cuir);
    padding: 0.25rem 0 0.6rem; display: grid; gap: 0.6rem;
  }
  .ligne-titre { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }
  h1 { font-size: 1.9rem; }
  .nombre { font-family: var(--font-sans); font-size: 1rem; font-weight: 400; }
  .outils { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; }
  .tri { display: inline-flex; border: 1px solid var(--color-couture); border-radius: 9999px; padding: 2px; }
  .tri button { min-height: 2.5rem; padding: 0 1rem; border-radius: 9999px; color: var(--color-mine); font-size: 0.9rem; }
  .tri button[aria-pressed='true'] { background: color-mix(in srgb, var(--color-onglet) 16%, transparent); color: var(--color-papier); }
  .menu { position: relative; }
  .panneau-groupes {
    position: absolute; right: 0; top: calc(100% + 0.35rem); z-index: 10; min-width: 15rem; max-height: 60dvh; overflow-y: auto;
    display: grid; padding: 0.3rem; box-shadow: 0 10px 28px rgb(0 0 0 / 0.5);
  }
  .panneau-groupes button {
    display: flex; justify-content: space-between; gap: 1rem; text-align: left; min-height: 2.75rem; padding: 0 0.75rem; border-radius: 6px;
  }
  .panneau-groupes button[aria-checked='true'] { color: var(--color-onglet); }
  .panneau-groupes button:hover { background: var(--color-cuir); }
  .carnet { display: grid; grid-template-columns: 1fr auto; gap: 0.25rem; }
  .lettre {
    position: sticky; z-index: 1; top: calc(env(safe-area-inset-top) + var(--haut-entete)); background: var(--color-cuir);
    color: var(--color-onglet); font-size: 1.15rem; padding: 0.4rem 0 0.2rem; border-bottom: 1px solid var(--color-couture);
    scroll-margin-top: calc(env(safe-area-inset-top) + var(--haut-entete));
  }
  .ligne { display: flex; align-items: center; gap: 0.6rem; min-height: 3.5rem; padding: 0.3rem 0.25rem; border-radius: 8px; }
  .ligne:hover, .ligne[aria-current] { background: var(--color-reliure); }
  .ligne[aria-current] { box-shadow: inset 3px 0 0 var(--color-onglet); }
  .texte { display: grid; min-width: 0; flex: 1; }
  .manques { display: flex; gap: 0.35rem; overflow-x: auto; scrollbar-width: none; margin-right: -0.25rem; }
  .manques .pastille { flex: none; min-height: 2.25rem; font-size: 0.82rem; }
  .ligne :global(.plateformes) { flex: none; max-width: 5.5rem; justify-content: flex-end; }
  .nom { font-family: var(--font-livre); font-size: 1.05rem; display: flex; align-items: center; gap: 0.45rem; }
  .detail { font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .marque { width: 0.45rem; height: 0.45rem; border-radius: 50%; background: var(--color-onglet); flex: none; }
  .vide { padding: 2rem 0; }

  /* iPhone : index fin, fixé sur le bord droit, sous l'en-tête */
  .index {
    position: fixed; z-index: 7; right: 2px; top: calc(env(safe-area-inset-top) + var(--haut-entete) + 0.5rem);
    bottom: calc(3.75rem + env(safe-area-inset-bottom)); display: flex; flex-direction: column; justify-content: center;
    touch-action: none; padding: 0 2px;
  }
  .index button {
    flex: 1; max-height: 1.35rem; width: 1.4rem; font-size: 0.68rem; font-weight: 600; color: var(--color-onglet);
    display: grid; place-items: center;
  }
  .index button.absente { color: var(--color-tranche); }
  .liste { padding-right: 1.1rem; }

  /* PC : deux volets, la liste défile seule */
  .contacts.large { max-width: none; display: grid; grid-template-columns: minmax(20rem, 26rem) minmax(0, 1fr); gap: 2rem; }
  .large .volet-liste { position: sticky; top: 1.75rem; height: calc(100dvh - 3.5rem); display: flex; flex-direction: column; min-height: 0; }
  .large .entete { position: static; }
  .large .carnet { flex: 1; min-height: 0; }
  .large .liste { overflow-y: auto; padding-right: 0.25rem; }
  .large .lettre { top: 0; scroll-margin-top: 0; }
  .large .volet-fiche { min-width: 0; }
  .tranche { display: flex; flex-direction: column; overflow-y: auto; scrollbar-width: none; }
  .tranche button {
    width: 2rem; min-height: 1.6rem; font-family: var(--font-livre); font-weight: 600; font-size: 0.85rem;
    color: #23190a; background: var(--color-onglet); border-radius: 0 6px 6px 0; margin-bottom: 2px;
    box-shadow: inset 3px 0 0 rgb(0 0 0 / 0.18);
  }
  .tranche button:nth-child(even) { background: #c8953a; }
</style>
