<script>
  let { fermer } = $props()
  const GROUPES = [
    ['↑ ↓', 'Changer de ligne'],
    ['1 à 9', 'Prendre la valeur de la colonne (ou garder / retirer une valeur multiple)'],
    ['0', 'Vider le champ ou retirer la valeur'],
    ['Espace', 'Garder ou retirer la valeur multiple'],
    ['Y', 'Changer le type (mobile, domicile…)'],
    ['E', 'Modifier la valeur retenue (Échap pour sortir)'],
    ['U F A R O C J', 'Ajouter ou retirer un groupe (la lettre est sur chaque bouton : O pour Collègues, C pour Clients)'],
    ['Entrée', 'Valider la fiche et passer à la suivante'],
    ['→ ←', 'Passer sans valider, revenir à la précédente'],
    ['M', 'Fusionner avec un autre contact'],
    ['X', 'Mettre le contact de côté (ni exporté, ni renvoyé)'],
  ]
</script>

<aside class="fixed right-6 bottom-6 w-[26rem] rounded-xl border border-tranche bg-reliure p-5 shadow-2xl z-30" aria-label="Raccourcis clavier">
  <div class="flex items-center mb-3">
    <h2 class="titre text-lg">Raccourcis</h2>
    <button class="ml-auto text-sm text-mine hover:text-papier" onclick={fermer}>Fermer</button>
  </div>
  <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
    {#each GROUPES as [touches, effet]}
      <dt class="text-right"><kbd>{touches}</kbd></dt>
      <dd class="text-mine">{effet}</dd>
    {/each}
  </dl>
</aside>
