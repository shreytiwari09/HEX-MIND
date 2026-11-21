import { Pause, Play, Square, Check } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { BackendConfig } from '../../../../preload/api'
import type { ApiClient } from '../../lib/api'
import { describeError, postAction, type MissionAction } from './actions'
import { HandoffPanel } from '../handoff/HandoffPanel'
import { ApplyPanel } from './ApplyPanel'
import { Checkpoints } from './Checkpoints'
import { CostsPanel } from './CostsPanel'
import { ProvenancePanel } from './ProvenancePanel'
import { ActivityFeed, TeamRoster } from './TeamRoster'
import { ValidationPanel } from './ValidationPanel'
import { FeatureTree } from './FeatureTree'
import { NeedsYou } from './NeedsYou'
import {
  actionsFor,
  activeFeature,
  elapsedMs,
  formatElapsed,
  formatUsd,
  isDelegationEvent,
  isMissionEvent,
  isWorkerEvent,
  progressOf,
  statusLabel,
  statusTone,
  toLines
} from './progress'
import type { Mission } from './types'
import { useMission, type MissionView } from './useMission'

const OUTPUT_LINES = 120
const LOG_LINES = 60

interface Props {
  api: ApiClient
  config: BackendConfig
  missionId: string
  /** Tell the mission list its row changed (status, title). */
  onChanged?: () => void
}

export function MissionControl({ api, config, missionId, onChanged }: Props) {
  const view = useMission(api, config, missionId)
  return <MissionScreen api={api} view={view} onChanged={onChanged} />
}

const CONNECTION_LABEL = {
  connecting: 'Connecting…',
  live: 'Live',
  reconnecting: 'Reconnecting…',
  closed: 'Disconnected'
} as const

