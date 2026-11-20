import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { ConnectionsPanel } from './ConnectionsPanel'
import type { Assignment, CatalogEntry, Connection, Persona, ProviderType } from './types'
import type { ModelsData } from './useModelsData'

const TYPES: ProviderType[] = [
  { type: 'moonshot', label: 'Moonshot', base_url: 'https://api.moonshot.ai/v1', requires_key: true, local: false }
]
const CONNECTION: Connection = {
  id: 'c1',
  name: 'Moonshot',
  provider_type: 'moonshot',
  base_url: 'https://api.moonshot.ai/v1',
  extra_headers: {},
  enabled: true,
  requires_key: true,
  keys: [{ id: 'k1', label: 'key 1', position: 0, disabled: false }],
  models: ['kimi-big', 'kimi-small'],
  last_test: { ok: true, error: null, tested_at: '2026-11-21T10:00:00Z' }
}
const PERSONAS: Persona[] = [
  { id: 'backend', name: 'Backend engineer', kind: 'worker', skills: [], plugins: [] },
  { id: 'pm', name: 'PM / Tech Lead', kind: 'orchestrator', skills: [], plugins: [] }
]
const entry = (model: string): CatalogEntry => ({
  connection_id: 'c1',
  connection_name: 'Moonshot',
  provider_type: 'moonshot',
  model,
  name: model,
  local: false,
  context_window: 128000,
  input_per_mtok: null,
  output_per_mtok: null,
  tool_call: true,
  deprecated: false,
  tiers: null, // a model nobody has rated
  has_profile: false,
  in_models_dev: false
})
const ASSIGNED: Assignment = {
  persona_id: 'pm',
  primary: { connection_id: 'c1', model: 'kimi-big' },
  fallbacks: [],
  escalate: null,
  set_by: 'user',
  reason: 'chosen by you',
  updated_at: ''
}

function data(extra: Partial<ModelsData> = {}): ModelsData {
  return {
    types: TYPES,
    connections: [CONNECTION],
    personas: PERSONAS,
    assignments: [],
    budgets: [],
    catalog: [entry('kimi-big'), entry('kimi-small')],
    loaded: true,
    error: null,
    reload: vi.fn(async () => undefined),
    ...extra
  }
}

const proposals = [
  { persona_id: 'backend', primary: { connection_id: 'c1', model: 'kimi-small' }, fallbacks: [], escalate: null, reason: 'unverified: no rating for kimi-small; best available', verified: false, outcome: 'would_save' },
  { persona_id: 'pm', primary: { connection_id: 'c1', model: 'kimi-big' }, fallbacks: [], escalate: null, reason: 'unverified: no rating for kimi-big; best available', verified: false, outcome: 'would_save' }
]

type Handler = (body?: unknown) => unknown
function makeApi(routes: Record<string, Handler | unknown> = {}) {
  const call = (method: string) => async (path: string, body?: unknown) => {
    const handler = routes[`${method} ${path}`]
    if (handler instanceof Error) throw handler
    return typeof handler === 'function' ? (handler as Handler)(body) : handler
  }
  return {
    get: vi.fn(call('GET')),
    post: vi.fn(call('POST')),
    put: vi.fn(call('PUT')),
    delete: vi.fn(call('DELETE'))
  } as unknown as ApiClient & Record<'get' | 'post' | 'put' | 'delete', ReturnType<typeof vi.fn>>
}

const auto = (body: unknown) => ({
  preset: 'balanced',
  proposals: proposals.map((p) => ((body as { dry_run: boolean }).dry_run ? p : { ...p, outcome: 'saved' }))
})
const box = () => screen.queryByRole('region', { name: 'Set up your team' })

