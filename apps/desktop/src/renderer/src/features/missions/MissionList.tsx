import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import type { ApiClient } from '../../lib/api'
import { statusLabel, statusTone } from './progress'
import type { Mission } from './types'

interface Props {
  api: ApiClient
  projectId: string | null
  selectedId: string | null
  /** Changes when a mission was created or changed, to reload the list. */
  refreshKey: number
  onSelect: (missionId: string) => void
  onNew: () => void
}

export function MissionList({ api, projectId, selectedId, refreshKey, onSelect, onNew }: Props) {
  const [missions, setMissions] = useState<Mission[] | null>(null)
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
      {missions && missions.length === 0 && <EmptyState title="No missions yet" />}
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
