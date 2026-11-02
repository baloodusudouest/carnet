<script>
  // État : la synchro iCloud de nuit (journal, interrupteur, bouton), la veille et les sauvegardes.
  // Une seule question : est-ce que tout va bien ? Le détail (simulation, suppressions à
  // confirmer) reste dans « iCloud en détail ».
  import { api } from '../lib/api.js'
  import { annoncer, bilan, chargerBilan, ecran, choisirVue } from '../lib/etat.svelte.js'
  import { dateCourte, pluriel } from '../lib/cles.js'

  let { deconnecter } = $props()
  let donnees = $state(null)
  let occupe = $state(false)

  async function charger() {
    try {
      donnees = await api.get('/api/synchro')
      if (['lecture', 'ecriture'].includes(donnees.tache?.etat)) setTimeout(charger, 1200)
      else if (occupe) {
        occupe = false
        if (donnees.tache?.message) annoncer(donnees.tache.message, donnees.tache.etat === 'erreur')
        chargerBilan(api).catch(() => {})
      }
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  charger()
  chargerBilan(api).catch(() => {})

  async function maintenant() {
    try {
      occupe = true
      await api.post('/api/synchro/maintenant')
      await charger()
    } catch (e) {
      occupe = false
      annoncer(e.message, true)
    }
  }
  async function regler(corps) {
    try {
      donnees = await api.post('/api/synchro/reglage', corps)
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  const r = $derived(donnees?.reglage)
  const derniere = $derived(donnees?.journal?.[0])
  const enCours = $derived(['lecture', 'ecriture'].includes(donnees?.tache?.etat))
  const s = $derived(bilan.donnees?.statut)
  const restauration = $derived(bilan.donnees?.restauration)
  const testVieux = $derived(!restauration || !restauration.ok || (Date.now() - new Date(restauration.le)) / 864e5 > 90)
  const MODES = { reel: 'écrite', a_blanc: 'à blanc', bloque: 'bloquée', arret: 'coupée' }
  function resume(e) {
    if (!e) return ''
    if (e.mode === 'a_blanc' && e.prevus) return `aurait écrit ${pluriel(e.prevus.crees, 'création', 'créations')}, ${pluriel(e.prevus.modifies, 'modification', 'modifications')}`
    if (e.mode === 'reel') return e.crees + e.modifies + e.groupes ? `${pluriel(e.crees, 'création', 'créations')}, ${pluriel(e.modifies, 'modification', 'modifications')}, ${pluriel(e.groupes, 'groupe', 'groupes')}` : 'iCloud était déjà à jour'
    if (e.mode === 'arret') return 'synchro de nuit coupée'
    return e.alerte || e.erreur || 'rien écrit'
  }
</script>

{#snippet ligne(etat, titre, texte, lien = null, libelle = null)}
  <li class="flex items-start gap-3 py-3">
    <span class="mt-1.5 w-2.5 h-2.5 shrink-0 rounded-full {etat === 'ok' ? 'bg-valide' : etat === 'attention' ? 'bg-onglet' : 'bg-alerte'}" aria-hidden="true"></span>
    <span class="flex-1 min-w-0">
      <span class="block text-papier">{titre}</span>
      <span class="block text-sm {etat === 'erreur' ? 'text-alerte' : 'text-mine'}">{texte}</span>
    </span>
    {#if lien}<a class="shrink-0 min-h-11 flex items-center text-sm text-onglet underline underline-offset-2" href={lien}>{libelle}</a>{/if}
  </li>
{/snippet}

<div class="max-w-3xl">
  <h1 class="titre text-2xl mb-1">État</h1>
  <p class="text-sm text-mine mb-5">Synchro avec iCloud, veille de l'iPhone et sauvegardes, chaque nuit.</p>

  {#if !donnees}
    <div class="h-40 rounded-2xl bg-reliure animate-pulse" aria-hidden="true"></div>
  {:else}
    <section class="rounded-2xl border border-couture bg-reliure p-4 mb-4" aria-labelledby="titre-synchro">
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-3">
        <h2 id="titre-synchro" class="titre text-xl">Synchro iCloud</h2>
        {#if !donnees.configure}
          <span class="text-sm text-alerte">identifiants iCloud absents de la stack</span>
        {:else if !r.actif}
          <span class="text-sm text-onglet">coupée la nuit</span>
        {:else if r.a_blanc}
          <span class="text-sm text-onglet">à blanc jusqu'au {dateCourte(r.a_blanc_jusqu_au)} : rien n'est écrit, le plan est noté</span>
        {:else}
          <span class="text-sm text-valide">écrit chaque nuit</span>
        {/if}
      </div>

      {#if derniere}
        <div class="rounded-xl border p-3 mb-3 {derniere.erreur || derniere.mode === 'bloque' ? 'border-alerte/60 bg-[#2a1b1b]' : 'border-couture'}">
          <p class="text-sm text-papier">{derniere.manuel ? 'À la demande' : 'Nuit'} du {dateCourte(derniere.le)} : {MODES[derniere.mode]} · {resume(derniere)}</p>
          {#if derniere.alerte}<p class="text-sm text-alerte mt-1">{derniere.alerte}</p>{/if}
          {#if derniere.erreur && derniere.mode !== 'bloque'}<p class="text-sm text-alerte mt-1">{derniere.erreur}</p>{/if}
          {#if derniere.en_revision}
            <p class="text-sm text-mine mt-1">{pluriel(derniere.en_revision, 'fiche changée', 'fiches changées')} sur l'iPhone, remise{derniere.en_revision > 1 ? 's' : ''} en révision au lieu d'être écrasée{derniere.en_revision > 1 ? 's' : ''}.
              <a class="text-onglet underline underline-offset-2" href="#/revision">Relire</a></p>
          {/if}
          {#if derniere.suppressions_en_attente}
            <p class="text-sm text-mine mt-1">{pluriel(derniere.suppressions_en_attente, 'suppression attend', 'suppressions attendent')} ton accord (jamais faites la nuit).
              <a class="text-onglet underline underline-offset-2" href="#/icloud">Voir et confirmer</a></p>
          {/if}
        </div>
      {:else}
        <p class="text-sm text-mine mb-3">Pas encore de synchro : la première a lieu cette nuit, ou maintenant avec le bouton.</p>
      {/if}

      <div class="flex flex-wrap gap-2">
        <button class="bouton bouton-principal min-h-11" disabled={enCours || !donnees.configure} onclick={maintenant}>
          {enCours ? (donnees.tache?.message ?? 'En cours…') : 'Synchroniser maintenant'}</button>
        <button class="bouton min-h-11" onclick={() => regler({ actif: !r.actif })} aria-pressed={r.actif}>
          {r.actif ? 'Couper la synchro de nuit' : 'Réactiver la synchro de nuit'}</button>
        {#if r.actif && r.a_blanc}
          <button class="bouton min-h-11" onclick={() => regler({ reel: true })}>Écrire pour de bon dès cette nuit</button>
        {/if}
      </div>
      <p class="text-xs text-mine mt-3">La nuit, carnet n'écrit jamais de suppression et s'arrête s'il y a plus de 10 créations
        ou 20 modifications (ou 5 % et 10 % des contacts), ou si la veille est en erreur. « Synchroniser maintenant » applique
        les mêmes règles, mais écrit même pendant la période à blanc.</p>

      {#if donnees.journal.length > 1}
        <details class="mt-3">
          <summary class="min-h-11 flex items-center text-sm text-mine cursor-pointer">Nuits précédentes</summary>
          <ul class="text-sm divide-y divide-couture">
            {#each donnees.journal.slice(1, 15) as e}
              <li class="py-2 flex gap-3"><span class="w-24 shrink-0 text-mine tabular-nums">{dateCourte(e.le)}</span>
                <span class="flex-1 {e.mode === 'bloque' || e.erreur ? 'text-alerte' : 'text-papier'}">{MODES[e.mode]} · {resume(e)}</span></li>
            {/each}
          </ul>
        </details>
      {/if}
    </section>

    {#if s}
      <section class="rounded-2xl border border-couture bg-reliure px-4 mb-4" aria-label="Veille et sauvegardes">
        <ul class="divide-y divide-couture">
          {@render ligne(!s.veille ? 'attention' : s.veille.ok ? 'ok' : 'erreur', 'Veille de l\'iPhone',
            !s.veille ? 'Pas encore faite.' : s.veille.ok ? `Nuit du ${dateCourte(s.veille.le)} : ${pluriel(s.veille.modifies + s.veille.nouveaux + s.veille.supprimes, 'changement remis', 'changements remis')} en révision.` : s.veille.erreur,
            '#/icloud', 'Détail')}
          {@render ligne(!s.sauvegarde ? 'attention' : s.sauvegarde.ok ? 'ok' : 'erreur', 'Sauvegarde de nuit',
            !s.sauvegarde ? 'Aucune sauvegarde pour l\'instant.' : s.sauvegarde.ok ? `Nuit du ${dateCourte(s.sauvegarde.le)} : ${pluriel(s.sauvegarde.contacts, 'contact', 'contacts')}${s.sauvegarde.synology ? ', copie Synology faite' : ''}.` : s.sauvegarde.erreur,
            '#/export', 'Sauvegardes')}
          {@render ligne(testVieux ? 'attention' : 'ok', 'Test de restauration',
            restauration ? `${restauration.ok ? 'Réussi' : 'Raté'} le ${dateCourte(restauration.le)}${testVieux && restauration.ok ? ' : à refaire (plus de 3 mois)' : ''}.` : 'Jamais fait : vérifie qu\'une sauvegarde s\'ouvre avec ta clé.',
            '#/export', 'Tester')}
          {#if s.archives_bientot}
            {@render ligne('attention', 'Archives bientôt supprimées', `${pluriel(s.contacts_archives_bientot, 'contact concerné', 'contacts concernés')}.`, '#/archives', 'Voir')}
          {/if}
        </ul>
      </section>
    {/if}
  {/if}

  {#if ecran.etroit}
    <ul class="mt-6 rounded-2xl border border-couture divide-y divide-couture overflow-hidden bg-reliure">
      <li><button class="w-full text-left px-4 min-h-12 text-papier active:bg-couture" onclick={() => choisirVue(!ecran.forcerPC)}>
        {ecran.forcerPC ? 'Revenir à la vue iPhone' : 'Afficher la vue PC'}</button></li>
      <li><button class="w-full text-left px-4 min-h-12 text-alerte active:bg-couture" onclick={deconnecter}>Se déconnecter</button></li>
    </ul>
  {/if}
</div>
