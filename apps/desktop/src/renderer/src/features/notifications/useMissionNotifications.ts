import { useEffect, useRef } from 'react'

import type { ApiClient } from '../../lib/api'
import type { Mission, Need } from '../missions/types'
import { bodyFromNeeds, noticesFor, statusesOf, type Notice } from './notices'

const SETTING = 'hexmind.notifications'
export const POLL_MS = 8000

export function notificationsEnabled(): boolean {
  try {
    return window.localStorage.getItem(SETTING) === 'on'
  } catch {
    return false
  }
}

export function setNotificationsEnabled(on: boolean): void {
  try {
    window.localStorage.setItem(SETTING, on ? 'on' : 'off')
  } catch {
    // Not remembered; the toggle still works for this session.
  }
}

export type Permission = NotificationPermission | 'unsupported'

export const permission = (): Permission => (typeof Notification === 'undefined' ? 'unsupported' : Notification.permission)

export async function askPermission(): Promise<Permission> {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.permission === 'default' ? Notification.requestPermission() : Notification.permission
}

interface Options {
  api: ApiClient
  projectId: string | null
  enabled: boolean
  /** The mission on screen: no need to tell you about what you are looking at. */
  viewingMissionId: string | null
  onOpen: (missionId: string) => void
}

/** Native notifications when a mission needs you, finishes or fails (PRD P7). It looks at the
 * project's missions every few seconds, so it works for missions you are not viewing. */
export function useMissionNotifications({ api, projectId, enabled, viewingMissionId, onOpen }: Options): void {
  const seen = useRef<Record<string, string> | null>(null)
  const latest = useRef({ viewingMissionId, onOpen })
  latest.current = { viewingMissionId, onOpen }

  useEffect(() => {
    seen.current = null
    if (!enabled || !projectId || permission() !== 'granted') return
    let stopped = false

    const show = async (notice: Notice) => {
      const { viewingMissionId: viewing, onOpen: open } = latest.current
      if (viewing === notice.missionId && document.hasFocus()) return
      let body = notice.body
      if (notice.kind === 'needs_you') {
        try {
          body = bodyFromNeeds(await api.get<Need[]>(`/missions/${notice.missionId}/needs`), body)
        } catch {
          // The generic text is still true.
        }
      }
      const shown = new Notification(notice.title, { body, tag: `${notice.missionId}:${notice.kind}` })
      shown.onclick = () => {
        window.focus()
        open(notice.missionId)
      }
    }

    const look = async () => {
      try {
        const missions = await api.get<Mission[]>('/missions', { project_id: projectId })
        if (stopped || !Array.isArray(missions)) return
        const news = noticesFor(seen.current, missions)
        seen.current = statusesOf(missions)
        for (const notice of news) await show(notice)
      } catch {
        // The backend may be restarting: try again next time.
      }
    }

    void look()
    const timer = window.setInterval(() => void look(), POLL_MS)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [api, projectId, enabled])
}
