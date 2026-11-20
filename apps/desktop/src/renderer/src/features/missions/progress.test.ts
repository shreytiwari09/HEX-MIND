import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import { describeEvent } from '../runs/events'
import {
  actionsFor,
  activeFeature,
  elapsedMs,
  formatElapsed,
  formatUsd,
  isMissionEvent,
  isWorkerEvent,
  progressOf,
  statusLabel,
  statusTone,
  toLines
} from './progress'
import { mission } from './fixtures'
import type { MissionStatus } from './types'

const base = { schema_version: 8 as const, event_id: 'e', run_id: 'r1', ts: '2026-11-19T10:00:00Z', agent_id: null, task_id: null }

describe('progressOf and activeFeature', () => {
  it('counts finished (done or skipped) features and milestones from the real statuses', () => {
    expect(progressOf(mission())).toEqual({
      total: 4,
      finished: 2,
      done: 1,
      skipped: 1,
      failed: 0,
      milestonesFinished: 1,
      milestonesTotal: 2
    })
    // A validated or accepted milestone counts as finished too; a failed one does not.
    const validated = mission()
    validated.milestones[0].status = 'passed'
    validated.milestones[1].status = 'accepted'
    expect(progressOf(validated).milestonesFinished).toBe(2)
    validated.milestones[1].status = 'failed'
    expect(progressOf(validated).milestonesFinished).toBe(1)
    expect(activeFeature(mission())?.id).toBe('c')
    expect(activeFeature(mission({ milestones: [] }))).toBeNull()
  })
})

describe('actionsFor', () => {
  const allowed = (status: MissionStatus) =>
    Object.entries(actionsFor(status))
      .filter(([, on]) => on)
      .map(([name]) => name)

  it('offers exactly what the backend allows in each state', () => {
    expect(allowed('awaiting_approval')).toEqual(['approve', 'stop', 'discard'])
    expect(allowed('running')).toEqual(['pause', 'stop'])
    expect(allowed('paused')).toEqual(['resume', 'stop', 'discard', 'restore'])
    expect(allowed('needs_user')).toEqual(['stop', 'discard', 'restore'])
    expect(allowed('completed')).toEqual(['review', 'apply', 'keep', 'discard', 'restore'])
    expect(allowed('kept')).toEqual(['review', 'apply', 'discard', 'restore'])
    expect(allowed('applied')).toEqual(['review', 'discard', 'revert'])
    expect(allowed('cancelled')).toEqual(['discard'])
    expect(allowed('failed')).toEqual(['discard', 'restore'])
    expect(allowed('discarded')).toEqual([])
  })
})

describe('status wording', () => {
  it('uses plain words and one tone per meaning', () => {
    expect(statusLabel('needs_user')).toBe('Needs you')
    expect(statusLabel('cancelled')).toBe('Stopped')
    expect(statusTone('running')).toBe('active')
    expect(statusTone('needs_user')).toBe('warning')
    expect(statusTone('failed')).toBe('danger')
    expect(statusTone('applied')).toBe('success')
  })
})

describe('log lines', () => {
  const events: AgentEvent[] = [
    { ...base, seq: 1, type: 'tool_called', payload: { tool: 'write_file', ok: true, summary: 'src/a.js: updated' } },
    { ...base, seq: 2, type: 'agent_started', payload: { agent: 'x', framework: 'adk', kind: 'custom', parent: null } },
    { ...base, seq: 3, type: 'feature_status_changed', payload: { feature_id: 'c', title: 'Filter', persona: 'frontend', status: 'in_progress', attempts: 2, commit: null } },
    { ...base, seq: 4, type: 'check_completed', payload: { name: 'test', exit_code: 0, duration_ms: 1500 } }
  ]

  it('splits worker output from mission progress and keeps the newest lines in order', () => {
    expect(events.filter(isWorkerEvent).map((e) => e.seq)).toEqual([1, 4])
    expect(events.filter(isMissionEvent).map((e) => e.seq)).toEqual([3])
    expect(toLines(events, isWorkerEvent, 10).map((l) => l.text)).toEqual([
      'write_file: src/a.js: updated',
      'test passed in 1.5s'
    ])
    expect(toLines(events, isWorkerEvent, 1).map((l) => l.seq)).toEqual([4])
  })

  it('describes the mission events in plain words', () => {
    const cases: [AgentEvent, string][] = [
      [{ ...base, seq: 1, type: 'mission_status_changed', payload: { status: 'running', previous: 'awaiting_approval', reason: 'plan approved' } }, 'awaiting_approval → running (plan approved)'],
      [{ ...base, seq: 2, type: 'milestone_status_changed', payload: { milestone_id: 'm1', title: 'Model', status: 'completed' } }, 'Model: completed'],
      [{ ...base, seq: 3, type: 'feature_status_changed', payload: { feature_id: 'c', title: 'Filter', persona: 'frontend', status: 'in_progress', attempts: 2, commit: null } }, 'Filter (frontend): in progress, attempt 2'],
      [{ ...base, seq: 4, type: 'handoff_recorded', payload: { feature_id: 'c', persona: 'frontend', model_used: 'groq:m', files_changed: ['a', 'b'], tokens_in: 1, tokens_out: 1, cost_usd: 0 } }, 'c: handoff from frontend, 2 file(s) changed on groq:m'],
      [{ ...base, seq: 5, type: 'checkpoint_created', payload: { commit: 'abc', label: 'c: Filter', feature_id: 'c' } }, 'checkpoint: c: Filter'],
      [{ ...base, seq: 6, type: 'need_raised', payload: { need_id: 'n', kind: 'budget_reached', summary: 'The budget is spent.', options: ['stop'], feature_id: null } }, 'The budget is spent.'],
      [{ ...base, seq: 7, type: 'need_answered', payload: { need_id: 'n', action: 'raise_budget' } }, 'answered: raise budget']
    ]
    for (const [event, text] of cases) expect(describeEvent(event)).toBe(text)
  })
})

describe('time and money', () => {
  it('measures elapsed time from the real timestamps, stopping at the end', () => {
    const now = Date.parse('2026-11-19T10:05:30Z')
    expect(elapsedMs(mission(), now)).toBe(330_000)
    expect(elapsedMs(mission({ finished_at: '2026-11-19T10:01:00Z' }), now)).toBe(60_000)
    expect(elapsedMs(mission({ started_at: null }), now)).toBeNull()
    expect(formatElapsed(330_000)).toBe('5m 30s')
    expect(formatElapsed(45_000)).toBe('45s')
    expect(formatElapsed(3_900_000)).toBe('1h 5m')
  })

  it('formats dollars with more precision for small amounts', () => {
    expect(formatUsd(0.0123)).toBe('$0.012')
    expect(formatUsd(2.5)).toBe('$2.50')
  })
})
