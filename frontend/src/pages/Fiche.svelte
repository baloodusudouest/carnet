<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { aller, apresEcriture, erreur, dire, etat } from '../lib/etat.svelte.js'
  import Avatar from '../components/Avatar.svelte'
  import Changements from '../components/Changements.svelte'
  import Editeur from '../components/Editeur.svelte'
  import Point from '../components/Point.svelte'
  import PhotosFiche from '../components/PhotosFiche.svelte'

  let { uid } = $props()
  const e = encodeURIComponent(uid)
  let donnees = $state(null)
  let brouillon = $state(null)    // fiche en cours de modification
  let apercu = $state(null)       // { fiche, champs } avant d'écrire
  let attente = $state(false)
  let proches = $state(null)
  let reunir = $state('')

  async function charger() {
    try { donnees = await api.get(`/api/contacts/${e}`) } catch (err) { erreur(err) }
  }
  function modifier() { brouillon = JSON.parse(JSON.stringify(donnees.fiche)); apercu = null }
  async function verifier() {
    attente = true
    try { apercu = await api.post(`/api/contacts/${e}/apercu`, { fiche: brouillon }) } catch (err) { erreur(err) } finally { attente = false }
  }
  async function ecrire() {
    attente = true
    try {
      const res = await api.put(`/api/contacts/${e}`, { fiche: apercu.fiche })
      brouillon = apercu = null
      await apresEcriture(res, 'Fiche écrite dans iCloud.')
      await charger()
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

  const SERVICE = { immich: 'Immich', treemich: 'Treemich' }
  const candidatsReunir = $derived.by(() => {
    const q = reunir.trim().toLowerCase()
    if (q.length < 2) return []
    return (etat.contacts || []).filter((c) => c.uid !== uid && c.nom.toLowerCase().includes(q)).slice(0, 6)
  })
  const f = $derived(donnees?.fiche)
  onMount(charger)
</script>

<section class="page">
  <a class="retour discret" href="#/contacts">Contacts</a>
  {#if !donnees}
    <p class="discret">Chargement…</p>
  {:else}
    <header class="entete">
      <Avatar {uid} nom={donnees.nom} photo={f.a_photo} taille={84} />
      <div>
        <h1 class="titre">{donnees.nom}</h1>
        {#if f.societe || f.fonction}<p class="discret">{[f.fonction, f.societe].filter(Boolean).join(', ')}</p>{/if}
        {#if f.groupes.length}<p class="groupes">{#each f.groupes as g}<span class="pastille">{g}</span>{/each}</p>{/if}
      </div>
    </header>

    {#if donnees.a_traiter.length}
      <div class="points">
        {#each donnees.a_traiter as p (p.id)}<Point point={p} ontraite={charger} />{/each}
      </div>
    {/if}

    {#if brouillon}
      <div class="feuille bloc">
        <Editeur bind:fiche={brouillon} groupesConnus={donnees.groupes_connus} />
      </div>
      <div class="barre">
        {#if apercu}
          <div class="apercu">
            <h2 class="titre">Ce qui part dans iCloud</h2>
            <Changements champs={apercu.champs} />
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
    {:else}
      <div class="feuille bloc lecture">
        <div class="raccourcis">
          {#each f.telephones as t}<a class="bouton" href={'tel:' + t.valeur}>{t.affichage || t.valeur} <span class="discret">{t.type}</span></a>{/each}
          {#each f.courriels as c}<a class="bouton" href={'mailto:' + c.valeur}>{c.valeur}</a>{/each}
        </div>
        <dl>
          {#if f.anniversaire}<dt>Anniversaire</dt><dd>{f.anniversaire.startsWith('--') ? f.anniversaire.slice(2).split('-').reverse().join('/') : f.anniversaire.split('-').reverse().join('/')}</dd>{/if}
          {#if f.surnom}<dt>Surnom</dt><dd>{f.surnom}</dd>{/if}
          {#each f.adresses as a}<dt>Adresse {a.type}</dt><dd>{[a.rue, `${a.cp} ${a.ville}`.trim(), a.pays].filter(Boolean).join(', ')}</dd>{/each}
          {#each f.noms_associes as n}<dt>{n.type}</dt><dd>{n.valeur}</dd>{/each}
          {#each f.sites as s}<dt>{s.type}</dt><dd><a href={s.valeur} target="_blank" rel="noreferrer">{s.valeur}</a></dd>{/each}
          {#if f.notes}<dt>Notes</dt><dd class="notes">{f.notes}</dd>{/if}
        </dl>
        <button class="bouton bouton-principal" onclick={modifier}>Modifier</button>
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
        {#if donnees.linkedin}<p class="discret">LinkedIn : {[donnees.linkedin.fonction, donnees.linkedin.societe].filter(Boolean).join(', ') || donnees.linkedin.url}</p>{/if}
      </div>

      <div class="feuille bloc">
        <h2 class="titre">Photo et affiche</h2>
        <PhotosFiche {uid} nom={donnees.nom} lieImmich={!!donnees.liaisons.immich} portraits={donnees.portraits}
                     affiche={donnees.affiche} societe={f.societe} onchange={charger} />
      </div>

      <div class="feuille bloc">
        <h2 class="titre">Réunir avec une autre fiche</h2>
        <input type="search" bind:value={reunir} placeholder="Nom de l'autre fiche" aria-label="Autre fiche" />
        {#each candidatsReunir as c (c.uid)}
          <button class="bouton choix" onclick={() => aller('fusion', uid, c.uid)}>{c.nom}</button>
        {/each}
      </div>
    {/if}
  {/if}
</section>

<style>
  .page { max-width: 46rem; display: grid; gap: 1rem; }
  .retour { justify-self: start; min-height: 2.75rem; display: inline-flex; align-items: center; }
  .entete { display: flex; gap: 1rem; align-items: center; }
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
  .notes { white-space: pre-line; }
  .liaison { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; min-height: 2.75rem; }
  .choix { margin-top: 0.4rem; margin-right: 0.4rem; }
  .barre {
    position: sticky; bottom: calc(3.5rem + env(safe-area-inset-bottom)); z-index: 5; display: grid; gap: 0.7rem;
    padding: 0.8rem 1rem; background: var(--color-reliure); border: 1px solid var(--color-tranche); border-radius: 10px;
    box-shadow: 0 -6px 18px rgb(0 0 0 / 0.35);
  }
  .apercu { max-height: 45dvh; overflow-y: auto; }
  .boutons { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 0.5rem; }
  @media (min-width: 900px) { .barre { bottom: 1rem; } }
</style>
