import type { Mission, Need } from '../missions/types'

export interface Notice {
  missionId: string
  title: string
  body: string
  /** needs_user: you must act. The others are for your information. */
  kind: 'needs_you' | 'finished' | 'failed'
}

type Statuses = Record<string, string>

export const statusesOf = (missions: Pick<Mission, 'id' | 'status'>[]): Statuses =>
  Object.fromEntries(missions.map((m) => [m.id, m.status]))

/**
 * What changed since the last look: a mission that now needs you, has finished, or has failed.
 * A mission seen for the first time, or whose status did not change, is not news, so opening the app
 * never replays old events.
 */
export function noticesFor(
  previous: Statuses | null,
  missions: Pick<Mission, 'id' | 'title' | 'status'>[]
): Notice[] {
  if (previous === null) return []
  const out: Notice[] = []
  for (const mission of missions) {
    const before = previous[mission.id]
    if (before === undefined || before === mission.status) continue
    if (mission.status === 'needs_user') {
      out.push({ missionId: mission.id, kind: 'needs_you', title: `${mission.title} needs you`, body: 'It stopped and is waiting for your decision.' })
    } else if (mission.status === 'completed') {
      out.push({ missionId: mission.id, kind: 'finished', title: `${mission.title} is finished`, body: 'The work is done and ready to review.' })
    } else if (mission.status === 'failed') {
      out.push({ missionId: mission.id, kind: 'failed', title: `${mission.title} failed`, body: 'It stopped and could not recover.' })
    }
  }
  return out
}

/** The text of the first open need, which says what is being asked of you. */
export const bodyFromNeeds = (needs: Pick<Need, 'status' | 'summary'>[], fallback: string): string =>
  needs.find((n) => n.status === 'open')?.summary || fallback
