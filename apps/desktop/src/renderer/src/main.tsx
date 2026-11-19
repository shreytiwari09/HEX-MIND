import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { BackendProvider } from './lib/backend'
import './styles/tokens.css'
import './styles/app.css'
import './styles/observability.css'
import './styles/missions.css'
import './styles/models.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BackendProvider>
      <App />
    </BackendProvider>
  </StrictMode>
)
