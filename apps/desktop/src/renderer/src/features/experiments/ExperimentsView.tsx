import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import { count, duration, usd } from '../metrics/format'
import { VariantManager } from './VariantManager'
import type { ConditionSummary, ExperimentInfo, ExperimentResults, Listing, SafetyReport, Sweep } from './types'

interface Props {
  api: ApiClient
}

const pct = (value: number | null): string => (value === null ? 'n/a' : `${Math.round(value * 100)}%`)
const num = (value: number | null, digits = 1): string => (value === null ? 'n/a' : value.toFixed(digits))

/** "n/a" is shown for what could not be measured; a spread is shown when there is more than one trial. */
function spread(mean: number | null, sd: number | null, format: (v: number) => string): string {
  if (mean === null) return 'n/a'
  return sd === null ? format(mean) : `${format(mean)} ± ${format(sd)}`
}

function interval(s: ConditionSummary): string {
  return s.interval === null ? 'n/a' : `${Math.round(s.interval[0] * 100)}–${Math.round(s.interval[1] * 100)}%`
}

/** Pass rates are only called different when their intervals do not overlap (PRD §15.5). */
function separated(a: ConditionSummary, b: ConditionSummary): boolean {
  if (a.interval === null || b.interval === null) return false
  return a.interval[1] < b.interval[0] || b.interval[1] < a.interval[0]
}

