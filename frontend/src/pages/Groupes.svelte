<script>
  // Groupes (2.9) : voir les groupes et leurs membres, ajouter ou retirer des contacts par lot,
  // créer, renommer, supprimer un groupe. Supprimer un groupe ne supprime aucune fiche.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { apresEcriture, dire, erreur, etat, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  import Avatar from '../components/Avatar.svelte'

  let groupes = $state(null)
  let choisi = $state(null)       // nom du groupe ouvert
  let membres = $state([])
  let coches = $state(new Set())
  let attente = $state(false)
  let nouveau = $state('')
  let renomme = $state(null)      // nouveau nom en cours de saisie
  let aSupprimer = $state(false)
  let recherche = $state('')

  const groupe = $derived(groupes?.find((g) => g.nom === choisi))
  const sansAccent = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  const candidats = $derived.by(() => {
    const q = sansAccent(recherche.trim())
    if (q.length < 2) return []
    const dedans = new Set(membres.map((m) => m.uid))
    return (etat.contacts || []).filter((c) => !dedans.has(c.uid) && sansAccent(`${c.nom} ${c.societe}`).includes(q)).slice(0, 8)
  })

  async function charger() {
    try { groupes = await api.get('/api/groupes-detail') } catch (e) { erreur(e) }
  }
  async function ouvrir(nom) {
    choisi = nom; coches = new Set(); renomme = null; aSupprimer = false; recherche = ''
    try { membres = await api.get(`/api/groupes/${encodeURIComponent(nom)}/membres`) } catch (e) { erreur(e) }
  }
  async function creer() {
    attente = true
    try {
      const r = await api.post('/api/groupes-creer', { nom: nouveau })
      dire(`Groupe « ${r.nom} » créé dans iCloud.`); nouveau = ''
      await charger(); ouvrir(r.nom)
    } catch (e) { erreur(e) } finally { attente = false }
  }
  async function changer(uids, action) {
    attente = true
    try {
      const r = await api.post(`/api/groupes/${encodeURIComponent(choisi)}/membres`, { uids, action })
      dire(`${r.faits} contact(s) ${action === 'ajouter' ? 'ajouté(s) au' : 'retiré(s) du'} groupe`
        + (r.restants ? `, ${r.restants} restent : recommence` : '') + (r.erreurs.length ? ` ; ${r.erreurs[0]}` : '') + '.')
      recherche = ''
      await Promise.all([charger(), ouvrir(choisi), rafraichirContacts(), rafraichirAccueil()])
    } catch (e) { erreur(e) } finally { attente = false }
  }
  async function renommer() {
    attente = true
    try {
      const r = await api.post(`/api/groupes/${encodeURIComponent(choisi)}/renommer`, { nouveau: renomme })
      dire(`Groupe renommé « ${r.nom} ».`)
      await Promise.all([charger(), rafraichirContacts()]); ouvrir(r.nom)
    } catch (e) { erreur(e) } finally { attente = false }
  }
  async function supprimer() {
    attente = true
    try {
      const r = await api.post(`/api/groupes/${encodeURIComponent(choisi)}/supprimer`, { confirmation: true })
      choisi = null; aSupprimer = false
      await apresEcriture(r, `Groupe « ${r.nom} » retiré d'iCloud. Aucune fiche n'a été supprimée.`)
      await charger()
    } catch (e) { erreur(e) } finally { attente = false }
  }
  function basculer(uid) {
    const s = new Set(coches)
    s.has(uid) ? s.delete(uid) : s.add(uid)
    coches = s
  }
  onMount(async () => { await charger(); if (!etat.contacts) rafraichirContacts() })
</script>

