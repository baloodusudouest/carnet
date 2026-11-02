<script>
  // Logos de sociétés : pour les contacts des groupes choisis (Clients, Artisans… par défaut)
  // qui n'ont pas de vraie photo, carnet lit le site de la société et propose son logo
  // en photo ronde du contact et en affiche iPhone. Rien n'est posé sans ton choix.
  import { api } from '../lib/api.js'
  import { annoncer, ref } from '../lib/etat.svelte.js'
  import { cleTexte, dateCourte } from '../lib/cles.js'

  let donnees = $state(null)
  let filtre = $state('a_choisir')
  let recherche = $state('')
  let vue = $state(null)          // { ligne, n }
  let occupe = $state(false)
  let tache = $state(null)

  async function charger() {
    try {
      donnees = await api.get('/api/logos')
    } catch (e) {
      annoncer(e.message, true)
    }
  }
  charger()

  async function basculerGroupe(g) {
    const groupes = donnees.groupes.includes(g) ? donnees.groupes.filter((x) => x !== g) : [...donnees.groupes, g]
    donnees = await api.post('/api/logos/groupes', { groupes })
  }

  async function suivre() {
    tache = (await api.get('/api/icloud')).tache
    if (['lecture', 'ecriture'].includes(tache?.etat)) setTimeout(suivre, 900)
    else {
      if (tache?.message) annoncer(tache.message, tache.etat === 'erreur')
      await charger()
    }
  }
  async function chercher(relire = false) {
    try {
      await api.post(`/api/logos/recherche${relire ? '?relire=true' : ''}`)
      await suivre()
    } catch (e) {
      annoncer(e.message, true)
    }
  }

  async function choisir(sorte) {
    const { ligne, n } = vue
    occupe = true
    try {
      await api.post('/api/logos/choix', { pid: ligne.pid, n, sorte })
      annoncer(sorte === 'photo' ? `Logo posé comme photo de ${ligne.nom} (iCloud suivra à la prochaine écriture).`
        : `Affiche de ${ligne.nom} rangée dans l'album Immich (Photos › Affiche iPhone pour l'enregistrer).`)
      await charger()
      vue = { ligne: donnees.lignes.find((x) => x.pid === ligne.pid) ?? ligne, n }
    } catch (e) {
      annoncer(e.message, true)
    } finally {
      occupe = false
    }
  }

  const lignes = $derived.by(() => {
    if (!donnees) return []
    const q = cleTexte(recherche)
    return donnees.lignes.filter((l) => (!q || cleTexte(`${l.nom} ${l.societe} ${l.domaine}`).includes(q)) &&
      (filtre === 'tous' || (filtre === 'a_choisir' ? l.cands.length && l.photo == null && !l.affiche
        : filtre === 'choisies' ? l.photo != null || l.affiche : !l.cands.length)))
  })
  const nonLus = $derived(donnees ? donnees.lignes.filter((l) => !l.cherche_le).length : 0)
  const enCours = $derived(['lecture', 'ecriture'].includes(tache?.etat))
  const apercu = (l, n, sorte = 'photo') => `/api/logos/apercu/${l.pid}/${n}?sorte=${sorte}`
  const afficheDe = (l, n) => l.affiche === `logo:${l.domaine}:${n}`
</script>

