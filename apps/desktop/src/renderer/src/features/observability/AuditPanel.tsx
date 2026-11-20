import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'

interface RunAudit {
  run_id: string
  ok: boolean
  events: number
  head: string | null
  legacy: number
  broken: { seq: number | null; reason: string } | null
}

interface Verify {
  ok: boolean
  runs: RunAudit[]
}

interface Props {
  api: ApiClient
  runId: string
}

/** The audit chain of one run (PRD §14.2): is the log still what was written? */
export function AuditPanel({ api, runId }: Props) {
  const [result, setResult] = useState<RunAudit | null>(null)
  const [kept, setKept] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const verify = useCallback(
    async (expectedHead?: string) => {
      setBusy(true)
      setError(null)
      try {
        const answer = await api.get<Verify>('/audit/verify', {
          run_id: runId,
          ...(expectedHead ? { expected_head: expectedHead } : {})
        })
        const first = answer?.runs?.[0]
        if (!first) throw new Error('unexpected answer')
        setResult(first)
      } catch (err) {
        setError(describeError(err).message)
      } finally {
        setBusy(false)
      }
    },
    [api, runId]
  )

  useEffect(() => {
    setResult(null)
    void verify()
  }, [verify])

  const wellFormed = /^[0-9a-f]{64}$/.test(kept.trim())
  return (
    <section className="audit" aria-label="Audit">
      <h3 className="mission__section-title">Is this log intact?</h3>
      <p className="mission__muted">
        Every event is chained to the one before it. Changing, removing or reordering one breaks every link after
        it. The chain proves the log is consistent; to catch a log that was rewritten end to end, keep the head
        hash somewhere else and check against it later.
      </p>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {result && (
        <div role="status" className="audit__result" data-ok={result.ok}>
          {result.ok ? (
            <p>
              <strong>Intact.</strong> {result.events} events, each chained to the one before.
              {result.legacy > 0 && ` ${result.legacy} older events are from before the chain existed and are not covered.`}
            </p>
          ) : (
            <p>
              <strong>Not intact.</strong>{' '}
              {result.broken?.seq != null ? `At event ${result.broken.seq}: ` : ''}
              {result.broken?.reason}.
            </p>
          )}
          {result.head && (
            <p className="mission__muted">
              Head hash (keep a copy): <code>{result.head}</code>
            </p>
          )}
        </div>
      )}
      <label className="new-mission__field">
        A head hash you recorded earlier
        <input value={kept} onChange={(event) => setKept(event.target.value)} placeholder="64 characters" />
      </label>
      <div className="new-mission__actions">
        <button type="button" className="button" disabled={busy} onClick={() => void verify()}>
          Check again
        </button>
        <button type="button" className="button" disabled={busy || !wellFormed} onClick={() => void verify(kept.trim())}>
          Check against it
        </button>
      </div>
    </section>
  )
}
