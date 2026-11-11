<script>
  // Réseaux (déplacé d'État vers Réglages en 2.8.4) : bilan par réseau, connexions LinkedIn et
  // Telegram, dépôts d'archives, personnes lues sans fiche.
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { dire, erreur, etat as global, rafraichirAccueil, rafraichirContacts } from '../lib/etat.svelte.js'
  import BoutonAnneau from './BoutonAnneau.svelte'
  import ListeNonLies from './ListeNonLies.svelte'
  import { absents, logoReseau } from '../lib/logos.svelte.js'
  import { de, envoyer, occupe, resumeImport } from '../lib/suivi.svelte.js'

  let e = $state(null)
  let attente = $state('')
  let adresseLinkedin = $state('')
  const bloque = $derived(!!attente || occupe() || global.accueil?.tache?.etat === 'en_cours')
  const date = (iso) => iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : 'jamais'
  async function charger() { try { e = await api.get('/api/etat') } catch (err) { erreur(err) } }
  async function lancer(nom, chemin, corps, message) {
    attente = nom
    try {
      const r = await api.post(chemin, corps)
      if (message) dire(typeof message === 'function' ? message(r) : message)
      await rafraichirAccueil()
      setTimeout(charger, 1500)
      return r
    } catch (err) { erreur(err) } finally { attente = '' }
  }
  async function importerFichier(cle, f) {
    try { dire(resumeImport(await envoyer(cle, f, cle))); rafraichirAccueil(); charger() } catch (err) { erreur(err) }
  }
  async function linkedinConnecter() {
    const r = await lancer('linkedin', '/api/linkedin/autorisation', {})
    if (r) window.open(r.url, '_blank', 'noopener')
  }
  async function linkedinCode() {
    await lancer('linkedin', '/api/linkedin/code', { adresse: adresseLinkedin },
      (r) => `LinkedIn : ${r.rattachees} relations reconnues, ${r.proposees} changement(s) à traiter.`)
    adresseLinkedin = ''
  }
  // Bilan des réseaux : un clic amène à la partie du réseau
  function allerReseau(s) {
    const cible = document.getElementById(`reseau-${s}`)
    cible?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
    cible?.classList.add('repere'); setTimeout(() => cible?.classList.remove('repere'), 1600)
  }
  async function rattacherReseau(service, x, uid) {
    try {
      const r = await api.post(`/api/reseaux/${service}/rattacher`, { ext_id: x.ext_id, uid })
      dire(`${x.nom} rattaché.`, { jeton: r?.jeton || null }); charger(); rafraichirContacts()
    } catch (err) { erreur(err); throw err }
  }
  async function linkedinRattacher(url, uid) {
    try { await api.post('/api/linkedin/rattacher', { url, uid }); dire(uid ? 'Relation rattachée.' : 'Relation détachée.'); charger() }
    catch (err) { erreur(err) }
  }
  // Telegram : numéro → code reçu dans Telegram → mot de passe si la double vérification est active.
  // La session n'existe qu'en mémoire le temps de l'import, puis carnet se déconnecte.
  let tg = $state({ telephone: '', code: '', mdp: '', etape: 'telephone' })
  async function telegramCode() {
    const r = await lancer('telegram', '/api/telegram/code', { telephone: tg.telephone }, 'Code envoyé dans Telegram.')
    if (r) tg.etape = 'code'
  }
  async function telegramImport() {
    const r = await lancer('telegram', '/api/telegram/import', { code: tg.code, mot_de_passe: tg.mdp })
    if (!r) return
    if (r.mot_de_passe) { tg.etape = 'mdp'; dire('Telegram demande ton mot de passe de double vérification.'); return }
    dire(`Telegram : ${r.lues} contact(s) lu(s), ${r.proposees} rattachement(s) proposé(s) dans « À traiter ».`)
    tg = { telephone: '', code: '', mdp: '', etape: 'telephone' }
  }
  async function telegramAbandon() {
    await lancer('telegram', '/api/telegram/abandon', {}, 'Connexion à Telegram abandonnée.')
    tg = { telephone: '', code: '', mdp: '', etape: 'telephone' }
  }
  const NOMS_RESEAUX = { linkedin: 'LinkedIn', telegram: 'Telegram', instagram: 'Instagram', facebook: 'Facebook',
                         x: 'X (Twitter)', whatsapp: 'WhatsApp' }

  onMount(charger)
</script>

