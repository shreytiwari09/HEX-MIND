import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { ConnectionsPanel } from './ConnectionsPanel'
import { TeamPanel } from './TeamPanel'
import type {
  Assignment,
  CatalogEntry,
  Connection,
  Persona,
  PersonaBudget,
  ProviderType
} from './types'
import type { ModelsData } from './useModelsData'

const TYPES: ProviderType[] = [
  { type: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1', requires_key: true, local: false },
  { type: 'custom', label: 'Custom (OpenAI-compatible URL)', base_url: null, requires_key: true, local: false },
  { type: 'ollama', label: 'Ollama (local)', base_url: 'http://127.0.0.1:11434', requires_key: false, local: true }
]

function connection(extra: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    name: 'OpenAI',
    provider_type: 'openai',
    base_url: 'https://api.openai.com/v1',
    extra_headers: {},
    enabled: true,
    requires_key: true,
    keys: [
      { id: 'k1', label: 'key 1', position: 0, disabled: false },
      { id: 'k2', label: 'work account', position: 1, disabled: false }
    ],
    models: ['gpt-5', 'gpt-5-mini'],
    last_test: { ok: true, error: null, tested_at: '2026-11-19T10:00:00Z' },
    ...extra
  }
}

const PERSONAS: Persona[] = [
  { id: 'backend', name: 'Backend engineer', kind: 'worker', skills: [], plugins: [] },
  { id: 'pm', name: 'PM / Tech Lead', kind: 'orchestrator', skills: [], plugins: [] }
]

function entry(model: string, connectionId = 'c1', name = 'OpenAI'): CatalogEntry {
  return {
    connection_id: connectionId,
    connection_name: name,
    provider_type: 'openai',
    model,
    name: model,
    local: false,
    context_window: 200000,
    input_per_mtok: '1.25',
    output_per_mtok: '10',
    tool_call: true,
    deprecated: false,
    tiers: { reasoning: 5, coding: 5, ui: 4, tool_use: 5 },
    has_profile: true,
    in_models_dev: true
  }
}

function data(extra: Partial<ModelsData> = {}): ModelsData {
  return {
    types: TYPES,
    connections: [connection()],
    personas: PERSONAS,
    assignments: [],
    budgets: [],
    catalog: [entry('gpt-5'), entry('gpt-5-mini')],
    loaded: true,
    error: null,
    reload: vi.fn(async () => undefined),
    ...extra
  }
}

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

beforeEach(() => {
  window.confirm = vi.fn(() => true)
})

