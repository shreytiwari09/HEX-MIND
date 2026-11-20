import { EmptyState } from '../../components/Panel'
import type { AgentEvent } from '../../generated/events'
import type { Task } from '../../lib/api'
import { formatMs } from '../runs/events'
import { deriveMessageFlow } from './derive'

interface Props {
  events: AgentEvent[]
  tasks: Task[]
}

const LABEL = { request: 'sends work', resend: 'sends it again', reply: 'replies', timeout: 'no answer in time' } as const

/**
 * The orchestrator and the crews as a sequence diagram (PRD §14.3), drawn from the recorded A2A
 * messages. With messaging coordination this is everything a worker ever learns about the mission:
 * the request it was sent. A request sent again uses the same exchange id, so the crew did the
 * work once.
 */
export function MessageFlow({ events, tasks }: Props) {
  const { lanes, messages } = deriveMessageFlow(events)
  const titles = new Map(tasks.map((t) => [t.id, t.title]))
  if (messages.length === 0) return <EmptyState title="No messages between the orchestrator and the crews in this run yet" />

  return (
    <section className="obs-section" aria-label="Message flow">
      <h3 className="obs-section__title">Message flow ({messages.length} messages)</h3>
      <div className="flow" style={{ ['--lanes' as string]: lanes.length }}>
        <div className="flow__lanes" aria-hidden="true">
          {lanes.map((lane) => (
            <span key={lane} className="flow__lane mono">
              {lane}
            </span>
          ))}
        </div>
        <ol className="flow__rows">
          {messages.map((m) => {
            const a = lanes.indexOf(m.from)
            const b = lanes.indexOf(m.to)
            return (
              <li key={`${m.seq}`} className="flow__row" data-kind={m.kind} aria-label={`${m.from} ${LABEL[m.kind]} to ${m.to}`}>
                <span
                  className="flow__arrow"
                  data-direction={a < b ? 'right' : 'left'}
                  style={{ gridColumn: `${Math.min(a, b) + 1} / ${Math.max(a, b) + 2}` }}
                />
                <span className="flow__text">
                  <span className="mono">{new Date(m.ts).toLocaleTimeString()}</span> {m.from} {LABEL[m.kind]}
                  {m.taskId && titles.get(m.taskId) ? `: ${titles.get(m.taskId)}` : ''}
                  {m.state ? ` (${m.state})` : ''}
                  {m.durationMs !== null ? ` · ${formatMs(m.durationMs)}` : ''}
                  {m.summary && <span className="flow__summary" title={m.summary}> {m.summary}</span>}
                  <span className="mono flow__id"> exchange {m.exchangeId.slice(0, 8)}</span>
                </span>
              </li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}
