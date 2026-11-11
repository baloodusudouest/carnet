// Icônes au trait (24 × 24, trait 1.8, sans remplissage) : onglets et boutons à anneau.
export const ICONES = {
  // Onglets
  'a-traiter': '<path d="M4 13.5 6.2 5.6A1.6 1.6 0 0 1 7.8 4.5h8.4a1.6 1.6 0 0 1 1.6 1.1L20 13.5"/><path d="M4 13.5V18a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 18v-4.5h-4.6l-1.2 2.2h-4.4l-1.2-2.2z"/>',
  contacts: '<path d="M6 3.5h11.5A1.5 1.5 0 0 1 19 5v14a1.5 1.5 0 0 1-1.5 1.5H6z"/><path d="M6 3.5v17M4 7.5h3.5M4 12h3.5M4 16.5h3.5"/><circle cx="12.6" cy="10" r="2.3"/><path d="M9.3 16.3c.6-1.9 1.8-2.8 3.3-2.8s2.7.9 3.3 2.8"/>',
  etat: '<path d="M4.5 16.5a7.5 7.5 0 1 1 15 0"/><path d="m12 16.5 3.6-4.6"/><circle cx="12" cy="16.5" r="1.2"/><path d="M4 19.5h16"/>',
  photos: '<rect x="3.5" y="5.5" width="17" height="13.5" rx="2"/><circle cx="9" cy="10.5" r="1.7"/><path d="m4.5 17.5 4.6-4.4 3.2 3 2.6-2.4 4.6 4.3"/>',
  reglages: '<path d="M5 7.5h6M15 7.5h4M5 16.5h3M12 16.5h7"/><circle cx="13" cy="7.5" r="2"/><circle cx="10" cy="16.5" r="2"/>',
  groupes: '<circle cx="9" cy="9" r="3"/><path d="M3.5 18.5c.6-3 2.7-4.5 5.5-4.5s4.9 1.5 5.5 4.5"/><circle cx="17" cy="8" r="2.3"/><path d="M16.2 13.6c2.4.2 3.9 1.6 4.3 4"/>',
  connexion: '<circle cx="12" cy="12" r="2.6"/><circle cx="5" cy="6" r="1.8"/><circle cx="19" cy="6" r="1.8"/><circle cx="5" cy="18" r="1.8"/><circle cx="19" cy="18" r="1.8"/><path d="m6.4 7.2 3.6 3M17.6 7.2l-3.6 3M6.4 16.8l3.6-3M17.6 16.8l-3.6-3"/>',
  // Boutons à anneau
  telecharger: '<path d="M12 6.5v10M7.5 12.5 12 17l4.5-4.5"/>',
  envoyer: '<path d="M12 17.5v-10M7.5 11.5 12 7l4.5 4.5"/>',
  relire: '<path d="M17.5 9.5A6 6 0 0 0 6.6 8.8M6.5 14.5a6 6 0 0 0 10.9.7"/><path d="M6.4 5.6v3.4h3.4M17.6 18.4V15h-3.4"/>',
  nuit: '<path d="M16.5 14.8A6 6 0 0 1 9.2 7.5a6 6 0 1 0 7.3 7.3z"/>',
  analyse: '<circle cx="10.8" cy="10.8" r="4.8"/><path d="m14.4 14.4 3.6 3.6"/>',
  copier: '<rect x="8.5" y="8.5" width="9" height="9" rx="1.5"/><path d="M6.5 15h-.5A1.5 1.5 0 0 1 4.5 13.5V6A1.5 1.5 0 0 1 6 4.5h7.5A1.5 1.5 0 0 1 15 6v.5"/>',
}

// Icônes des services de Connexion (les réseaux sociaux montrent leur propre logo)
export const ICONES_SERVICES = {
  icloud: '<path d="M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.1 9.5 4.3 4.3 0 0 0 7 18z"/>',
  immich: '<rect x="3.5" y="5.5" width="17" height="13.5" rx="2"/><circle cx="9" cy="10.5" r="1.7"/><path d="m4.5 17.5 4.6-4.4 3.2 3 2.6-2.4 4.6 4.3"/>',
  treemich: '<circle cx="12" cy="5.5" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/><path d="M12 7.5v4M12 11.5H6V16M12 11.5h6V16"/>',
  synology: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  sauvegardes: '<path d="M4 7h16v12H4z"/><path d="M4 7l2-3h12l2 3"/><path d="M10 12h4"/>',
  import: '<path d="M12 4v10M7.5 10 12 14.5 16.5 10"/><path d="M5 18.5h14"/>',
  ha: '<path d="M4 11.5 12 4l8 7.5"/><path d="M6.5 10v9h11v-9"/><path d="M12 19v-5"/><circle cx="12" cy="12.5" r="1.3"/>',
  kit: '<rect x="4" y="7.5" width="16" height="11.5" rx="2"/><path d="M9 7.5V6a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 6v1.5"/><path d="M12 10.5v5M9.5 13h5"/>',
  attentes: '<rect x="4" y="4.5" width="16" height="15" rx="2"/><path d="m7.5 10 1.6 1.6 2.9-3M7.5 15.5l1.6 1.6 2.9-3M14.5 10h2.5M14.5 15.5h2.5"/>',
  defaut: '<circle cx="12" cy="12" r="7.5"/>',
}
// Icônes des tuiles d'« À traiter »
export const ICONES_TUILES = {
  icloud: '<rect x="7.5" y="3.5" width="9" height="17" rx="2"/><path d="M11 17.5h2"/>',
  sans_groupe: '<circle cx="12" cy="9" r="3.2"/><path d="M5.5 19c.8-3.4 3.3-5 6.5-5"/><path d="M16 15.5v5M13.5 18h5"/>',
  immich: ICONES_SERVICES.immich,
  treemich: ICONES_SERVICES.treemich,
  doublons: '<circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5"/>',
  societes: '<path d="M5 20V6.5L12 4v16M12 9.5l7 2V20M4 20h16"/><path d="M8 9.5h1M8 13h1M8 16.5h1M15.5 14h1M15.5 17h1"/>',
  forme: '<path d="M5 18.5 9.5 6h1L15 18.5M6.8 14h6.4"/><path d="M17 11.5h3M17 15h3M17 18.5h3"/>',
  reseaux: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 10.9l7.6-3.8M8.2 13.1l7.6 3.8"/>',
  imports: '<path d="M12 4v10M7.5 10 12 14.5 16.5 10"/><path d="M5 18.5h14"/>',
  incomplet: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 8 8h-8z"/>',
}
