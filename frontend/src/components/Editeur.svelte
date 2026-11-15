<script>
  // Formulaire d'une fiche. Les formats (Prénom NOM, +33 6 …) sont appliqués par carnet à
  // l'aperçu : on peut saisir librement.
  // 2.11.2 : un nom associé se choisit parmi les contacts du carnet, ou s'écrit à la main.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  let { fiche = $bindable(), groupesConnus = [] } = $props()

  let connus = $state([])            // noms du carnet, proposés pendant la saisie d'un nom associé
  onMount(async () => {
    try { connus = [...new Set((await api.get('/api/contacts')).map((c) => c.nom).filter(Boolean))] } catch { connus = [] }
  })
  const soi = $derived([fiche.prenom, fiche.nom].filter(Boolean).join(' ').toLocaleLowerCase('fr'))
  const proposes = $derived(connus.filter((n) => n.toLocaleLowerCase('fr') !== soi))

  // 2.24 : les types sont ceux de la fiche de l'iPhone ; un libellé écrit à la main sur l'iPhone reste proposé
  const TYPES = {
    telephones: ['mobile', 'domicile', 'travail', 'bureau', 'principal', 'école', 'apple watch', 'fax domicile', 'fax travail', 'pager', 'autre'],
    courriels: ['domicile', 'travail', 'école', 'autre'],
    adresses: ['domicile', 'travail', 'école', 'autre'],
    sites: ['site', 'domicile', 'travail', 'école', 'linkedin', 'facebook', 'instagram', 'x', 'tiktok', 'telegram', 'whatsapp', 'signal', 'flickr', 'myspace', 'sina weibo', 'autre'],
    noms_associes: ['conjoint', 'partenaire', 'mari', 'épouse', 'mère', 'père', 'parent', 'enfant', 'fils', 'fille', 'frère', 'sœur', 'frère ou sœur', 'ami', 'assistant', 'responsable', 'autre'],
    messageries: ['Skype', 'MSN', 'GoogleTalk', 'Facebook', 'AIM', 'Yahoo', 'ICQ', 'Jabber'],
    dates_autres: ['anniversaire (Apple)', 'autre'],
  }
  const typesDe = (cle, actuel) => TYPES[cle].includes(actuel) || !actuel ? TYPES[cle] : [...TYPES[cle], actuel]
  const MULTIPLES = [
    { cle: 'telephones', nom: 'Téléphones', vide: { valeur: '', type: 'mobile' }, saisie: 'tel' },
    { cle: 'courriels', nom: 'Courriels', vide: { valeur: '', type: 'domicile' }, saisie: 'email' },
    { cle: 'sites', nom: 'Sites et réseaux', vide: { valeur: '', type: 'site' }, saisie: 'url' },
    { cle: 'dates_autres', nom: 'Dates', vide: { valeur: '', type: 'autre' }, saisie: 'text' },
    { cle: 'noms_associes', nom: 'Noms associés', vide: { valeur: '', type: 'conjoint' }, saisie: 'text' },
    { cle: 'messageries', nom: 'Messageries instantanées', vide: { valeur: '', type: 'Skype' }, saisie: 'text' },
  ]
  // Comme sur l'iPhone : les champs courants sont toujours là, les autres s'ajoutent par « Ajouter un champ »
  // et restent visibles dès qu'ils sont remplis. Même ordre que sur l'iPhone.
  const CHAMPS = [['titre', 'Titre', 0], ['prenom', 'Prénom', 1], ['prononciation_prenom', 'Prénom phonétique', 0],
                  ['dire_prenom', 'Prononciation du prénom', 0], ['second_prenom', 'Second prénom', 0],
                  ['phonetique_second_prenom', 'Second prénom phonétique', 0], ['nom', 'Nom', 1],
                  ['prononciation_nom', 'Nom de famille phonétique', 0], ['dire_nom', 'Prononciation du nom', 0],
                  ['nom_naissance', 'Nom de naissance', 0], ['suffixe', 'Suffixe', 0], ['surnom', 'Surnom', 0],
                  ['societe', 'Société', 1], ['phonetique_societe', 'Nom de société phonétique', 0],
                  ['service', 'Service', 0], ['fonction', 'Fonction', 1], ['anniversaire', 'Anniversaire', 1], ['fete', 'Fête', 1],
                  ['mariage', 'Mariage ou PACS', 1], ['deces', 'Décès', 1]]
  let ajoutes = $state([])           // champs sortis du menu pendant cette modification
  const simples = $derived(CHAMPS.filter(([cle, , toujours]) => toujours || fiche[cle] || ajoutes.includes(cle)))
  const aAjouter = $derived(CHAMPS.filter(([cle, , toujours]) => !toujours && !fiche[cle] && !ajoutes.includes(cle)))
  function ajouterChamp(ev) {
    const cle = ev.currentTarget.value
    ev.currentTarget.value = ''
    if (cle) { fiche[cle] = fiche[cle] || ''; ajoutes = [...ajoutes, cle] }
  }
  const AIDES = { anniversaire: '15/03/1985, ou 15/03/1900 sans année', fete: '15/08 — vide : celle du calendrier',
                  mariage: '12/06/2010', deces: '02/01/2020', dire_prenom: 'Comme on le dit', service: 'Au sein de la société',
                  titre: 'Dr, Me, Pr…', suffixe: 'Jr, fils…', nom_naissance: 'Avant le mariage' }

  function ajouter(cle, vide) { fiche[cle] = [...(fiche[cle] || []), { ...vide }] }
  function retirer(cle, i) { fiche[cle] = fiche[cle].filter((_, j) => j !== i) }
  function basculer(g) {
    const actuels = new Set(fiche.groupes || [])
    actuels.has(g) ? actuels.delete(g) : actuels.add(g)
    fiche.groupes = [...actuels].sort()
  }
