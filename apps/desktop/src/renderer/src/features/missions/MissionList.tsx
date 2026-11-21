import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import type { ApiClient } from '../../lib/api'
import { isOpenPlanning, PLANNING_LABEL, PLANNING_TONE, planningState } from './planning'
import { statusLabel, statusTone } from './progress'
import type { Mission, ScopingSession } from './types'

interface Props {
  api: ApiClient
  projectId: string | null
  selectedId: string | null
  /** Changes when a mission was created or changed, to reload the list. */
  refreshKey: number
  onSelect: (missionId: string) => void
  /** Ideas the PM is still planning, so they never disappear from view. */
  selectedPlanningId?: string | null
  onSelectPlanning?: (scopingId: string) => void
  onNew: () => void
}

const PLANNING_POLL_MS = 4000

export function MissionList({ api, projectId, selectedId, refreshKey, onSelect, selectedPlanningId, onSelectPlanning, onNew }: Props) {
  const [missions, setMissions] = useState<Mission[] | null>(null)
  const [planning, setPlanning] = useState<ScopingSession[]>([])
  const [reload, setReload] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setMissions(null)
    setError(null)
    if (!projectId) return
    let cancelled = false
    api
      .get<Mission[]>('/missions', { project_id: projectId })
      .then((list) => {
        if (!cancelled) setMissions(list)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [api, projectId, refreshKey, reload])

  // Ideas being planned. Polled, because the PM answers in the background and a plan that
  // turns into a mission must move from this group to the missions below.
  useEffect(() => {
    setPlanning([])
    if (!projectId) return
    let live = true
    let started = false
    const load = () =>
      api
        .get<ScopingSession[]>('/scoping', { project_id: projectId })
        .then((list) => {
          if (!live) return
          const open = list.filter(isOpenPlanning)
          setPlanning((before) => {
            // one left planning (it became a mission): reload the missions too
            if (started && before.length > open.length) setReload((n) => n + 1)
            return open
          })
          started = true
        })
        .catch(() => {})
    void load()
    const timer = window.setInterval(load, PLANNING_POLL_MS)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [api, projectId, refreshKey])

  if (!projectId) return <EmptyState title="Open a workspace to start a mission" />
  return (
    <div className="mission-list">
      <button type="button" className="button button--small mission-list__new" onClick={onNew}>
        <Plus size={14} aria-hidden="true" /> New mission
      </button>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {planning.length > 0 && (
        <>
          <h3 className="mission-list__group">Being planned</h3>
          <ul className="mission-list__items" aria-label="Ideas being planned">
            {planning.map((session) => {
              const state = planningState(session)
              return (
                <li key={session.id}>
                  <button
                    type="button"
                    className="mission-list__item"
                    aria-current={session.id === selectedPlanningId ? 'true' : undefined}
                    onClick={() => onSelectPlanning?.(session.id)}
                  >
                    <span className="mission-list__title">{session.idea}</span>
                    <span className="status-pill" data-tone={PLANNING_TONE[state]}>
                      <span className="status-dot" aria-hidden="true" />
                      {PLANNING_LABEL[state]}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          {missions && missions.length > 0 && <h3 className="mission-list__group">Missions</h3>}
        </>
      )}
      {missions && missions.length === 0 && planning.length === 0 && <EmptyState title="No missions yet" />}
      <ul className="mission-list__items" aria-label="Missions">
        {(missions ?? []).map((mission) => (
          <li key={mission.id}>
            <button
              type="button"
              className="mission-list__item"
              aria-current={mission.id === selectedId ? 'true' : undefined}
              onClick={() => onSelect(mission.id)}
            >
              <span className="mission-list__title">{mission.title}</span>
              <span className="status-pill" data-tone={statusTone(mission.status)}>
                <span className="status-dot" aria-hidden="true" />
                {statusLabel(mission.status)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
