// Suivi des boutons à anneau : un état par action (repos, en_cours, succes, echec) et sa progression.
// - tache(cle, chemin, corps, nom) : opération lancée à part par le serveur, suivie par /api/accueil
// - appel(cle, promesse)           : opération qui répond quand elle a fini
// - telecharger(cle, url, nom)     : téléchargement avec progression, puis enregistrement du fichier
// - envoyer(cle, fichier)          : import avec progression d'envoi
import { api, ErreurApi } from './api.js'
import { etat as app, rafraichirAccueil } from './etat.svelte.js'

export const suivi = $state({})

const RETOUR = { succes: 2600, echec: 5000 }   // délai avant le retour au repos
const minuteurs = {}

function poser(cle, e, progression = null, detail = '') {
  clearTimeout(minuteurs[cle])
  suivi[cle] = { etat: e, progression, detail }
  if (RETOUR[e]) minuteurs[cle] = setTimeout(() => { suivi[cle] = { etat: 'repos', progression: null, detail: '' } }, RETOUR[e])
}
export const de = (cle) => suivi[cle] || { etat: 'repos', progression: null, detail: '' }
export const occupe = () => Object.values(suivi).some((s) => s.etat === 'en_cours')

export async function appel(cle, promesse) {
  poser(cle, 'en_cours')
  try {
    const r = await promesse()
    poser(cle, 'succes')
    return r
  } catch (err) {
    poser(cle, 'echec', null, err.message)
    throw err
  }
}

// Opération de fond : on suit c.tache (nom, etat, progression) jusqu'à la fin
export async function tache(cle, chemin, corps, nom) {
  poser(cle, 'en_cours')
  try {
    await api.post(chemin, corps)
  } catch (err) {
    poser(cle, 'echec', null, err.message)
    throw err
  }
  return new Promise((fini) => {
    const verifier = async () => {
      await rafraichirAccueil()
      const t = app.accueil?.tache
      if (t?.nom === nom && t.etat === 'en_cours') {
        suivi[cle] = { etat: 'en_cours', progression: typeof t.progression === 'number' ? t.progression : null, detail: t.message }
        setTimeout(verifier, 1500)
      } else if (t?.nom === nom && t.etat === 'erreur') {
        poser(cle, 'echec', null, t.message); fini(false)
      } else {
        poser(cle, 'succes', null, t?.nom === nom ? t.message : ''); fini(true)
      }
    }
    setTimeout(verifier, 800)
  })
}

export async function telecharger(cle, url, nomParDefaut) {
  poser(cle, 'en_cours', 0)
  try {
    const r = await fetch(url, { credentials: 'same-origin' })
    if (!r.ok) {
      let detail = `Erreur ${r.status}`
      try { detail = (await r.json()).detail || detail } catch { /* corps non JSON */ }
      throw new ErreurApi(detail, r.status)
    }
    const total = Number(r.headers.get('Content-Length')) || 0
    const lecteur = r.body.getReader()
    const morceaux = []
    let recu = 0
    for (;;) {
      const { done, value } = await lecteur.read()
      if (done) break
      morceaux.push(value)
      recu += value.length
      suivi[cle] = { etat: 'en_cours', progression: total ? recu / total : null, detail: '' }
    }
    const nom = /filename="?([^";]+)"?/.exec(r.headers.get('Content-Disposition') || '')?.[1] || nomParDefaut
    const lien = document.createElement('a')
    lien.href = URL.createObjectURL(new Blob(morceaux, { type: 'text/vcard' }))
    lien.download = nom
    lien.click()
    setTimeout(() => URL.revokeObjectURL(lien.href), 10000)
    poser(cle, 'succes', null, `${nom}, ${Math.max(1, Math.round(recu / 1024))} Ko`)
    return nom
  } catch (err) {
    poser(cle, 'echec', null, err.message === 'Failed to fetch' ? 'Connexion coupée : réessaie.' : err.message)
    throw err
  }
}

// Envoi d'un fichier avec progression (fetch ne donne pas l'avancement de l'envoi)
export function envoyer(cle, fichier) {
  poser(cle, 'en_cours', 0)
  return new Promise((ok, ko) => {
    const x = new XMLHttpRequest()
    x.open('POST', `/api/import?nom=${encodeURIComponent(fichier.name)}`)
    x.setRequestHeader('Content-Type', 'application/octet-stream')
    x.upload.onprogress = (e) => {
      // L'envoi va jusqu'à 90 % ; le reste, c'est la lecture par carnet
      if (e.lengthComputable) suivi[cle] = { etat: 'en_cours', progression: 0.9 * e.loaded / e.total, detail: '' }
    }
    x.upload.onload = () => { suivi[cle] = { etat: 'en_cours', progression: null, detail: 'Lecture…' } }
    x.onload = () => {
      let d = null
      try { d = JSON.parse(x.responseText) } catch { /* vide */ }
      if (x.status >= 200 && x.status < 300) { poser(cle, 'succes'); ok(d) }
      else {
        const message = (d && typeof d.detail === 'string') ? d.detail : `Erreur ${x.status}`
        poser(cle, 'echec', null, message); ko(new ErreurApi(message, x.status))
      }
    }
    x.onerror = () => { poser(cle, 'echec', null, 'Connexion coupée : réessaie.'); ko(new ErreurApi('Connexion coupée : réessaie.', 0)) }
    x.send(fichier)
  })
}

// Bilan lisible d'un import, le même partout
export function resumeImport(r) {
  return r.source === 'linkedin'
    ? `LinkedIn : ${r.rattachees} relations reconnues, ${r.proposees} changement(s) à traiter.`
    : r.source === 'facebook'
      ? `Facebook : ${r.lues} ami(s) lu(s), ${r.proposees} rattachement(s) proposé(s) dans « À traiter ». L'archive n'est pas gardée.`
    : r.source === 'instagram'
      ? `Instagram : ${r.lues} compte(s) lu(s), ${r.proposees} rattachement(s) proposé(s). L'archive n'est pas gardée.`
      : `${r.lues} fiche(s) lue(s), ${r.a_traiter} à vérifier dans « À traiter ».`
}
