// Appels à l'API FastAPI. Une réponse 401 renvoie vers l'écran de connexion.
import { session } from './etat.svelte.js'

async function appel(methode, chemin, corps, keepalive = false) {
  // X-Carnet : exigé par le serveur pour toute écriture (protection contre les autres sites)
  const options = { method: methode, headers: { 'X-Carnet': '1' }, credentials: 'same-origin', keepalive }
  if (corps instanceof FormData) options.body = corps
  else if (corps !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(corps)
  }
  const r = await fetch(chemin, options)
  if (r.status === 401 && chemin !== '/api/connexion') {
    session.connecte = false
    throw new Error('Connexion requise.')
  }
  const donnees = r.headers.get('content-type')?.includes('json') ? await r.json() : null
  if (!r.ok) throw new Error(donnees?.detail ?? `Erreur ${r.status}`)
  return donnees
}

export const api = {
  get: (c) => appel('GET', c),
  post: (c, corps = {}) => appel('POST', c, corps),
  put: (c, corps, keepalive = false) => appel('PUT', c, corps, keepalive),
}
