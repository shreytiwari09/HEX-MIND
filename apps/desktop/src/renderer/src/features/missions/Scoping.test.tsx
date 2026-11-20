import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { mission } from './fixtures'
import { NewMission } from './NewMission'
import type { MissionPlanDoc, ScopingSession } from './types'

const PLAN: MissionPlanDoc = {
  title: 'Todo app',
  milestones: [
    {
      id: 'm1-model',
      title: 'Todo model',
      validators: ['code-reviewer', 'qa'],
      features: [
        {
          id: 'todo-model',
          title: 'Todo model',
          persona: 'backend',
          expected_behavior: ['addTodo trims titles']
        }
      ]
    }
  ],
  validation_contract: [
    { id: 'VC-1', text: 'addTodo trims titles', how: 'unit test', feature: 'todo-model' },
    { id: 'VC-2', text: 'the page lists todos', how: 'browser', feature: 'todo-model' }
  ]
}

function session(extra: Partial<ScopingSession> = {}): ScopingSession {
  return {
    id: 's1',
    project_id: 'p1',
    run_id: 'r1',
    idea: 'A todo app',
    status: 'asking',
    messages: [
      { role: 'pm', content: 'A few questions first.', questions: ['Who uses it?'], at: '2026-11-20T10:00:00Z' }
    ],
    plan: null,
    prd: null,
    error: null,
    budget_usd: null,
    mission_id: null,
    cost_usd: 0.0123,
    created_at: '2026-11-20T10:00:00Z',
    updated_at: '2026-11-20T10:00:00Z',
    ...extra
  }
}

const planned = (extra: Partial<ScopingSession> = {}) =>
  session({
    status: 'planned',
    plan: PLAN,
    prd: '# Todo app',
    updated_at: '2026-11-20T10:05:00Z',
    messages: [
      { role: 'pm', content: 'Who uses it?', at: '2026-11-20T10:00:00Z' },
      { role: 'user', content: 'just me', at: '2026-11-20T10:01:00Z' },
      { role: 'pm', content: 'Here is the plan.', at: '2026-11-20T10:05:00Z' }
    ],
    ...extra
  })

function makeApi(handlers: Record<string, unknown>) {
  const respond = async (path: string) => {
    const value = handlers[path]
    if (value instanceof Error) throw value
    return value
  }
  return {
    get: vi.fn(respond),
    post: vi.fn(async (path: string, _body?: unknown) => respond(path)),
    put: vi.fn(async (path: string, _body?: unknown) => respond(path))
  } as unknown as ApiClient & {
    post: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
  }
}

const props = (api: ApiClient) => ({ api, projectId: 'p1', onCreated: vi.fn(), onCancel: vi.fn() })

async function startIdea(api: ApiClient, idea = 'A todo app') {
  const p = props(api)
  render(<NewMission {...p} />)
  fireEvent.change(screen.getByLabelText(/What do you want built/), { target: { value: idea } })
  fireEvent.click(screen.getByRole('button', { name: 'Start scoping' }))
  return p
}

