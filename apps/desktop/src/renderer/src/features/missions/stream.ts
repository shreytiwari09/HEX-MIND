import type { AgentEvent } from '../../generated/events'
import type { Mission } from './types'

/**
 * Client for the backend's mission stream (`/ws/missions/{id}`, see apps/backend/app/api/stream.py).
 *
 * Protocol: the first frame we send is `{type: 'auth', token}`. The server answers with a
 * snapshot, then every event of the mission's run in `seq` order, with no gaps. This client
 * checks that: an event whose `seq` is not the next one means frames were lost, so it
 * reconnects and asks to resume after the last event it has. After any disconnect it reconnects
 * the same way, with a growing delay. Codes 4401 (bad token) and 4404 (no such mission) are final.
 */

export type StreamState = 'connecting' | 'live' | 'reconnecting' | 'closed'

export interface StreamListener {
  onSnapshot(mission: Mission): void
  onEvents(events: AgentEvent[]): void
  onState(state: StreamState, detail?: string): void
}

/** The part of the browser WebSocket this client uses (tests pass a fake). */
export interface SocketLike {
  onopen: (() => void) | null
  onmessage: ((message: { data: unknown }) => void) | null
  onclose: ((event: { code: number }) => void) | null
  send(data: string): void
  close(): void
}

export interface StreamOptions {
  /** Backend base URL, e.g. `http://127.0.0.1:8765`. */
  url: string
  token: string | null
  missionId: string
  listener: StreamListener
  createSocket?: (url: string) => SocketLike
  setTimer?: (fn: () => void, ms: number) => unknown
  clearTimer?: (handle: unknown) => void
}

export const UNAUTHORIZED = 4401
export const NOT_FOUND = 4404
const MIN_DELAY_MS = 500
const MAX_DELAY_MS = 10_000
const FLUSH_MS = 16

export function streamUrl(base: string, missionId: string, afterSeq: number): string {
  const url = new URL(`/ws/missions/${missionId}`, base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('after_seq', String(afterSeq))
  return url.toString()
}

export class MissionStream {
  private socket: SocketLike | null = null
  private lastSeq = 0
  private attempt = 0
  private stopped = false
  private timer: unknown = null
  private flushTimer: unknown = null
  private buffer: AgentEvent[] = []

  private readonly createSocket: (url: string) => SocketLike
  private readonly setTimer: (fn: () => void, ms: number) => unknown
  private readonly clearTimer: (handle: unknown) => void

  constructor(private readonly options: StreamOptions) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike)
    this.setTimer = options.setTimer ?? ((fn, ms) => setTimeout(fn, ms))
    this.clearTimer = options.clearTimer ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>))
  }

  start(): void {
    this.stopped = false
    this.connect()
  }

  stop(): void {
    this.stopped = true
    this.cancel(this.timer)
    this.cancel(this.flushTimer)
    this.timer = this.flushTimer = null
    this.buffer = []
    const socket = this.socket
    this.socket = null
    if (socket) {
      socket.onclose = socket.onmessage = socket.onopen = null
      socket.close()
    }
  }

  /** The highest `seq` received with no gap before it. */
  get contiguousSeq(): number {
    return this.lastSeq
  }

  private cancel(handle: unknown) {
    if (handle !== null) this.clearTimer(handle)
  }

  private connect(): void {
    const { url, missionId, token, listener } = this.options
    listener.onState(this.attempt === 0 && this.lastSeq === 0 ? 'connecting' : 'reconnecting')
    const socket = this.createSocket(streamUrl(url, missionId, this.lastSeq))
    this.socket = socket
    socket.onopen = () => socket.send(JSON.stringify({ type: 'auth', token }))
    socket.onmessage = (message) => this.receive(socket, message.data)
    socket.onclose = (event) => this.closed(socket, event.code)
  }

  private receive(socket: SocketLike, data: unknown): void {
    if (socket !== this.socket || typeof data !== 'string') return
    let frame: { type?: string; mission?: Mission; event?: AgentEvent }
    try {
      frame = JSON.parse(data)
    } catch {
      return
    }
    if (frame.type === 'snapshot' && frame.mission) {
      this.attempt = 0
      this.options.listener.onSnapshot(frame.mission)
      this.options.listener.onState('live')
    } else if (frame.type === 'event' && frame.event) {
      const { seq } = frame.event
      if (seq <= this.lastSeq) return // a replayed duplicate
      if (seq !== this.lastSeq + 1) {
        // Frames were lost: start over from the last event we have.
        this.dropSocket(socket)
        this.scheduleReconnect()
        return
      }
      this.lastSeq = seq
      this.buffer.push(frame.event)
      if (this.flushTimer === null) this.flushTimer = this.setTimer(() => this.flush(), FLUSH_MS)
    }
  }

  /** Deliver events in batches so replaying a long history is one render, not thousands. */
  private flush(): void {
    this.flushTimer = null
    if (this.buffer.length === 0) return
    const events = this.buffer
    this.buffer = []
    this.options.listener.onEvents(events)
  }

  private closed(socket: SocketLike, code: number): void {
    if (socket !== this.socket || this.stopped) return
    this.socket = null
    if (code === UNAUTHORIZED || code === NOT_FOUND) {
      this.flush()
      this.options.listener.onState(
        'closed',
        code === UNAUTHORIZED ? 'The backend rejected the token.' : 'This mission no longer exists.'
      )
      return
    }
    this.scheduleReconnect()
  }

  private dropSocket(socket: SocketLike): void {
    this.socket = null
    socket.onclose = socket.onmessage = socket.onopen = null
    socket.close()
  }

  private scheduleReconnect(): void {
    this.flush()
    this.options.listener.onState('reconnecting')
    const delay = Math.min(MIN_DELAY_MS * 2 ** this.attempt, MAX_DELAY_MS)
    this.attempt += 1
    this.timer = this.setTimer(() => {
      this.timer = null
      if (!this.stopped) this.connect()
    }, delay)
  }
}