<section class="page">
  <h1 class="titre">Groupes</h1>
  {#if !groupes}
    <p class="discret">Chargement…</p>
  {:else}
    <div class="deux" class:ouvert={!!choisi}>
      <div class="colonne liste-groupes">
        <ul>
          {#each groupes as g (g.nom)}
            <li><button class="ligne-groupe" aria-current={choisi === g.nom ? 'true' : undefined} onclick={() => ouvrir(g.nom)}>
              <span class="nom">{g.nom}</span><span class="nombre">{g.nombre}</span></button></li>
          {/each}
        </ul>
        <form class="creer" onsubmit={(e) => { e.preventDefault(); creer() }}>
          <input bind:value={nouveau} placeholder="Nouveau groupe" aria-label="Nom du nouveau groupe" autocomplete="off" />
          <button class="bouton" disabled={attente || !nouveau.trim()}>Créer</button>
        </form>
      </div>

      {#if groupe}
        <div class="colonne feuille bloc detail">
          <div class="entete">
            <button class="bouton retour" onclick={() => (choisi = null)}>‹ Groupes</button>
            <h2 class="titre">{groupe.nom} <span class="discret">{groupe.nombre}</span></h2>
          </div>
          <p class="discret">{groupe.attentes ? `${groupe.attentes} information(s) attendue(s) pour ce groupe` : 'Aucune information attendue'} : à régler dans <a href="#/connexion">Connexion</a>, icône Attentes.
            {#if groupe.integre} Groupe d'origine de carnet : il ne se renomme pas et ne se supprime pas.{/if}</p>

          <label class="ajout"><span class="discret">Ajouter un contact</span>
            <input type="search" bind:value={recherche} placeholder="Nom ou société" autocomplete="off" /></label>
          {#each candidats as c (c.uid)}
            <button class="bouton candidat" disabled={attente} onclick={() => changer([c.uid], 'ajouter')}>{c.nom}{c.societe && c.societe !== c.nom ? ` — ${c.societe}` : ''}</button>
          {/each}

          {#if !membres.length}
            <p class="discret">Ce groupe est vide.</p>
          {:else}
            <div class="outils">
              <button class="bouton" onclick={() => (coches = coches.size ? new Set() : new Set(membres.slice(0, 20).map((m) => m.uid)))}>
                {coches.size ? 'Tout décocher' : membres.length > 20 ? 'Cocher les 20 premiers' : 'Tout cocher'}</button>
              <button class="bouton" disabled={attente || !coches.size} onclick={() => changer([...coches], 'retirer')}>Retirer du groupe ({coches.size})</button>
            </div>
            <ul class="membres">
              {#each membres as m (m.uid)}
                <li><label><input type="checkbox" checked={coches.has(m.uid)} onchange={() => basculer(m.uid)} aria-label={'Cocher ' + m.nom} />
                  <Avatar uid={m.uid} nom={m.nom} photo={m.a_photo} taille={32} />
                  <a href={'#/contacts/' + encodeURIComponent(m.uid)}>{m.nom}</a></label></li>
              {/each}
            </ul>
          {/if}

          {#if !groupe.integre && groupe.dans_icloud}
            <div class="gestion">
              {#if renomme === null}
                <button class="bouton" disabled={attente} onclick={() => { renomme = groupe.nom; aSupprimer = false }}>Renommer</button>
              {:else}
                <form class="creer" onsubmit={(e) => { e.preventDefault(); renommer() }}>
                  <input bind:value={renomme} aria-label="Nouveau nom du groupe" autocomplete="off" />
                  <button class="bouton bouton-principal" disabled={attente || !renomme.trim() || renomme.trim() === groupe.nom}>Renommer</button>
                  <button type="button" class="bouton" onclick={() => (renomme = null)}>Annuler</button>
                </form>
              {/if}
              {#if !aSupprimer}
                <button class="bouton bouton-danger" disabled={attente} onclick={() => { aSupprimer = true; renomme = null }}>Supprimer ce groupe…</button>
              {:else}
                <div class="confirmer-suppression" role="alertdialog" aria-label="Confirmer la suppression du groupe">
                  <p><strong>Supprimer le groupe {groupe.nom} ?</strong></p>
                  <p class="discret">Le groupe sera retiré d'iCloud, donc de l'iPhone. Ses {groupe.nombre} contact(s) restent dans le carnet : aucune fiche n'est supprimée.
                    Ses attentes sont oubliées. Tu auras 10 secondes pour annuler.</p>
                  <span class="outils">
                    <button class="bouton bouton-danger" disabled={attente} onclick={supprimer}>Supprimer le groupe</button>
                    <button class="bouton" onclick={() => (aSupprimer = false)}>Garder le groupe</button></span>
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {:else if etat.large}
        <p class="discret colonne">Choisis un groupe pour voir ses contacts.</p>
      {/if}
    </div>
  {/if}
</section>

<style>
  .page { display: grid; gap: 1rem; max-width: 64rem; }
  h1 { font-size: 1.9rem; }
  h2 { font-size: 1.25rem; }
  .deux { display: grid; gap: 1rem; }
  .deux.ouvert .liste-groupes { display: none; }
  .ligne-groupe { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 1rem; min-height: 3rem; padding: 0 0.6rem;
    text-align: left; border-top: 1px solid var(--color-couture); }
  .ligne-groupe[aria-current='true'] { background: var(--color-reliure); border-radius: 8px; }
  .ligne-groupe .nom { font-weight: 600; }
  .nombre { color: var(--color-mine); font-variant-numeric: tabular-nums; }
  .creer { display: flex; gap: 0.4rem; margin-top: 0.8rem; flex-wrap: wrap; }
  .creer input { flex: 1; min-width: 10rem; }
  .bloc { padding: 1rem; display: grid; gap: 0.7rem; align-content: start; }
  .bloc a { text-decoration: underline; text-underline-offset: 3px; }
  .entete { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
  .ajout { display: grid; gap: 0.2rem; }
  .candidat { justify-content: flex-start; text-align: left; }
  .outils { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .membres { display: grid; max-height: 60vh; overflow-y: auto; }
  .membres label { display: flex; align-items: center; gap: 0.6rem; min-height: 2.9rem; border-top: 1px solid var(--color-couture); }
  .membres input { width: 1.2rem; height: 1.2rem; accent-color: var(--color-onglet); flex: none; }
  .gestion { display: grid; gap: 0.6rem; justify-items: start; padding-top: 0.8rem; border-top: 1px dashed var(--color-tranche); }
  .confirmer-suppression { display: grid; gap: 0.5rem; }
  @media (min-width: 900px) {
    .deux, .deux.ouvert { grid-template-columns: 18rem minmax(0, 1fr); align-items: start; }
    .deux.ouvert .liste-groupes { display: block; }
    .retour { display: none; }
  }
</style>
