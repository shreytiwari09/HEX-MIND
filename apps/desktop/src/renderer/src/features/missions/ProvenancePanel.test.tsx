import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { ProvenancePanel } from './ProvenancePanel'

const change = (extra: object = {}) => ({
  feature: { id: 'todo-model', title: 'Todo model', milestone: 'm1' },
  persona: { id: 'backend', version: 2 },
  agent_id: 'backend_01',
  attempt: 1,
  model_used: 'groq:llama',
  variant_id: null,
  skills: [
    { name: 'rest-api', version: 'rest-api@abc', loaded: true },
    { name: 'auth-basics', version: 'auth-basics@def', loaded: false }
  ],
  plugins: [],
  commit: 'c'.repeat(40),
  validated_by: [{ validator: 'code-reviewer', round: 1, verdict: 'pass' }],
  model_calls: [{ at: 'x', purpose: 'coder', provider: 'groq', model: 'llama', input_tokens: 1, output_tokens: 1, cost_usd: 0, request_sha256: 'h' }],
  handoff_event: { seq: 9, hash: 'f'.repeat(64) },
  ...extra
})

const DOC = {
  approval: { seq: 3, ts: '2026-11-20T10:00:00Z', hash: 'a'.repeat(64) },
  audit: { ok: true, events: 50, broken: null },
  files: [
    { path: 'src/todos.js', changes: [change(), change({ feature: { id: 'filter', title: 'Filter helper', milestone: 'm2' }, persona: { id: 'frontend', version: 1 }, attempt: 2, agent_id: 'frontend_02' })] },
    { path: 'src/filter.js', changes: [change({ plugins: [{ id: 'notes', config_hash: 'h', called: true }], variant_id: 'terse', validated_by: [] })] }
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

describe('ProvenancePanel', () => {
  it('lists the changed files with the latest feature and persona behind each', async () => {
    const api = makeApi(DOC)
    render(<ProvenancePanel api={api} missionId="m1" refreshKey="x" />)

    const list = await screen.findByRole('list', { name: 'Changed files' })
    expect(within(list).getByRole('button', { name: /src\/todos\.js/ })).toHaveTextContent('Filter helper · frontend v1 · +1 earlier')
    expect(within(list).getByRole('button', { name: /src\/filter\.js/ })).toHaveTextContent('Todo model · backend v2')
    expect(screen.getByText(/Plan approved/)).toBeInTheDocument()
    expect(screen.getByText(/Audit log intact/)).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/missions/m1/provenance')
  })

  it('opens a file to show who changed it, in order, with the evidence', async () => {
    render(<ProvenancePanel api={makeApi(DOC)} missionId="m1" refreshKey="x" />)
    fireEvent.click(await screen.findByRole('button', { name: /src\/todos\.js/ }))

    const history = screen.getByRole('list', { name: 'History of src/todos.js' })
    const text = history.textContent ?? ''
    expect(text.indexOf('Todo model')).toBeLessThan(text.indexOf('Filter helper'))
    expect(history).toHaveTextContent('By backend version 2, backend_01 (attempt 1)')
    expect(history).toHaveTextContent('By frontend version 1, frontend_02 (attempt 2)')
    expect(history).toHaveTextContent('Model: groq:llama · 1 model call(s)')
    expect(history).toHaveTextContent('Skills offered: rest-api (loaded), auth-basics')
    expect(history).toHaveTextContent('Checked by: code-reviewer pass')
    expect(history).toHaveTextContent('Commit cccccccccc · audit ffffffffffff')
  })

  it('shows plugins, a prompt variant and an unreviewed change honestly', async () => {
    render(<ProvenancePanel api={makeApi(DOC)} missionId="m1" refreshKey="x" />)
    fireEvent.click(await screen.findByRole('button', { name: /src\/filter\.js/ }))

    const history = screen.getByRole('list', { name: 'History of src/filter.js' })
    expect(history).toHaveTextContent('prompt variant terse')
    expect(history).toHaveTextContent('Plugins: notes (used)')
    expect(history).toHaveTextContent('Checked by: its own tests only')
  })

  it('warns when the audit log is not intact', async () => {
    const broken = { ...DOC, audit: { ok: false, events: 50, broken: 'its content was changed after it was written' } }
    render(<ProvenancePanel api={makeApi(broken)} missionId="m1" refreshKey="x" />)

    expect(await screen.findByText(/NOT intact \(its content was changed/)).toBeInTheDocument()
  })

  it('says when nothing has changed yet, and when it cannot load', async () => {
    const empty = render(<ProvenancePanel api={makeApi({ ...DOC, files: [] })} missionId="m1" refreshKey="x" />)
    expect(await screen.findByText('No files have been changed yet.')).toBeInTheDocument()
    empty.unmount()

    render(<ProvenancePanel api={makeApi(new ApiError(404, 'x', { detail: 'mission not found' }))} missionId="m1" refreshKey="x" />)
    expect(await screen.findByText(/Could not load where the changes came from: mission not found/)).toBeInTheDocument()
  })

  it('exports the PROV-JSON file', async () => {
    const api = makeApi(DOC)
    const click = vi.fn()
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const original = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const element = original(tag)
      if (tag === 'a') element.click = click
      return element
    })
    render(<ProvenancePanel api={api} missionId="12345678-aaaa" refreshKey="x" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Export as PROV-JSON' }))

    await waitFor(() => expect(click).toHaveBeenCalled())
    expect(api.get).toHaveBeenLastCalledWith('/missions/12345678-aaaa/provenance', { format: 'prov' })
    expect(create).toHaveBeenCalled()
    vi.restoreAllMocks()
  })
})
