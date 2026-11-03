// Appels à l'API de carnet. Une erreur renvoie le message lisible donné par le serveur.
export class ErreurApi extends Error {
  constructor(message, statut) { super(message); this.statut = statut }
}

async function appel(methode, chemin, corps) {
  const options = { method: methode, headers: {}, credentials: 'same-origin' }
  if (corps instanceof FormData) options.body = corps
  else if (corps !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(corps)
  }
  const r = await fetch(chemin, options)
  if (r.status === 401 && !chemin.endsWith('/connexion')) {
    window.dispatchEvent(new CustomEvent('carnet:deconnecte'))
  }
  const texte = await r.text()
  let donnees = null
  try { donnees = texte ? JSON.parse(texte) : null } catch { donnees = texte }
  if (!r.ok) {
    const detail = donnees && typeof donnees === 'object' ? donnees.detail : donnees
    throw new ErreurApi(typeof detail === 'string' ? detail : `Erreur ${r.status}`, r.status)
  }
  return donnees
}

export const api = {
  get: (c) => appel('GET', c),
  post: (c, corps = {}) => appel('POST', c, corps),
  put: (c, corps) => appel('PUT', c, corps),
}
