import { CheckCircle2, CircleAlert, CircleDashed, LoaderCircle, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { AgentEvent } from '../../generated/events'
import { ago, stepText, teamActivity, type Member, type MemberState } from './team'

const ICONS: Record<MemberState, typeof LoaderCircle> = {
  working: LoaderCircle,
  done: CheckCircle2,
  failed: CircleAlert,
  idle: CircleDashed
}
const STATE_TEXT: Record<MemberState, string> = { working: 'Working', done: 'Done', failed: 'Had a problem', idle: 'Waiting' }

/** The current time, ticking every second while `active`. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return now
}

interface Props {
  events: AgentEvent[]
  /** True while the mission is running: timers tick and "working" is shown. */
  active: boolean
}

/** Who is working right now, on what, for how long; click a member to see its steps. */
export function TeamRoster({ events, active }: Props) {
  const team = useMemo(() => teamActivity(events, active), [events, active])
  const [open, setOpen] = useState<string | null>(null)
  const now = useNow(active)
  const last = events[events.length - 1]
  const quiet = active && last ? Math.round((now - Date.parse(last.ts)) / 1000) : 0
  const waitingOnModel = last?.type === 'llm_call_started'

  if (team.length === 0) {
    return (
      <section className="team-roster" aria-label="Team">
        <h3 className="mission__section-title">Team</h3>
        <p className="mission__muted">{active ? 'The team is getting ready: the working copy and the sandbox start first.' : 'Nobody has worked on this mission yet.'}</p>
      </section>
    )
  }
  const selected = team.find((m) => m.id === open) ?? null
  return (
    <section className="team-roster" aria-label="Team">
      <div className="team-roster__head">
        <h3 className="mission__section-title">Team</h3>
        {active && last && (
          <span className="team-roster__pulse" data-quiet={quiet > 90}>
            <span className="team-roster__beat" aria-hidden="true" />
            Last activity {ago(last.ts, now)} ago
            {waitingOnModel && quiet > 10 ? ' · waiting for the model to answer' : ''}
          </span>
        )}
      </div>
      <ul className="team-roster__list">
        {team.map((m) => {
          const Icon = ICONS[m.state]
          return (
            <li key={m.id}>
              <button
                type="button"
                className="member"
                data-state={m.state}
                aria-pressed={open === m.id}
                onClick={() => setOpen(open === m.id ? null : m.id)}
              >
                <Icon size={16} className="member__icon" aria-label={STATE_TEXT[m.state]} />
                <span className="member__name">{m.name}</span>
                <span className="member__doing" title={m.doing}>{m.doing}</span>
                <span className="member__time">
                  {m.state === 'working' && m.since ? ago(m.since, now) : m.calls > 0 ? `${m.calls} call${m.calls === 1 ? '' : 's'}` : ''}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {selected && <MemberDrawer member={selected} now={now} onClose={() => setOpen(null)} />}
    </section>
  )
}

function MemberDrawer({ member, now, onClose }: { member: Member; now: number; onClose: () => void }) {
  const end = useRef<HTMLLIElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'nearest' })
  }, [member.steps.length])
  return (
    <aside className="member-drawer" aria-label={`${member.name}: what it did`}>
      <header className="member-drawer__head">
        <div>
          <h4 className="member-drawer__title">{member.name}</h4>
          <p className="mission__muted">
            {STATE_TEXT[member.state]} · {member.calls} model call{member.calls === 1 ? '' : 's'} ·{' '}
            {member.tokensIn.toLocaleString()} in / {member.tokensOut.toLocaleString()} out tokens
            {member.lastAt ? ` · last activity ${ago(member.lastAt, now)} ago` : ''}
          </p>
        </div>
        <button type="button" className="icon-button" aria-label="Close" onClick={onClose}>
          <X size={14} />
        </button>
      </header>
      {member.files.length > 0 && (
        <p className="member-drawer__files">
          <strong>Changed:</strong> {member.files.join(', ')}
        </p>
      )}
      <ol className="member-drawer__steps">
        {member.steps.map((step, i) => (
          <li key={step.seq} data-tone={step.tone} ref={i === member.steps.length - 1 ? end : undefined}>
            <time dateTime={step.ts}>{new Date(step.ts).toLocaleTimeString()}</time>
            <span>{step.text}</span>
          </li>
        ))}
      </ol>
    </aside>
  )
}

/** The mission's activity as plain sentences, newest last, each with who did it. */
export function ActivityFeed({ events, limit = 200 }: { events: AgentEvent[]; limit?: number }) {
  const lines = useMemo(() => {
    const team = teamActivity(events, true)
    const name = new Map(team.flatMap((m) => m.steps.map((s) => [s.seq, m.name] as const)))
    const out: { seq: number; ts: string; who: string; text: string; tone: string }[] = []
    for (const e of events) {
      const step = stepText(e)
      if (!step) continue
      out.push({ seq: e.seq, ts: e.ts, who: name.get(e.seq) ?? 'Team', ...step })
    }
    return out.slice(-limit)
  }, [events, limit])
  const end = useRef<HTMLLIElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'nearest' })
  }, [lines.length])
  if (lines.length === 0) return <p className="mission__muted">Nothing yet. Each step appears here as it happens.</p>
  return (
    <ol className="activity">
      {lines.map((line, i) => (
        <li key={line.seq} data-tone={line.tone} ref={i === lines.length - 1 ? end : undefined}>
          <time dateTime={line.ts}>{new Date(line.ts).toLocaleTimeString()}</time>
          <span className="activity__who">{line.who}</span>
          <span>{line.text}</span>
        </li>
      ))}
    </ol>
  )
}
