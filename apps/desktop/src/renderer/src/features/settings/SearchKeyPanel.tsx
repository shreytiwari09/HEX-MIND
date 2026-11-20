import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'

export interface SearchStatus {
  provider: string
  configured: boolean
  /** keychain: saved in this computer's key store. env: read from the backend's .env file. */
  source: 'keychain' | 'env' | null
}

interface TestResult {
  ok: boolean
  error: string | null
  credits: number | null
}

interface Props {
  api: ApiClient
  /** Called whenever the status is known or changes (the new-mission form uses it). */
  onStatus?: (status: SearchStatus) => void
}

const WHERE = {
  keychain: 'saved in your computer’s key store',
  env: 'read from the backend’s .env file'
} as const

/** The web search key for Advanced research (Tavily). The key goes to the key store and is never
 * shown again: this panel only ever says whether one is set and where it lives. */
export function SearchKeyPanel({ api, onStatus }: Props) {
  const [status, setStatus] = useState<SearchStatus | null>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [test, setTest] = useState<TestResult | null>(null)

  const apply = useCallback(
    (next: SearchStatus) => {
      setStatus(next)
      onStatus?.(next)
    },
    [onStatus]
  )

  useEffect(() => {
    api
      .get<SearchStatus>('/research/search')
      .then((loaded) => {
        if (loaded && typeof loaded.configured === 'boolean') apply(loaded)
      })
      .catch((err) => setError(describeError(err).message))
  }, [api, apply])

  const act = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    act(async () => {
      apply(await api.put<SearchStatus>('/research/search/key', { api_key: key }))
      setKey('')
      setTest(null)
    })

  const remove = () =>
    act(async () => {
      apply(await api.delete<SearchStatus>('/research/search/key'))
      setTest(null)
    })

  const runTest = () =>
    act(async () => {
      setTest(await api.post<TestResult>('/research/search/test'))
    })

  return (
    <section className="persona-editor" aria-label="Web search">
      <h2 className="mission__title">Web search for Advanced research</h2>
      <p className="mission__muted">
        Advanced research lets researchers search the web and read public pages before the PM plans. Searching uses
        Tavily, which has a free plan (about 1,000 searches a month, no card). Get a key at tavily.com. The key is
        kept in your computer’s key store and is never shown again.
      </p>
      <p role="status">
        {status === null
          ? 'Checking…'
          : status.configured
            ? `A search key is set (${status.source ? WHERE[status.source] : 'found'}).`
            : 'No search key is set yet.'}
      </p>
      <label className="new-mission__field">
        Tavily API key
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(event) => setKey(event.target.value)}
          placeholder={status?.configured ? 'Paste a new key to replace it' : 'tvly-…'}
        />
      </label>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {test && (
        <p role={test.ok ? 'status' : 'alert'} className={test.ok ? 'mission__muted' : 'mission__error'}>
          {test.ok
            ? `The search works. Tavily counted ${test.credits === null ? 'an unknown number of' : test.credits} credit(s).`
            : `The search did not work: ${test.error ?? 'unknown reason'}`}
        </p>
      )}
      <div className="new-mission__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={busy || key.trim() === ''}
          onClick={() => void save()}
        >
          Save key
        </button>
        <button type="button" className="button" disabled={busy || !status?.configured} onClick={() => void runTest()}>
          Test search (uses about 1 credit)
        </button>
        {status?.source === 'keychain' && (
          <button type="button" className="button" disabled={busy} onClick={() => void remove()}>
            Remove key
          </button>
        )}
      </div>
    </section>
  )
}
