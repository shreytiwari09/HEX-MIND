import { describe, expect, it } from 'vitest'

import type { AgentEvent } from '../../generated/events'
import {
  MissionStream,
  NOT_FOUND,
  UNAUTHORIZED,
  streamUrl,
  type SocketLike,
  type StreamListener,
  type StreamState
} from './stream'
import type { Mission } from './types'

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null
  onmessage: ((message: { data: unknown }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  sent: string[] = []
  closed = false
  constructor(readonly url: string) {}
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.closed = true
  }
  open() {
    this.onopen?.()
  }
  receive(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
  drop(code = 1006) {
    this.onclose?.({ code })
  }
}

const MISSION = { id: 'm1', title: 'Todo app', status: 'running', milestones: [] } as unknown as Mission

function event(seq: number): AgentEvent {
  return {
    schema_version: 8,
    event_id: `e${seq}`,
    run_id: 'r1',
    seq,
    ts: '2026-11-19T10:00:00Z',
    type: 'checkpoint_created',
    agent_id: null,
    task_id: null,
    payload: { commit: `c${seq}`, label: `f${seq}`, feature_id: null }
  }
}

function setup() {
  const sockets: FakeSocket[] = []
  const timers: { fn: () => void; ms: number; cancelled: boolean }[] = []
  const snapshots: Mission[] = []
  const batches: number[][] = []
  const states: [StreamState, string | undefined][] = []
  const listener: StreamListener = {
    onSnapshot: (mission) => snapshots.push(mission),
    onEvents: (events) => batches.push(events.map((e) => e.seq)),
    onState: (state, detail) => states.push([state, detail])
  }
  const stream = new MissionStream({
    url: 'http://127.0.0.1:8765',
    token: 'secret-token',
    missionId: 'm1',
    listener,
    createSocket: (url) => {
      const socket = new FakeSocket(url)
      sockets.push(socket)
      return socket
    },
    setTimer: (fn, ms) => {
      const timer = { fn, ms, cancelled: false }
      timers.push(timer)
      return timer
    },
    clearTimer: (handle) => {
      ;(handle as { cancelled: boolean }).cancelled = true
    }
  })
  const fire = () => {
    const due = timers.filter((t) => !t.cancelled)
    timers.length = 0
    due.forEach((t) => t.fn())
  }
  const lastState = () => states[states.length - 1]
  return { stream, sockets, timers, snapshots, batches, states, fire, lastState }
}

describe('streamUrl', () => {
  it('uses ws(s) and carries the resume position, never the token', () => {
    expect(streamUrl('http://127.0.0.1:8765', 'm1', 7)).toBe('ws://127.0.0.1:8765/ws/missions/m1?after_seq=7')
    expect(streamUrl('https://example.test', 'm1', 0)).toBe('wss://example.test/ws/missions/m1?after_seq=0')
  })
})

describe('MissionStream', () => {
  it('sends the token as its first frame, then reports the snapshot and batches events', () => {
    const t = setup()
    t.stream.start()
    const [socket] = t.sockets
    expect(socket.url).toBe('ws://127.0.0.1:8765/ws/missions/m1?after_seq=0')
    expect(t.lastState()).toEqual(['connecting', undefined])
    expect(socket.sent).toEqual([])
    socket.open()
    expect(socket.sent.map((s) => JSON.parse(s))).toEqual([{ type: 'auth', token: 'secret-token' }])

    socket.receive({ type: 'snapshot', mission: MISSION, last_seq: 3 })
    for (const seq of [1, 2, 3]) socket.receive({ type: 'event', event: event(seq) })

    expect(t.snapshots).toEqual([MISSION])
    expect(t.lastState()).toEqual(['live', undefined])
    expect(t.batches).toEqual([]) // buffered until the flush timer
    t.fire()
    expect(t.batches).toEqual([[1, 2, 3]]) // one delivery for the whole replay
    expect(t.stream.contiguousSeq).toBe(3)
  })

  it('ignores a replayed duplicate', () => {
    const t = setup()
    t.stream.start()
    const [socket] = t.sockets
    socket.receive({ type: 'event', event: event(1) })
    socket.receive({ type: 'event', event: event(1) })
    socket.receive({ type: 'event', event: event(2) })
    t.fire()
    expect(t.batches).toEqual([[1, 2]])
  })

  it('reconnects from the last event it has after a disconnect, with a growing delay', () => {
    const t = setup()
    t.stream.start()
    t.sockets[0].receive({ type: 'event', event: event(1) })
    t.sockets[0].receive({ type: 'event', event: event(2) })
    t.sockets[0].drop()
    expect(t.lastState()).toEqual(['reconnecting', undefined])
    expect(t.batches).toEqual([[1, 2]]) // what arrived is delivered, not lost

    const first = t.timers.filter((x) => !x.cancelled).at(-1)!
    expect(first.ms).toBe(500)
    t.fire()
    expect(t.sockets[1].url).toContain('after_seq=2')
    t.sockets[1].drop()
    expect(t.timers.filter((x) => !x.cancelled).at(-1)!.ms).toBe(1000)
    t.fire()
    expect(t.sockets[2].url).toContain('after_seq=2')

    // A snapshot means the link works again: the delay starts over.
    t.sockets[2].receive({ type: 'snapshot', mission: MISSION, last_seq: 2 })
    t.sockets[2].drop()
    expect(t.timers.filter((x) => !x.cancelled).at(-1)!.ms).toBe(500)
  })

  it('treats a missing event as lost frames: drops the link and resumes after the last good one', () => {
    const t = setup()
    t.stream.start()
    const [socket] = t.sockets
    socket.receive({ type: 'event', event: event(1) })
    socket.receive({ type: 'event', event: event(3) }) // seq 2 never arrived

    expect(socket.closed).toBe(true)
    expect(t.batches).toEqual([[1]]) // the event before the gap is kept, the one after is not
    t.fire()
    expect(t.sockets[1].url).toContain('after_seq=1')
    t.sockets[1].receive({ type: 'event', event: event(2) })
    t.sockets[1].receive({ type: 'event', event: event(3) })
    t.fire()
    expect(t.batches).toEqual([[1], [2, 3]])
  })

  it.each([
    [UNAUTHORIZED, 'The backend rejected the token.'],
    [NOT_FOUND, 'This mission no longer exists.']
  ])('stops for good on close code %i', (code, detail) => {
    const t = setup()
    t.stream.start()
    t.sockets[0].drop(code)
    expect(t.lastState()).toEqual(['closed', detail])
    t.fire()
    expect(t.sockets).toHaveLength(1) // no retry
  })

  it('stop() closes the socket and never reconnects or delivers late events', () => {
    const t = setup()
    t.stream.start()
    const [socket] = t.sockets
    socket.receive({ type: 'event', event: event(1) })
    t.stream.stop()
    expect(socket.closed).toBe(true)
    socket.receive({ type: 'event', event: event(2) })
    socket.drop()
    t.fire()
    expect(t.sockets).toHaveLength(1)
    expect(t.batches).toEqual([])
  })

  it('ignores frames it cannot parse', () => {
    const t = setup()
    t.stream.start()
    t.sockets[0].onmessage?.({ data: 'not json' })
    t.sockets[0].onmessage?.({ data: new ArrayBuffer(2) })
    t.sockets[0].receive({ type: 'event', event: event(1) })
    t.fire()
    expect(t.batches).toEqual([[1]])
  })
})
