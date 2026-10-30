<script>
  import { onDestroy } from 'svelte'
  import { api } from '../lib/api.js'
  import { statut, annoncer } from '../lib/etat.svelte.js'
  import { dateCourte, pluriel } from '../lib/cles.js'

  // Écriture des contacts vérifiés dans iCloud (CardDAV) : simulation, essai sur sa propre
  // fiche, puis écriture complète précédée d'une sauvegarde.
  let infos = $state(null)
  let confirme = $state(false)
  let minuteur = null

  const enCours = $derived(['lecture', 'ecriture'].includes(infos?.tache?.etat))
  const plan = $derived(infos?.plan)

  async function charger() {
    const avant = infos?.tache?.etat
    infos = await api.get('/api/icloud')
    const maintenant = infos.tache.etat
    if (['lecture', 'ecriture'].includes(maintenant)) {
      minuteur = setTimeout(charger, 800)
    } else if (['lecture', 'ecriture'].includes(avant)) {
      annoncer(infos.tache.message, maintenant === 'erreur')
      Object.assign(statut, await api.get('/api/statut'))
      confirme = false
    }
  }
  charger()
  onDestroy(() => clearTimeout(minuteur))

  async function lancer(chemin, corps) {
    try {
      await api.post(chemin, corps)
      await charger()
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  const ACTIONS = { creer: 'création', modifier: 'mise à jour', supprimer: 'suppression' }
  const resumeGroupe = (g) => g.action === 'supprimer' ? `supprimé (${g.motif})`
    : `${ACTIONS[g.action]}, ${[g.ajoutes && `+${g.ajoutes}`, g.retires && `−${g.retires}`].filter(Boolean).join(' ')}`
</script>

<div class="max-w-5xl">
  <h1 class="titre text-3xl mb-2">Écriture dans iCloud</h1>
  <p class="text-mine mb-6">
    carnet met à jour tes contacts iCloud avec les fiches vérifiées, crée les groupes et retire les doublons et
    les contacts mis de côté. Rien n'est écrit sans simulation, et une sauvegarde complète d'iCloud est faite juste avant.
  </p>

  {#if infos && !infos.configure}
    <div class="rounded-xl border border-onglet/60 bg-reliure p-5">
      <h2 class="titre text-xl mb-2">Compte iCloud à renseigner</h2>
      <p class="text-sm text-mine mb-2">Ajoute ces deux variables dans la stack (Portainer), puis redéploie :</p>
      <pre class="text-sm bg-cuir rounded-md p-3 mb-3">CARNET_ICLOUD_USER=ton identifiant Apple
CARNET_ICLOUD_PASSWORD=xxxx-xxxx-xxxx-xxxx</pre>
      <p class="text-sm text-mine">Le mot de passe est un <strong class="text-papier">mot de passe d'application</strong>
        (account.apple.com › Connexion et sécurité › Mots de passe pour app), pas celui de ton compte.</p>
    </div>
  {:else if infos}
    <div class="flex flex-wrap items-center gap-4 mb-6">
      <span class="text-sm text-mine">Compte : <span class="text-papier">{infos.compte}</span></span>
      <button class="bouton {plan ? '' : 'bouton-principal'} ml-auto" disabled={enCours} onclick={() => lancer('/api/icloud/simulation')}>
        {plan ? 'Refaire la simulation' : 'Simuler'}
      </button>
    </div>

    {#if statut.a_reviser}
      <p class="text-sm text-onglet mb-4">
        {pluriel(statut.a_reviser, 'contact est encore à réviser : sa fiche iCloud reste', 'contacts sont encore à réviser : leurs fiches iCloud restent')} telle(s) quelle(s).
      </p>
    {/if}

    {#if infos.tache.etat !== 'repos'}
      <div class="rounded-xl border border-couture bg-reliure px-5 py-3 mb-6 {infos.tache.etat === 'erreur' ? 'border-alerte text-alerte' : ''}">
        <p class="text-sm">{infos.tache.message}</p>
        {#if enCours && infos.tache.total}
          <div class="mt-2 h-1.5 rounded-full bg-couture overflow-hidden">
            <div class="h-full bg-valide transition-all" style="width: {Math.round((100 * infos.tache.fait) / infos.tache.total)}%"></div>
          </div>
          <p class="text-xs text-mine mt-1 tabular-nums">{infos.tache.fait} / {infos.tache.total}</p>
        {/if}
      </div>
    {/if}

    {#if plan && !enCours}
      <section class="mb-8">
        <h2 class="titre text-xl mb-1">Simulation du {dateCourte(plan.le)}</h2>
        <p class="text-sm text-mine mb-4">
          {pluriel(plan.icloud, 'contact lu', 'contacts lus')} dans iCloud, {pluriel(plan.groupes_icloud, 'groupe', 'groupes')}.
          {pluriel(plan.identiques, 'fiche est déjà à jour', 'fiches sont déjà à jour')}. Valable 30 minutes.
        </p>
        <div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {#each [
            ['À mettre à jour', plan.modifier, (x) => x.nom],
            ['À créer', plan.creer, (x) => `${x.nom} (${x.motif})`],
            ['À supprimer', plan.supprimer, (x) => `${x.nom} (${x.motif})`],
            ['Groupes', plan.groupes, (x) => `${x.nom} : ${resumeGroupe(x)}`],
            ['Nouveaux dans iCloud, importés pour révision', plan.inconnus.map((nom) => ({ nom })), (x) => x.nom],
            ['Groupes iCloud non gérés (laissés tels quels)', plan.groupes_non_geres.map((nom) => ({ nom })), (x) => x.nom],
          ] as [titre, liste, libelle]}
            <details class="rounded-xl border border-couture bg-reliure px-4 py-3" open={liste.length > 0 && liste.length <= 8}>
              <summary class="cursor-pointer flex items-baseline gap-2">
                <span class="text-2xl tabular-nums {liste.length ? 'text-papier' : 'text-mine/60'}">{liste.length}</span>
                <span class="text-sm text-mine">{titre}</span>
              </summary>
              {#if liste.length}
                <ul class="mt-2 max-h-56 overflow-auto text-sm space-y-0.5">
                  {#each liste as x}<li class="truncate" title={libelle(x)}>{libelle(x)}</li>{/each}
                </ul>
              {/if}
            </details>
          {/each}
        </div>
      </section>

      <section class="grid gap-6 lg:grid-cols-2 mb-10">
        <div class="rounded-xl border border-couture bg-reliure p-5">
          <h2 class="titre text-xl mb-1">1. Essai sur ta fiche</h2>
          {#if plan.essai}
            <p class="text-sm text-mine mb-4">Écrit uniquement <span class="text-papier">{plan.essai}</span> et le groupe Moi. Regarde ensuite le résultat sur l'iPhone : téléphones, postes, adresses, photo.</p>
            <button class="bouton" disabled={enCours} onclick={() => lancer('/api/icloud/ecriture', { essai: true })}>Écrire seulement ma fiche</button>
          {:else}
            <p class="text-sm text-mine">Ajoute ta propre fiche au groupe Moi (touche I en révision) pour pouvoir faire un essai.</p>
          {/if}
        </div>
        <div class="rounded-xl border border-onglet/60 bg-reliure p-5">
          <h2 class="titre text-xl mb-1">2. Écriture complète</h2>
          <p class="text-sm text-mine mb-3">
            {pluriel(plan.modifier.length + plan.creer.length + plan.supprimer.length + plan.groupes.length, 'écriture', 'écritures')}.
            Un contact modifié sur l'iPhone depuis la simulation n'est pas écrasé : il est signalé.
          </p>
          <label class="flex items-start gap-2 text-sm mb-4">
            <input type="checkbox" bind:checked={confirme} class="mt-1" />
            <span>J'ai vérifié la simulation. Une sauvegarde complète d'iCloud sera enregistrée dans carnet/archives avant d'écrire.</span>
          </label>
          <button class="bouton bouton-principal" disabled={!confirme || enCours}
            onclick={() => lancer('/api/icloud/ecriture', { confirme: true })}>Écrire dans iCloud</button>
        </div>
      </section>
    {/if}

    {#if infos.journal.length}
      <section>
        <h2 class="titre text-xl mb-2">Journal</h2>
        <ul class="divide-y divide-couture border-y border-couture text-sm">
          {#each infos.journal as j}
            <li class="py-2.5">
              <div class="flex flex-wrap gap-x-4">
                <span class="text-papier">{dateCourte(j.le)} {new Date(j.le).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>
                <span class="text-mine">{j.essai ? 'Essai' : 'Écriture'} : {j.crees} créé(s), {j.modifies} mis à jour, {j.supprimes} supprimé(s), {j.groupes} groupe(s){j.importes ? `, ${j.importes} importé(s) pour révision` : ''}</span>
                <span class="text-xs text-mine ml-auto">sauvegarde : {j.sauvegarde}</span>
              </div>
              {#if j.conflits.length}<p class="text-onglet text-xs mt-1">Modifiés sur l'iPhone entre-temps, non écrasés : {j.conflits.join(', ')}. Refais une simulation pour les reprendre.</p>{/if}
              {#if j.erreurs.length}<p class="text-alerte text-xs mt-1">{j.erreurs.join(' · ')}</p>{/if}
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
</div>
