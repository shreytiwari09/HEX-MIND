import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import { AddConnection } from './AddConnection'
import { AutoSetup } from './AutoSetup'
import type { Connection, ConnectionResult } from './types'
import type { ModelsData } from './useModelsData'

interface Props {
  api: ApiClient
  data: ModelsData
}

/** Connections and their key pools (PRD S3). */
export function ConnectionsPanel({ api, data }: Props) {
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)

  // Models you can use but a team with no model chosen: offer the one-click setup, once.
  useEffect(() => {
    if (data.loaded && data.catalog.length > 0 && data.assignments.length === 0) setSetupOpen(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.loaded])

  const report = (result: ConnectionResult) => {
    const { connection, test } = result
    setError(null)
    setNotice(
      test?.ok
        ? `${connection.name} works: ${test.models.length} model${test.models.length === 1 ? '' : 's'} reachable.`
        : test
          ? `${connection.name} was added, but the test failed: ${test.error ?? 'unknown error'}`
          : `${connection.name} was added.`
    )
    if (test?.ok) setSetupOpen(true)
    void data.reload()
  }

  const attempt = async (work: () => Promise<unknown>) => {
    setError(null)
    setNotice(null)
    try {
      await work()
      await data.reload()
    } catch (err) {
      setError(describeError(err).message)
    }
  }

  return (
    <div className="connections">
      <p className="mission__muted connections__caution">
        Rate limits are often per account or organisation, so two keys from one account usually share a limit.
        Rotating across accounts just to get around limits may break a provider&apos;s terms. Falling back to
        another provider is the default; key rotation only applies to keys you add to a pool on purpose.
      </p>
      {notice && (
        <p role="status" className="connections__notice">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {setupOpen && <AutoSetup api={api} data={data} onClose={() => setSetupOpen(false)} />}
      {data.loaded && data.connections.length === 0 && (
        <p className="mission__muted">No connections yet. Add one below to let the team use its models.</p>
      )}
      <ul className="connections__list" aria-label="Connections">
        {data.connections.map((connection) => (
          <ConnectionCard key={connection.id} api={api} connection={connection} attempt={attempt} onKeyAdded={report} />
        ))}
      </ul>
      <AddConnection api={api} types={data.types} onAdded={report} />
    </div>
  )
}

function ConnectionCard({
  api,
  connection,
  attempt,
  onKeyAdded
}: {
  api: ApiClient
  connection: Connection
  attempt: (work: () => Promise<unknown>) => Promise<void>
  onKeyAdded: (result: ConnectionResult) => void
}) {
  const [newKey, setNewKey] = useState('')
  const [label, setLabel] = useState('')
  const [keyError, setKeyError] = useState<string | null>(null)
  const test = connection.last_test
  const status =
    test.ok === null
      ? { tone: 'neutral', text: 'Not tested' }
      : test.ok
        ? { tone: 'success', text: `Connected · ${connection.models.length} models` }
        : { tone: 'danger', text: `Test failed: ${test.error ?? 'unknown error'}` }

  const addKey = async (event: React.FormEvent) => {
    event.preventDefault()
    setKeyError(null)
    try {
      const result = await api.post<ConnectionResult>(`/connections/${connection.id}/keys`, {
        api_key: newKey,
        label: label.trim()
      })
      setNewKey('')
      setLabel('')
      onKeyAdded(result)
    } catch (err) {
      setKeyError(describeError(err).message)
    }
  }

  return (
    <li className="connection" data-enabled={connection.enabled}>
      <div className="connection__head">
        <strong className="connection__name">{connection.name}</strong>
        <span className="status-pill" data-tone={status.tone}>
          <span className="status-dot" aria-hidden="true" />
          {status.text}
        </span>
      </div>
      <p className="mission__muted">
        <code>{connection.base_url}</code>
        {!connection.enabled && ' · disabled'}
      </p>

      {connection.requires_key && (
        <div>
          <h4 className="mission__label">Keys ({connection.keys.length})</h4>
          {connection.keys.length === 0 ? (
            <p className="mission__muted">No keys yet: this connection cannot be used.</p>
          ) : (
            <ol className="connection__keys">
              {connection.keys.map((key) => (
                <li key={key.id}>
                  <span>{key.label}</span>
                  <span className="mission__muted">{key.position === 0 ? 'tried first' : `fallback ${key.position}`}</span>
                  <button
                    type="button"
                    className="button button--small"
                    aria-label={`Remove ${key.label} from ${connection.name}`}
                    onClick={() => {
                      if (window.confirm(`Remove “${key.label}” from ${connection.name}? It is deleted from your keychain.`)) {
                        void attempt(() => api.delete(`/connections/${connection.id}/keys/${key.id}`))
                      }
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ol>
          )}
          <form className="connection__add-key" onSubmit={(event) => void addKey(event)}>
            <input
              type="password"
              value={newKey}
              onChange={(event) => setNewKey(event.target.value)}
              placeholder="Add another key"
              aria-label={`New key for ${connection.name}`}
              autoComplete="off"
              spellCheck={false}
              required
            />
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Label (optional)"
              aria-label={`Label for the new ${connection.name} key`}
              maxLength={64}
            />
            <button type="submit" className="button button--small">
              Add key
            </button>
          </form>
          {keyError && (
            <p role="alert" className="mission__error">
              {keyError}
            </p>
          )}
        </div>
      )}

      {connection.models.length > 0 && (
        <details>
          <summary>{connection.models.length} models reachable</summary>
          <ul className="connection__models">
            {connection.models.map((model) => (
              <li key={model}>
                <code>{model}</code>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="connection__actions">
        <button
          type="button"
          className="button button--small"
          onClick={() => void attempt(() => api.post(`/connections/${connection.id}/test`))}
        >
          Test
        </button>
        <button
          type="button"
          className="button button--small"
          onClick={() => void attempt(() => api.put(`/connections/${connection.id}`, { enabled: !connection.enabled }))}
        >
          {connection.enabled ? 'Disable' : 'Enable'}
        </button>
        <button
          type="button"
          className="button button--small"
          onClick={() => {
            if (window.confirm(`Delete ${connection.name} and all its keys?`)) {
              void attempt(() => api.delete(`/connections/${connection.id}`))
            }
          }}
        >
          Delete
        </button>
      </div>
    </li>
  )
}
