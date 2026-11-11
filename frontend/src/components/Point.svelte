<script>
  // Un point de la boîte « À traiter » : ce qui s'est passé, puis les décisions possibles
  import { api } from '../lib/api.js'
  import { aller, apresEcriture, erreur, dire } from '../lib/etat.svelte.js'
  import Avatar from './Avatar.svelte'
  import Changements from './Changements.svelte'
  let { point, ontraite } = $props()
  let attente = $state(false)
  const FAMILLE = ['mariage', 'mariage_different', 'deces_different']
  // Dates de famille : valeurs = [{ source, date }] ; date de naissance : valeurs = { service: date }
  let date = $state(FAMILLE.includes(point.motif) ? (point.donnees.valeurs?.[0]?.date || '')
    : Object.values(point.donnees.valeurs || {}).find((v) => v) || '')
  let saisie = $state('')   // date de mariage tapée (JJ/MM/AAAA)
  const d = point.donnees

  const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
  // « 1985-03-14 » → « 14 mars 1985 » ; « --03-14 » (année inconnue) → « 14 mars »
  const dateLisible = (v) => {
    const m = /^(\d{4}|-)-(\d{2})-(\d{2})$/.exec(v || '')
    if (!m) return v
    const j = Number(m[3])
    return `${j === 1 ? '1er' : j} ${MOIS[Number(m[2]) - 1]}${m[1] !== '-' ? ' ' + m[1] : ''}`
  }
  const SERVICE = { immich: 'Immich', treemich: 'Treemich', telegram: 'Telegram', instagram: 'Instagram',
                    whatsapp: 'WhatsApp', facebook: 'Facebook' }
  const CHAMPS = { societe: 'Société', fonction: 'Fonction', courriel: 'Courriel' }

  function resume(f) {
    if (!f) return []
    return [f.societe, f.fonction, ...(f.telephones || []).map((t) => t.affichage || t.valeur),
            ...(f.courriels || []).map((c) => c.valeur)].filter(Boolean)
  }

  function ecartsConflit(a, b) {
    const noms = { prenom: 'Prénom', nom: 'Nom', societe: 'Société', fonction: 'Fonction', anniversaire: 'Anniversaire',
                   notes: 'Notes', telephones: 'Téléphones', courriels: 'Courriels', adresses: 'Adresses', groupes: 'Groupes' }
    const texte = (v) => Array.isArray(v) ? v.map((x) => x.affichage || x.valeur || x.rue || x).join(', ') : (v || '')
    return Object.keys(noms).filter((k) => texte(a?.[k]) !== texte(b?.[k]))
      .map((k) => ({ libelle: noms[k], mienne: texte(a?.[k]), iphone: texte(b?.[k]) }))
  }

  async function faire(action, valeur, messageOk) {
    attente = true
    try {
      const res = await api.post(`/api/a-traiter/${encodeURIComponent(point.id)}`, { action, valeur })
      ontraite(point)
      if (res?.jeton || res?.etag || res?.uid) await apresEcriture(res, messageOk || 'Écrit dans iCloud.')
      else dire(messageOk || 'C\'est noté.')
    } catch (e) { erreur(e) } finally { attente = false }
  }
</script>

