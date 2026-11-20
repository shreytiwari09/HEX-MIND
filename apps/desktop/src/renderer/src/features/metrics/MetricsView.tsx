import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import type { Mission } from '../missions/types'
import { Bars } from './Bars'
import { count, duration, percent, usd } from './format'
import type { Metrics } from './types'

interface Props {
  api: ApiClient
  projectId: string
  /** null: all of the project's missions. */
  missionId: string | null
}

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metrics__card">
      <span className="metrics__card-label">{label}</span>
      <strong className="metrics__card-value">{value}</strong>
      {hint && <span className="mission__muted">{hint}</span>}
    </div>
  )
}

/** What the missions cost and how the process behaved (PRD §14.3), from stored data only. */
export function MetricsView({ api, projectId, missionId }: Props) {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const loaded = await api.get<Metrics>('/metrics', missionId ? { mission_id: missionId } : { project_id: projectId })
      if (!loaded || !loaded.calls) throw new Error('unexpected answer')
      setMetrics(loaded)
      setError(null)
    } catch (err) {
      setError(describeError(err).message)
    }
  }, [api, projectId, missionId])

  useEffect(() => {
    setMetrics(null)
    void load()
  }, [load])

  if (error) {
    return (
      <p role="alert" className="mission__error">
        {error}
      </p>
    )
  }
  if (!metrics) return <p className="mission__muted">Loading…</p>
  const { calls, process, validators, features } = metrics

  return (
    <section className="metrics" aria-label="Metrics">
      <div className="metrics__cards">
        <Card label="Missions" value={count(metrics.missions.count)} hint={`avg ${duration(metrics.missions.avg_duration_s)}`} />
        <Card label="Spent" value={usd(calls.cost_usd)} hint={calls.without_cost > 0 ? `${calls.without_cost} calls had no price` : undefined} />
        <Card label="Model calls" value={count(calls.count)} hint={`${percent(calls.error_rate)} failed${calls.replayed ? `, ${calls.replayed} replayed` : ''}`} />
        <Card label="Tokens" value={count(calls.input_tokens + calls.output_tokens)} hint={`${count(calls.input_tokens)} in · ${count(calls.output_tokens)} out`} />
        <Card
          label="Latency"
          value={calls.p50_latency_ms === null ? 'n/a' : `${count(calls.p50_latency_ms)} ms`}
          hint={calls.p95_latency_ms === null ? undefined : `p95 ${count(calls.p95_latency_ms)} ms`}
        />
        <Card label="Done first try" value={percent(features.first_try_rate)} hint={`${features.retried} retried`} />
      </div>

      <Bars
        title="Cost by team member"
        rows={metrics.by_persona.map((p) => ({
          label: p.persona ?? 'no persona',
          value: p.cost_usd,
          text: usd(p.cost_usd),
          note: `${count(p.calls)} calls${p.failed ? `, ${p.failed} failed` : ''}`
        }))}
        empty="No model calls yet."
      />
      <Bars
        title="Cost by model"
        rows={metrics.by_model.map((m) => ({
          label: `${m.provider} · ${m.model}`,
          value: m.cost_usd,
          text: usd(m.cost_usd),
          note: `${count(m.calls)} calls · avg ${count(m.avg_latency_ms)} ms`
        }))}
        empty="No model calls yet."
      />

      <section className="metrics__block" aria-label="Process">
        <h3 className="mission__section-title">How the process went</h3>
        <dl className="metrics__facts">
          <dt>Features retried</dt>
          <dd>{features.retried} of {Object.values(features.by_status).reduce((a, b) => a + b, 0)}</dd>
          <dt>Escalations to a stronger model</dt>
          <dd>{process.escalations}</dd>
          <dt>Provider fallbacks</dt>
          <dd>{process.fallbacks}</dd>
          <dt>Key rotations</dt>
          <dd>{process.key_rotations}</dd>
          <dt>Budget warnings</dt>
          <dd>{process.budget_warnings}</dd>
          <dt>Times it needed you</dt>
          <dd>{process.needs_raised}</dd>
          <dt>Guardrail triggers</dt>
          <dd>
            {process.guardrail_triggers}
            {Object.entries(process.guardrails).map(([name, n]) => (
              <span key={name} className="mission__muted">
                {' '}
                · {name} {n}
              </span>
            ))}
          </dd>
        </dl>
      </section>

      <section className="metrics__block" aria-label="Validators">
        <h3 className="mission__section-title">What the validators found</h3>
        <dl className="metrics__facts">
          <dt>Milestone checks</dt>
          <dd>{validators.checks}</dd>
          <dt>Found something blocking</dt>
          <dd>
            {validators.caught} ({percent(validators.catch_rate)})
          </dd>
          <dt>…and it was then fixed</dt>
          <dd>{validators.caught_and_fixed}</dd>
          <dt>Could not check</dt>
          <dd>{validators.unavailable}</dd>
          <dt>False-positive rate</dt>
          <dd>
            {percent(validators.false_positive_rate)}{' '}
            <span className="mission__muted">(needs a known-correct answer, which a mission does not have)</span>
          </dd>
          <dt>Edit-format compliance</dt>
          <dd>
            {percent(metrics.edit_format_compliance)} <span className="mission__muted">(that layer is not built yet)</span>
          </dd>
        </dl>
      </section>

      {metrics.by_variant.some((v) => v.variant_id !== null) && (
        <Bars
          title="By prompt variant"
          rows={metrics.by_variant.map((v) => ({
            label: v.variant_id ?? 'no variant',
            value: v.cost_usd,
            text: usd(v.cost_usd),
            note: `${v.completed} of ${v.missions} missions completed`
          }))}
        />
      )}
    </section>
  )
}

interface ScopeProps {
  api: ApiClient
  projectId: string | null
  selected: string | null
  onSelect: (missionId: string | null) => void
}

/** The sidebar of the Metrics view: the whole project, or one mission. */
export function MetricsScope({ api, projectId, selected, onSelect }: ScopeProps) {
  const [missions, setMissions] = useState<Mission[]>([])
  useEffect(() => {
    if (!projectId) return
    api
      .get<Mission[]>('/missions', { project_id: projectId })
      .then((list) => setMissions(Array.isArray(list) ? list : []))
      .catch(() => setMissions([]))
  }, [api, projectId])

  return (
    <nav className="mission-list" aria-label="Measure">
      <button type="button" className="mission-list__item" aria-current={selected === null ? 'true' : undefined} onClick={() => onSelect(null)}>
        <strong>The whole project</strong>
      </button>
      {missions.map((mission) => (
        <button
          key={mission.id}
          type="button"
          className="mission-list__item"
          aria-current={selected === mission.id ? 'true' : undefined}
          onClick={() => onSelect(mission.id)}
        >
          {mission.title}
        </button>
      ))}
    </nav>
  )
}
