// Plateformes suivies par carnet : abréviation, nom et teinte (pas de logos de marque)
export const PLATEFORMES = {
  icloud: { court: 'iC', nom: 'iCloud', teinte: '#8fa9c7' },
  immich: { court: 'Im', nom: 'Immich', teinte: '#c79bd6' },
  treemich: { court: 'Tr', nom: 'Treemich', teinte: '#8fbf8f' },
  linkedin: { court: 'Li', nom: 'LinkedIn', teinte: '#6fa3d8' },
  facebook: { court: 'Fb', nom: 'Facebook', teinte: '#7f95e0' },
  instagram: { court: 'Ig', nom: 'Instagram', teinte: '#e08fb3' },
  whatsapp: { court: 'Wa', nom: 'WhatsApp', teinte: '#7fcf98' },
  telegram: { court: 'Tg', nom: 'Telegram', teinte: '#76c0e6' },
}
export const ORDRE = Object.keys(PLATEFORMES)
// Réseaux qu'on rattache depuis la fiche
export const RESEAUX = ['facebook', 'instagram', 'telegram', 'whatsapp']