export function Results({ data }: { data: ExperimentResults }) {
  const rows = data.conditions
  const apart = rows.flatMap((a, i) => rows.slice(i + 1).filter((b) => separated(a, b)).map((b) => `${a.condition} vs ${b.condition}`))
  return (
    <div className="experiments__results">
      <table className="experiments__table">
        <thead>
          <tr>
            <th>Condition</th>
            <th>Trials</th>
            <th>Errors</th>
            <th>Pass rate (95%)</th>
            <th>pass^k</th>
            <th>Needs you</th>
            <th>Retries</th>
            <th>Time</th>
            <th>Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.condition}>
              <th scope="row">{s.condition}</th>
              <td>{s.trials}</td>
              <td>{s.errors}</td>
              <td>
                {s.passed}/{s.trials - s.errors} = {pct(s.pass_rate)} ({interval(s)})
              </td>
              <td>{s.pass_k === null ? 'n/a' : `${pct(s.pass_k)} (k=${s.k})`}</td>
              <td>{num(s.needs_you_mean)}</td>
              <td>{num(s.retries_mean)}</td>
              <td>{spread(s.duration_s_mean, s.duration_s_sd, duration)}</td>
              <td>
                {spread(s.cost_usd_mean, s.cost_usd_sd, usd)}
                {s.cost_trials !== s.trials - s.errors && s.trials - s.errors > 0 && (
                  <span className="mission__muted"> (known for {s.cost_trials})</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mission__muted">
        {rows.length < 2
          ? 'One condition so far: there is nothing to compare yet.'
          : apart.length > 0
            ? `Pass rates that differ beyond their intervals: ${apart.join('; ')}.`
            : 'The conditions cannot be told apart on pass rate at this number of trials. That is a null result for now, not evidence that they are equal.'}
      </p>
      {data.errors.length > 0 && (
        <details>
          <summary>{data.errors.length} trials errored (not counted in the rates)</summary>
          <ul>
            {data.errors.map((e, i) => (
              <li key={i}>
                {e.condition} / {e.app} / repeat {e.repeat}: {e.error}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function RunForm({ api, experiment, apps, onStarted }: { api: ApiClient; experiment: ExperimentInfo; apps: string[]; onStarted: () => void }) {
  const [repeats, setRepeats] = useState('1')
  const [budget, setBudget] = useState('5')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const trials = experiment.conditions.length * apps.length * Math.max(1, Number(repeats) || 1)
  const variants = experiment.conditions.filter((c) => c.id.startsWith('variant:')).map((c) => c.id.slice('variant:'.length))

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await api.post(`/experiments/${experiment.id}/run`, { repeats: Number(repeats), budget_usd: Number(budget), variants })
      onStarted()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="experiments__form" onSubmit={(event) => void submit(event)}>
      <label className="new-mission__field">
        Repeats per condition and app
        <input type="number" min="1" max="10" value={repeats} onChange={(event) => setRepeats(event.target.value)} />
      </label>
      <label className="new-mission__field">
        Budget per trial (USD)
        <input type="number" min="0.5" step="0.5" value={budget} onChange={(event) => setBudget(event.target.value)} />
      </label>
      <p className="mission__muted">
        Up to {trials} trials. Each builds a whole app with real model calls and costs money; trials that already have a stored
        result are skipped.
      </p>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      <button type="submit" className="button button--primary" disabled={busy}>
        Run {experiment.id}
      </button>
    </form>
  )
}

/** Experiments E1 to E6 (PRD §15.3): what can run, what cannot and why, and the stored results. */
export function ExperimentsView({ api }: Props) {
  const [listing, setListing] = useState<Listing | null>(null)
  const [results, setResults] = useState<ExperimentResults[]>([])
  const [sweeps, setSweeps] = useState<Sweep[]>([])
  const [safety, setSafety] = useState<SafetyReport | null>(null)
  const [report, setReport] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [listed, stored, running] = await Promise.all([
        api.get<Listing>('/experiments'),
        api.get<{ experiments: ExperimentResults[] }>('/experiments/results'),
        api.get<Sweep[]>('/experiments/sweeps')
      ])
      if (!listed || !listed.experiments) throw new Error('unexpected answer')
      setListing(listed)
      setResults(stored.experiments)
      setSweeps(running)
      setError(null)
    } catch (err) {
      setError(describeError(err).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const active = sweeps.find((s) => s.state === 'running')
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => void load(), 10_000)
    return () => clearInterval(timer)
  }, [active, load])

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    try {
      await work()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !listing) {
    return (
      <p role="alert" className="mission__error">
        {error}
      </p>
    )
  }
  if (!listing) return <p className="mission__muted">Loading…</p>

  return (
    <section className="experiments" aria-label="Experiments">
      <h2 className="mission__title">Experiments</h2>
      <p className="mission__muted">
        Mission benchmark {listing.benchmark_version}: {listing.apps.map((a) => a.id).join(', ')}. Every number comes from stored runs
        and the hidden tests; nothing here is estimated.
      </p>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {active && (
        <div role="status" className="experiments__sweep">
          <strong>
            {active.experiment}: {active.done}/{active.total} trials done
          </strong>
          {active.current && <span className="mission__muted"> now {active.current}</span>}
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={() => void act(async () => { await api.post(`/experiments/sweeps/${active.id}/stop`); await load() })}
          >
            Stop
          </button>
        </div>
      )}
      <VariantManager api={api} onChanged={() => void load()} />
      {listing.experiments.map((experiment) => {
        const stored = results.find((r) => r.experiment === experiment.id)
        return (
          <article key={experiment.id} className="experiments__card" aria-label={`${experiment.id} ${experiment.title}`}>
            <h3 className="mission__section-title">
              {experiment.id} {experiment.title}
            </h3>
            <p>{experiment.question}</p>
            {experiment.note && <p className="mission__muted">{experiment.note}</p>}
            {experiment.blocked ? (
              <p className="mission__muted">Not runnable yet: {experiment.blocked}.</p>
            ) : (
              <>
                <p className="mission__muted">
                  Varies {experiment.varies}: {experiment.conditions.map((c) => c.label).join(' · ')}
                </p>
                {!active && (
                  <RunForm api={api} experiment={experiment} apps={listing.apps.map((a) => a.id)} onStarted={() => void load()} />
                )}
              </>
            )}
            {stored && stored.trials > 0 ? (
              <Results data={stored} />
            ) : (
              !experiment.blocked && <p className="mission__muted">No trials have been run yet.</p>
            )}
          </article>
        )
      })}
      <div className="experiments__actions">
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => void act(async () => setReport((await api.get<{ markdown: string }>('/experiments/report')).markdown))}
        >
          Show the dated report
        </button>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => void act(async () => setSafety(await api.get<SafetyReport>('/experiments/safety')))}
        >
          Run safety negatives
        </button>
      </div>
      {report && <pre className="experiments__report">{report}</pre>}
      {safety && (
        <div className="experiments__safety" aria-label="Safety negatives">
          <p role="status">
            {safety.summary.blocked} of {safety.summary.cases} attacks blocked
            {safety.summary.got_through > 0 && `, ${safety.summary.got_through} GOT THROUGH`}
            {safety.summary.not_run > 0 && `, ${safety.summary.not_run} not run`}.
          </p>
          <ul>
            {safety.cases.map((c) => (
              <li key={c.id}>
                {c.blocked === true ? 'Blocked' : c.blocked === false ? 'GOT THROUGH' : 'Not run'}: {c.attack}{' '}
                <span className="mission__muted">({c.category}: {c.evidence})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="mission__muted">{count(results.reduce((n, r) => n + r.trials, 0))} trials stored in total.</p>
    </section>
  )
}
