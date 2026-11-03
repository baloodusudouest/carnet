// État partagé de l'interface : page affichée (adresse #/…), accueil (compteurs, tâche en
// cours), liste des contacts gardée en mémoire et message bref avec « Annuler ».
import { api } from './api.js'

function lireTri() {
  try { return localStorage.getItem('carnet-tri') === 'nom' ? 'nom' : 'prenom' } catch { return 'prenom' }
}

const LARGE = matchMedia('(min-width: 900px)')

export const etat = $state({
  route: lireRoute(),
  accueil: null,
  contacts: null,
  message: null,       // { texte, erreur, jeton }
  connecte: null,
  large: LARGE.matches, // PC : liste et fiche côte à côte
  tri: lireTri(),       // « prenom » ou « nom », gardé sur cet appareil
})
LARGE.addEventListener('change', (e) => { etat.large = e.matches })

export function choisirTri(tri) {
  etat.tri = tri
  try { localStorage.setItem('carnet-tri', tri) } catch { /* navigation privée : choix non gardé */ }
}

function lireRoute() {
  const morceaux = (location.hash.replace(/^#\/?/, '') || 'a-traiter').split('/').map(decodeURIComponent)
  return { page: morceaux[0], args: morceaux.slice(1) }
}

window.addEventListener('hashchange', () => {
  const avant = etat.route.page
  etat.route = lireRoute()
  // Sur PC, ouvrir une fiche garde la liste à sa place
  if (!(etat.large && avant === etat.route.page)) window.scrollTo(0, 0)
})
window.addEventListener('carnet:deconnecte', () => { etat.connecte = false })

export function aller(...morceaux) {
  location.hash = '#/' + morceaux.map(encodeURIComponent).join('/')
}

let minuterie
export function dire(texte, { erreur = false, jeton = null } = {}) {
  clearTimeout(minuterie)
  etat.message = { texte, erreur, jeton }
  minuterie = setTimeout(() => { etat.message = null }, jeton ? 10000 : erreur ? 8000 : 4000)
}

export function erreur(e) { dire(e?.message || String(e), { erreur: true }) }

export async function rafraichirAccueil() {
  try { etat.accueil = await api.get('/api/accueil') } catch { /* hors ligne : on garde l'ancien */ }
}

export async function rafraichirContacts() {
  etat.contacts = await api.get('/api/contacts')
  return etat.contacts
}

// Après une écriture : listes à jour, et message avec « Annuler » quand l'écriture le permet
export async function apresEcriture(res, texte = 'Écrit dans iCloud.') {
  dire(texte, { jeton: res?.jeton || null })
  await Promise.all([rafraichirAccueil(), rafraichirContacts()])
}

export async function annuler(jeton) {
  try {
    await api.post(`/api/annuler/${jeton}`)
    dire('Annulé : la fiche est revenue comme avant.')
    await Promise.all([rafraichirAccueil(), rafraichirContacts()])
  } catch (e) { erreur(e) }
}
