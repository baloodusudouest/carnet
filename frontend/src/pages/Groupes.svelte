<script>
  import { api } from '../lib/api.js'
  import { ref, annoncer } from '../lib/etat.svelte.js'
  import { pluriel, rechercheLinkedin } from '../lib/cles.js'

  // Groupes intégrés (règles fixes, non modifiables) et groupes créés à la main.
  const REGLES = [
    { cle: '', nom: 'Aucune règle' },
    { cle: 'proches', nom: 'Proches : un seul portable → mobile' },
    { cle: 'travail', nom: 'Travail : portable → travail, fixe → bureau' },
  ]
  const libelleRegle = (r) => ({ proches: 'proches', travail: 'travail' })[r] ?? '—'

  let groupes = $state([])
  let nouveau = $state({ nom: '', regle: '' })
  let edition = $state(null)      // { ancien, nom, regle }
  let suppression = $state(null)  // { nom, nb, vers }
  let occupe = $state(false)

  // LinkedIn des membres d'un groupe : vert si le profil est déjà dans la fiche,
  // sinon recherche sur linkedin.com et adresse du profil à coller ici
  let groupeLi = $state(null)
  let contacts = $state(null)
  let profils = $state({})          // pid → adresse collée
  async function ouvrirLinkedin(g) {
    groupeLi = groupeLi === g ? null : g
    if (groupeLi && !contacts) contacts = await api.get('/api/contacts')
  }
  const membres = $derived(contacts && groupeLi
    ? contacts.filter((p) => p.statut !== 'ecarte' && p.groupes.includes(groupeLi)) : [])
  async function ajouterProfil(p) {
    try {
      const r = await api.post(`/api/personnes/${p.id}/linkedin`, { url: profils[p.id] ?? '' })
      p.linkedin = r.linkedin
      profils[p.id] = ''
      annoncer(`Profil LinkedIn ajouté à ${p.nom}${p.statut === 'verifie' ? ' (iCloud suivra à la prochaine écriture)' : ''}.`)
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  async function charger() {
    groupes = await api.get('/api/groupes')
    Object.assign(ref, await api.get('/api/config'))
  }
  charger()

  async function agir(chemin, corps, message) {
    occupe = true
    try {
      const r = await api.post(chemin, corps)
      annoncer(message(r))
      edition = suppression = null
      await charger()
      return true
    } catch (e) {
      annoncer(e.message, true)
      return false
    } finally {
      occupe = false
    }
  }

  async function creer(e) {
    e.preventDefault()
    if (await agir('/api/groupes', { nom: nouveau.nom, regle: nouveau.regle || null }, (r) => `Groupe « ${r.nom} » créé.`))
      nouveau = { nom: '', regle: '' }
  }
</script>

<div class="max-w-4xl">
  <h1 class="titre text-3xl mb-2">Groupes</h1>
  <p class="text-mine mb-6">
    Les groupes intégrés portent les règles de carnet et ne se modifient pas. Ceux que tu crées se renomment ou se
    suppriment ici. iCloud suit à la prochaine écriture : un groupe renommé y est recréé sous son nouveau nom.
  </p>

  <form class="rounded-xl border border-couture bg-reliure p-5 mb-8 flex flex-wrap items-end gap-3" onsubmit={creer}>
    <label class="flex flex-col gap-1 text-sm text-mine">Nouveau groupe
      <input class="w-56" maxlength="40" bind:value={nouveau.nom} placeholder="ex. Rugby, Voisins…" />
    </label>
    <label class="flex flex-col gap-1 text-sm text-mine">Règle des téléphones
      <select bind:value={nouveau.regle}>{#each REGLES as r}<option value={r.cle}>{r.nom}</option>{/each}</select>
    </label>
    <button class="bouton bouton-principal" disabled={occupe || !nouveau.nom.trim()}>Créer</button>
  </form>

  <ul class="rounded-xl border border-couture divide-y divide-couture overflow-hidden">
    {#each groupes as g (g.nom)}
      <li class="px-4 py-3">
        {#if edition?.ancien === g.nom}
          <form class="flex flex-wrap items-center gap-3"
            onsubmit={(e) => { e.preventDefault(); agir('/api/groupes/modifier', { ancien: g.nom, nom: edition.nom, regle: edition.regle || null },
              (r) => `Groupe enregistré${r.contacts ? ` (${pluriel(r.contacts, 'contact mis à jour', 'contacts mis à jour')})` : ''}.`) }}>
            <input class="w-56" maxlength="40" bind:value={edition.nom} aria-label="Nom du groupe" />
            <select bind:value={edition.regle} aria-label="Règle">{#each REGLES as r}<option value={r.cle}>{r.nom}</option>{/each}</select>
            <button class="bouton bouton-principal !py-1" disabled={occupe || !edition.nom.trim()}>Enregistrer</button>
            <button type="button" class="text-sm text-mine hover:text-papier" onclick={() => (edition = null)}>Annuler</button>
          </form>
        {:else if suppression?.nom === g.nom}
          <div class="flex flex-wrap items-center gap-3">
            <span>Supprimer <strong>{g.nom}</strong> ?</span>
            {#if g.nb}
              <label class="text-sm text-mine">Ses {pluriel(g.nb, 'contact', 'contacts')} vont dans
                <select class="ml-1" bind:value={suppression.vers}>
                  <option value="">aucun groupe</option>
                  {#each ref.groupes.filter((x) => x !== g.nom) as autre}<option value={autre}>{autre}</option>{/each}
                </select>
              </label>
            {/if}
            <button class="bouton !py-1 !border-alerte !text-alerte" disabled={occupe}
              onclick={() => agir('/api/groupes/supprimer', { nom: g.nom, vers: suppression.vers || null },
                (r) => `Groupe supprimé${r.contacts ? `, ${pluriel(r.contacts, 'contact déplacé', 'contacts déplacés')}` : ''}.`)}>Supprimer</button>
            <button class="text-sm text-mine hover:text-papier" onclick={() => (suppression = null)}>Annuler</button>
          </div>
        {:else}
          <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span class="w-56 truncate {g.fixe ? 'text-mine' : 'text-papier'}">{g.nom}</span>
            <span class="text-xs text-mine w-24">règle : {libelleRegle(g.regle)}</span>
            <span class="text-sm text-mine tabular-nums w-28">{pluriel(g.nb, 'contact', 'contacts')}</span>
            <button class="text-sm rounded-full border px-2.5 py-0.5 {groupeLi === g.nom ? 'border-onglet text-papier' : 'border-couture text-mine hover:text-papier'}"
              disabled={!g.nb} aria-expanded={groupeLi === g.nom} onclick={() => ouvrirLinkedin(g.nom)}>LinkedIn</button>
            {#if g.fixe}
              <span class="ml-auto text-xs text-mine/70">intégré</span>
            {:else}
              <span class="ml-auto flex gap-3 text-sm">
                <button class="text-mine hover:text-papier underline underline-offset-2"
                  onclick={() => { suppression = null; edition = { ancien: g.nom, nom: g.nom, regle: g.regle ?? '' } }}>Modifier</button>
                <button class="text-mine hover:text-alerte underline underline-offset-2"
                  onclick={() => { edition = null; suppression = { nom: g.nom, vers: '' } }}>Supprimer</button>
              </span>
            {/if}
          </div>
          {#if groupeLi === g.nom}
            <div class="mt-3 rounded-lg border border-couture bg-reliure/60 p-3">
              {#if !contacts}<p class="text-sm text-mine">Chargement…</p>
              {:else}
                <p class="text-xs text-mine mb-2">{membres.filter((p) => p.linkedin).length} sur {membres.length} ont leur profil LinkedIn.
                  « Chercher » ouvre LinkedIn dans un nouvel onglet ; colle ensuite l'adresse du profil (linkedin.com/in/…).</p>
                <ul class="divide-y divide-couture text-sm">
                  {#each membres as p (p.id)}
                    <li class="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                      <a href={`#/revision/${p.id}`} class="w-56 truncate hover:text-onglet">{p.nom}</a>
                      <span class="w-40 truncate text-xs text-mine">{p.societe}</span>
                      {#if p.linkedin}
                        <a class="rounded-full border border-valide/60 bg-valide/15 text-valide px-2.5 py-0.5 text-xs" href={p.linkedin}
                          target="_blank" rel="noopener noreferrer">LinkedIn ✓</a>
                      {:else}
                        <a class="rounded-full border border-couture text-mine hover:text-papier px-2.5 py-0.5 text-xs"
                          href={rechercheLinkedin(p.nom, p.societe)} target="_blank" rel="noopener noreferrer">Chercher sur LinkedIn</a>
                        <form class="flex flex-1 min-w-56 gap-2" onsubmit={(e) => { e.preventDefault(); ajouterProfil(p) }}>
                          <input class="flex-1 !py-0.5 text-xs" placeholder="linkedin.com/in/…" bind:value={profils[p.id]}
                            aria-label={`Adresse du profil LinkedIn de ${p.nom}`} />
                          <button class="bouton !py-0.5 text-xs" disabled={!profils[p.id]?.trim()}>Ajouter</button>
                        </form>
                      {/if}
                    </li>
                  {/each}
                </ul>
              {/if}
            </div>
          {/if}
        {/if}
      </li>
    {/each}
  </ul>
</div>
