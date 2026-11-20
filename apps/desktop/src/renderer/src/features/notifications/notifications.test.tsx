import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '../../lib/api'
import { bodyFromNeeds, noticesFor, statusesOf } from './notices'
import { NotificationsPanel } from './NotificationsPanel'
import { POLL_MS, notificationsEnabled, setNotificationsEnabled, useMissionNotifications } from './useMissionNotifications'

const m = (id: string, status: string, title = `Mission ${id}`) => ({ id, status, title }) as never

describe('noticesFor', () => {
  it('is silent the first time it looks, so opening the app never replays old news', () => {
    expect(noticesFor(null, [m('a', 'needs_user'), m('b', 'completed')])).toEqual([])
  })

  it('reports a mission that now needs you, finished or failed', () => {
    const before = statusesOf([m('a', 'running'), m('b', 'running'), m('c', 'running'), m('d', 'running')])

    const news = noticesFor(before, [m('a', 'needs_user'), m('b', 'completed'), m('c', 'failed'), m('d', 'paused')])

    expect(news.map((n) => [n.missionId, n.kind])).toEqual([
      ['a', 'needs_you'],
      ['b', 'finished'],
      ['c', 'failed']
    ])
    expect(news[0].title).toBe('Mission a needs you')
  })

  it('ignores missions whose status did not change, ones it has not seen, and quiet changes', () => {
    const before = statusesOf([m('a', 'needs_user'), m('b', 'running')])

    expect(noticesFor(before, [m('a', 'needs_user'), m('b', 'paused'), m('new', 'completed')])).toEqual([])
  })

  it('tells you again when it needs you a second time', () => {
    let seen = statusesOf([m('a', 'running')])
    expect(noticesFor(seen, [m('a', 'needs_user')])).toHaveLength(1)
    seen = statusesOf([m('a', 'needs_user')])
    expect(noticesFor(seen, [m('a', 'running')])).toEqual([]) // you answered
    seen = statusesOf([m('a', 'running')])
    expect(noticesFor(seen, [m('a', 'needs_user')])).toHaveLength(1)
  })

  it('uses the open need as the message', () => {
    expect(bodyFromNeeds([{ status: 'answered', summary: 'old' }, { status: 'open', summary: 'The budget is spent.' }], 'x')).toBe('The budget is spent.')
    expect(bodyFromNeeds([], 'fallback')).toBe('fallback')
    expect(bodyFromNeeds([{ status: 'open', summary: '' }], 'fallback')).toBe('fallback')
  })
})