/** The screen itself, separate from the data hook so it can be rendered from fixed data. */
export function MissionScreen({
  api,
  view,
  onChanged
}: {
  api: ApiClient
  view: MissionView
  onChanged?: () => void
}) {
  const { mission, events, needs, checkpoints, connection, error } = view
  const [actionError, setActionError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const now = useNow(mission?.status === 'running')

  if (!mission) {
    return (
      <div className="mission mission--empty" role="status">
        {error ? `Could not load the mission: ${error}` : connection.detail ?? 'Loading the mission…'}
      </div>
    )
  }

  const actions = actionsFor(mission.status)
  const progress = progressOf(mission)
  const active = activeFeature(mission)
  const elapsed = elapsedMs(mission, now)
  const percent = progress.total === 0 ? 0 : Math.round((progress.finished / progress.total) * 100)
  const adopt = (fresh: Mission) => {
    view.adopt(fresh)
    onChanged?.()
  }

  const act = async (action: MissionAction) => {
    setBusy(true)
    setActionError(null)
    try {
      adopt(await postAction(api, mission.id, action))
    } catch (err) {
      setActionError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const stop = () => {
    if (window.confirm('Stop this mission? Work in progress is dropped.')) void act('stop')
  }

  return (
    <section className="mission" aria-label={`Mission: ${mission.title}`}>
      <header className="mission__header">
        <div className="mission__title-row">
          <h2 className="mission__title">{mission.title}</h2>
          <span className="status-pill" data-tone={statusTone(mission.status)}>
            <span className="status-dot" aria-hidden="true" />
            {statusLabel(mission.status)}
          </span>
          <span className="mission__connection" data-state={connection.state} title={connection.detail}>
            {CONNECTION_LABEL[connection.state]}
          </span>
        </div>
        <div className="mission__progress">
          <div
            className="mission__bar"
            role="progressbar"
            aria-label="Features finished"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.finished}
          >
            <div className="mission__bar-fill" style={{ width: `${percent}%` }} />
          </div>
          <span className="mission__counts">
            Feature {progress.finished} of {progress.total}
            {progress.skipped > 0 ? ` (${progress.skipped} skipped)` : ''} · Milestone{' '}
            {progress.milestonesFinished} of {progress.milestonesTotal}
          </span>
        </div>
        <dl className="mission__meta">
          {elapsed !== null && (
            <div>
              <dt>Elapsed</dt>
              <dd>{formatElapsed(elapsed)}</dd>
            </div>
          )}
          <div>
            <dt>Spent</dt>
            <dd>
              {formatUsd(mission.spent_usd)}
              {mission.budget_usd !== null ? ` of ${formatUsd(mission.budget_usd)}` : ''}
            </dd>
          </div>
          <div>
            <dt>Tokens</dt>
            <dd>
              {mission.tokens_in.toLocaleString()} in / {mission.tokens_out.toLocaleString()} out
            </dd>
          </div>
          {mission.coordination === 'messaging' && (
            <div>
              <dt>Team</dt>
              <dd>messages only</dd>
            </div>
          )}
          <div>
            <dt>Branch</dt>
            <dd>
              <code>{mission.branch}</code>
            </dd>
          </div>
        </dl>
      </header>

      <div className="mission__actions" role="toolbar" aria-label="Mission controls">
        {actions.approve && (
          <button type="button" className="button button--primary" disabled={busy} onClick={() => void act('approve')}>
            <Check size={14} aria-hidden="true" /> Approve and start
          </button>
        )}
        {actions.pause && (
          <button type="button" className="button" disabled={busy} onClick={() => void act('pause')}>
            <Pause size={14} aria-hidden="true" /> Pause
          </button>
        )}
        {actions.resume && (
          <button type="button" className="button button--primary" disabled={busy} onClick={() => void act('resume')}>
            <Play size={14} aria-hidden="true" /> Resume
          </button>
        )}
        {actions.stop && (
          <button type="button" className="button" disabled={busy} onClick={stop}>
            <Square size={14} aria-hidden="true" /> Stop
          </button>
        )}
      </div>
      {(actionError || error) && (
        <p role="alert" className="mission__error">
          {actionError ?? error}
        </p>
      )}

      <NeedsYou api={api} needs={needs} onAnswered={adopt} />
      {actions.review && <ApplyPanel api={api} mission={mission} onChanged={adopt} />}
      {mission.status === 'applied' && (
        <HandoffPanel api={api} projectId={mission.project_id} projectName={mission.title} />
      )}

      <TeamRoster events={events} active={mission.status === 'running'} />

      <div className="mission__body">
        <div className="mission__main">
          <ActiveFeatureCard mission={mission} active={active} />
          <LiveOutput view={view} />
        </div>
        <div className="mission__side">
          <section aria-label="Plan">
            <h3 className="mission__section-title">Plan</h3>
            <FeatureTree mission={mission} />
          </section>
          <ProgressLog events={events} />
          <section aria-label="Validation">
            <h3 className="mission__section-title">Validation</h3>
            <ValidationPanel
              api={api}
              missionId={mission.id}
              refreshKey={`${mission.status}:${events.filter((e) => e.type === 'validator_reported').length}`}
            />
          </section>
          <section aria-label="Costs">
            <h3 className="mission__section-title">Costs and delegation</h3>
            <CostsPanel
              api={api}
              missionId={mission.id}
              refreshKey={`${mission.status}:${mission.spent_usd}:${mission.tokens_in}:${events.filter(isDelegationEvent).length}`}
            />
          </section>
          <section aria-label="Provenance">
            <h3 className="mission__section-title">Where the changes came from</h3>
            <ProvenancePanel
              api={api}
              missionId={mission.id}
              refreshKey={`${mission.status}:${events.filter((e) => e.type === 'handoff_recorded').length}`}
            />
          </section>
          <section aria-label="Checkpoints">
            <h3 className="mission__section-title">Checkpoints</h3>
            <Checkpoints
              api={api}
              missionId={mission.id}
              checkpoints={checkpoints}
              canRestore={actions.restore}
              onRestored={adopt}
            />
          </section>
        </div>
      </div>
    </section>
  )
}

function ActiveFeatureCard({ mission, active }: { mission: Mission; active: ReturnType<typeof activeFeature> }) {
  if (!active) {
    const idle: Partial<Record<Mission['status'], string>> = {
      awaiting_approval: 'Review the plan on the right, then approve to start the team.',
      paused: 'Paused. Resume when you are ready; the team continues from its last checkpoint.',
      needs_user: 'The team is waiting for your decision above.',
      completed: 'Every feature is done or skipped.',
      applied: 'Applied to your project.',
      kept: 'Kept on its branch.',
      cancelled: 'Stopped.',
      failed: 'The mission failed. The progress log shows why.',
      running: 'Picking the next feature…'
    }
    return (
      <section className="mission__card" aria-label="Active feature">
        <h3 className="mission__section-title">Active feature</h3>
        <p className="mission__muted">{idle[mission.status] ?? 'Nothing is running.'}</p>
      </section>
    )
  }
  return (
    <section className="mission__card" aria-label="Active feature">
      <h3 className="mission__section-title">Active feature</h3>
      <p className="mission__feature-title">{active.title}</p>
      <p className="mission__muted">
        {active.persona} · attempt {active.attempts + 1}
      </p>
      {active.description && <p>{active.description}</p>}
      {active.preconditions.length > 0 && (
        <>
          <h4 className="mission__label">Before it starts</h4>
          <ul>
            {active.preconditions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      )}
      <h4 className="mission__label">Expected</h4>
      <ul>
        {active.expected_behavior.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

function LiveOutput({ view }: { view: MissionView }) {
  const [raw, setRaw] = useState(false)
  const lines = toLines(view.events, isWorkerEvent, OUTPUT_LINES)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (raw) end.current?.scrollIntoView?.({ block: 'end' })
  }, [lines.length, raw])
  return (
    <section className="mission__card mission__output" aria-label="Live output">
      <div className="mission__output-head">
        <h3 className="mission__section-title">{raw ? 'Raw log' : 'Activity'}</h3>
        <button type="button" className="button button--small" aria-pressed={raw} onClick={() => setRaw((r) => !r)}>
          {raw ? 'Show steps' : 'Show raw log'}
        </button>
      </div>
      {!raw ? (
        <ActivityFeed events={view.events} />
      ) : lines.length === 0 ? (
        <p className="mission__muted">Nothing yet. Tool calls, checks and model calls appear here as they happen.</p>
      ) : (
        <ol className="mission__lines">
          {lines.map((line) => (
            <li key={line.seq}>{line.text}</li>
          ))}
          <div ref={end} />
        </ol>
      )}
    </section>
  )
}

function ProgressLog({ events }: { events: MissionView['events'] }) {
  const lines = toLines(events, isMissionEvent, LOG_LINES).reverse()
  return (
    <section aria-label="Progress log">
      <h3 className="mission__section-title">Progress log</h3>
      {lines.length === 0 ? (
        <p className="mission__muted">No progress yet.</p>
      ) : (
        <ol className="mission__log">
          {lines.map((line) => (
            <li key={line.seq}>
              <time dateTime={line.ts}>{new Date(line.ts).toLocaleTimeString()}</time> {line.text}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

/** The current time, refreshed every second while `active` (for the elapsed clock). */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [active])
  return now
}
