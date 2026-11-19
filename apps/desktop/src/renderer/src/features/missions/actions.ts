import { ApiError, type ApiClient } from '../../lib/api'
import type { Mission } from './types'

export type MissionAction = 'approve' | 'pause' | 'resume' | 'stop' | 'keep' | 'discard' | 'revert'

export const postAction = (api: ApiClient, missionId: string, action: MissionAction): Promise<Mission> =>
  api.post<Mission>(`/missions/${missionId}/${action}`)

export interface ApplyOptions {
  include_mission_files: boolean
  commit: boolean
}

export const applyMission = (api: ApiClient, missionId: string, options: ApplyOptions): Promise<Mission> =>
  api.post<Mission>(`/missions/${missionId}/apply`, options)

export const restoreCheckpoint = (api: ApiClient, missionId: string, commit: string): Promise<Mission> =>
  api.post<Mission>(`/missions/${missionId}/checkpoints/${commit}/restore`)

export const answerNeed = (
  api: ApiClient,
  needId: string,
  action: string,
  budgetUsd?: number
): Promise<Mission> =>
  api.post<Mission>(`/needs/${needId}/answer`, { action, budget_usd: budgetUsd })

export interface ErrorText {
  message: string
  /** Files the backend named (a stale-file conflict), if any. */
  paths: string[]
}

/** Turn what the backend sent back into something a person can read. */
export function describeError(err: unknown): ErrorText {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') return { message: detail, paths: [] }
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const { message, paths } = detail as { message?: unknown; paths?: unknown }
      return {
        message: typeof message === 'string' ? message : err.message,
        paths: Array.isArray(paths) ? paths.map(String) : []
      }
    }
    if (Array.isArray(detail)) {
      // FastAPI validation errors: [{loc: [...], msg: '...'}]
      const lines = detail.slice(0, 3).map((item) => {
        const { loc, msg } = item as { loc?: unknown[]; msg?: string }
        const where = (loc ?? []).filter((part) => part !== 'body').join(' › ')
        return where ? `${where}: ${msg}` : String(msg)
      })
      return { message: lines.join('; '), paths: [] }
    }
    return { message: err.message, paths: [] }
  }
  return { message: err instanceof Error ? err.message : String(err), paths: [] }
}
