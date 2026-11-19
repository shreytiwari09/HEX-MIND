import type { AgentEvent } from '../../generated/events'
import { describeEvent } from '../runs/events'
import type { Mission, MissionFeature, MissionStatus } from './types'

export type Tone = 'success' | 'warning' | 'danger' | 'active' | 'neutral'

const STATUS_LABEL: Record<MissionStatus, string> = {
  draft: 'Draft',
  scoping: 'Scoping',
  awaiting_approval: 'Awaiting approval',
  running: 'Running',
  paused: 'Paused',
  needs_user: 'Needs you',
  completed: 'Completed',
  applied: 'Applied',
  kept: 'Kept on branch',
  discarded: 'Discarded',
  cancelled: 'Stopped',
  failed: 'Failed'
}

const STATUS_TONE: Record<MissionStatus, Tone> = {
  draft: 'neutral',
  scoping: 'active',
  awaiting_approval: 'warning',
  running: 'active',
  paused: 'warning',
  needs_user: 'warning',
  completed: 'success',
  applied: 'success',
  kept: 'success',
  discarded: 'neutral',
  cancelled: 'neutral',
  failed: 'danger'
}

export const statusLabel = (status: MissionStatus): string => STATUS_LABEL[status] ?? status
export const statusTone = (status: MissionStatus): Tone => STATUS_TONE[status] ?? 'neutral'

export function allFeatures(mission: Mission): MissionFeature[] {
  return mission.milestones.flatMap((m) => m.features)
}

export interface Progress {
  total: number
  /** Done or skipped: finished, one way or the other. */
  finished: number
  done: number
  skipped: number
  failed: number
  milestonesFinished: number
  milestonesTotal: number
}

export function progressOf(mission: Mission): Progress {
  const features = allFeatures(mission)
  const count = (status: MissionFeature['status']) => features.filter((f) => f.status === status).length
  const done = count('done')
  const skipped = count('skipped')
  return {
    total: features.length,
    finished: done + skipped,
    done,
    skipped,
    failed: count('failed'),
    // Done building: validated, accepted by you, or (with no validators) just completed.
    milestonesFinished: mission.milestones.filter((m) =>
      ['completed', 'passed', 'accepted'].includes(m.status)
    ).length,
    milestonesTotal: mission.milestones.length
  }
}

/** The feature being worked on now; null when nothing is in progress. */
export function activeFeature(mission: Mission): MissionFeature | null {
  return allFeatures(mission).find((f) => f.status === 'in_progress') ?? null
}

export interface Actions {
  approve: boolean
  pause: boolean
  resume: boolean
  stop: boolean
  review: boolean
  apply: boolean
  keep: boolean
  discard: boolean
  revert: boolean
  restore: boolean
}

/** What the backend allows in each state (see missions/lifecycle.py and api/missions.py). */
export function actionsFor(status: MissionStatus): Actions {
  const is = (...states: MissionStatus[]) => states.includes(status)
  return {
    approve: is('awaiting_approval'),
    pause: is('running'),
    resume: is('paused'),
    stop: is('awaiting_approval', 'running', 'paused', 'needs_user'),
    review: is('completed', 'kept', 'applied'),
    apply: is('completed', 'kept'),
    keep: is('completed'),
    discard: is(
      'awaiting_approval',
      'paused',
      'needs_user',
      'completed',
      'kept',
      'cancelled',
      'failed',
      'applied'
    ),
    revert: is('applied'),
    restore: is('paused', 'needs_user', 'completed', 'kept', 'failed')
  }
}

/** Event types that change what the mission view shows; each one triggers a state refresh. */
export const MISSION_EVENT_TYPES: ReadonlySet<AgentEvent['type']> = new Set([
  'mission_status_changed',
  'milestone_status_changed',
  'feature_status_changed',
  'handoff_recorded',
  'checkpoint_created',
  'need_raised',
  'need_answered',
  // Delegation: what the router did with this mission's model calls.
  'key_rotated',
  'provider_fallback',
  'escalated',
  'budget_warning',
  // Validators checking a milestone.
  'validator_started',
  'validator_reported'
])

/** What the worker is doing, for the live output pane. */
const WORKER_EVENT_TYPES: ReadonlySet<AgentEvent['type']> = new Set([
  'tool_called',
  'check_started',
  'check_completed',
  'llm_call_completed',
  'provider_fallback'
])

export const isMissionEvent = (event: AgentEvent) => MISSION_EVENT_TYPES.has(event.type)

const DELEGATION_EVENT_TYPES: ReadonlySet<AgentEvent['type']> = new Set([
  'key_rotated',
  'provider_fallback',
  'escalated',
  'budget_warning'
])
export const isDelegationEvent = (event: AgentEvent) => DELEGATION_EVENT_TYPES.has(event.type)
export const isWorkerEvent = (event: AgentEvent) => WORKER_EVENT_TYPES.has(event.type)

export interface LogLine {
  seq: number
  ts: string
  text: string
}

/** The newest `limit` events that pass `keep`, oldest first, described in plain words. */
export function toLines(events: AgentEvent[], keep: (e: AgentEvent) => boolean, limit: number): LogLine[] {
  const lines: LogLine[] = []
  for (let i = events.length - 1; i >= 0 && lines.length < limit; i -= 1) {
    const event = events[i]
    if (keep(event)) lines.push({ seq: event.seq, ts: event.ts, text: describeEvent(event) })
  }
  return lines.reverse()
}

export function elapsedMs(mission: Mission, now: number): number | null {
  if (!mission.started_at) return null
  const end = mission.finished_at ? Date.parse(mission.finished_at) : now
  return Math.max(0, end - Date.parse(mission.started_at))
}

export function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`
}

export const formatUsd = (usd: number): string => `$${usd.toFixed(usd < 1 ? 3 : 2)}`