{#if !e}
  <div class="feuille bloc"><h2 class="titre">Réseaux</h2><p class="discret">Chargement…</p></div>
{:else}
<div class="feuille bloc">
  <h2 class="titre">Réseaux</h2>
  <dl>
    {#each Object.entries(e.reseaux) as [s, r]}
      <dt><button class="reseau" onclick={() => allerReseau(s)} title={'Aller à ' + NOMS_RESEAUX[s]}>
        {#if !absents[s]}<img class="logo-reseau" src={logoReseau(s)} alt="" onerror={() => (absents[s] = true)} />{/if}{NOMS_RESEAUX[s]}</button></dt>
      <dd>{r.liees} fiche(s) liée(s){#if r.lues}, {r.lues} personne(s) lue(s){/if}{#if r.importe_le}{" "}<span class="discret">(import du {date(r.importe_le)})</span>{/if}</dd>
    {/each}
  </dl>
  <p class="discret">Chaque rapprochement arrive dans « À traiter » (Réseaux) : rien n'est lié sans toi. Les personnes lues mais jamais liées sont effacées au bout de 90 jours.</p>

  <h3 class="titre-reseau" id="reseau-linkedin">{#if !absents.linkedin}<img class="logo-reseau" src={logoReseau('linkedin')} alt="" onerror={() => (absents.linkedin = true)} />{/if}LinkedIn</h3>
  <p class="discret">Tes relations par l'API de portabilité, ou le fichier Connections.csv de l'export LinkedIn. Seuls les changements de poste ou de société remontent dans « À traiter ».</p>
  <BoutonAnneau icone="envoyer" libelle="Déposer Connections.csv" enCours="Envoi du fichier…" {...de('linkedin_csv')}
                fichier=".csv,text/csv" disabled={bloque} onfichier={(f) => importerFichier('linkedin_csv', f)} />
  {#if e.linkedin.api}
    <div class="boutons">
      <button class="bouton" disabled={!!attente} onclick={linkedinConnecter}>Se connecter à LinkedIn</button>
      {#if e.linkedin.en_attente}<button class="bouton" disabled={!!attente} onclick={() => lancer('linkedin', '/api/linkedin/reessayer', {}, (r) => `${r.rattachees} relations reconnues.`)}>Réessayer</button>{/if}
    </div>
    <label class="colle"><span class="discret">Adresse de retour de LinkedIn, collée ici</span>
      <span class="rangee"><input bind:value={adresseLinkedin} placeholder="https://localhost/carnet-linkedin?code=…" />
        <button class="bouton" disabled={!adresseLinkedin || !!attente} onclick={linkedinCode}>Importer</button></span></label>
  {/if}
  <ListeNonLies titre="Relations sans fiche" items={e.linkedin.sans_contact} cle={(r) => r.url}
                detail={(r) => [r.fonction, r.societe].filter(Boolean).join(', ')}
                rattacher={(r, uid) => linkedinRattacher(r.url, uid)} detacher={(r) => linkedinRattacher(r.url, null)} />

  <h3 class="titre-reseau" id="reseau-telegram">{#if !absents.telegram}<img class="logo-reseau" src={logoReseau('telegram')} alt="" onerror={() => (absents.telegram = true)} />{/if}Telegram</h3>
  {#if !e.telegram.configure}
    <p class="discret">Ajoute CARNET_TELEGRAM_API_ID et CARNET_TELEGRAM_API_HASH dans la stack (my.telegram.org, « API development tools »).</p>
  {:else if tg.etape === 'telephone'}
    <span class="rangee"><input type="tel" bind:value={tg.telephone} placeholder="+33 6 12 34 56 78" aria-label="Ton numéro Telegram" autocomplete="tel" />
      <button class="bouton" disabled={!tg.telephone || !!attente} onclick={telegramCode}>Recevoir le code</button></span>
  {:else}
    <span class="rangee"><input inputmode="numeric" bind:value={tg.code} placeholder="Code reçu dans Telegram" aria-label="Code Telegram" autocomplete="one-time-code" />
      {#if tg.etape === 'mdp'}<input type="password" bind:value={tg.mdp} placeholder="Mot de passe Telegram" aria-label="Mot de passe Telegram" autocomplete="off" />{/if}
      <button class="bouton bouton-principal" disabled={!tg.code || (tg.etape === 'mdp' && !tg.mdp) || !!attente} onclick={telegramImport}>Importer</button>
      <button class="bouton" disabled={!!attente} onclick={telegramAbandon}>Abandonner</button></span>
  {/if}
  {#if e.telegram.configure}<p class="discret">Import ponctuel : carnet lit tes contacts Telegram puis se déconnecte. La session n'est ni gardée ni sauvegardée.</p>{/if}

  <ListeNonLies titre="Importés de Telegram sans fiche" charger={() => api.get('/api/reseaux/telegram/non-lies')}
                detail={(x) => [x.pseudo && x.pseudo !== x.nom && '@' + x.pseudo, x.telephone].filter(Boolean).join(', ')}
                rattacher={(x, uid) => rattacherReseau('telegram', x, uid)} />

  <h3 class="titre-reseau" id="reseau-facebook">{#if !absents.facebook}<img class="logo-reseau" src={logoReseau('facebook')} alt="" onerror={() => (absents.facebook = true)} />{/if}Facebook</h3>
  <p class="discret">Compte Meta › Vos informations et autorisations › Exporter vos informations : choisis seulement Contacts › <strong>Ami(e)s</strong> (et Followers si tu veux), format <strong>JSON</strong>. Dépose le .zip tel quel, ou seulement <strong>your_friends.json</strong> si tu l'as décompressé (les autres fichiers sont des suggestions ou des demandes, ils ne sont pas lus). Facebook ne donne que les noms : un ami est proposé quand son nom désigne une seule fiche. « Lier » pose la pastille Facebook ; pour écrire le lien du profil dans iCloud, colle son adresse sur la fiche.</p>
  <BoutonAnneau icone="envoyer" libelle="Déposer l'export Facebook" enCours="Envoi de l'archive…" {...de('facebook')}
                fichier=".zip,.json,application/zip,application/json" disabled={bloque}
                onfichier={(f) => importerFichier('facebook', f)} />

  <ListeNonLies titre="Importés de Facebook sans fiche" charger={() => api.get('/api/reseaux/facebook/non-lies')}
                detail={(x) => [x.pseudo && x.pseudo !== x.nom && '@' + x.pseudo, x.telephone].filter(Boolean).join(', ')}
                rattacher={(x, uid) => rattacherReseau('facebook', x, uid)} />

  <h3 class="titre-reseau" id="reseau-instagram">{#if !absents.instagram}<img class="logo-reseau" src={logoReseau('instagram')} alt="" onerror={() => (absents.instagram = true)} />{/if}Instagram</h3>
  <p class="discret">Dans Instagram : Paramètres, Espace Comptes, Télécharger tes informations, format JSON, « Abonnés et abonnements ». Seuls les pseudos sont lus.</p>
  <BoutonAnneau icone="envoyer" libelle="Déposer l'export Instagram" enCours="Envoi de l'archive…" {...de('instagram')}
                fichier=".zip,.json,application/zip,application/json" disabled={bloque}
                onfichier={(f) => importerFichier('instagram', f)} />
  <p class="discret">Les archives sont lues en mémoire puis oubliées : rien n'est gardé sur le NAS.</p>
  <ListeNonLies titre="Importés d'Instagram sans fiche" charger={() => api.get('/api/reseaux/instagram/non-lies')}
                detail={(x) => [x.pseudo && x.pseudo !== x.nom && '@' + x.pseudo, x.telephone].filter(Boolean).join(', ')}
                rattacher={(x, uid) => rattacherReseau('instagram', x, uid)} />

  <h3 class="titre-reseau" id="reseau-x">{#if !absents.x}<img class="logo-reseau" src={logoReseau('x')} alt="" onerror={() => (absents.x = true)} />{/if}X (Twitter)</h3>
  <p class="discret">L'archive de X ne donne que des numéros de compte, sans pseudo ni nom : rien à rapprocher. Sur la fiche, colle le pseudo (@…) ou l'adresse x.com dans Plateformes ; les profils Twitter déjà présents sur tes cartes iCloud sont reconnus.</p>

  <h3 class="titre-reseau" id="reseau-whatsapp">{#if !absents.whatsapp}<img class="logo-reseau" src={logoReseau('whatsapp')} alt="" onerror={() => (absents.whatsapp = true)} />{/if}WhatsApp</h3>
  <p class="discret">Pas d'export des contacts : sur la fiche, choisis le numéro WhatsApp (section Plateformes).</p>
</div>
{/if}

<style>
  .logo-reseau { width: 1.35rem; height: 1.35rem; border-radius: 5px; background: #f4efe7; object-fit: contain;
    box-shadow: 0 0 0 1px rgb(0 0 0 / 0.25); flex: none; }
  .titre-reseau { display: flex; align-items: center; gap: 0.5rem; scroll-margin-top: calc(1rem + env(safe-area-inset-top));
    border-radius: 6px; transition: background-color 0.6s ease; }
  :global(.titre-reseau.repere) { background: color-mix(in srgb, var(--color-onglet) 18%, transparent); }
  button.reseau { display: flex; align-items: center; gap: 0.45rem; color: var(--color-mine); text-align: left; min-height: 1.8rem; }
  button.reseau:hover { color: var(--color-papier); text-decoration: underline; text-underline-offset: 3px; }
  h2 { font-size: 1.2rem; margin-bottom: 0.6rem; }
  h3 { font-weight: 600; margin: 0.9rem 0 0.4rem; }
  .bloc { padding: 1rem; display: grid; gap: 0.6rem; }
  dl { display: grid; grid-template-columns: minmax(8rem, auto) 1fr; gap: 0.3rem 1rem; }
  dt { color: var(--color-mine); }
  .boutons { display: flex; flex-wrap: wrap; gap: 0.5rem; }
  .colle { display: grid; gap: 0.3rem; }
  .rangee { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
  .rangee input { flex: 1; min-width: 12rem; }
</style>
