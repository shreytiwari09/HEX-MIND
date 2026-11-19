import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeEvent } from '../runs/events'
import { formatUsd } from './progress'
import type { Costs, Delegation } from './types'

interface Props {
  api: ApiClient
  missionId: string
  /** Changes when the mission's spend or state changed, to fetch again. */
  refreshKey: string
}

const WARN_AT = 0.8

/**
 * Where the money went (PRD S8): real totals from the provider layer, by persona and by model,
 * and who uses which model and why. Calls whose model has no known price are counted and said so,
 * never priced by guess.
 */
export function CostsPanel({ api, missionId, refreshKey }: Props) {
  const [costs, setCosts] = useState<Costs | null>(null)
  const [delegation, setDelegation] = useState<Delegation | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.get<Costs>(`/missions/${missionId}/costs`),
      api.get<Delegation>(`/missions/${missionId}/delegation`)
    ])
      .then(([c, d]) => {
        if (cancelled) return
        setCosts(c)
        setDelegation(d)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [api, missionId, refreshKey])

  if (error) {
    return (
      <p role="alert" className="mission__error">
        Could not load costs: {error}
      </p>
    )
  }
  if (!costs || !delegation) return <p className="mission__muted">Loading costs…</p>

  const ratio = costs.budget_usd ? costs.total_usd / costs.budget_usd : null
  return (
    <div className="costs">
      <p>
        <strong>{formatUsd(costs.total_usd)}</strong>
        {costs.budget_usd !== null && ` of ${formatUsd(costs.budget_usd)}`} · {costs.tokens_in.toLocaleString()} in /{' '}
        {costs.tokens_out.toLocaleString()} out tokens · {costs.calls} model calls
      </p>
      {ratio !== null && <Meter ratio={ratio} label="Mission budget used" />}
      {costs.unpriced_calls > 0 && (
        <p className="mission__muted">
          {costs.unpriced_calls} call{costs.unpriced_calls === 1 ? '' : 's'} used models with no known price, so
          their cost is not included above.
        </p>
      )}

      <h4 className="mission__label">By persona</h4>
      {costs.by_persona.length === 0 ? (
        <p className="mission__muted">No model calls yet.</p>
      ) : (
        <table className="costs__table" aria-label="Spend by persona">
          <tbody>
            {costs.by_persona.map((row) => (
              <tr key={row.persona_id ?? 'other'}>
                <td>{row.persona_id ?? 'Other calls'}</td>
                <td>{formatUsd(row.spent_usd)}</td>
                <td>
                  {row.budget_usd !== null ? (
                    <Meter ratio={row.spent_usd / row.budget_usd} label={`${row.persona_id} budget used`} />
                  ) : (
                    <span className="mission__muted">no cap</span>
                  )}
                </td>
                <td className="mission__muted">{row.calls} calls</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4 className="mission__label">By model</h4>
      <table className="costs__table" aria-label="Spend by model">
        <tbody>
          {costs.by_model.map((row) => (
            <tr key={`${row.provider}|${row.model}`}>
              <td>
                {row.provider} · {row.model}
              </td>
              <td>{formatUsd(row.spent_usd)}</td>
              <td className="mission__muted">
                {row.tokens_in.toLocaleString()} in / {row.tokens_out.toLocaleString()} out
              </td>
              <td className="mission__muted">{row.calls} calls</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4 className="mission__label">Who uses which model</h4>
      {delegation.assignments.length === 0 ? (
        <p className="mission__muted">No persona has a model assigned: the default provider order is used.</p>
      ) : (
        <ul className="costs__team" aria-label="Team models">
          {delegation.assignments.map((a) => (
            <li key={a.persona_id} title={a.reason ?? undefined}>
              <strong>{a.persona_id}</strong> {a.connection ?? '?'} · {a.model}{' '}
              <span className="team__set-by" data-set-by={a.set_by}>
                {a.set_by === 'user' ? 'You' : 'Auto'}
              </span>
              {a.escalate_model && <span className="mission__muted"> escalates to {a.escalate_model}</span>}
            </li>
          ))}
        </ul>
      )}

      <h4 className="mission__label">Delegation log</h4>
      {delegation.events.length === 0 ? (
        <p className="mission__muted">No fallbacks, key rotations or escalations so far.</p>
      ) : (
        <ol className="mission__log" aria-label="Delegation log">
          {delegation.events.map((event) => (
            <li key={event.seq}>{describeEvent(event)}</li>
          ))}
        </ol>
      )}
    </div>
  )
}

function Meter({ ratio, label }: { ratio: number; label: string }) {
  const percent = Math.min(100, Math.round(ratio * 100))
  return (
    <div
      className="mission__bar costs__meter"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      data-warn={ratio >= WARN_AT}
    >
      <div className="mission__bar-fill" style={{ width: `${percent}%` }} />
    </div>
  )
}
