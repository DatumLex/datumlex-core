import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import AccessApp from './AccessApp.jsx'
import './index.css'
import './access.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AccessApp />
  </StrictMode>,
)
