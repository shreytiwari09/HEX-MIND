import { render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import type { ApiClient } from '../../lib/api'
import { CostsPanel } from './CostsPanel'
import type { Costs, Delegation } from './types'

const base = { schema_version: 8 as const, event_id: 'e', run_id: 'r1', ts: '2026-11-19T10:00:00Z', agent_id: null, task_id: null }

const COSTS: Costs = {
  total_usd: 2.35,
  budget_usd: 5,
  tokens_in: 1950,
  tokens_out: 385,
  calls: 6,
  unpriced_calls: 2,
  by_persona: [
    { persona_id: 'backend', spent_usd: 2.0, budget_usd: 2.2, calls: 2, tokens_in: 1500, tokens_out: 300 },
    { persona_id: 'qa', spent_usd: 0.25, budget_usd: null, calls: 3, tokens_in: 340, tokens_out: 34 },
    { persona_id: null, spent_usd: 0.1, budget_usd: null, calls: 1, tokens_in: 10, tokens_out: 1 }
  ],
  by_model: [{ provider: 'OpenAI', model: 'gpt-5', spent_usd: 2.0, calls: 2, tokens_in: 1500, tokens_out: 300 }]
}

const events: AgentEvent[] = [
  { ...base, seq: 4, type: 'key_rotated', agent_id: 'backend_01', payload: { connection: 'OpenAI', from_key: 'key 1', to_key: 'key 2', reason: 'rate limit' } },
  { ...base, seq: 9, type: 'escalated', payload: { persona: 'backend', feature_id: 'todo-model', attempt: 3, connection: 'OpenAI', model: 'gpt-5', reason: 'attempts 1 to 2 were rejected' } },
  { ...base, seq: 12, type: 'budget_warning', payload: { scope: 'backend', spent_usd: 2, budget_usd: 2.2, percent: 90 } }
]

const DELEGATION: Delegation = {
  assignments: [
    { persona_id: 'backend', connection: 'OpenAI', model: 'gpt-5-mini', set_by: 'auto', reason: 'cheapest model meeting coding ≥4', escalate_model: 'gpt-5', budget_usd: 2.2 },
    { persona_id: 'pm', connection: 'Claude', model: 'opus', set_by: 'user', reason: null, escalate_model: null, budget_usd: null }
  ],
  events
}

function api(costs: unknown, delegation: unknown) {
  return {
    get: vi.fn(async (path: string) => {
      const value = path.endsWith('/costs') ? costs : delegation
      if (value instanceof Error) throw value
      return value
    }),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  } as unknown as ApiClient & { get: ReturnType<typeof vi.fn> }
}

describe('CostsPanel', () => {
  it('shows real totals, per-persona budgets that turn to a warning at 80%, models, and unpriced calls', async () => {
    const client = api(COSTS, DELEGATION)
    render(<CostsPanel api={client} missionId="m1" refreshKey="a" />)

    expect(await screen.findByText('$2.35')).toBeInTheDocument()
    expect(screen.getByText(/of \$5\.00 · 1,950 in \/ 385 out tokens · 6 model calls/)).toBeInTheDocument()
    expect(screen.getByText(/2 calls used models with no known price, so their cost is not included/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Mission budget used' })).toHaveAttribute('aria-valuenow', '47')
    const personas = screen.getByRole('table', { name: 'Spend by persona' })
    expect(within(personas).getByText('Other calls')).toBeInTheDocument()
    expect(within(personas).getAllByText('no cap')).toHaveLength(2) // qa and the unattributed calls
    expect(within(personas).getByRole('progressbar', { name: 'backend budget used' })).toHaveAttribute('data-warn', 'true') // 2.0 of 2.2
    const models = screen.getByRole('table', { name: 'Spend by model' })
    expect(within(models).getByText('OpenAI · gpt-5')).toBeInTheDocument()
    expect(within(models).getByText('1,500 in / 300 out')).toBeInTheDocument()
    expect(client.get).toHaveBeenCalledWith('/missions/m1/costs')
    expect(client.get).toHaveBeenCalledWith('/missions/m1/delegation')
  })

  it('shows who uses which model and why, and the delegation log in plain words', async () => {
    render(<CostsPanel api={api(COSTS, DELEGATION)} missionId="m1" refreshKey="a" />)

    const team = await screen.findByRole('list', { name: 'Team models' })
    const backend = within(team).getByText('backend').closest('li')!
    expect(backend).toHaveAttribute('title', 'cheapest model meeting coding ≥4')
    expect(within(backend).getByText('Auto')).toBeInTheDocument()
    expect(within(backend).getByText(/escalates to gpt-5/)).toBeInTheDocument()
    expect(within(within(team).getByText('pm').closest('li')!).getByText('You')).toBeInTheDocument()
    const log = screen.getByRole('list', { name: 'Delegation log' })
    expect(within(log).getByText('OpenAI: key 1 → key 2 (rate limit)')).toBeInTheDocument()
    expect(within(log).getByText('backend, attempt 3: escalated to gpt-5 on OpenAI (attempts 1 to 2 were rejected)')).toBeInTheDocument()
    expect(within(log).getByText('backend has used 90% of its budget ($2.00 of $2.20)')).toBeInTheDocument()
  })

  it('says so when nothing has happened yet, and does not claim a budget that is not set', async () => {
    const empty: Costs = { ...COSTS, total_usd: 0, budget_usd: null, tokens_in: 0, tokens_out: 0, calls: 0, unpriced_calls: 0, by_persona: [], by_model: [] }
    render(<CostsPanel api={api(empty, { assignments: [], events: [] })} missionId="m1" refreshKey="a" />)

    expect(await screen.findByText('No model calls yet.')).toBeInTheDocument()
    expect(screen.getByText(/No persona has a model assigned/)).toBeInTheDocument()
    expect(screen.getByText(/No fallbacks, key rotations or escalations/)).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).toBeNull()
    expect(screen.queryByText(/no known price/)).toBeNull()
  })

  it('fetches again when the key changes, and reports a failure instead of showing stale numbers', async () => {
    const client = api(COSTS, DELEGATION)
    const { rerender } = render(<CostsPanel api={client} missionId="m1" refreshKey="a" />)
    await screen.findByText('$2.35')
    client.get.mockClear()

    rerender(<CostsPanel api={client} missionId="m1" refreshKey="b" />)
    await waitFor(() => expect(client.get).toHaveBeenCalledTimes(2))

    const broken = api(new Error('HTTP 500'), DELEGATION)
    render(<CostsPanel api={broken} missionId="m2" refreshKey="a" />)
    expect(await screen.findByText(/Could not load costs: HTTP 500/)).toBeInTheDocument()
  })
})
