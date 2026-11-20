import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import { deriveMessageFlow } from './derive'
import { MessageFlow } from './MessageFlow'

let seq = 0
function a2a(side: 'client' | 'server', direction: 'sent' | 'received', extra: Record<string, unknown> = {}): AgentEvent {
  seq += 1
  return {
    seq,
    ts: new Date(2026, 10, 20, 12, 0, seq).toISOString(),
    type: 'a2a_message',
    task_id: 't1',
    payload: { side, direction, agent: 'orchestrator', peer: 'persona_crew', exchange_id: 'ex-aaaaaaaa', task_state: null, summary: null, duration_ms: null, ...extra }
  } as unknown as AgentEvent
}

describe('deriveMessageFlow', () => {
  it('draws a request and its reply between the orchestrator and the crew', () => {
    const flow = deriveMessageFlow([a2a('client', 'sent', { summary: 'Feature: Todo model' }), a2a('server', 'received'), a2a('client', 'received', { task_state: 'completed', duration_ms: 1500 })])

    expect(flow.lanes).toEqual(['orchestrator', 'persona_crew'])
    expect(flow.messages.map((m) => [m.kind, m.from, m.to])).toEqual([
      ['request', 'orchestrator', 'persona_crew'],
      ['reply', 'persona_crew', 'orchestrator']
    ])
  })

  it('shows a lost reply and the same request sent again under the same exchange id', () => {
    const flow = deriveMessageFlow([
      a2a('client', 'sent'),
      a2a('client', 'received', { task_state: 'failed', summary: 'TimeoutError: persona_crew did not answer in time' }),
      a2a('client', 'sent'),
      a2a('client', 'received', { task_state: 'completed' })
    ])

    expect(flow.messages.map((m) => m.kind)).toEqual(['request', 'timeout', 'resend', 'reply'])
    expect(new Set(flow.messages.map((m) => m.exchangeId)).size).toBe(1)
  })

  it('does not call an ordinary failure a timeout', () => {
    const flow = deriveMessageFlow([a2a('client', 'sent'), a2a('client', 'received', { task_state: 'failed', summary: 'crew failed: bad output' })])

    expect(flow.messages[1].kind).toBe('reply')
  })

  it('gives each crew its own lane', () => {
    const flow = deriveMessageFlow([a2a('client', 'sent', { peer: 'planner_crew' }), a2a('client', 'sent', { peer: 'persona_crew', exchange_id: 'ex-bbbbbbbb' })])

    expect(flow.lanes).toEqual(['orchestrator', 'planner_crew', 'persona_crew'])
  })
})

describe('MessageFlow', () => {
  it('says so when nothing was sent', () => {
    render(<MessageFlow events={[]} tasks={[]} />)

    expect(screen.getByText(/No messages between the orchestrator and the crews/)).toBeInTheDocument()
  })

  it('lists each message with its task, state and exchange', () => {
    const events = [a2a('client', 'sent', { summary: 'Feature: Todo model' }), a2a('client', 'received', { task_state: 'completed', duration_ms: 1500 })]
    render(<MessageFlow events={events} tasks={[{ id: 't1', title: 'Todo model' } as never]} />)

    expect(screen.getByText('Message flow (2 messages)')).toBeInTheDocument()
    expect(screen.getByRole('listitem', { name: /orchestrator sends work to persona_crew/ })).toHaveTextContent('Todo model')
    expect(screen.getByRole('listitem', { name: /persona_crew replies to orchestrator/ })).toHaveTextContent('completed')
  })
})
