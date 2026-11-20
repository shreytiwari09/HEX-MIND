import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { Bars } from './Bars'
import { barWidth, count, duration, percent, usd } from './format'
import { MetricsScope, MetricsView } from './MetricsView'
import type { Metrics } from './types'

const METRICS: Metrics = {
  missions: { count: 3, by_status: { completed: 2, failed: 1 }, avg_duration_s: 540 },
  calls: {
    count: 120,
    failed: 6,
    error_rate: 0.05,
    input_tokens: 45000,
    output_tokens: 9000,
    cost_usd: 1.5,
    without_cost: 4,
    avg_latency_ms: 900,
    p50_latency_ms: 700,
    p95_latency_ms: 2100
  },
  by_persona: [
    { persona: 'backend', calls: 80, failed: 5, input_tokens: 30000, output_tokens: 6000, cost_usd: 0.9, avg_latency_ms: 800 },
    { persona: 'frontend', calls: 40, failed: 1, input_tokens: 15000, output_tokens: 3000, cost_usd: 0.6, avg_latency_ms: 1100 },
    { persona: null, calls: 2, failed: 0, input_tokens: 10, output_tokens: 10, cost_usd: 0, avg_latency_ms: 50 }
  ],
  by_model: [{ provider: 'groq', model: 'llama', calls: 120, failed: 6, input_tokens: 45000, output_tokens: 9000, cost_usd: 1.5, avg_latency_ms: 900 }],
  by_variant: [
    { variant_id: 'terse', missions: 2, completed: 1, cost_usd: 0.7 },
    { variant_id: null, missions: 1, completed: 1, cost_usd: 0.8 }
  ],
  features: { by_status: { done: 7, failed: 1 }, attempts: 12, retried: 3, first_try_rate: 0.5 },
  process: { fallbacks: 2, key_rotations: 1, escalations: 3, budget_warnings: 0, guardrail_triggers: 3, needs_raised: 2, guardrails: { prompt_injection: 2, secret_scan: 1 } },
  validators: { milestones: 6, checks: 12, caught: 4, caught_and_fixed: 3, unavailable: 1, catch_rate: 0.3333, false_positive_rate: null },
  edit_format_compliance: null
}

function makeApi(answer: unknown) {
  return {
    get: vi.fn(async () => {
      if (answer instanceof Error) throw answer
      return answer
    })
  } as unknown as ApiClient & { get: ReturnType<typeof vi.fn> }
}

describe('formatting', () => {
  it('writes money with more precision for small amounts', () => {
    expect(usd(0.0123)).toBe('$0.012')
    expect(usd(2.5)).toBe('$2.50')
    expect(usd(0)).toBe('$0.000')
  })

  it('says "not measured" for a missing figure instead of a number', () => {
    expect(percent(null)).toBe('not measured')
    expect(percent(0.3333)).toBe('33%')
    expect(percent(0)).toBe('0%')
  })

  it('writes counts and durations a person can read', () => {
    expect(count(45000)).toBe('45,000')
    expect(duration(null)).toBe('n/a')
    expect(duration(45)).toBe('45 s')
    expect(duration(540)).toBe('9 min')
    expect(duration(7200)).toBe('2.0 h')
  })

  it('draws bars relative to the largest, and a small non-zero value still shows', () => {
    expect(barWidth(50, 100)).toBe(50)
    expect(barWidth(100, 100)).toBe(100)
    expect(barWidth(0.001, 100)).toBe(1.5)
    expect(barWidth(0, 100)).toBe(0)
    expect(barWidth(5, 0)).toBe(0)
  })
})

describe('Bars', () => {
  it('lists every value as text next to its bar, and says when there is nothing', () => {
    const { rerender } = render(<Bars title="Cost" rows={[{ label: 'a', value: 2, text: '$2.00', note: '3 calls' }, { label: 'b', value: 1, text: '$1.00' }]} />)

    const list = screen.getByRole('list')
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    expect(list).toHaveTextContent('a$2.00 3 calls')
    const bars = list.querySelectorAll<HTMLElement>('.bars__bar')
    expect(bars[0].style.width).toBe('100%')
    expect(bars[1].style.width).toBe('50%')

    rerender(<Bars title="Cost" rows={[]} empty="No calls." />)
    expect(screen.getByText('No calls.')).toBeInTheDocument()
  })
})

