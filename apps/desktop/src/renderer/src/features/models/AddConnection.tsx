import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import type { ConnectionResult, ProviderType } from './types'

interface Props {
  api: ApiClient
  types: ProviderType[]
  onAdded: (result: ConnectionResult) => void
}

/**
 * Add a provider connection. The key goes straight to the backend, which tests it and stores it in
 * the operating system's keychain; it is never shown again, and this form forgets it as soon as it
 * has been sent.
 */
export function AddConnection({ api, types, onAdded }: Props) {
  const [type, setType] = useState('')
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const preset = types.find((t) => t.type === type)
  const needsUrl = preset !== undefined && preset.base_url === null

  const choose = (next: string) => {
    setType(next)
    const chosen = types.find((t) => t.type === next)
    setName(chosen?.label ?? '')
    setBaseUrl('')
    setError(null)
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!preset) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.post<ConnectionResult>('/connections', {
        name: name.trim(),
        provider_type: type,
        base_url: baseUrl.trim() || undefined,
        api_key: apiKey || undefined
      })
      setApiKey('') // the key is not kept anywhere in the app
      setType('')
      setName('')
      setBaseUrl('')
      onAdded(result)
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="add-connection" onSubmit={(event) => void submit(event)} aria-label="Add a connection">
      <h3 className="mission__section-title">Add a connection</h3>
      <label className="new-mission__field">
        Provider
        <select value={type} onChange={(event) => choose(event.target.value)} required>
          <option value="">Choose a provider…</option>
          {types.map((t) => (
            <option key={t.type} value={t.type}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      {preset && (
        <>
          <label className="new-mission__field">
            Name
            <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={64} />
          </label>
          <label className="new-mission__field">
            Base URL{needsUrl ? '' : ' (optional)'}
            <input
              type="url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={preset.base_url ?? 'https://your-server.example/v1'}
              required={needsUrl}
            />
          </label>
          {preset.requires_key ? (
            <label className="new-mission__field">
              API key
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                required
              />
              <span className="mission__muted">
                Stored in your system keychain. It is tested before it is saved and never shown again.
              </span>
            </label>
          ) : (
            <p className="mission__muted">
              {preset.local ? 'A local provider: no key needed, and nothing leaves your machine.' : 'No key needed.'}
            </p>
          )}
          {error && (
            <p role="alert" className="mission__error">
              {error}
            </p>
          )}
          <div className="new-mission__actions">
            <button type="submit" className="button button--primary" disabled={busy}>
              {busy ? 'Testing…' : 'Add and test'}
            </button>
          </div>
        </>
      )}
    </form>
  )
}