describe('the one-click team setup', () => {
  it('is offered when you have models but nobody has one yet, and needs no model names', async () => {
    render(<ConnectionsPanel api={makeApi()} data={data()} />)

    const setup = await screen.findByRole('region', { name: 'Set up your team' })
    expect(within(setup).getByText(/do not need to know any model names/)).toBeInTheDocument()
    expect(within(setup).getByText(/change any member’s model later on the Team models tab/)).toBeInTheDocument()
  })

  it('shows what it would pick and why, saves nothing, then saves only when you agree', async () => {
    const api = makeApi({ 'POST /assignments/auto': auto })
    const info = data()
    render(<ConnectionsPanel api={api} data={info} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Show me what it would pick' }))

    const list = await screen.findByRole('list', { name: 'What it would pick' })
    expect(within(list).getByText(/no rating for kimi-big/)).toBeInTheDocument()
    expect(within(list).getAllByText('unverified')).toHaveLength(2) // said plainly, never hidden
    expect(within(list).getByText(/Moonshot · kimi-small/)).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/assignments/auto', { preset: 'balanced', dry_run: true, overwrite_manual: false })
    expect(info.reload).not.toHaveBeenCalled() // a preview changes nothing

    fireEvent.click(screen.getByRole('button', { name: 'Use this setup' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Your team is set up: 2 members now have a model')
    expect(api.post).toHaveBeenLastCalledWith('/assignments/auto', { preset: 'balanced', dry_run: false, overwrite_manual: false })
    expect(info.reload).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(box()).toBeNull()
  })

  it('never replaces a model you chose yourself, and says when there is nothing to pick', async () => {
    const kept = proposals.map((p) => ({ ...p, outcome: 'kept_manual' }))
    const api = makeApi({ 'POST /assignments/auto': { preset: 'balanced', proposals: kept } })
    render(<ConnectionsPanel api={api} data={data()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Show me what it would pick' }))

    expect(await screen.findByText(/every team member already has a model you chose/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use this setup' })).toBeDisabled()
    expect(api.post).toHaveBeenCalledWith('/assignments/auto', expect.objectContaining({ overwrite_manual: false }))
  })

  it('can be skipped with Not now', async () => {
    render(<ConnectionsPanel api={makeApi()} data={data()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Not now' }))

    expect(box()).toBeNull()
  })

  it('is not offered when the team already has models, or when there are no models yet', () => {
    const { unmount } = render(<ConnectionsPanel api={makeApi()} data={data({ assignments: [ASSIGNED] })} />)
    expect(box()).toBeNull()
    unmount()

    render(<ConnectionsPanel api={makeApi()} data={data({ connections: [], catalog: [] })} />)
    expect(box()).toBeNull()
  })

  it('appears right after a key works, even if the team already has models', async () => {
    const created = {
      connection: CONNECTION,
      test: { ok: true, error: null, models: ['kimi-big', 'kimi-small'], latency_ms: 40, auth_rejected: false }
    }
    const api = makeApi({ 'POST /connections': created })
    render(<ConnectionsPanel api={api} data={data({ connections: [], assignments: [ASSIGNED] })} />)
    expect(box()).toBeNull()

    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'moonshot' } })
    fireEvent.change(screen.getByLabelText(/^API key/), { target: { value: 'sk-kimi-0123456789' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add and test' }))

    expect(await screen.findByRole('region', { name: 'Set up your team' })).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('sk-kimi')
  })

  it('does not appear after a key that failed its test', async () => {
    const created = {
      connection: CONNECTION,
      test: { ok: false, error: 'could not reach the provider', models: [], latency_ms: 0, auth_rejected: false }
    }
    const api = makeApi({ 'POST /connections': created })
    render(<ConnectionsPanel api={api} data={data({ connections: [], catalog: [], assignments: [ASSIGNED] })} />)

    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'moonshot' } })
    fireEvent.change(screen.getByLabelText(/^API key/), { target: { value: 'sk-kimi-0123456789' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add and test' }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('the test failed'))
    expect(box()).toBeNull()
  })

  it('shows the reason when the setup cannot be done', async () => {
    const api = makeApi({ 'POST /assignments/auto': new ApiError(409, 'conflict', { detail: 'no connection has a usable model' }) })
    render(<ConnectionsPanel api={api} data={data()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Show me what it would pick' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('no connection has a usable model')
  })
})
