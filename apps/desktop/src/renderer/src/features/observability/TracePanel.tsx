import { useCallback, useEffect, useMemo, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'

export interface Span {
  trace_id: string
  span_id: string
  parent_span_id: string | null
  name: string
  kind: 'agent' | 'model' | 'tool' | 'crew' | 'a2a' | 'sandbox' | 'other'
  depth: number
  offset_ms: number
  duration_ms: number
  status: 'ok' | 'error' | 'unset'
  status_message: string | null
  attributes: Record<string, unknown>
}

interface Trace {
  run_id: string
  spans: Span[]
  traces: number
  duration_ms: number
  truncated: boolean
}

const KINDS: Span['kind'][] = ['agent', 'crew', 'model', 'tool', 'a2a', 'sandbox', 'other']

export const formatMs = (ms: number): string => (ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`)

/** Where a bar sits, as percentages of the whole trace; a very short span still shows. */
export function barOf(span: Pick<Span, 'offset_ms' | 'duration_ms'>, total: number): { left: number; width: number } {
  if (total <= 0) return { left: 0, width: 100 }
  const left = Math.min(100, Math.max(0, (span.offset_ms / total) * 100))
  const width = Math.max(0.6, Math.min(100 - left, (span.duration_ms / total) * 100))
  return { left, width }
}

interface Props {
  api: ApiClient
  runId: string
}

/** The run's OpenTelemetry spans as a waterfall (PRD §14.2), from what was stored: it works with no
 * collector running. Prompts and secrets are never in a stored span. */
export function TracePanel({ api, runId }: Props) {
  const [trace, setTrace] = useState<Trace | null>(null)
  const [hidden, setHidden] = useState<Set<Span['kind']>>(new Set())
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const loaded = await api.get<Trace>('/traces', { run_id: runId })
      if (!loaded || !Array.isArray(loaded.spans)) throw new Error('unexpected answer')
      setTrace(loaded)
      setError(null)
    } catch (err) {
      setError(describeError(err).message)
    }
  }, [api, runId])

  useEffect(() => {
    setTrace(null)
    setOpen(null)
    void load()
  }, [load])

  const shown = useMemo(() => (trace?.spans ?? []).filter((s) => !hidden.has(s.kind)), [trace, hidden])
  const present = useMemo(() => KINDS.filter((k) => trace?.spans.some((s) => s.kind === k)), [trace])
  const toggle = (kind: Span['kind']) =>
    setHidden((current) => {
      const next = new Set(current)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })

  return (
    <section className="trace" aria-label="Trace">
      <div className="trace__header">
        <button type="button" className="button button--small" onClick={() => void load()}>
          Refresh
        </button>
        {trace && trace.spans.length > 0 && (
          <span className="mission__muted">
            {trace.spans.length} spans in {trace.traces} trace{trace.traces === 1 ? '' : 's'} · {formatMs(trace.duration_ms)}
            {trace.truncated && ' · cut short'}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {trace && trace.spans.length === 0 && (
        <p className="mission__muted">No spans were stored for this run yet.</p>
      )}
      {present.length > 1 && (
        <div className="trace__kinds" role="group" aria-label="Show spans of kind">
          {present.map((kind) => (
            <label key={kind} className="trace__kind" data-kind={kind}>
              <input type="checkbox" checked={!hidden.has(kind)} onChange={() => toggle(kind)} />
              {kind}
            </label>
          ))}
        </div>
      )}
      <ol className="trace__rows" aria-label="Spans">
        {shown.map((span) => {
          const bar = barOf(span, trace?.duration_ms ?? 0)
          const expanded = open === span.span_id
          return (
            <li key={`${span.trace_id}:${span.span_id}`} className="trace__row" data-kind={span.kind} data-status={span.status}>
              <button
                type="button"
                className="trace__line"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : span.span_id)}
              >
                <span className="trace__name" style={{ paddingLeft: `${span.depth * 14}px` }}>
                  <span className="trace__kind-tag">{span.kind}</span> {span.name}
                </span>
                <span className="trace__duration">{formatMs(span.duration_ms)}</span>
                <span className="trace__track" aria-hidden="true">
                  <span className="trace__bar" style={{ left: `${bar.left}%`, width: `${bar.width}%` }} />
                </span>
              </button>
              {expanded && (
                <dl className="trace__details" aria-label={`Details of ${span.name}`}>
                  <dt>Status</dt>
                  <dd>
                    {span.status}
                    {span.status_message ? `: ${span.status_message}` : ''}
                  </dd>
                  {Object.entries(span.attributes).map(([key, value]) => (
                    <div key={key} className="trace__attribute">
                      <dt>{key}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
