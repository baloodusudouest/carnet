<script>
  // Photo de la fiche (lue dans iCloud), sinon les initiales
  let { uid, nom = '', photo = false, taille = 40 } = $props()
  let rate = $state(false)
  const initiales = $derived(nom.split(/\s+/).filter(Boolean).slice(0, 2).map((m) => m[0]).join('').toUpperCase())
</script>

<span class="avatar" style:width="{taille}px" style:height="{taille}px" style:font-size="{taille * 0.38}px" aria-hidden="true">
  {#if photo && !rate}
    <img src={`/api/contacts/${encodeURIComponent(uid)}/photo?cote=${taille * 2}`} alt="" loading="lazy" onerror={() => (rate = true)} />
  {:else}
    {initiales}
  {/if}
</span>

<style>
  .avatar {
    flex: none; display: inline-grid; place-items: center; border-radius: 50%; overflow: hidden;
    background: var(--color-reliure); color: var(--color-mine); font-weight: 600; box-shadow: inset 0 0 0 1px var(--color-couture);
  }
  img { width: 100%; height: 100%; object-fit: cover; }
</style>