describe('useMissionNotifications', () => {
  const shown: { title: string; options: NotificationOptions; onclick: (() => void) | null }[] = []

  beforeEach(() => {
    vi.useFakeTimers()
    shown.length = 0
    class FakeNotification {
      static permission: NotificationPermission = 'granted'
      static requestPermission = vi.fn(async () => 'granted' as NotificationPermission)
      onclick: (() => void) | null = null
      constructor(public title: string, public options: NotificationOptions) {
        shown.push(this)
      }
    }
    vi.stubGlobal('Notification', FakeNotification)
    vi.spyOn(document, 'hasFocus').mockReturnValue(false)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function makeApi(lists: unknown[][], needs: unknown[] = []) {
    let call = 0
    return {
      get: vi.fn(async (path: string) => {
        if (path.endsWith('/needs')) return needs
        return lists[Math.min(call++, lists.length - 1)]
      })
    } as unknown as ApiClient & { get: ReturnType<typeof vi.fn> }
  }

  const tick = async () => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS)
    })
  }

  it('notifies when a mission starts needing you, with what is being asked, and opens it on click', async () => {
    const api = makeApi([[m('a', 'running')], [m('a', 'needs_user')]], [{ status: 'open', summary: 'The budget is spent.' }])
    const onOpen = vi.fn()
    renderHook(() => useMissionNotifications({ api, projectId: 'p1', enabled: true, viewingMissionId: null, onOpen }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(shown).toHaveLength(0) // the first look is not news

    await tick()

    expect(shown).toHaveLength(1)
    expect(shown[0].title).toBe('Mission a needs you')
    expect(shown[0].options.body).toBe('The budget is spent.')
    shown[0].onclick?.()
    expect(onOpen).toHaveBeenCalledWith('a')
  })

  it('does not interrupt you about the mission you are looking at', async () => {
    vi.spyOn(document, 'hasFocus').mockReturnValue(true)
    const api = makeApi([[m('a', 'running')], [m('a', 'completed')]])
    renderHook(() => useMissionNotifications({ api, projectId: 'p1', enabled: true, viewingMissionId: 'a', onOpen: vi.fn() }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    await tick()

    expect(shown).toHaveLength(0)
  })

  it('does nothing when it is off, there is no project, or permission was not given', async () => {
    const api = makeApi([[m('a', 'running')], [m('a', 'needs_user')]])
    renderHook(() => useMissionNotifications({ api, projectId: 'p1', enabled: false, viewingMissionId: null, onOpen: vi.fn() }))
    renderHook(() => useMissionNotifications({ api, projectId: null, enabled: true, viewingMissionId: null, onOpen: vi.fn() }))
    ;(Notification as unknown as { permission: string }).permission = 'denied'
    renderHook(() => useMissionNotifications({ api, projectId: 'p1', enabled: true, viewingMissionId: null, onOpen: vi.fn() }))

    await tick()
    await tick()

    expect(api.get).not.toHaveBeenCalled()
    expect(shown).toHaveLength(0)
  })

  it('keeps going when the backend is briefly unreachable, and stops when unmounted', async () => {
    let calls = 0
    const api = {
      get: vi.fn(async () => {
        calls += 1
        if (calls === 2) throw new Error('restarting')
        return calls === 1 ? [m('a', 'running')] : [m('a', 'failed')]
      })
    } as unknown as ApiClient & { get: ReturnType<typeof vi.fn> }
    const { unmount } = renderHook(() => useMissionNotifications({ api, projectId: 'p1', enabled: true, viewingMissionId: null, onOpen: vi.fn() }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    await tick() // fails quietly
    await tick() // recovers and reports

    expect(shown.map((n) => n.title)).toEqual(['Mission a failed'])
    unmount()
    const before = api.get.mock.calls.length
    await tick()
    expect(api.get.mock.calls.length).toBe(before)
  })
})

describe('NotificationsPanel', () => {
  beforeEach(() => {
    window.localStorage.clear()
    class FakeNotification {
      static permission: NotificationPermission = 'default'
      static requestPermission = vi.fn(async () => {
        FakeNotification.permission = 'granted'
        return 'granted' as NotificationPermission
      })
    }
    vi.stubGlobal('Notification', FakeNotification)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('asks for permission when turned on, remembers the choice and tells the app', async () => {
    const onChange = vi.fn()
    render(<NotificationsPanel onChange={onChange} />)
    const box = screen.getByRole('checkbox', { name: 'Tell me about my missions' })
    expect(box).not.toBeChecked()

    fireEvent.click(box)

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(true))
    expect(box).toBeChecked()
    expect(notificationsEnabled()).toBe(true)
    fireEvent.click(box)
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(false))
    expect(notificationsEnabled()).toBe(false)
  })

  it('stays off and explains when the system blocks notifications', async () => {
    ;(Notification as unknown as { permission: string; requestPermission: () => Promise<string> }).permission = 'denied'
    const onChange = vi.fn()
    render(<NotificationsPanel onChange={onChange} />)

    fireEvent.click(screen.getByRole('checkbox'))

    expect(await screen.findByRole('alert')).toHaveTextContent('blocked')
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })

  it('says so when the system cannot show notifications at all', () => {
    vi.stubGlobal('Notification', undefined)

    render(<NotificationsPanel onChange={vi.fn()} />)

    expect(screen.getByRole('checkbox')).toBeDisabled()
    expect(screen.getByText(/cannot show notifications/)).toBeInTheDocument()
  })

  it('reads and writes the setting safely even when storage is unavailable', () => {
    const broken = { getItem: () => { throw new Error('no') }, setItem: () => { throw new Error('no') } }
    vi.stubGlobal('localStorage', broken)

    expect(notificationsEnabled()).toBe(false)
    expect(() => setNotificationsEnabled(true)).not.toThrow()
  })
})