describe('MetricsView', () => {
  it('shows the headline numbers for the project', async () => {
    const api = makeApi(METRICS)
    render(<MetricsView api={api} projectId="p1" missionId={null} />)

    const region = await screen.findByRole('region', { name: 'Metrics' })
    const spent = screen.getByText('Spent').closest('.metrics__card') as HTMLElement
    expect(within(spent).getByText('$1.50')).toBeInTheDocument()
    expect(within(region).getByText('4 calls had no price')).toBeInTheDocument()
    expect(within(region).getByText('120')).toBeInTheDocument()
    expect(within(region).getByText('5% failed')).toBeInTheDocument()
    expect(within(region).getByText('54,000')).toBeInTheDocument()
    expect(within(region).getByText('700 ms')).toBeInTheDocument()
    expect(within(region).getByText('p95 2,100 ms')).toBeInTheDocument()
    expect(within(region).getByText('avg 9 min')).toBeInTheDocument()
    expect(within(region).getByText('50%')).toBeInTheDocument() // done first try
    expect(api.get).toHaveBeenCalledWith('/metrics', { project_id: 'p1' })
  })

  it('splits cost by team member and by model, most expensive first as the server sent it', async () => {
    render(<MetricsView api={makeApi(METRICS)} projectId="p1" missionId={null} />)

    const persona = await screen.findByRole('region', { name: 'Cost by team member' })
    expect(within(persona).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'backend$0.900 80 calls, 5 failed',
      'frontend$0.600 40 calls, 1 failed',
      'no persona$0.000 2 calls'
    ])
    expect(screen.getByRole('region', { name: 'Cost by model' })).toHaveTextContent('groq · llama$1.50 120 calls · avg 900 ms')
  })

  it('reports the process and what the validators found, and is honest about what it cannot measure', async () => {
    render(<MetricsView api={makeApi(METRICS)} projectId="p1" missionId={null} />)

    const process = await screen.findByRole('region', { name: 'Process' })
    expect(process).toHaveTextContent('Features retried3 of 8')
    expect(process).toHaveTextContent('Escalations to a stronger model3')
    expect(process).toHaveTextContent('Guardrail triggers3 · prompt_injection 2 · secret_scan 1')
    const validators = screen.getByRole('region', { name: 'Validators' })
    expect(validators).toHaveTextContent('Found something blocking4 (33%)')
    expect(validators).toHaveTextContent('…and it was then fixed3')
    expect(validators).toHaveTextContent('False-positive ratenot measured')
    expect(validators).toHaveTextContent('Edit-format compliancenot measured')
  })

  it('compares prompt variants only when one was used', async () => {
    const { unmount } = render(<MetricsView api={makeApi(METRICS)} projectId="p1" missionId={null} />)
    const variants = await screen.findByRole('region', { name: 'By prompt variant' })
    expect(within(variants).getByText(/1 of 2 missions completed/)).toBeInTheDocument()
    expect(within(variants).getByText('no variant')).toBeInTheDocument()
    unmount()

    render(<MetricsView api={makeApi({ ...METRICS, by_variant: [{ variant_id: null, missions: 3, completed: 2, cost_usd: 1 }] })} projectId="p1" missionId={null} />)
    await screen.findByRole('region', { name: 'Metrics' })
    expect(screen.queryByRole('region', { name: 'By prompt variant' })).toBeNull()
  })

  it('asks for one mission when one is chosen', async () => {
    const api = makeApi(METRICS)
    render(<MetricsView api={api} projectId="p1" missionId="m7" />)

    await screen.findByRole('region', { name: 'Metrics' })
    expect(api.get).toHaveBeenCalledWith('/metrics', { mission_id: 'm7' })
  })

  it('handles a project with no calls without inventing numbers', async () => {
    const empty: Metrics = {
      ...METRICS,
      missions: { count: 1, by_status: {}, avg_duration_s: null },
      calls: { ...METRICS.calls, count: 0, failed: 0, error_rate: null, input_tokens: 0, output_tokens: 0, cost_usd: 0, without_cost: 0, p50_latency_ms: null, p95_latency_ms: null },
      by_persona: [],
      by_model: [],
      features: { by_status: {}, attempts: 0, retried: 0, first_try_rate: null },
      validators: { ...METRICS.validators, checks: 0, caught: 0, caught_and_fixed: 0, unavailable: 0, catch_rate: null }
    }
    render(<MetricsView api={makeApi(empty)} projectId="p1" missionId={null} />)

    await screen.findByRole('region', { name: 'Metrics' })
    expect(screen.getAllByText('not measured').length).toBeGreaterThan(2)
    expect(screen.getAllByText('No model calls yet.')).toHaveLength(2)
    expect(screen.getByText('n/a')).toBeInTheDocument()
  })

  it('shows an error when the metrics cannot be loaded', async () => {
    render(<MetricsView api={makeApi(new ApiError(404, 'x', { detail: 'project not found' }))} projectId="p1" missionId={null} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('project not found')
  })
})

describe('MetricsScope', () => {
  it('chooses the whole project or one mission', async () => {
    const api = makeApi([{ id: 'm1', title: 'Todo app' }, { id: 'm2', title: 'Blog' }])
    const onSelect = vi.fn()
    render(<MetricsScope api={api} projectId="p1" selected="m2" onSelect={onSelect} />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Todo app' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Blog' })).toHaveAttribute('aria-current', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Todo app' }))
    fireEvent.click(screen.getByRole('button', { name: 'The whole project' }))
    expect(onSelect).toHaveBeenNthCalledWith(1, 'm1')
    expect(onSelect).toHaveBeenNthCalledWith(2, null)
    expect(api.get).toHaveBeenCalledWith('/missions', { project_id: 'p1' })
  })
})
