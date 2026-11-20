import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '../../lib/api'
import { ExperimentsView, Results } from './ExperimentsView'
import type { ConditionSummary, ExperimentResults, Listing, SafetyReport, Sweep } from './types'

const LISTING: Listing = {
  benchmark_version: 'm1',
  apps: [
    { id: 'todo-login', idea: 'x', features: ['auth'] },
    { id: 'notes-tags', idea: 'y', features: ['notes-model'] }
  ],
  experiments: [
    {
      id: 'E4',
      title: 'State sharing',
      question: 'Does the way agents share state change the outcome?',
      varies: 'coordination backend',
      conditions: [
        { id: 'blackboard', label: 'Blackboard (default)' },
        { id: 'messaging', label: 'Messaging only' }
      ],
      blocked: null,
      note: 'Two of the six patterns are built.'
    },
    { id: 'E1', title: 'Patterns', question: 'Does the mission team beat a single agent?', varies: '', conditions: [], blocked: 'needs the other team patterns' }
  ]
}

function summary(condition: string, passed: number, trials: number, extra: Partial<ConditionSummary> = {}): ConditionSummary {
  return {
    condition,
    trials,
    errors: 0,
    completed: trials,
    passed,
    pass_rate: trials ? passed / trials : null,
    interval: trials ? [Math.max(0, passed / trials - 0.3), Math.min(1, passed / trials + 0.3)] : null,
    pass_k: null,
    k: null,
    needs_you_mean: 0,
    retries_mean: 0.5,
    escalations_mean: 0,
    duration_s_mean: 600,
    duration_s_sd: null,
    cost_usd_mean: 0.42,
    cost_usd_sd: null,
    cost_trials: trials,
    tokens_in_mean: 1000,
    tokens_out_mean: 500,
    by_app: {},
    ...extra
  }
}

const RESULTS = (conditions: ConditionSummary[]): { experiments: ExperimentResults[] } => ({
  experiments: [
    {
      experiment: 'E4',
      title: 'State sharing',
      blocked: null,
      trials: conditions.reduce((n, c) => n + c.trials, 0),
      benchmark_versions: ['m1'],
      conditions,
      errors: []
    },
    { experiment: 'E1', title: 'Patterns', blocked: 'x', trials: 0, benchmark_versions: [], conditions: [], errors: [] }
  ]
})

function makeApi(handlers: Record<string, unknown>) {
  return {
    get: vi.fn(async (path: string) => {
      const answer = handlers[path]
      if (answer instanceof Error) throw answer
      return answer
    }),
    post: vi.fn(async (path: string) => handlers[`POST ${path}`] ?? {})
  } as unknown as ApiClient & { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn> }
}

const base = (results: { experiments: ExperimentResults[] }, sweeps: Sweep[] = []) => ({
  '/experiments': LISTING,
  '/experiments/results': results,
  '/experiments/sweeps': sweeps
})

describe('Results', () => {
  it('says when two conditions cannot be told apart instead of declaring a winner', () => {
    render(<Results data={RESULTS([summary('blackboard', 2, 3), summary('messaging', 1, 3)]).experiments[0]} />)

    expect(screen.getByText(/cannot be told apart/)).toBeInTheDocument()
    expect(screen.getByText(/not evidence that they are equal/)).toBeInTheDocument()
  })

  it('names the conditions whose pass rates differ beyond their intervals', () => {
    const wide = { interval: [0.9, 1] as [number, number] }
    const low = { interval: [0, 0.1] as [number, number] }
    render(<Results data={RESULTS([summary('blackboard', 30, 30, wide), summary('messaging', 1, 30, low)]).experiments[0]} />)

    expect(screen.getByText(/blackboard vs messaging/)).toBeInTheDocument()
  })

  it('shows n/a for what was not measured and says how many trials had a cost', () => {
    const unpriced = summary('messaging', 1, 2, { cost_usd_mean: null, cost_usd_sd: null, cost_trials: 0, pass_rate: null, interval: null })
    render(<Results data={RESULTS([unpriced]).experiments[0]} />)

    const row = screen.getByRole('row', { name: /messaging/ })
    expect(within(row).getAllByText(/n\/a/).length).toBeGreaterThanOrEqual(2)
    expect(within(row).getByText(/known for 0/)).toBeInTheDocument()
    expect(screen.getByText(/nothing to compare yet/)).toBeInTheDocument()
  })
})

describe('ExperimentsView', () => {
  it('says why an experiment cannot run and offers a run for the ones that can', async () => {
    const api = makeApi(base(RESULTS([])))
    render(<ExperimentsView api={api} />)

    expect(await screen.findByText(/Not runnable yet: needs the other team patterns/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Run E/ })).toHaveLength(1) // only E4
    expect(screen.getByText(/Two of the six patterns are built/)).toBeInTheDocument()
    expect(screen.getByText(/No trials have been run yet/)).toBeInTheDocument()
  })

  it('starts a sweep with the repeats and the budget', async () => {
    const api = makeApi(base(RESULTS([])))
    render(<ExperimentsView api={api} />)
    const form = await screen.findByRole('button', { name: 'Run E4' })

    fireEvent.change(screen.getByLabelText(/Repeats/), { target: { value: '3' } })
    expect(screen.getByText(/Up to 12 trials/)).toBeInTheDocument() // 2 conditions x 2 apps x 3
    fireEvent.click(form)

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/experiments/E4/run', { repeats: 3, budget_usd: 5, variants: [] })
    )
  })

  it('shows the running sweep with a stop button instead of the run form', async () => {
    const sweep: Sweep = { id: 's1', experiment: 'E4', total: 4, skipped: 0, done: 1, current: 'messaging / todo-login / repeat 0', state: 'running' }
    const api = makeApi({ ...base(RESULTS([]), [sweep]), 'POST /experiments/sweeps/s1/stop': {} })
    render(<ExperimentsView api={api} />)

    expect(await screen.findByText(/E4: 1\/4 trials done/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run E4' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/experiments/sweeps/s1/stop'))
  })

  it('reports the safety negatives, and a failure loudly', async () => {
    const report: SafetyReport = {
      summary: { cases: 2, blocked: 1, got_through: 1, not_run: 0 },
      cases: [
        { id: 'a', category: 'path escape', attack: 'read ../x', blocked: true, evidence: 'refused' },
        { id: 'b', category: 'secret read', attack: 'read .env', blocked: false, evidence: 'the action was carried out' }
      ]
    }
    const api = makeApi({ ...base(RESULTS([])), '/experiments/safety': report })
    render(<ExperimentsView api={api} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Run safety negatives' }))

    expect(await screen.findByText(/1 of 2 attacks blocked, 1 GOT THROUGH/)).toBeInTheDocument()
    expect(screen.getByText(/GOT THROUGH: read \.env/)).toBeInTheDocument()
  })

  it('shows the dated report', async () => {
    const api = makeApi({ ...base(RESULTS([])), '/experiments/report': { date: '2026-11-20', markdown: '# results 2026-11-20' } })
    render(<ExperimentsView api={api} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Show the dated report' }))

    expect(await screen.findByText('# results 2026-11-20')).toBeInTheDocument()
  })

  it('shows an error when the backend cannot be read', async () => {
    render(<ExperimentsView api={makeApi({ '/experiments': new Error('down') })} />)

    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
