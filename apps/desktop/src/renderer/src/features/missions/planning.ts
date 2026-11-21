import type { ScopingSession } from './types'

/** Where an idea is before it becomes a mission: the PM is working on it, waiting for your
 * answers, has a plan for you to review, or stopped with an error. */
export type PlanningState = 'thinking' | 'asking' | 'planned' | 'failed'

export function planningState(session: ScopingSession): PlanningState {
  if (session.status === 'planned') return 'planned'
  if (session.error) return 'failed'
  const last = session.messages[session.messages.length - 1]
  return !last || last.role === 'user' ? 'thinking' : 'asking'
}

export const PLANNING_LABEL: Record<PlanningState, string> = {
  thinking: 'PM is planning…',
  asking: 'Waiting for your answers',
  planned: 'Plan ready to review',
  failed: 'Stopped: open to retry'
}

export const PLANNING_TONE: Record<PlanningState, string> = {
  thinking: 'active',
  asking: 'warning',
  planned: 'warning',
  failed: 'danger'
}

/** Ideas still being planned: not started as a mission and not abandoned. */
export function isOpenPlanning(session: ScopingSession): boolean {
  return (session.status === 'asking' || session.status === 'planned') && !session.mission_id
}
