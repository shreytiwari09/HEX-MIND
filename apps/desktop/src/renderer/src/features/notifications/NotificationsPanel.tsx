import { useState } from 'react'

import { askPermission, notificationsEnabled, permission, setNotificationsEnabled, type Permission } from './useMissionNotifications'

interface Props {
  /** Called when the setting changes, so the app starts or stops watching. */
  onChange: (on: boolean) => void
}

/** Whether to be told when a mission needs you, finishes or fails. */
export function NotificationsPanel({ onChange }: Props) {
  const [on, setOn] = useState(notificationsEnabled)
  const [allowed, setAllowed] = useState<Permission>(permission)

  const toggle = async (next: boolean) => {
    if (next) {
      const result = await askPermission()
      setAllowed(result)
      if (result !== 'granted') return
    }
    setNotificationsEnabled(next)
    setOn(next)
    onChange(next)
  }

  return (
    <section className="persona-editor" aria-label="Notifications">
      <h2 className="mission__title">Notifications</h2>
      <p className="mission__muted">
        Get a desktop notification when a mission needs your decision, finishes, or fails, even when you are looking
        at something else.
      </p>
      <label className="persona-editor__skill">
        <input
          type="checkbox"
          checked={on && allowed === 'granted'}
          disabled={allowed === 'unsupported'}
          onChange={(event) => void toggle(event.target.checked)}
        />
        <span>Tell me about my missions</span>
      </label>
      {allowed === 'denied' && (
        <p role="alert" className="mission__error">
          Notifications are blocked for this app. Allow them in your system settings, then turn this on again.
        </p>
      )}
      {allowed === 'unsupported' && <p className="mission__muted">This system cannot show notifications.</p>}
    </section>
  )
}
