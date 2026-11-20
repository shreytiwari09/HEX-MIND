import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'

type Mode = 'any' | 'trusted' | 'local'

interface Privacy {
  mode: Mode
  trusted_connections: string[]
  connections: { id: string; name: string; local: boolean }[]
}

const MODES: { id: Mode; label: string; help: string }[] = [
  { id: 'any', label: 'Any provider', help: 'Every connection you added may be used for this project.' },
  {
    id: 'trusted',
    label: 'Trusted providers',
    help: 'Local models, plus only the connections you tick below.'
  },
  { id: 'local', label: 'Local models only', help: 'Nothing leaves your machine. Plugins with network access do not run.' }
]

interface Props {
  api: ApiClient
  projectId: string
  projectName: string
}

/** Which providers may see this project's prompts (PRD §13.5). Only the prompt of each model call
 * ever leaves the machine; mission state, code and memory stay local. */
export function PrivacyPanel({ api, projectId, projectName }: Props) {
  const [saved, setSaved] = useState<Privacy | null>(null)
  const [mode, setMode] = useState<Mode>('any')
  const [trusted, setTrusted] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const loaded = await api.get<Privacy>(`/projects/${projectId}/privacy`)
      if (!loaded || !Array.isArray(loaded.connections)) throw new Error('unexpected answer')
      setSaved(loaded)
      setMode(loaded.mode)
      setTrusted(loaded.trusted_connections)
      setError(null)
    } catch (err) {
      setError(describeError(err).message)
    }
  }, [api, projectId])

  useEffect(() => {
    void load()
  }, [load])

  const dirty = saved !== null && (mode !== saved.mode || trusted.join() !== saved.trusted_connections.join())

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const next = await api.put<Privacy>(`/projects/${projectId}/privacy`, {
        mode,
        trusted_connections: mode === 'trusted' ? trusted : []
      })
      setSaved(next)
      setTrusted(next.trusted_connections)
      setNotice('Saved. It applies to the next model call.')
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const remote = saved?.connections.filter((c) => !c.local) ?? []
  return (
    <section className="persona-editor" aria-label="Privacy">
      <h2 className="mission__title">Privacy for {projectName}</h2>
      <p className="mission__muted">
        Only the prompt of each model call leaves your machine. This decides which providers may receive it. If no
        allowed model is available, the call fails instead of going elsewhere.
      </p>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {saved && (
        <fieldset className="persona-editor__skills">
          <legend>Who may see this project&apos;s prompts</legend>
          {MODES.map((option) => (
            <label key={option.id} className="persona-editor__skill">
              <input type="radio" name="privacy-mode" checked={mode === option.id} onChange={() => setMode(option.id)} />
              <span>
                <strong>{option.label}</strong> <span className="mission__muted">{option.help}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {saved && mode === 'trusted' && (
        <fieldset className="persona-editor__skills">
          <legend>Trusted connections</legend>
          {remote.length === 0 ? (
            <p className="mission__muted">You have no remote connections yet; only local models can be used.</p>
          ) : (
            remote.map((connection) => (
              <label key={connection.id} className="persona-editor__skill">
                <input
                  type="checkbox"
                  checked={trusted.includes(connection.id)}
                  onChange={(event) =>
                    setTrusted((current) =>
                      event.target.checked ? [...current, connection.id] : current.filter((id) => id !== connection.id)
                    )
                  }
                />
                <span>{connection.name}</span>
              </label>
            ))
          )}
        </fieldset>
      )}
      {notice && (
        <p role="status" className="mission__muted">
          {notice}
        </p>
      )}
      <div className="new-mission__actions">
        <button type="button" className="button button--primary" disabled={busy || !dirty} onClick={() => void save()}>
          Save
        </button>
      </div>
    </section>
  )
}