describe('starting a mission from an idea', () => {
  it('starts scoping and shows the PM\'s questions and what the PM has cost', async () => {
    const api = makeApi({ '/scoping': session() })

    await startIdea(api)

    expect(await screen.findByRole('heading', { name: 'Scoping with the PM' })).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/scoping', { project_id: 'p1', idea: 'A todo app', budget_usd: undefined })
    const chat = screen.getByRole('list', { name: 'Conversation' })
    expect(within(chat).getByText('Who uses it?')).toBeInTheDocument()
    expect(screen.getByText(/cost so far \$0\.012/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Plan' })).toBeNull()
  })

  it('shows an error when the PM cannot be reached and lets you try again', async () => {
    const api = makeApi({
      '/scoping': session({ error: 'model unavailable', messages: [] }),
      '/scoping/s1/retry': planned()
    })
    await startIdea(api)

    expect(await screen.findByText(/The PM could not answer: model unavailable/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('heading', { name: 'Review the plan' })).toBeInTheDocument()
    expect(screen.queryByText(/could not answer/)).toBeNull()
  })

  it('reports a failed start in words', async () => {
    const api = makeApi({
      '/scoping': new ApiError(409, 'conflict', { detail: 'missions need a Git repository' })
    })
    await startIdea(api)

    expect(await screen.findByRole('alert')).toHaveTextContent('missions need a Git repository')
    expect(screen.getByRole('button', { name: 'Start scoping' })).toBeEnabled()
  })

  it('still lets you write the plan yourself', () => {
    render(<NewMission {...props(makeApi({}))} />)

    fireEvent.click(screen.getByRole('button', { name: 'Write the plan myself' }))

    expect(screen.getByLabelText('Plan (JSON)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create mission' })).toBeInTheDocument()
  })
})

describe('answering and reviewing the plan', () => {
  it('sends your answer and shows the plan the PM comes back with', async () => {
    const api = makeApi({ '/scoping': session(), '/scoping/s1/messages': planned() })
    await startIdea(api)
    fireEvent.change(await screen.findByLabelText('Your answer'), { target: { value: 'just me' } })

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('heading', { name: 'Review the plan' })).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/scoping/s1/messages', { content: 'just me' })
    const plan = screen.getByRole('region', { name: 'Plan' })
    expect(within(plan).getByText('Todo model', { selector: 'strong' })).toBeInTheDocument()
    expect(within(plan).getByText(/checked by code-reviewer, qa/)).toBeInTheDocument()
    expect(within(plan).getByText('(backend)')).toBeInTheDocument()
    expect(within(plan).getByText('VC-1')).toBeInTheDocument()
    // A browser criterion is honest about not being checked yet.
    expect(within(plan).getAllByText(/not checked automatically yet/)).toHaveLength(1)
    expect(screen.getByLabelText('Ask the PM to change the plan')).toBeInTheDocument()
  })

  it('creates the mission only from a saved plan, and opens it', async () => {
    const created = mission({ status: 'awaiting_approval' })
    const api = makeApi({
      '/scoping': planned(),
      '/scoping/s1/plan': planned({ prd: '# Todo app\nMy note', budget_usd: 2.5, updated_at: '2026-11-20T10:09:00Z' }),
      '/scoping/s1/mission': created
    })
    const p = await startIdea(api)
    const prd = await screen.findByLabelText(/What will be built/)
    const create = screen.getByRole('button', { name: 'Create mission' })
    expect(create).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()

    fireEvent.change(prd, { target: { value: '# Todo app\nMy note' } })
    fireEvent.change(screen.getByLabelText('Budget in USD (optional)'), { target: { value: '2.5' } })
    expect(screen.getByRole('button', { name: 'Create mission' })).toBeDisabled() // unsaved edits
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create mission' })).toBeEnabled())
    expect(api.put).toHaveBeenCalledWith('/scoping/s1/plan', {
      plan: PLAN,
      prd: '# Todo app\nMy note',
      budget_usd: 2.5
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create mission' }))

    await waitFor(() => expect(p.onCreated).toHaveBeenCalledWith(created))
    expect(api.post).toHaveBeenCalledWith('/scoping/s1/mission')
  })

  it('refuses invalid JSON before it reaches the server and shows the server\'s reason for a bad plan', async () => {
    const api = makeApi({
      '/scoping': planned(),
      '/scoping/s1/plan': new ApiError(422, 'invalid', {
        detail: [{ loc: ['body', 'plan'], msg: "Value error, milestone m1-model: 'backend' is not a validator" }]
      })
    })
    await startIdea(api)
    const json = await screen.findByLabelText('Plan (JSON)')

    fireEvent.change(json, { target: { value: '{ not json' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The plan is not valid JSON')
    expect(api.put).not.toHaveBeenCalled()

    fireEvent.change(json, { target: { value: JSON.stringify({ ...PLAN, title: 'Changed' }) } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText(/'backend' is not a validator/)).toBeInTheDocument()
  })

  it('discards the session and closes', async () => {
    const api = makeApi({ '/scoping': session(), '/scoping/s1/abandon': session({ status: 'abandoned' }) })
    const p = await startIdea(api)

    fireEvent.click(await screen.findByRole('button', { name: 'Discard' }))

    await waitFor(() => expect(p.onCancel).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/scoping/s1/abandon')
  })
})


describe('choosing how the team shares work', () => {
  it('sends the choice of messaging, and nothing extra for the default', async () => {
    const api = makeApi({ '/variants': [], '/scoping': session() })
    render(<NewMission {...props(api)} />)

    fireEvent.change(screen.getByLabelText('How the team shares work'), { target: { value: 'messaging' } })
    fireEvent.change(screen.getByLabelText(/What do you want built/), { target: { value: 'A todo app' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start scoping' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/scoping', {
        project_id: 'p1',
        idea: 'A todo app',
        budget_usd: undefined,
        variant_id: undefined,
        coordination: 'messaging'
      })
    )
  })
})

describe('choosing a prompt variant', () => {
  it('offers the variants you have and sends the one you pick', async () => {
    const api = makeApi({
      '/variants': [{ id: 'terse', name: 'Terse builders' }],
      '/scoping': session({ variant_id: 'terse' } as Partial<ScopingSession>)
    })
    const p = props(api)
    render(<NewMission {...p} />)

    const select = await screen.findByLabelText('Prompt variant (optional)')
    expect(screen.getByRole('option', { name: 'None: the team as it is' })).toBeInTheDocument()
    fireEvent.change(select, { target: { value: 'terse' } })
    fireEvent.change(screen.getByLabelText(/What do you want built/), { target: { value: 'A todo app' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start scoping' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/scoping', { project_id: 'p1', idea: 'A todo app', budget_usd: undefined, variant_id: 'terse' })
    )
  })

  it('shows no selector when there are no variants, and sends none', async () => {
    const api = makeApi({ '/variants': [], '/scoping': session() })
    render(<NewMission {...props(api)} />)

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/variants'))
    expect(screen.queryByLabelText('Prompt variant (optional)')).toBeNull()
    fireEvent.change(screen.getByLabelText(/What do you want built/), { target: { value: 'A todo app' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start scoping' }))
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/scoping', { project_id: 'p1', idea: 'A todo app', budget_usd: undefined, variant_id: undefined })
    )
  })
})
