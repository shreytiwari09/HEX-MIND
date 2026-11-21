import { CheckCircle2, CircleAlert, Info, X } from 'lucide-react'
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

export type ToastKind = 'success' | 'error' | 'info'

interface Toast {
  id: number
  kind: ToastKind
  text: string
}

type Notify = (text: string, kind?: ToastKind) => void

const ToastContext = createContext<Notify>(() => {})

const LIFETIME_MS = { success: 3500, info: 3500, error: 7000 } as const
const ICONS = { success: CheckCircle2, error: CircleAlert, info: Info } as const

/** Short notices for actions that otherwise happen out of sight (a terminal opened, a folder
 * failed to open). Errors stay longer; every toast can be dismissed. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const next = useRef(1)

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const notify = useCallback<Notify>(
    (text, kind = 'info') => {
      const id = next.current++
      setToasts((all) => [...all.slice(-3), { id, kind, text }])
      window.setTimeout(() => dismiss(id), LIFETIME_MS[kind])
    },
    [dismiss]
  )
  const value = useMemo(() => notify, [notify])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => {
          const Icon = ICONS[t.kind]
          return (
            <div key={t.id} className="toast" data-kind={t.kind}>
              <Icon size={16} className="toast__icon" aria-hidden="true" />
              <span className="toast__text">{t.text}</span>
              <button type="button" className="icon-button toast__close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): Notify {
  return useContext(ToastContext)
}
