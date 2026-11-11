<script>
  // Anneau de complétude autour de l'avatar : la part des attentes de ses groupes qui est remplie.
  // Sans aucune attente (fiche sans groupe, ou groupe qui n'attend rien), l'anneau reste vide.
  let { score = 0, total = 0, statut = null, taille = 40, children } = $props()
  const part = $derived(statut === 'valide' ? 1 : total ? Math.min(1, score / total) : 0)
  const r = $derived(taille / 2 + 3)
  const tour = $derived(2 * Math.PI * r)
  const couleur = $derived(statut === 'valide' ? 'var(--color-valide)' : statut === 'a_revoir' ? 'var(--color-alerte)' : 'var(--color-onglet)')
</script>

<span class="jauge" style:width="{taille + 8}px" style:height="{taille + 8}px"
      title={statut === 'valide' ? 'Fiche validée' : statut === 'a_revoir' ? 'Validée, à revoir' : total ? `${score} sur ${total}` : 'Rien d\'attendu'}>
  <svg viewBox="0 0 {taille + 8} {taille + 8}" aria-hidden="true">
    <circle cx={taille / 2 + 4} cy={taille / 2 + 4} {r} fill="none" stroke="var(--color-couture)" stroke-width="2.5" />
    <circle cx={taille / 2 + 4} cy={taille / 2 + 4} {r} fill="none" stroke={couleur} stroke-width="2.5" stroke-linecap="round"
            stroke-dasharray="{tour * part} {tour}" transform="rotate(-90 {taille / 2 + 4} {taille / 2 + 4})" />
  </svg>
  <span class="dedans">{@render children?.()}</span>
</span>

<style>
  .jauge { position: relative; display: inline-grid; place-items: center; flex: none; }
  svg { position: absolute; inset: 0; }
  .dedans { display: grid; }
</style>
