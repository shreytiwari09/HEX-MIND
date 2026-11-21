import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import { ago, personaOf, teamActivity } from './team'

let seq = 0
function ev(type: string, agent_id: string | null, payload: Record<string, unknown>, ts = '2026-11-22T01:00:00Z'): AgentEvent {
  seq += 1
  return { type, agent_id, payload, seq, ts, run_id: 'r', event_id: String(seq), schema_version: 8, task_id: null } as unknown as AgentEvent
}

const feature = (status: string, persona: string, ts?: string) =>
  ev('feature_status_changed', 'mission_runner', { status, persona, title: 'Calculator engine', feature_id: 'f', attempts: 1, commit: null }, ts)

describe('team activity from real events', () => {
  it('maps agent ids to personas and leaves shared infrastructure unassigned', () => {
    expect(personaOf('backend_01')).toBe('backend')
    expect(personaOf('qa_acceptance_01')).toBe('qa')
    expect(personaOf('review_calc_ui')).toBe('code-reviewer')
    expect(personaOf('review-calc-ui')).toBe('code-reviewer')
    expect(personaOf('pm_scoping')).toBe('pm')
    expect(personaOf('security_review_01')).toBe('security')
    expect(personaOf('sandbox')).toBeNull()
    expect(personaOf(null)).toBeNull()
  })

  it('shows who is working now and what they are doing, from the latest event', () => {
    const team = teamActivity(
      [
        feature('in_progress', 'backend', '2026-11-22T01:00:00Z'),
        ev('tool_called', 'backend_01', { tool: 'write_file', ok: true, summary: 'src/calculator.py: created' }),
        ev('check_started', 'sandbox', { name: 'test' })
      ],
      true
    )
    expect(team[0]).toMatchObject({ id: 'backend', name: 'Backend', state: 'working', since: '2026-11-22T01:00:00Z' })
    expect(team[0].doing).toBe('Running "test" in the sandbox') // the sandbox check belongs to whoever is working
    expect(team[0].steps.map((s) => s.text)).toContain('Writing src/calculator.py')
  })

  it('a finished member shows its last result, not "Thinking", and nobody works on a stopped mission', () => {
    const events = [
      feature('in_progress', 'backend'),
      ev('llm_call_started', 'backend_01', { model: 'm', provider: 'p', purpose: 'coder' }),
      ev('llm_call_completed', 'backend_01', { ok: true, model: 'm', provider: 'p', purpose: 'coder', input_tokens: 10, output_tokens: 5, latency_ms: 1, attempts: 1, error: null, replayed: false, request_sha256: null, response_sha256: null }),
      feature('done', 'backend'),
      ev('llm_call_started', 'pm_scoping', { model: 'm', provider: 'p', purpose: 'planner' })
    ]
    const team = teamActivity(events, false)
    const backend = team.find((m) => m.id === 'backend')!
    expect(backend).toMatchObject({ state: 'done', doing: 'Finished "Calculator engine"', calls: 1, tokensIn: 10, tokensOut: 5 })
    expect(team.find((m) => m.id === 'pm')!.doing).not.toMatch(/^Thinking/)
    expect(team.every((m) => m.state !== 'working')).toBe(true)
  })

  it('validators work from their start to their verdict', () => {
    const team = teamActivity(
      [
        ev('validator_started', 'qa', { validator: 'qa', milestone_id: 'm1', round: 1 }),
        ev('validator_reported', 'qa', { validator: 'qa', milestone_id: 'm1', round: 1, verdict: 'fail', findings: 2, blocking: 1 })
      ],
      true
    )
    expect(team[0]).toMatchObject({ id: 'qa', state: 'failed', doing: 'Verdict on m1: fail, 2 findings' })
  })

  it('words tool calls as plain sentences', () => {
    const say = (tool: string, summary: string, ok = true) =>
      teamActivity([feature('in_progress', 'backend'), ev('tool_called', 'backend_01', { tool, ok, summary })], true)[0].steps.at(-1)?.text
    expect(say('run_check', 'test: exit 0')).toBe('Running the "test" check')
    expect(say('git_diff', 'diff')).toBe('Using git diff')
    expect(say('write_file', 'app.py: created', false)).toBe('Writing app.py (it failed)')
    expect(say('list_features', 'scaffold | m1')).toBe('Reading the plan')
  })

  it('formats elapsed time', () => {
    const now = Date.parse('2026-11-22T01:02:05Z')
    expect(ago('2026-11-22T01:02:00Z', now)).toBe('5 s')
    expect(ago('2026-11-22T01:00:00Z', now)).toBe('2 min 5 s')
    expect(ago(null, now)).toBe('')
  })
})