<article class="point feuille">
  <header>
    <Avatar uid={point.uid} nom={point.nom} photo={false} taille={36} />
    <div class="qui">
      {#if point.uid && point.motif !== 'iphone_supprimee'}
        <a class="nom titre" href={'#/contacts/' + encodeURIComponent(point.uid)}>{point.nom}</a>
      {:else}
        <span class="nom titre">{point.nom}</span>
      {/if}
      <span class="motif">{point.titre}</span>
    </div>
  </header>

  <div class="corps">
    {#if point.motif === 'iphone_modifiee'}
      <Changements champs={d.champs} />
    {:else if point.motif === 'iphone_nouvelle' || point.motif === 'import' || point.motif === 'iphone_supprimee'}
      <p class="discret">{resume(d.fiche).join(', ') || 'Fiche sans téléphone ni courriel.'}</p>
      {#if point.motif === 'import'}<p class="discret">Depuis {d.fichier}</p>{/if}
    {:else if point.motif === 'conflit'}
      <p>Tu as modifié cette fiche pendant qu'elle changeait sur l'iPhone. Rien n'a été écrasé.</p>
      <dl class="conflit">
        {#each ecartsConflit(d.voulue, d.iphone) as e}
          <dt class="discret">{e.libelle}</dt>
          <dd><span class="etiquette">Toi</span> {e.mienne || '(vide)'}</dd>
          <dd><span class="etiquette">iPhone</span> {e.iphone || '(vide)'}</dd>
        {/each}
      </dl>
    {:else if point.motif === 'linkedin'}
      <dl class="conflit">
        {#each Object.entries(d.changements) as [champ, v]}
          <dt class="discret">{CHAMPS[champ]}</dt>
          <dd>{#if d.actuel?.[champ]}<span class="avant">{d.actuel[champ]}</span>{/if} <span class="apres">{v}</span></dd>
        {/each}
      </dl>
    {:else if point.motif === 'doublon'}
      <p>Avec <a href={'#/contacts/' + encodeURIComponent(d.b)}>{point.autre}</a> : {d.raisons.join(', ')}.</p>
    {:else if point.motif === 'forme'}
      <ul class="ecarts">
        {#each d.ecarts as e}<li><span class="avant">{e.avant}</span> <span class="apres">{e.apres}</span></li>{/each}
      </ul>
    {:else if point.motif === 'emoji'}
      <p>{d.emoji} dans {d.champs.join(', ')}, mais pas dans le groupe {d.groupe}.</p>
    {:else if point.motif === 'liaison'}
      <p>Personne Immich proche : <strong>{d.immich.nom}</strong> ({d.immich.score} %{d.immich.naissance ? `, née le ${d.immich.naissance.slice(0, 10)}` : ''}).</p>
    {:else if point.motif === 'date'}
      <fieldset class="choix">
        <legend class="discret">Date à garder partout</legend>
        {#each [...new Set(Object.values(d.valeurs).filter(Boolean))] as v}
          <label><input type="radio" name={'date-' + point.id} value={v} bind:group={date} />
            {dateLisible(v)}{#if v.startsWith('--')}<span class="discret"> (sans année : fiche seulement)</span>{/if} <span class="discret">({Object.entries(d.valeurs).filter(([, x]) => x === v).map(([k]) => k === 'carnet' ? 'fiche' : SERVICE[k]).join(', ')})</span></label>
        {/each}
      </fieldset>
    {:else if point.motif === 'nom'}
      <p>Dans {SERVICE[d.service]} : <span class="avant">{d.actuel}</span> <span class="apres">{d.voulu}</span></p>
    {:else if point.motif === 'reseau'}
      <p>Dans {SERVICE[d.service]} : <strong>{d.nom || d.pseudo}</strong>{#if d.pseudo && d.nom}{' '}<span class="discret">@{d.pseudo}</span>{/if}</p>
      <p class="discret">Raison : {d.raison}.{#if d.telephone} Numéro absent de la fiche : {d.telephone}.{/if}</p>
    {:else if point.motif === 'relations'}
      <ul class="ecarts">{#each d.ajouts as a}<li><span class="apres">{a.valeur}</span> <span class="discret">({a.type})</span></li>{/each}</ul>
    {:else if point.motif === 'mariage'}
      <p>{d.couple} forment un couple dans Treemich, sans date de mariage.</p>
      <label class="saisie-date"><span class="discret">Date du mariage ou du PACS</span>
        <input bind:value={saisie} placeholder="12/06/2010" inputmode="numeric" autocomplete="off" /></label>
      <p class="discret">Elle sera écrite dans Treemich et sur la fiche iCloud de chaque conjoint relié.</p>
    {:else if point.motif === 'mariage_different' || point.motif === 'deces_different'}
      {#if d.couple}<p>{d.couple}</p>{/if}
      <fieldset class="choix">
        <legend class="discret">Date à garder partout</legend>
        {#each [...new Set(d.valeurs.map((v) => v.date))] as v}
          <label><input type="radio" name={'date-' + point.id} value={v} bind:group={date} />
            {dateLisible(v)} <span class="discret">({d.valeurs.filter((x) => x.date === v).map((x) => x.source).join(', ')})</span></label>
        {/each}
      </fieldset>
    {/if}
  </div>

  <footer>
    {#if point.motif === 'iphone_modifiee'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('garder', null, 'Modification gardée.')}>Garder</button>
      <button class="bouton" disabled={attente} onclick={() => faire('revenir', null, 'Fiche remise comme avant.')}>Revenir à avant</button>
    {:else if point.motif === 'iphone_nouvelle'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('garder', null, 'Fiche gardée.')}>Garder</button>
      <button class="bouton" onclick={() => aller('contacts', point.uid)}>Corriger</button>
    {:else if point.motif === 'iphone_supprimee'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('confirmer', null, 'Suppression confirmée.')}>Confirmer la suppression</button>
      <button class="bouton" disabled={attente} onclick={() => faire('recreer', null, 'Fiche remise dans iCloud.')}>Remettre la fiche</button>
    {:else if point.motif === 'conflit'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('garder', null, 'Version de l\'iPhone gardée.')}>Garder l'iPhone</button>
      <button class="bouton" disabled={attente} onclick={() => faire('reprendre', null, 'Ta version est écrite.')}>Écrire ma version</button>
    {:else if point.motif === 'import'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('creer', null, 'Fiche créée dans iCloud.')}>Créer dans iCloud</button>
      <button class="bouton" disabled={attente} onclick={() => faire('ignorer')}>Ignorer</button>
    {:else if point.motif === 'doublon'}
      <button class="bouton bouton-principal" onclick={() => aller('fusion', d.a, d.b)}>Comparer et réunir</button>
      <button class="bouton" disabled={attente} onclick={() => faire('distincts', null, 'Gardées séparées.')}>Pas la même personne</button>
    {:else if point.motif === 'liaison'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('lier', null, 'Lié à Immich.')}>Lier</button>
      <button class="bouton" disabled={attente} onclick={() => faire('pas_lui', null, 'Plus proposé.')}>Pas lui</button>
    {:else if point.motif === 'date'}
      <button class="bouton bouton-principal" disabled={attente || !date} onclick={() => faire('choisir', date, 'Date écrite partout.')}>Écrire partout</button>
      <button class="bouton" disabled={attente} onclick={() => faire('ignorer')}>Ignorer</button>
    {:else if point.motif === 'nom'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('renommer', null, `Nom écrit dans ${SERVICE[d.service]}.`)}>Renommer dans {SERVICE[d.service]}</button>
      <button class="bouton" disabled={attente} onclick={() => faire('ignorer')}>Ignorer</button>
    {:else if point.motif === 'reseau'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('lier', null, `Lié à ${SERVICE[d.service]}.`)}>Lier</button>
      {#if d.telephone}
        <button class="bouton" disabled={attente} onclick={() => faire('lier_numero', null, 'Lié, numéro ajouté à la fiche.')}>Lier et ajouter le numéro</button>
      {/if}
      <button class="bouton" disabled={attente} onclick={() => faire('pas_lui', null, 'Plus proposé.')}>Pas lui</button>
    {:else if point.motif === 'relations'}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('ajouter', null, 'Liens familiaux ajoutés.')}>Ajouter à la fiche</button>
      <button class="bouton" disabled={attente} onclick={() => faire('ignorer')}>Ignorer</button>
    {:else if point.motif === 'mariage'}
      <button class="bouton bouton-principal" disabled={attente || !saisie.trim()} onclick={() => faire('ecrire', saisie, 'Date de mariage écrite partout.')}>Écrire la date</button>
      <button class="bouton" disabled={attente} onclick={() => faire('sans', null, 'Noté : la question ne sera plus posée pour ce couple.')}>Pas de mariage ni PACS</button>
    {:else if point.motif === 'mariage_different' || point.motif === 'deces_different'}
      <button class="bouton bouton-principal" disabled={attente || !date} onclick={() => faire('ecrire', date, 'Date écrite partout.')}>Écrire partout</button>
      <button class="bouton" disabled={attente} onclick={() => faire('ignorer')}>Ignorer</button>
    {:else}
      <button class="bouton bouton-principal" disabled={attente} onclick={() => faire('appliquer', null, 'Écrit dans iCloud.')}>
        {point.motif === 'emoji' ? `Ajouter à ${d.groupe}` : 'Appliquer'}</button>
      <button class="bouton" disabled={attente} onclick={() => faire('ignorer')}>Ignorer</button>
    {/if}
  </footer>
</article>

<style>
  .saisie-date { display: grid; gap: 0.2rem; max-width: 16rem; }
  .point { padding: 1rem 1.1rem; display: grid; gap: 0.75rem; }
  header { display: flex; gap: 0.7rem; align-items: center; }
  .qui { display: grid; min-width: 0; }
  .nom { font-size: 1.02rem; color: var(--color-papier); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .motif { color: var(--color-onglet); font-size: 0.82rem; font-weight: 500; }
  .corps { min-width: 0; overflow-wrap: anywhere; }
  footer { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .conflit { display: grid; grid-template-columns: auto 1fr; gap: 0.2rem 0.8rem; margin-top: 0.5rem; }
  .conflit dt { grid-column: 1 / -1; margin-top: 0.3rem; }
  .conflit dd { grid-column: 1 / -1; }
  .etiquette { display: inline-block; min-width: 3.2rem; color: var(--color-mine); font-size: 0.8rem; }
  .ecarts { display: grid; gap: 0.2rem; }
  .choix { display: grid; gap: 0.35rem; }
  .choix label { display: flex; align-items: center; gap: 0.5rem; min-height: 2.5rem; }
  a { color: var(--color-papier); text-decoration-color: var(--color-tranche); }
</style>
