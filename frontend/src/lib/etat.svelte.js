// État partagé de l'interface : page affichée (adresse #/…), accueil (compteurs, tâche en
// cours), liste des contacts gardée en mémoire et message bref avec « Annuler ».
import { api } from './api.js'

export const etat = $state({
  route: lireRoute(),
  accueil: null,
  contacts: null,
  message: null,       // { texte, erreur, jeton }
  connecte: null,
})

function lireRoute() {
  const morceaux = (location.hash.replace(/^#\/?/, '') || 'a-traiter').split('/').map(decodeURIComponent)
  return { page: morceaux[0], args: morceaux.slice(1) }
}

window.addEventListener('hashchange', () => { etat.route = lireRoute(); window.scrollTo(0, 0) })
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