describe('ConnectionsPanel', () => {
  it('shows each connection, its real test result, its key pool by label, and the pool caution', () => {
    const failing = connection({
      id: 'c2',
      name: 'Mine',
      keys: [],
      models: [],
      last_test: { ok: false, error: 'the provider rejected the key', tested_at: null }
    })
    render(<ConnectionsPanel api={makeApi()} data={data({ connections: [connection(), failing] })} />)

    expect(screen.getByText('Connected · 2 models')).toBeInTheDocument()
    expect(screen.getByText('Test failed: the provider rejected the key')).toBeInTheDocument()
    expect(screen.getByText('work account')).toBeInTheDocument()
    expect(screen.getByText('tried first')).toBeInTheDocument()
    expect(screen.getByText('fallback 1')).toBeInTheDocument()
    expect(screen.getByText(/No keys yet: this connection cannot be used/)).toBeInTheDocument()
    expect(screen.getByText(/often per account or organisation/)).toBeInTheDocument()
    expect(screen.getByText('2 models reachable')).toBeInTheDocument()
  })

  it('says so when there are no connections yet', () => {
    render(<ConnectionsPanel api={makeApi()} data={data({ connections: [] })} />)
    expect(screen.getByText(/No connections yet/)).toBeInTheDocument()
  })

  it('adds a connection with the key in a password field, then forgets the key', async () => {
    const created = { connection: connection(), test: { ok: true, error: null, models: ['gpt-5', 'gpt-5-mini'], latency_ms: 40, auth_rejected: false } }
    const api = makeApi({ 'POST /connections': created })
    const info = data({ connections: [] })
    render(<ConnectionsPanel api={api} data={info} />)

    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'openai' } })
    expect(screen.getByLabelText('Name')).toHaveValue('OpenAI')
    const key = screen.getByLabelText(/^API key/)
    expect(key).toHaveAttribute('type', 'password')
    fireEvent.change(key, { target: { value: 'sk-secret-0123456789' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add and test' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/connections', {
      name: 'OpenAI',
      provider_type: 'openai',
      base_url: undefined,
      api_key: 'sk-secret-0123456789'
    })
    expect(await screen.findByRole('status')).toHaveTextContent('OpenAI works: 2 models reachable.')
    expect(info.reload).toHaveBeenCalled()
    // The key is not kept: the form is reset and the page never shows it.
    expect(document.body.textContent).not.toContain('sk-secret')
    expect(screen.queryByDisplayValue('sk-secret-0123456789')).toBeNull()
  })

  it('reports a connection that was added but failed its test', async () => {
    const created = { connection: connection({ name: 'Mine' }), test: { ok: false, error: 'could not connect (ConnectError): check the base URL', models: [], latency_ms: 0, auth_rejected: false } }
    render(<ConnectionsPanel api={makeApi({ 'POST /connections': created })} data={data({ connections: [] })} />)

    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'custom' } })
    expect(screen.getByLabelText(/^Base URL$/)).toBeRequired() // a custom provider needs a URL
    fireEvent.change(screen.getByLabelText(/^Base URL/), { target: { value: 'https://llm.example/v1' } })
    fireEvent.change(screen.getByLabelText(/^API key/), { target: { value: 'k-123456789' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add and test' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Mine was added, but the test failed: could not connect (ConnectError): check the base URL'
    )
  })

  it('shows the backend’s refusal, such as a key the provider rejects', async () => {
    const refused = new ApiError(422, 'HTTP 422', { detail: 'the provider rejected this key, so it was not saved' })
    render(<ConnectionsPanel api={makeApi({ 'POST /connections': refused })} data={data({ connections: [] })} />)

    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'openai' } })
    fireEvent.change(screen.getByLabelText(/^API key/), { target: { value: 'sk-bad' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add and test' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('the provider rejected this key, so it was not saved')
  })

  it('needs no key for a local provider', () => {
    render(<ConnectionsPanel api={makeApi()} data={data({ connections: [] })} />)

    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'ollama' } })

    expect(screen.queryByLabelText(/^API key/)).toBeNull()
    expect(screen.getByText(/nothing leaves your machine/)).toBeInTheDocument()
  })

  it('adds a key to a pool, tests, disables and deletes, asking before anything destructive', async () => {
    const api = makeApi({
      'POST /connections/c1/keys': { connection: connection(), test: { ok: true, error: null, models: [], latency_ms: 1, auth_rejected: false } },
      'POST /connections/c1/test': { connection: connection(), test: null },
      'PUT /connections/c1': connection({ enabled: false }),
      'DELETE /connections/c1/keys/k2': connection(),
      'DELETE /connections/c1': undefined
    })
    const info = data()
    render(<ConnectionsPanel api={api} data={info} />)

    fireEvent.change(screen.getByLabelText('New key for OpenAI'), { target: { value: 'sk-second-0123456789' } })
    fireEvent.change(screen.getByLabelText('Label for the new OpenAI key'), { target: { value: 'home' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add key' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/connections/c1/keys', { api_key: 'sk-second-0123456789', label: 'home' }))
    await waitFor(() => expect(screen.getByLabelText('New key for OpenAI')).toHaveValue(''))

    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/connections/c1/test'))
    fireEvent.click(screen.getByRole('button', { name: 'Disable' }))
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/connections/c1', { enabled: false }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove work account from OpenAI' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/connections/c1/keys/k2'))
    window.confirm = vi.fn(() => false)
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(api.delete).not.toHaveBeenCalledWith('/connections/c1')
    window.confirm = vi.fn(() => true)
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/connections/c1'))
    expect(info.reload).toHaveBeenCalled()
  })
})

