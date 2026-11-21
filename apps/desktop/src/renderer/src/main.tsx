import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { ToastProvider } from './components/Toasts'
import { BackendProvider } from './lib/backend'
import './styles/tokens.css'
import './styles/app.css'
import './styles/observability.css'
import './styles/missions.css'
import './styles/models.css'
import './styles/shell.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BackendProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </BackendProvider>
  </StrictMode>
)
