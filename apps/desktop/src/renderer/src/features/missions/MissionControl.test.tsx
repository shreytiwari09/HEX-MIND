import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import { ApiError, type ApiClient } from '../../lib/api'
import { describeError } from './actions'
import { MissionScreen } from './MissionControl'
import { mission } from './fixtures'
import type { Checkpoint, MissionDiff, Need } from './types'
import type { MissionView } from './useMission'
import { useMission } from './useMission'

function makeApi(handlers: Record<string, unknown> = {}) {
  const respond = async (path: string) => {
    const value = handlers[path]
    if (value instanceof Error) throw value
    return value
  }
  return {
    get: vi.fn(respond),
    post: vi.fn(async (path: string) => respond(path)),
    put: vi.fn()
  } as unknown as ApiClient & { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn> }
}

function makeView(extra: Partial<MissionView> = {}): MissionView & { adopt: ReturnType<typeof vi.fn> } {
  return {
    mission: mission(),
    events: [],
    needs: [],
    checkpoints: [],
    connection: { state: 'live' },
    error: null,
    adopt: vi.fn(),
    ...extra
  } as MissionView & { adopt: ReturnType<typeof vi.fn> }
}

const base = { schema_version: 8 as const, event_id: 'e', run_id: 'r1', ts: '2026-11-19T10:00:00Z', agent_id: null, task_id: null }

beforeEach(() => {
  vi.stubGlobal('confirm', vi.fn(() => true))
  window.confirm = vi.fn(() => true)
})
afterEach(() => vi.unstubAllGlobals())