describe('TeamPanel', () => {
  const auto: Assignment = {
    persona_id: 'backend',
    primary: { connection_id: 'c1', model: 'gpt-5-mini' },
    fallbacks: [{ connection_id: 'c1', model: 'gpt-5' }],
    escalate: { connection_id: 'c1', model: 'gpt-5' },
    set_by: 'auto',
    reason: 'cheapest model meeting coding ≥4, tool use ≥4: gpt-5-mini on OpenAI ($0.25 in / $2 out per Mtok)',
    updated_at: ''
  }

  it('shows who uses which model, who set it and why, and what has no assignment', () => {
    render(<TeamPanel api={makeApi()} data={data({ assignments: [auto] })} />)

    const table = screen.getByRole('table', { name: 'Team' })
    const backend = within(table).getByText('Backend engineer').closest('tr')!
    // The model cell (the same text is also an option in the "Change model" list).
    expect(within(backend).getAllByText('OpenAI · gpt-5-mini')[0].tagName).toBe('DIV')
    expect(within(backend).getByText('Auto')).toBeInTheDocument()
    expect(within(backend).getByText(/cheapest model meeting coding/)).toBeInTheDocument()
    expect(within(backend).getByText(/1 fallback · escalates to OpenAI · gpt-5/)).toBeInTheDocument()
    const pm = within(table).getByText('PM / Tech Lead').closest('tr')!
    expect(within(pm).getByText(/Default routing/)).toBeInTheDocument()
  })

  it('previews Auto’s choices with reasons without saving anything, then applies them', async () => {
    const proposals = [
      { persona_id: 'backend', primary: { connection_id: 'c1', model: 'gpt-5-mini' }, fallbacks: [], escalate: null, reason: 'cheapest model meeting coding ≥4: gpt-5-mini on OpenAI', verified: true, outcome: 'would_save' },
      { persona_id: 'pm', primary: { connection_id: 'c1', model: 'gpt-5' }, fallbacks: [], escalate: null, reason: 'unverified: none of your models is profiled to meet reasoning ≥5; best available', verified: false, outcome: 'would_save' }
    ]
    const api = makeApi({
      'POST /assignments/auto': (body: unknown) => ({
        preset: 'balanced',
        proposals: proposals.map((p) => ((body as { dry_run: boolean }).dry_run ? p : { ...p, outcome: 'saved' }))
      })
    })
    const info = data()
    render(<TeamPanel api={api} data={info} />)

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))

    const preview = await screen.findByRole('list', { name: 'Preview' })
    expect(within(preview).getByText(/cheapest model meeting coding ≥4: gpt-5-mini on OpenAI/)).toBeInTheDocument()
    expect(within(preview).getByText('unverified')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/assignments/auto', { preset: 'balanced', dry_run: true, overwrite_manual: false })
    expect(api.put).not.toHaveBeenCalled() // a preview saves nothing
    expect(info.reload).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Assigned 2 personas with the balanced preset.')
    expect(api.post).toHaveBeenLastCalledWith('/assignments/auto', { preset: 'balanced', dry_run: false, overwrite_manual: false })
    expect(info.reload).toHaveBeenCalled()
    expect(screen.queryByRole('list', { name: 'Preview' })).toBeNull()
  })

  it('sends the chosen preset and the option to replace your own choices', async () => {
    const api = makeApi({ 'POST /assignments/auto': { preset: 'private', proposals: [] } })
    render(<TeamPanel api={api} data={data()} />)

    fireEvent.change(screen.getByLabelText('Preset'), { target: { value: 'private' } })
    expect(screen.getByText(/nothing leaves your machine/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Replace my own choices too'))
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/assignments/auto', { preset: 'private', dry_run: true, overwrite_manual: true })
    )
  })

  it('explains that there is nothing to choose from before a connection works', () => {
    render(<TeamPanel api={makeApi()} data={data({ catalog: [], connections: [] })} />)

    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
    expect(screen.getByText(/Add and test a connection first/)).toBeInTheDocument()
  })

  it('lets you choose a model yourself, keeping the fallbacks, or go back to default routing', async () => {
    const api = makeApi({ 'PUT /assignments/backend': {}, 'DELETE /assignments/backend': undefined })
    const info = data({ assignments: [auto] })
    render(<TeamPanel api={api} data={info} />)

    fireEvent.change(screen.getByLabelText('Model for Backend engineer'), { target: { value: 'c1|gpt-5' } })

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/assignments/backend', {
        primary: { connection_id: 'c1', model: 'gpt-5' },
        fallbacks: auto.fallbacks,
        escalate: auto.escalate
      })
    )
    expect(info.reload).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Use default routing' }))
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/assignments/backend'))
  })

  it('sets, changes and clears a persona budget, and rejects nonsense', async () => {
    const api = makeApi({ 'PUT /budgets/personas/backend': {}, 'DELETE /budgets/personas/backend': undefined })
    const budgets: PersonaBudget[] = [{ persona_id: 'backend', budget_usd: 2 }]
    const { rerender } = render(<TeamPanel api={api} data={data()} />)

    const input = screen.getByLabelText('Budget for Backend engineer in USD')
    fireEvent.change(input, { target: { value: '2.5' } })
    fireEvent.blur(input)
    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/budgets/personas/backend', { budget_usd: 2.5 }))

    fireEvent.change(input, { target: { value: '-1' } })
    fireEvent.blur(input)
    expect(await screen.findByRole('alert')).toHaveTextContent('positive number of dollars')
    expect(api.put).toHaveBeenCalledTimes(1)

    rerender(<TeamPanel api={api} data={data({ budgets })} />)
    const saved = screen.getByLabelText('Budget for Backend engineer in USD')
    expect(saved).toHaveValue(2)
    fireEvent.change(saved, { target: { value: '' } })
    fireEvent.blur(saved)
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/budgets/personas/backend'))
  })
})
