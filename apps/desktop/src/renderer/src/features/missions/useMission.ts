import { useCallback, useEffect, useRef, useState } from 'react'

import type { BackendConfig } from '../../../../preload/api'
import type { AgentEvent } from '../../generated/events'
import type { ApiClient } from '../../lib/api'
import { isMissionEvent } from './progress'
import { MissionStream, type StreamState } from './stream'
import type { Checkpoint, Mission, Need } from './types'

const REFRESH_MS = 300

export interface MissionView {
  mission: Mission | null
  events: AgentEvent[]
  needs: Need[]
  checkpoints: Checkpoint[]
  connection: { state: StreamState; detail?: string }
  error: string | null
  /** Replace the mission with a fresher copy (an action's response) and reload its lists. */
  adopt(mission: Mission): void
}

/**
 * A mission's live state. The stream delivers the snapshot and every event as it happens; when a
 * mission-level event arrives (a status, feature, handoff, checkpoint or Needs-you change) the
 * authoritative state (spend, Needs you, checkpoints) is fetched once, shortly after. Nothing here
 * polls.
 */
export function useMission(api: ApiClient, config: BackendConfig, missionId: string | null): MissionView {
  const [mission, setMission] = useState<Mission | null>(null)
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [needs, setNeeds] = useState<Need[]>([])
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([])
  const [connection, setConnection] = useState<MissionView['connection']>({ state: 'connecting' })
  const [error, setError] = useState<string | null>(null)
  const refreshRef = useRef<() => void>(() => undefined)

  useEffect(() => {
    // Reset without creating new references when there is nothing to clear, so an unstable
    // `api` can never turn this effect into a render loop.
    setMission(null)
    setEvents((known) => (known.length === 0 ? known : []))
    setNeeds((known) => (known.length === 0 ? known : []))
    setCheckpoints((known) => (known.length === 0 ? known : []))
    setError(null)
    setConnection((known) => (known.state === 'connecting' && !known.detail ? known : { state: 'connecting' }))
    if (!missionId) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const load = async () => {
      try {
        const [fresh, openNeeds, points] = await Promise.all([
          api.get<Mission>(`/missions/${missionId}`),
          api.get<Need[]>(`/missions/${missionId}/needs`),
          api.get<Checkpoint[]>(`/missions/${missionId}/checkpoints`)
        ])
        if (cancelled) return
        setMission(fresh)
        setNeeds(openNeeds.filter((n) => n.status === 'open'))
        setCheckpoints(points)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }
    const scheduleRefresh = () => {
      if (timer !== undefined) return
      timer = setTimeout(() => {
        timer = undefined
        void load()
      }, REFRESH_MS)
    }
    refreshRef.current = () => void load()

    const stream = new MissionStream({
      url: config.url,
      token: config.token,
      missionId,
      listener: {
        onSnapshot: (snapshot) => {
          setMission(snapshot)
          scheduleRefresh() // the snapshot has no Needs you or checkpoint lists
        },
        onEvents: (incoming) => {
          setEvents((known) => known.concat(incoming))
          if (incoming.some(isMissionEvent)) scheduleRefresh()
        },
        onState: (state, detail) => setConnection({ state, detail })
      }
    })
    stream.start()

    return () => {
      cancelled = true
      clearTimeout(timer)
      stream.stop()
    }
  }, [api, config.url, config.token, missionId])

  const adopt = useCallback((fresh: Mission) => {
    setMission(fresh)
    refreshRef.current()
  }, [])

  return { mission, events, needs, checkpoints, connection, error, adopt }
}
