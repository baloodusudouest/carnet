import { mount } from 'svelte'
import '@fontsource/spectral/400.css'
import '@fontsource/spectral/600.css'
import '@fontsource/spectral/400-italic.css'
import '@fontsource-variable/instrument-sans'
import './app.css'
import App from './App.svelte'

mount(App, { target: document.getElementById('app') })