describe('MissionScreen: a running mission', () => {
  it('shows real progress, the active feature, spend against budget, and only the controls that apply', () => {
    const view = makeView({ mission: mission({ spent_usd: 0.25, budget_usd: 5 }) })
    render(<MissionScreen api={makeApi()} view={view} />)

    expect(screen.getByRole('heading', { name: 'Todo app' })).toBeInTheDocument()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Features finished' })).toHaveAttribute('aria-valuenow', '2')
    expect(screen.getByText(/Feature 2 of 4 \(1 skipped\) · Milestone 1 of 2/)).toBeInTheDocument()
    expect(screen.getByText('$0.250 of $5.00')).toBeInTheDocument()
    const active = screen.getByRole('region', { name: 'Active feature' })
    expect(within(active).getByText('Feature c')).toBeInTheDocument()
    expect(within(active).getByText('backend · attempt 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Pause/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Stop/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/ })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Finish the mission' })).toBeNull()
  })

  it('pauses through the API and hands the new state to the view', async () => {
    const paused = mission({ status: 'paused' })
    const api = makeApi({ '/missions/m1/pause': paused })
    const view = makeView()
    const onChanged = vi.fn()
    render(<MissionScreen api={api} view={view} onChanged={onChanged} />)

    fireEvent.click(screen.getByRole('button', { name: /Pause/ }))

    expect(api.post).toHaveBeenCalledWith('/missions/m1/pause')
    await waitFor(() => expect(view.adopt).toHaveBeenCalledWith(paused))
    expect(onChanged).toHaveBeenCalled()
  })

  it('asks before stopping and does nothing if you decline', async () => {
    window.confirm = vi.fn(() => false)
    const api = makeApi()
    render(<MissionScreen api={api} view={makeView()} />)

    fireEvent.click(screen.getByRole('button', { name: /Stop/ }))

    expect(window.confirm).toHaveBeenCalled()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('shows what the team is doing from the pushed events only', () => {
    const events: AgentEvent[] = [
      { ...base, seq: 1, type: 'tool_called', payload: { tool: 'write_file', ok: true, summary: 'src/filter.js: updated' } },
      { ...base, seq: 2, type: 'check_completed', payload: { name: 'test', exit_code: 1, duration_ms: 900 } },
      { ...base, seq: 3, type: 'feature_status_changed', payload: { feature_id: 'c', title: 'Filter', persona: 'frontend', status: 'in_progress', attempts: 1, commit: null } }
    ]
    render(<MissionScreen api={makeApi()} view={makeView({ events })} />)

    const output = screen.getByRole('region', { name: 'Live output' })
    // readable steps by default, each with who did it
    expect(within(output).getByText('Writing src/filter.js')).toBeInTheDocument()
    expect(within(output).getByText('"test" failed in 0.9 s')).toBeInTheDocument()
    expect(within(output).getByText('Started "Filter"')).toBeInTheDocument()
    // the raw log is one click away
    fireEvent.click(within(output).getByRole('button', { name: 'Show raw log' }))
    expect(within(output).getByText('write_file: src/filter.js: updated')).toBeInTheDocument()
    expect(within(output).getByText('test failed (exit 1) in 0.9s')).toBeInTheDocument()
    // the team roster shows who is on it
    const team = screen.getByRole('region', { name: 'Team' })
    expect(within(team).getByText('Frontend')).toBeInTheDocument()
    const log = screen.getByRole('region', { name: 'Progress log' })
    expect(within(log).getByText(/Filter \(frontend\): in progress/)).toBeInTheDocument()
  })

  it('says so when it has nothing to show, and when the connection drops', () => {
    render(
      <MissionScreen api={makeApi()} view={makeView({ connection: { state: 'reconnecting' } })} />
    )
    expect(screen.getByText(/Nothing yet\. Each step appears/)).toBeInTheDocument()
    expect(screen.getByText('No progress yet.')).toBeInTheDocument()
    expect(screen.getByText('Reconnecting…')).toBeInTheDocument()
  })

  it('shows a loading or error state before the mission arrives', () => {
    const { rerender } = render(<MissionScreen api={makeApi()} view={makeView({ mission: null })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading the mission…')
    rerender(<MissionScreen api={makeApi()} view={makeView({ mission: null, error: 'HTTP 500' })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Could not load the mission: HTTP 500')
  })
})

describe('MissionScreen: awaiting approval', () => {
  it('starts the mission only on Approve', async () => {
    const started = mission({ status: 'running' })
    const api = makeApi({ '/missions/m1/approve': started })
    const fresh = mission({ status: 'awaiting_approval', started_at: null })
    fresh.milestones = fresh.milestones.map((m) => ({
      ...m,
      status: 'pending',
      features: m.features.map((f) => ({ ...f, status: 'pending', attempts: 0 }))
    }))
    const view = makeView({ mission: fresh })
    render(<MissionScreen api={api} view={view} />)

    expect(screen.getByText(/Review the plan on the right/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Approve and start/ }))

    expect(api.post).toHaveBeenCalledWith('/missions/m1/approve')
    await waitFor(() => expect(view.adopt).toHaveBeenCalledWith(started))
  })

  it('shows the error when the backend refuses', async () => {
    const api = makeApi({ '/missions/m1/approve': new ApiError(409, 'x', { detail: 'a running mission cannot move to running' }) })
    render(<MissionScreen api={api} view={makeView({ mission: mission({ status: 'awaiting_approval' }) })} />)

    fireEvent.click(screen.getByRole('button', { name: /Approve and start/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('a running mission cannot move to running')
  })
})

describe('Needs you', () => {
  const failed: Need = {
    id: 'n1',
    mission_id: 'm1',
    feature_id: 'f1',
    kind: 'feature_failed',
    summary: 'backend could not finish “Todo model” after 3 attempts.',
    evidence: { attempts: 3, last_findings: 'test: FAILED (exit 1)' },
    options: ['retry', 'skip', 'stop'],
    status: 'open',
    created_at: ''
  }

  it('shows the summary and evidence and sends the chosen option', async () => {
    const answered = mission({ status: 'running' })
    const api = makeApi({ '/needs/n1/answer': answered })
    const view = makeView({ mission: mission({ status: 'needs_user' }), needs: [failed] })
    render(<MissionScreen api={api} view={view} />)

    const panel = screen.getByRole('region', { name: 'Needs you' })
    expect(within(panel).getByText('A feature could not be finished')).toBeInTheDocument()
    expect(within(panel).getByText(/after 3 attempts/)).toBeInTheDocument()
    expect(within(panel).getByText('test: FAILED (exit 1)')).toBeInTheDocument()
    fireEvent.click(within(panel).getByRole('button', { name: 'Skip this feature' }))

    expect(api.post).toHaveBeenCalledWith('/needs/n1/answer', { action: 'skip', budget_usd: undefined })
    await waitFor(() => expect(view.adopt).toHaveBeenCalledWith(answered))
  })

  it('needs an amount before raising a budget', async () => {
    const budget: Need = { ...failed, id: 'n2', kind: 'budget_reached', summary: 'Spent 0.5 of 0.25.', evidence: {}, options: ['raise_budget', 'stop'] }
    const api = makeApi({ '/needs/n2/answer': mission() })
    render(<MissionScreen api={api} view={makeView({ mission: mission({ status: 'needs_user' }), needs: [budget] })} />)

    fireEvent.click(screen.getByRole('button', { name: 'Raise budget' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter the new budget in dollars.')
    expect(api.post).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('New budget (USD)'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Raise budget' }))
    expect(api.post).toHaveBeenCalledWith('/needs/n2/answer', { action: 'raise_budget', budget_usd: 5 })
  })
})

describe('finishing a mission', () => {
  const done = () => mission({ status: 'completed', finished_at: '2026-11-19T10:10:00Z' })
  const diff: MissionDiff = {
    run_id: 'r1',
    base_commit: 'abc',
    files: [
      { path: 'src/todos.js', change_type: 'added', status: 'pending', original: null, modified: 'x', diff: '+function addTodo() {}' },
      { path: 'README.md', change_type: 'modified', status: 'pending', original: 'a', modified: 'b', diff: '-a\n+b' }
    ]
  }

  it('lets you review the changes before anything is applied', async () => {
    const api = makeApi({ '/missions/m1/diff': diff })
    render(<MissionScreen api={api} view={makeView({ mission: done() })} />)

    expect(screen.getByText(/Nothing in your project has changed yet/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Review changes' }))

    const files = await screen.findByRole('list', { name: 'Changed files' })
    expect(within(files).getByText('src/todos.js')).toBeInTheDocument()
    expect(within(files).getByText('new')).toBeInTheDocument()
    expect(within(files).getByText('changed')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('applies with the chosen options', async () => {
    const applied = mission({
      status: 'applied',
      apply: { state: 'applied', files: ['src/todos.js'], commit: 'abcdef1234', commit_error: null, include_mission_files: false }
    })
    const api = makeApi({ '/missions/m1/apply': applied })
    const view = makeView({ mission: done() })
    render(<MissionScreen api={api} view={view} />)

    fireEvent.click(screen.getByLabelText(/Include the mission/))
    fireEvent.click(screen.getByRole('button', { name: 'Apply to my project' }))

    expect(api.post).toHaveBeenCalledWith('/missions/m1/apply', { include_mission_files: false, commit: true })
    await waitFor(() => expect(view.adopt).toHaveBeenCalledWith(applied))
  })

  it('names the files when your own edits block the apply', async () => {
    const conflict = new ApiError(409, 'HTTP 409', {
      detail: { message: 'these files changed in your project since the mission started; nothing was applied', paths: ['src/todos.js'] }
    })
    render(<MissionScreen api={makeApi({ '/missions/m1/apply': conflict })} view={makeView({ mission: done() })} />)

    fireEvent.click(screen.getByRole('button', { name: 'Apply to my project' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('nothing was applied')
    expect(within(alert).getByText('src/todos.js')).toBeInTheDocument()
  })

  it('offers revert after applying, with no apply button', async () => {
    const applied = mission({
      status: 'applied',
      apply: { state: 'applied', files: ['a', 'b'], commit: 'abcdef1234', commit_error: null, include_mission_files: true }
    })
    const api = makeApi({ '/missions/m1/revert': mission({ status: 'completed' }) })
    render(<MissionScreen api={api} view={makeView({ mission: applied })} />)

    expect(screen.getByText(/Applied to your project: 2 file\(s\) in commit abcdef1/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply to my project' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Revert' }))
    expect(api.post).toHaveBeenCalledWith('/missions/m1/revert')
  })
})

describe('checkpoints', () => {
  const points: Checkpoint[] = [
    { commit: 'aaaaaaa1111', label: 'todo-model: Todo model', feature_id: 'f1', created_at: '' },
    { commit: 'bbbbbbb2222', label: 'Mission complete', feature_id: null, created_at: '' }
  ]

  it('restores to a feature checkpoint, but not to the closing one', async () => {
    const restored = mission({ status: 'paused' })
    const api = makeApi({ '/missions/m1/checkpoints/aaaaaaa1111/restore': restored })
    const view = makeView({ mission: mission({ status: 'completed' }), checkpoints: points })
    render(<MissionScreen api={api} view={view} />)

    const list = screen.getByRole('list', { name: 'Checkpoints' })
    expect(within(list).getAllByRole('button', { name: 'Restore to here' })).toHaveLength(1)
    fireEvent.click(within(list).getByRole('button', { name: 'Restore to here' }))

    expect(api.post).toHaveBeenCalledWith('/missions/m1/checkpoints/aaaaaaa1111/restore')
    await waitFor(() => expect(view.adopt).toHaveBeenCalledWith(restored))
  })

  it('hides restore while the mission is running', () => {
    render(<MissionScreen api={makeApi()} view={makeView({ checkpoints: points })} />)
    expect(screen.queryByRole('button', { name: 'Restore to here' })).toBeNull()
  })
})

describe('describeError', () => {
  it('reads strings, structured conflicts and validation errors', () => {
    expect(describeError(new ApiError(409, 'x', { detail: 'nope' }))).toEqual({ message: 'nope', paths: [] })
    expect(describeError(new ApiError(409, 'x', { detail: { message: 'stale', paths: ['a.js'] } }))).toEqual({ message: 'stale', paths: ['a.js'] })
    expect(
      describeError(new ApiError(422, 'x', { detail: [{ loc: ['body', 'plan', 'milestones'], msg: 'List should have at least 1 item' }] }))
    ).toEqual({ message: 'plan › milestones: List should have at least 1 item', paths: [] })
    expect(describeError(new ApiError(500, 'HTTP 500', null)).message).toBe('HTTP 500')
    expect(describeError(new Error('boom')).message).toBe('boom')
  })
})

describe('useMission (live, not polled)', () => {
  class FakeWebSocket {
    static instances: FakeWebSocket[] = []
    onopen: (() => void) | null = null
    onmessage: ((m: { data: unknown }) => void) | null = null
    onclose: ((e: { code: number }) => void) | null = null
    sent: string[] = []
    constructor(readonly url: string) {
      FakeWebSocket.instances.push(this)
    }
    send(data: string) {
      this.sent.push(data)
    }
    close() {}
    push(frame: unknown) {
      this.onmessage?.({ data: JSON.stringify(frame) })
    }
  }

  const config = { url: 'http://127.0.0.1:8765', token: 'tok' }

  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('applies the snapshot and pushed events, and refetches state once after a mission event', async () => {
    const fresh = mission({ spent_usd: 0.4 })
    const api = makeApi({
      '/missions/m1': fresh,
      '/missions/m1/needs': [],
      '/missions/m1/checkpoints': []
    })
    const { result } = renderHook(() => useMission(api, config, 'm1'))
    const [socket] = FakeWebSocket.instances
    expect(socket.url).toBe('ws://127.0.0.1:8765/ws/missions/m1?after_seq=0')
    act(() => socket.onopen?.())
    expect(JSON.parse(socket.sent[0])).toEqual({ type: 'auth', token: 'tok' })

    act(() => {
      socket.push({ type: 'snapshot', mission: mission(), last_seq: 0 })
      socket.push({
        type: 'event',
        event: { ...base, seq: 1, type: 'tool_called', payload: { tool: 'read_file', ok: true, summary: 'a' } }
      })
      socket.push({
        type: 'event',
        event: { ...base, seq: 2, type: 'handoff_recorded', payload: { feature_id: 'a', persona: 'backend', model_used: 'm', files_changed: [], tokens_in: 0, tokens_out: 0, cost_usd: 0 } }
      })
      vi.advanceTimersByTime(20)
    })
    expect(result.current.mission?.spent_usd).toBe(0)
    expect(result.current.events.map((e) => e.seq)).toEqual([1, 2])
    expect(result.current.connection.state).toBe('live')
    expect(api.get).not.toHaveBeenCalled() // nothing is fetched until a mission event says so

    await act(async () => {
      await vi.advanceTimersByTimeAsync(400)
    })

    expect(api.get.mock.calls.map((c) => c[0]).sort()).toEqual([
      '/missions/m1',
      '/missions/m1/checkpoints',
      '/missions/m1/needs'
    ])
    expect(result.current.mission?.spent_usd).toBe(0.4)

    // A worker-only event does not trigger another fetch.
    api.get.mockClear()
    act(() => {
      socket.push({ type: 'event', event: { ...base, seq: 3, type: 'tool_called', payload: { tool: 'read_file', ok: true, summary: 'b' } } })
      vi.advanceTimersByTime(20)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(api.get).not.toHaveBeenCalled()
  })

  it('only reports open Needs you items', async () => {
    const open: Need = { id: 'n1', mission_id: 'm1', feature_id: null, kind: 'budget_reached', summary: 's', evidence: {}, options: ['stop'], status: 'open', created_at: '' }
    const api = makeApi({
      '/missions/m1': mission(),
      '/missions/m1/needs': [open, { ...open, id: 'n0', status: 'answered' }],
      '/missions/m1/checkpoints': []
    })
    const { result } = renderHook(() => useMission(api, config, 'm1'))
    act(() => FakeWebSocket.instances[0].push({ type: 'snapshot', mission: mission(), last_seq: 0 }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400)
    })
    expect(result.current.needs.map((n) => n.id)).toEqual(['n1'])
  })

  it('does nothing without a mission id', () => {
    const api = makeApi()
    const { result } = renderHook(() => useMission(api, config, null))
    expect(FakeWebSocket.instances).toHaveLength(0)
    expect(result.current.mission).toBeNull()

    // Even an API object that changes on every render must not loop.
    const { result: unstable } = renderHook(() => useMission(makeApi(), config, null))
    expect(unstable.current.events).toEqual([])
  })
})

