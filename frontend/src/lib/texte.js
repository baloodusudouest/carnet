// Texte comparable : sans accents, en minuscules, espaces réduits (recherches et filtres)
export const cleTexte = (t) => (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim()
