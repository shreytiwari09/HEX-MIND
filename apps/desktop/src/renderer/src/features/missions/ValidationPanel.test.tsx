import { render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import type { ApiClient } from '../../lib/api'
import { describeEvent } from '../runs/events'
import { ValidationPanel } from './ValidationPanel'
import type { ValidatorReportView } from './types'

const base = { schema_version: 8 as const, event_id: 'e', run_id: 'r1', ts: '', agent_id: null, task_id: null }

const REPORTS: ValidatorReportView[] = [
  {
    milestone_id: 'm1-model',
    validator: 'code-reviewer',
    round: 1,
    verdict: 'fail',
    commands: [
      { command: 'node --test', exit_code: 0, duration_s: 1.2, summary: '' },
      { command: 'npx eslint .', exit_code: 1, duration_s: 0.4, summary: '' }
    ],
    findings: [
      { feature_id: 'todo-model', file: 'src/todos.js', line: 12, severity: 'major', message: 'addTodo accepts an empty title', evidence: null },
      { feature_id: null, file: null, line: null, severity: 'info', message: 'Dependencies changed in package.json.', evidence: null }
    ],
    created_at: ''
  },
  { milestone_id: 'm1-model', validator: 'security', round: 1, verdict: 'needs_user', commands: [], findings: [], created_at: '' },
  { milestone_id: 'm1-model', validator: 'code-reviewer', round: 2, verdict: 'pass', commands: [], findings: [], created_at: '' }
]

function api(value: unknown) {
  return {
    get: vi.fn(async () => {
      if (value instanceof Error) throw value
      return value
    }),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  } as unknown as ApiClient & { get: ReturnType<typeof vi.fn> }
}

describe('ValidationPanel', () => {
  it('shows each validator’s verdict, the commands the sandbox ran, and its findings with file and line', async () => {
    const client = api(REPORTS)
    render(<ValidationPanel api={client} missionId="m1" refreshKey="a" />)

    const list = await screen.findByRole('list', { name: 'Validator reports' })
    const first = within(list).getAllByRole('listitem', { name: '' })[0]
    expect(within(list).getByText('Found problems')).toBeInTheDocument()
    expect(within(list).getByText('Passed')).toBeInTheDocument()
    expect(within(list).getAllByText('m1-model, round 1')).toHaveLength(2)
    const commands = within(list).getByRole('list', { name: 'Commands run' })
    expect(within(commands).getByText('node --test')).toBeInTheDocument()
    expect(within(commands).getByText('passed')).toBeInTheDocument()
    expect(within(commands).getByText('exit 1')).toBeInTheDocument()
    const findings = within(list).getByRole('list', { name: 'Findings' })
    expect(within(findings).getByText('src/todos.js:12')).toBeInTheDocument()
    expect(within(findings).getByText(/addTodo accepts an empty title/)).toBeInTheDocument()
    expect(within(findings).getByText('major')).toBeInTheDocument()
    expect(first).toBeTruthy()
    expect(client.get).toHaveBeenCalledWith('/missions/m1/validation')
  })

  it('says a validator that could not run checked nothing, instead of passing it', async () => {
    render(<ValidationPanel api={api(REPORTS)} missionId="m1" refreshKey="a" />)

    expect(await screen.findByText('Could not check')).toBeInTheDocument()
  })

  it('explains the empty state, fetches again for a new key, and survives a bad answer or an error', async () => {
    const client = api([])
    const { rerender } = render(<ValidationPanel api={client} missionId="m1" refreshKey="a" />)
    expect(await screen.findByText(/No validators have run yet/)).toBeInTheDocument()
    client.get.mockClear()
    rerender(<ValidationPanel api={client} missionId="m1" refreshKey="b" />)
    await waitFor(() => expect(client.get).toHaveBeenCalledTimes(1))

    render(<ValidationPanel api={api(undefined)} missionId="m2" refreshKey="a" />)
    expect((await screen.findAllByText(/No validators have run yet/)).length).toBeGreaterThan(0)
    render(<ValidationPanel api={api(new Error('HTTP 500'))} missionId="m3" refreshKey="a" />)
    expect(await screen.findByText(/Could not load validation: HTTP 500/)).toBeInTheDocument()
  })

  it('describes validator events in plain words', () => {
    const started: AgentEvent = { ...base, seq: 1, type: 'validator_started', payload: { validator: 'security', milestone_id: 'm2', round: 2 } }
    const reported: AgentEvent = { ...base, seq: 2, type: 'validator_reported', payload: { validator: 'code-reviewer', milestone_id: 'm2', round: 1, verdict: 'needs_user', findings: 3, blocking: 1 } }
    const clean: AgentEvent = { ...base, seq: 3, type: 'validator_reported', payload: { validator: 'security', milestone_id: 'm2', round: 1, verdict: 'pass', findings: 0, blocking: 0 } }

    expect(describeEvent(started)).toBe('security is checking m2 (round 2)')
    expect(describeEvent(reported)).toBe('code-reviewer on m2: needs user (3 finding(s), 1 blocking)')
    expect(describeEvent(clean)).toBe('security on m2: pass (no findings)')
  })
})
