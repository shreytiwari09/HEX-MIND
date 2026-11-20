import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { barOf, formatMs, TracePanel, type Span } from './TracePanel'

const span = (extra: Partial<Span>): Span => ({
  trace_id: 't',
  span_id: 's',
  parent_span_id: null,
  name: 'span',
  kind: 'other',
  depth: 0,
  offset_ms: 0,
  duration_ms: 10,
  status: 'ok',
  status_message: null,
  attributes: {},
  ...extra
})

const TRACE = {
  run_id: 'r1',
  traces: 1,
  duration_ms: 900,
  truncated: false,
  spans: [
    span({ span_id: 'a', name: 'invoke_agent mission_runner', kind: 'agent', duration_ms: 900 }),
    span({ span_id: 'b', name: 'crewai.crew backend_01', kind: 'crew', depth: 1, offset_ms: 100, duration_ms: 700 }),
    span({ span_id: 'c', name: 'call_llm', kind: 'model', depth: 2, offset_ms: 150, duration_ms: 450, attributes: { 'gen_ai.request.model': 'gpt-5' } }),
    span({ span_id: 'd', name: 'execute_tool write_file', kind: 'tool', depth: 3, offset_ms: 300, duration_ms: 1250, status: 'error', status_message: 'EROFS' })
  ]
}

function makeApi(answer: unknown) {
  return {
    get: vi.fn(async () => {
      if (answer instanceof Error) throw answer
      return answer
    })
  } as unknown as ApiClient & { get: ReturnType<typeof vi.fn> }
}

describe('barOf and formatMs', () => {
  it('places a bar within the trace and keeps a very short span visible', () => {
    const bar = barOf({ offset_ms: 150, duration_ms: 450 }, 900)
    expect(bar.left).toBeCloseTo(16.667, 2)
    expect(bar.width).toBe(50)
    expect(barOf({ offset_ms: 0, duration_ms: 0.01 }, 900).width).toBe(0.6)
    const end = barOf({ offset_ms: 890, duration_ms: 500 }, 900)
    expect(end.left + end.width).toBeCloseTo(100, 5) // never past the end of the trace
    expect(barOf({ offset_ms: 5, duration_ms: 5 }, 0)).toEqual({ left: 0, width: 100 })
  })

  it('writes durations a person can read', () => {
    expect(formatMs(3.14159)).toBe('3.1 ms')
    expect(formatMs(450)).toBe('450 ms')
    expect(formatMs(1250)).toBe('1.25 s')
  })
})

describe('TracePanel', () => {
  it('shows the spans as a tree with their kinds, indentation and timings', async () => {
    const api = makeApi(TRACE)
    render(<TracePanel api={api} runId="r1" />)

    const rows = await screen.findByRole('list', { name: 'Spans' })
    expect(within(rows).getAllByRole('listitem')).toHaveLength(4)
    expect(screen.getByText(/4 spans in 1 trace · 900 ms/)).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/traces', { run_id: 'r1' })
    const names = within(rows).getAllByText(/invoke_agent|crewai|call_llm|execute_tool/, { selector: '.trace__name' })
    expect(names.map((n) => (n as HTMLElement).style.paddingLeft)).toEqual(['0px', '14px', '28px', '42px'])
    expect(within(rows).getAllByRole('listitem')[3]).toHaveAttribute('data-status', 'error')
  })

  it('opens a span to show its stored attributes and its status', async () => {
    render(<TracePanel api={makeApi(TRACE)} runId="r1" />)
    fireEvent.click(await screen.findByRole('button', { name: /call_llm/ }))

    const details = screen.getByLabelText('Details of call_llm')
    expect(within(details).getByText('gen_ai.request.model')).toBeInTheDocument()
    expect(within(details).getByText('gpt-5')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /execute_tool write_file/ }))
    expect(screen.getByLabelText('Details of execute_tool write_file')).toHaveTextContent('error: EROFS')
  })

  it('hides a kind of span when you untick it', async () => {
    render(<TracePanel api={makeApi(TRACE)} runId="r1" />)
    await screen.findByRole('list', { name: 'Spans' })

    fireEvent.click(screen.getByRole('checkbox', { name: 'tool' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'model' }))

    const rows = screen.getByRole('list', { name: 'Spans' })
    expect(within(rows).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: /call_llm/ })).toBeNull()
    fireEvent.click(screen.getByRole('checkbox', { name: 'tool' }))
    expect(screen.getByRole('button', { name: /execute_tool/ })).toBeInTheDocument()
  })

  it('says when nothing was stored, when the trace was cut short, and when it cannot load', async () => {
    const { unmount } = render(<TracePanel api={makeApi({ ...TRACE, spans: [], traces: 0, duration_ms: 0 })} runId="r1" />)
    expect(await screen.findByText('No spans were stored for this run yet.')).toBeInTheDocument()
    unmount()

    const cut = render(<TracePanel api={makeApi({ ...TRACE, truncated: true })} runId="r1" />)
    expect(await screen.findByText(/cut short/)).toBeInTheDocument()
    cut.unmount()

    render(<TracePanel api={makeApi(new ApiError(404, 'x', { detail: 'run not found' }))} runId="r1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('run not found')
  })

  it('loads again on Refresh', async () => {
    const api = makeApi(TRACE)
    render(<TracePanel api={api} runId="r1" />)
    await screen.findByRole('list', { name: 'Spans' })

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
  })
})