{#if !donnees}
  <p class="text-mine">Chargement…</p>
{:else}
  <div class="rounded-2xl border border-couture bg-reliure p-3 mb-3 text-sm">
    <p class="text-mine text-xs mb-2">Contacts sans photo des groupes cochés : carnet lit le site de leur société (adresse du site
      de la fiche, sinon domaine du courriel pro) et propose son logo.</p>
    <div class="flex flex-wrap gap-1.5 mb-3" role="group" aria-label="Groupes concernés">
      {#each ref.groupes as g}
        <button class="h-8 px-3 rounded-full border text-xs {donnees.groupes.includes(g) ? 'border-onglet text-papier bg-onglet/10' : 'border-couture text-mine'}"
          aria-pressed={donnees.groupes.includes(g)} onclick={() => basculerGroupe(g)}>{g}</button>
      {/each}
    </div>
    <button class="w-full h-11 rounded-xl border border-onglet text-onglet disabled:opacity-50" disabled={enCours || !donnees.lignes.length}
      onclick={() => chercher(false)}>{enCours ? (tache?.message ?? 'Recherche…') : nonLus ? `Chercher les logos (${nonLus} contact${nonLus > 1 ? 's' : ''})` : 'Tous les sites sont lus'}</button>
    {#if donnees.journal.length}
      <p class="text-xs text-mine mt-2">Dernière recherche le {dateCourte(donnees.journal[0].le)} ·
        <button class="underline" disabled={enCours} onclick={() => chercher(true)}>Relire tous les sites</button></p>
    {/if}
  </div>

  <input class="w-full h-11 !rounded-xl !px-4 text-base mb-2" type="search" placeholder="Filtrer : nom, société, site" bind:value={recherche}
    aria-label="Filtrer les contacts" autocomplete="off" />
  <div class="flex flex-wrap gap-2 text-sm mb-3" role="group" aria-label="Filtre">
    {#each [['a_choisir', 'À choisir'], ['choisies', 'Choisies'], ['sans', 'Sans logo trouvé'], ['tous', 'Tous']] as [v, t]}
      <button class="h-8 px-3 rounded-full border {filtre === v ? 'border-onglet text-papier' : 'border-couture text-mine'}"
        aria-pressed={filtre === v} onclick={() => (filtre = v)}>{t}</button>
    {/each}
  </div>

  <ul class="space-y-3">
    {#each lignes as l (l.pid)}
      <li class="rounded-2xl border border-couture bg-reliure p-3">
        <div class="flex items-center gap-2 mb-2">
          <span class="flex-1 min-w-0">
            <span class="block truncate text-papier">{l.nom}</span>
            <span class="block truncate text-xs text-mine">{[l.societe, l.domaine].filter(Boolean).join(' · ')}</span>
          </span>
          {#if l.photo != null}<span class="text-xs text-valide">photo ✓</span>{/if}
          {#if l.affiche}<span class="text-xs text-valide">affiche ✓</span>{/if}
        </div>
        {#if l.cands.length}
          <div class="flex gap-2 overflow-x-auto -mx-3 px-3 pb-1" data-defile>
            {#each l.cands as c (c.n)}
              <button class="shrink-0 w-20 h-20 rounded-full overflow-hidden border-2 {l.photo === c.n || afficheDe(l, c.n) ? 'border-onglet' : 'border-transparent'}"
                onclick={() => (vue = { ligne: l, n: c.n })} aria-label={`Logo ${c.n + 1} de ${l.societe || l.nom}`}>
                <img class="w-full h-full object-cover bg-couture" src={apercu(l, c.n)} alt="" loading="lazy" />
              </button>
            {/each}
          </div>
        {:else}
          <p class="text-xs text-mine">{l.cherche_le ? `Aucun logo lisible sur ${l.domaine}.` : 'Site pas encore lu.'}</p>
        {/if}
      </li>
    {:else}
      <li class="text-sm text-mine py-6 text-center">Rien dans ce filtre.</li>
    {/each}
  </ul>
{/if}

{#if vue}
  <div class="fixed inset-0 z-40 bg-black/90 flex flex-col pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]"
    role="dialog" aria-modal="true" aria-label={`Logo pour ${vue.ligne.nom}`}>
    <div class="flex items-center px-4 h-12">
      <span class="flex-1 truncate text-papier">{vue.ligne.nom}</span>
      <button class="h-10 px-2 text-onglet" onclick={() => (vue = null)}>Fermer</button>
    </div>
    <div class="flex-1 min-h-0 grid grid-cols-2 gap-4 items-center px-4">
      <figure class="flex flex-col items-center gap-2">
        <img class="w-full max-w-48 aspect-square rounded-full object-cover bg-couture" src={apercu(vue.ligne, vue.n)} alt="" />
        <figcaption class="text-xs text-mine">Photo du contact</figcaption>
      </figure>
      <figure class="flex flex-col items-center gap-2 min-h-0 h-full justify-center">
        <img class="max-h-[60vh] w-auto rounded-xl object-contain bg-couture" src={apercu(vue.ligne, vue.n, 'affiche')} alt="" />
        <figcaption class="text-xs text-mine">Affiche iPhone</figcaption>
      </figure>
    </div>
    <div class="p-4 grid grid-cols-2 gap-2">
      <button class="h-12 rounded-xl bg-onglet text-onglet-sombre font-semibold disabled:opacity-50"
        disabled={occupe || vue.ligne.photo === vue.n} onclick={() => choisir('photo')}>{vue.ligne.photo === vue.n ? 'Photo posée ✓' : 'Photo du contact'}</button>
      <button class="h-12 rounded-xl border border-onglet text-onglet disabled:opacity-50"
        disabled={occupe || !donnees.immich || afficheDe(vue.ligne, vue.n)} onclick={() => choisir('affiche')}>{afficheDe(vue.ligne, vue.n) ? 'Affiche rangée ✓' : 'Affiche iPhone'}</button>
    </div>
  </div>
{/if}
