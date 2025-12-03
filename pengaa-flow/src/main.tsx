import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Support both 'root' (standalone) and 'pengaa-flow-root' (Django embedded)
const rootElement = document.getElementById('pengaa-flow-root') || document.getElementById('root')

if (rootElement) {
  createRoot(rootElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
