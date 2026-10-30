// État partagé de l'interface (runes Svelte 5).
export const session = $state({ connecte: null })
export const ref = $state({ groupes: [], regles: {}, types: {}, sources: {}, groupe_verifies: '✓ Vérifiés' })
export const statut = $state({ total: 0, verifies: 0, a_reviser: 0 })
export const message = $state({ texte: '', erreur: false, id: 0 })

export function annoncer(texte, erreur = false) {
  message.texte = texte
  message.erreur = erreur
  message.id += 1
}

// Navigation par l'ancre : #/revision, #/revision/<id>, #/contacts…
export const route = $state({ page: 'accueil', id: null })

function lireAncre() {
  const [page, id] = location.hash.replace(/^#\/?/, '').split('/')
  route.page = page || 'accueil'
  route.id = id || null
}
window.addEventListener('hashchange', lireAncre)
lireAncre()

export function aller(page, id = null) {
  location.hash = id ? `#/${page}/${id}` : `#/${page}`
}
