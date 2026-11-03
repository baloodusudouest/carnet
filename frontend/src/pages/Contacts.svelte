<script>
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { etat, erreur, rafraichirContacts, dire } from '../lib/etat.svelte.js'
  import Avatar from '../components/Avatar.svelte'

  let recherche = $state('')
  let groupe = $state(null)
  let groupes = $state([])
  let envoi = $state(false)

  const sansAccent = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  const lettre = (c) => {
    const l = sansAccent(c.nom_famille || c.nom).charAt(0).toUpperCase()
    return /[A-Z]/.test(l) ? l : '#'
  }
  const filtres = $derived.by(() => {
    const q = sansAccent(recherche.trim())
    const chiffres = recherche.replace(/\D/g, '')
    return (etat.contacts || []).filter((c) => (!groupe || c.groupes.includes(groupe)) && (!q ||
      sansAccent(`${c.nom} ${c.societe} ${c.fonction} ${c.courriel}`).includes(q) ||
      (chiffres.length >= 3 && c.valeur_tel.replace(/\D/g, '').includes(chiffres.replace(/^0/, '')))))
  })
  const sections = $derived.by(() => {
    const res = new Map()
    for (const c of filtres) {
      const l = lettre(c)
      if (!res.has(l)) res.set(l, [])
      res.get(l).push(c)
    }
    return [...res.entries()].sort(([a], [b]) => (a === '#') - (b === '#') || a.localeCompare(b))
  })

  function sauter(l) {
    document.getElementById('lettre-' + l)?.scrollIntoView({ block: 'start' })
  }

  async function importer(e) {
    const fichier = e.target.files?.[0]
    if (!fichier) return
    envoi = true
    const fd = new FormData()
    fd.append('fichier', fichier)
    try {
      const r = await api.post('/api/import', fd)
      dire(r.source === 'linkedin'
        ? `LinkedIn : ${r.rattachees} relations reconnues, ${r.proposees} changement(s) à traiter.`
        : `${r.lues} fiche(s) lue(s), ${r.a_traiter} à vérifier dans « À traiter ».`)
    } catch (err) { erreur(err) } finally { envoi = false; e.target.value = '' }
  }

  onMount(async () => {
    try {
      if (!etat.contacts) await rafraichirContacts()
      groupes = (await api.get('/api/groupes')).filter((g) => g.nombre)
    } catch (e) { erreur(e) }
  })
</script>

<section class="page">
  <div class="entete">
    <h1 class="titre">Contacts <span class="discret nombre">{etat.contacts?.length ?? ''}</span></h1>
    <label class="bouton importer">
      {envoi ? 'Import…' : 'Importer'}
      <input type="file" accept=".vcf,.vcard,.csv,text/vcard,text/csv" onchange={importer} hidden />
    </label>
  </div>
  <input class="recherche" type="search" placeholder="Nom, société, numéro…" bind:value={recherche} aria-label="Chercher un contact" />
  {#if groupes.length}
    <div class="filtres" role="group" aria-label="Groupes">
      <button class="pastille" aria-pressed={!groupe} onclick={() => (groupe = null)}>Tous</button>
      {#each groupes as g}
        <button class="pastille" aria-pressed={groupe === g.nom} onclick={() => (groupe = groupe === g.nom ? null : g.nom)}>{g.nom} {g.nombre}</button>
      {/each}
    </div>
  {/if}

  {#if !etat.contacts}
    <p class="discret">Chargement…</p>
  {:else if !filtres.length}
    <p class="discret vide">Aucun contact ne correspond{recherche ? ` à « ${recherche} »` : ''}.</p>
  {:else}
    <div class="carnet">
      <div class="liste">
        {#each sections as [l, liste] (l)}
          <h2 id={'lettre-' + l} class="lettre titre">{l}</h2>
          <ul>
            {#each liste as c (c.uid)}
              <li>
                <a class="ligne" href={'#/contacts/' + encodeURIComponent(c.uid)}>
                  <Avatar uid={c.uid} nom={c.nom} photo={c.a_photo} />
                  <span class="texte">
                    <span class="nom">{c.nom}{#if c.a_traiter}<span class="marque" aria-label="À traiter"></span>{/if}</span>
                    <span class="discret detail">{[c.societe, c.telephone].filter(Boolean).join(', ')}</span>
                  </span>
                </a>
              </li>
            {/each}
          </ul>
        {/each}
      </div>
      <!-- La tranche du carnet : une lettre par onglet, à portée de pouce -->
      <nav class="tranche" aria-label="Aller à la lettre">
        {#each sections as [l]}
          <button onclick={() => sauter(l)}>{l}</button>
        {/each}
      </nav>
    </div>
  {/if}
</section>

<style>
  .page { max-width: 46rem; }
  .entete { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; margin-bottom: 0.75rem; }
  h1 { font-size: 1.9rem; }
  .nombre { font-family: var(--font-sans); font-size: 1rem; font-weight: 400; }
  .recherche { margin-bottom: 0.6rem; }
  .filtres { display: flex; gap: 0.4rem; overflow-x: auto; padding-bottom: 0.4rem; scrollbar-width: none; }
  .filtres .pastille { flex: none; }
  .carnet { display: grid; grid-template-columns: 1fr auto; gap: 0.25rem; margin-top: 0.5rem; }
  .lettre {
    position: sticky; top: 0; z-index: 1; background: var(--color-cuir); color: var(--color-onglet);
    font-size: 1.15rem; padding: 0.4rem 0 0.2rem; scroll-margin-top: 0.5rem; border-bottom: 1px solid var(--color-couture);
  }
  .ligne { display: flex; align-items: center; gap: 0.75rem; min-height: 3.5rem; padding: 0.3rem 0.25rem; border-radius: 8px; }
  .ligne:hover { background: var(--color-reliure); }
  .texte { display: grid; min-width: 0; }
  .nom { font-family: var(--font-livre); font-size: 1.05rem; display: flex; align-items: center; gap: 0.45rem; }
  .detail { font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .marque { width: 0.45rem; height: 0.45rem; border-radius: 50%; background: var(--color-onglet); flex: none; }
  .tranche {
    position: sticky; top: 0.5rem; align-self: start; display: flex; flex-direction: column;
    max-height: calc(100dvh - 6rem); overflow-y: auto; scrollbar-width: none;
  }
  .tranche button {
    width: 2rem; min-height: 1.6rem; font-family: var(--font-livre); font-weight: 600; font-size: 0.85rem;
    color: #23190a; background: var(--color-onglet); border-radius: 0 6px 6px 0; margin-bottom: 2px;
    box-shadow: inset 3px 0 0 rgb(0 0 0 / 0.18);
  }
  .tranche button:nth-child(even) { background: #c8953a; }
  .importer { cursor: pointer; }
  .vide { padding: 2rem 0; }
  @media (pointer: coarse) { .tranche button { min-height: 1.9rem; } }
</style>