</script>

<div class="editeur">
  <div class="simples">
    {#each simples as [cle, nom] (cle)}
      <label class:large={cle === 'societe' || cle === 'fonction'}>
        <span class="discret">{nom}</span>
        <input bind:value={fiche[cle]} placeholder={AIDES[cle] || ''}
               autocomplete="off" autocapitalize={['prenom', 'nom', 'second_prenom', 'nom_naissance'].includes(cle) ? 'words' : 'sentences'} />
      </label>
    {/each}
    {#if aAjouter.length}
      <label class="ajout-champ">
        <span class="discret">Ajouter un champ</span>
        <select onchange={ajouterChamp} aria-label="Ajouter un champ">
          <option value="">Choisir…</option>
          {#each aAjouter as [cle, nom]}<option value={cle}>{nom}</option>{/each}
        </select>
      </label>
    {/if}
  </div>

  {#each MULTIPLES as m}
    <fieldset>
      <legend class="discret">{m.nom}</legend>
      {#each fiche[m.cle] || [] as item, i}
        <div class="rangee">
          {#if m.cle === 'dates_autres'}
            <input type="text" bind:value={item.type} aria-label="Libellé de la date" list="libelles-de-date"
                   placeholder="Libellé" autocomplete="off" />
          {:else}
            <select bind:value={item.type} aria-label="Type">
              {#each typesDe(m.cle, item.type) as t}<option value={t}>{t}</option>{/each}
            </select>
          {/if}
          {#if m.cle === 'dates_autres'}
            <input type="text" bind:value={item.valeur} aria-label="Date" placeholder="15/03/1985, ou 15/03 sans année" autocomplete="off" />
          {:else if m.cle === 'noms_associes'}
            <input type="text" bind:value={item.valeur} aria-label={m.nom} list="noms-du-carnet"
                   placeholder="Choisir dans le carnet, ou écrire" autocomplete="off" autocapitalize="words" />
          {:else}
            <input type={m.saisie} bind:value={item.valeur} aria-label={m.nom} />
          {/if}
          <button class="bouton retirer" onclick={() => retirer(m.cle, i)} aria-label="Retirer">✕</button>
        </div>
      {/each}
      <button class="bouton ajouter" onclick={() => ajouter(m.cle, m.vide)}>Ajouter</button>
    </fieldset>
  {/each}

  <datalist id="libelles-de-date">{#each TYPES.dates_autres as t}<option value={t}></option>{/each}</datalist>
  <datalist id="noms-du-carnet">{#each proposes as n}<option value={n}></option>{/each}</datalist>

  <fieldset>
    <legend class="discret">Adresses</legend>
    {#each fiche.adresses || [] as a, i}
      <div class="adresse">
        <select bind:value={a.type} aria-label="Type">{#each typesDe('adresses', a.type) as t}<option value={t}>{t}</option>{/each}</select>
        <input bind:value={a.rue} placeholder="Rue" aria-label="Rue" />
        <div class="ville">
          <input bind:value={a.cp} placeholder="Code postal" aria-label="Code postal" inputmode="numeric" />
          <input bind:value={a.ville} placeholder="Ville" aria-label="Ville" />
        </div>
        <input bind:value={a.pays} placeholder="Pays" aria-label="Pays" />
        <button class="bouton retirer" onclick={() => retirer('adresses', i)}>Retirer cette adresse</button>
      </div>
    {/each}
    <button class="bouton ajouter" onclick={() => ajouter('adresses', { rue: '', cp: '', ville: '', region: '', pays: '', type: 'domicile' })}>Ajouter</button>
  </fieldset>

  <fieldset>
    <legend class="discret">Groupes</legend>
    <div class="groupes">
      {#each [...new Set([...groupesConnus, ...(fiche.groupes || [])])] as g}
        <button class="pastille" aria-pressed={(fiche.groupes || []).includes(g)} onclick={() => basculer(g)}>{g}</button>
      {/each}
    </div>
  </fieldset>

  <label><span class="discret">Notes</span><textarea rows="4" bind:value={fiche.notes}></textarea></label>
</div>

<style>
  .editeur { display: grid; gap: 1.1rem; }
  .simples { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem 0.8rem; }
  label { display: grid; gap: 0.2rem; }
  fieldset { display: grid; gap: 0.45rem; }
  legend { margin-bottom: 0.3rem; }
  .rangee { display: grid; grid-template-columns: 8.5rem 1fr auto; gap: 0.4rem; }
  .retirer { padding: 0 0.7rem; color: var(--color-mine); }
  .ajouter { justify-self: start; }
  .adresse { display: grid; gap: 0.4rem; padding: 0.6rem; border: 1px solid var(--color-couture); border-radius: 8px; }
  .ville { display: grid; grid-template-columns: 7rem 1fr; gap: 0.4rem; }
  .groupes { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  @media (max-width: 30rem) {
    .simples { grid-template-columns: 1fr; }
    .rangee { grid-template-columns: 7.5rem 1fr auto; }
  }
</style>
