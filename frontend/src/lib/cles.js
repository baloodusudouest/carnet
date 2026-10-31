// Clés de comparaison des valeurs multiples : mêmes règles que app/normalisation.py,
// pour regrouper sur une seule ligne les valeurs identiques venues de sources différentes.
export const sansAccents = (t) => (t ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '')
export const cleTexte = (t) =>
  sansAccents(t).toLowerCase().replace(/[^a-z0-9@+]+/g, ' ').trim().replace(/\s+/g, ' ')

export const CLES = {
  telephones: (t) => (t.valide ? t.valeur : (t.valeur ?? '').replace(/\D/g, '')),
  courriels: (c) => (c.valeur ?? '').trim().toLowerCase(),
  adresses: (a) => cleTexte([a.rue, a.cp, a.ville].join(' ')),
  sites: (s) => (s.valeur ?? '').trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, ''),
  noms_associes: (n) => cleTexte(n.valeur),
}

export function texteItem(champ, item) {
  if (champ === 'telephones') return item.affichage || item.valeur
  if (champ === 'adresses') {
    return [item.rue?.replace(/\n/g, ', '), [item.cp, item.ville].filter(Boolean).join(' '), item.pays]
      .filter(Boolean).join(', ')
  }
  return item.valeur
}

export function anniversaireLisible(v) {
  if (!v) return ''
  const mois = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
    'septembre', 'octobre', 'novembre', 'décembre']
  const m = v.match(/^(\d{4}|-)-?(\d{2})-(\d{2})$/)
  if (!m) return v
  const jour = Number(m[3]) === 1 ? '1er' : String(Number(m[3]))
  return `${jour} ${mois[Number(m[2]) - 1]}${m[1] !== '-' ? ' ' + m[1] : ''}`
}

export function dateCourte(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })
}

// « 1 contact », « 3 contacts »
export const pluriel = (n, un, plusieurs) => `${n} ${n > 1 ? plusieurs : un}`

// Recherche de personnes sur LinkedIn (nouvel onglet) : nom et société, sans le groupe
export const rechercheLinkedin = (nom, societe = '') =>
  `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent([nom, societe].filter(Boolean).join(' '))}`
