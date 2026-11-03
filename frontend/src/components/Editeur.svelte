<script>
  // Formulaire d'une fiche. Les formats (Prénom NOM, +33 6 …) sont appliqués par carnet à
  // l'aperçu : on peut saisir librement.
  let { fiche = $bindable(), groupesConnus = [] } = $props()

  const TYPES = {
    telephones: ['mobile', 'domicile', 'travail', 'bureau', 'principal', 'autre'],
    courriels: ['domicile', 'travail', 'autre'],
    adresses: ['domicile', 'travail', 'autre'],
    sites: ['site', 'linkedin', 'facebook', 'instagram', 'x', 'tiktok', 'telegram', 'whatsapp', 'signal', 'autre'],
    noms_associes: ['conjoint', 'partenaire', 'mère', 'père', 'parent', 'enfant', 'frère', 'sœur', 'ami', 'assistant', 'responsable', 'autre'],
  }
  const MULTIPLES = [
    { cle: 'telephones', nom: 'Téléphones', vide: { valeur: '', type: 'mobile' }, saisie: 'tel' },
    { cle: 'courriels', nom: 'Courriels', vide: { valeur: '', type: 'domicile' }, saisie: 'email' },
    { cle: 'sites', nom: 'Sites et réseaux', vide: { valeur: '', type: 'site' }, saisie: 'url' },
    { cle: 'noms_associes', nom: 'Noms associés', vide: { valeur: '', type: 'conjoint' }, saisie: 'text' },
  ]
  const simples = [['prenom', 'Prénom'], ['nom', 'Nom'], ['surnom', 'Surnom'], ['societe', 'Société'], ['fonction', 'Fonction'],
                   ['anniversaire', 'Anniversaire']]

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
    {#each simples as [cle, nom]}
      <label class:large={cle === 'societe' || cle === 'fonction'}>
        <span class="discret">{nom}</span>
        <input bind:value={fiche[cle]} placeholder={cle === 'anniversaire' ? '15/03/1985, ou 15/03/1900 sans année' : ''}
               autocomplete="off" autocapitalize={cle === 'prenom' || cle === 'nom' ? 'words' : 'sentences'} />
      </label>
    {/each}
  </div>

  {#each MULTIPLES as m}
    <fieldset>
      <legend class="discret">{m.nom}</legend>
      {#each fiche[m.cle] || [] as item, i}
        <div class="rangee">
          <select bind:value={item.type} aria-label="Type">
            {#each TYPES[m.cle] as t}<option value={t}>{t}</option>{/each}
          </select>
          <input type={m.saisie} bind:value={item.valeur} aria-label={m.nom} />
          <button class="bouton retirer" onclick={() => retirer(m.cle, i)} aria-label="Retirer">✕</button>
        </div>
      {/each}
      <button class="bouton ajouter" onclick={() => ajouter(m.cle, m.vide)}>Ajouter</button>
    </fieldset>
  {/each}

  <fieldset>
    <legend class="discret">Adresses</legend>
    {#each fiche.adresses || [] as a, i}
      <div class="adresse">
        <select bind:value={a.type} aria-label="Type">{#each TYPES.adresses as t}<option value={t}>{t}</option>{/each}</select>
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
  .rangee { display: grid; grid-template-columns: 7.5rem 1fr auto; gap: 0.4rem; }
  .retirer { padding: 0 0.7rem; color: var(--color-mine); }
  .ajouter { justify-self: start; }
  .adresse { display: grid; gap: 0.4rem; padding: 0.6rem; border: 1px solid var(--color-couture); border-radius: 8px; }
  .ville { display: grid; grid-template-columns: 7rem 1fr; gap: 0.4rem; }
  .groupes { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  @media (max-width: 30rem) {
    .simples { grid-template-columns: 1fr; }
    .rangee { grid-template-columns: 6.5rem 1fr auto; }
  }
</style>
