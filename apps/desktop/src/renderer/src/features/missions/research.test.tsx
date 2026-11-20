import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { NewMission } from './NewMission'
import { ResearchNotes } from './ResearchNotes'
import type { ResearchNotes as Notes, ScopingSession } from './types'

const NOTES: Notes = {
  at: '2026-11-21T10:00:00Z',
  questions: ['How do sessions work?', 'Which stores are used?'],
  credits: null,
  findings: [
    {
      question: 'How do sessions work?',
      answer: 'Sessions live on the server.',
      sources: [{ title: 'session middleware', url: 'https://expressjs.com/en/resources/middleware/session' }],
      gaps: '1 cited source(s) were left out: the researcher never saw them.',
      searches: 1,
      pages: 2,
      credits: 1,
      error: null
    },
    {
      question: 'Which stores are used?',
      answer: '',
      sources: [],
      gaps: '',
      searches: 3,
      pages: 0,
      credits: null,
      error: 'the researcher could not finish (ResearchStopped)'
    }
  ]
}

function session(extra: Partial<ScopingSession> = {}): ScopingSession {
  return {
    id: 's1',
    project_id: 'p1',
    run_id: 'r1',
    idea: 'A todo app',
    status: 'asking',
    messages: [{ role: 'pm', content: 'A question.', questions: ['Who uses it?'], at: '2026-11-21T10:00:00Z' }],
    plan: null,
    prd: null,
    error: null,
    budget_usd: null,
    mission_id: null,
    cost_usd: 0,
    created_at: '2026-11-21T10:00:00Z',
    updated_at: '2026-11-21T10:00:00Z',
    ...extra
  }
}

function makeApi(handlers: Record<string, unknown>) {
  const respond = async (path: string) => {
    const value = handlers[path]
    if (value instanceof Error) throw value
    return value
  }
  return {
    get: vi.fn(respond),
    post: vi.fn(async (path: string, _body?: unknown) => respond(path)),
    put: vi.fn(respond),
    delete: vi.fn(respond)
  } as unknown as ApiClient & { post: ReturnType<typeof vi.fn> }
}

const keySet = { provider: 'tavily', configured: true, source: 'env' }
const noKey = { provider: 'tavily', configured: false, source: null }
const idea = () =>
  fireEvent.change(screen.getByLabelText(/What do you want built/), { target: { value: 'A todo app' } })
const render_ = (api: ApiClient) =>
  render(<NewMission api={api} projectId="p1" onCreated={vi.fn()} onCancel={vi.fn()} />)

describe('the Advanced research switch', () => {
  it('is off by default, shows nothing about research and sends nothing about it', async () => {
    const api = makeApi({ '/scoping': session() })
    render_(api)
    idea()

    expect(screen.getByRole('checkbox', { name: /Look things up on the web/ })).not.toBeChecked()
    expect(screen.queryByText(/I understand: researchers/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Start scoping' }))

    await screen.findByRole('heading', { name: 'Scoping with the PM' })
    const body = api.post.mock.calls[0][1] as Record<string, unknown>
    expect(body.research).toBeUndefined()
    expect(body.research_confirmed).toBeUndefined()
  })

  it('explains what happens and needs a tick before it can start', async () => {
    const api = makeApi({ '/research/search': keySet, '/scoping': session({ research: true }) })
    render_(api)
    idea()
    fireEvent.click(screen.getByRole('checkbox', { name: /Look things up on the web/ }))

    expect(screen.getByText(/can only read public websites/)).toBeInTheDocument()
    expect(screen.getByText(/those searches go to Tavily/)).toBeInTheDocument()
    await screen.findByText(/A search key is set/)
    const start = screen.getByRole('button', { name: 'Start scoping' })
    expect(start).toBeDisabled()
    expect(start).toHaveAttribute('title', 'Confirm that researchers may use the web')

    fireEvent.click(screen.getByRole('checkbox', { name: /I understand: researchers may search the web/ }))
    expect(start).toBeEnabled()
    fireEvent.click(start)

    await screen.findByRole('heading', { name: 'Scoping with the PM' })
    expect(api.post).toHaveBeenCalledWith('/scoping', expect.objectContaining({ research: true, research_confirmed: true }))
  })

  it('cannot start without a search key, and says what to do', async () => {
    render_(makeApi({ '/research/search': noKey }))
    idea()
    fireEvent.click(screen.getByRole('checkbox', { name: /Look things up on the web/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /I understand: researchers may search the web/ }))

    expect(await screen.findByText('No search key is set yet.')).toBeInTheDocument()
    const start = screen.getByRole('button', { name: 'Start scoping' })
    expect(start).toBeDisabled()
    expect(start).toHaveAttribute('title', 'Add a search key first')
    expect(screen.getByLabelText('Tavily API key')).toBeInTheDocument()
  })

  it('shows the reason when the backend refuses (for example the privacy mode)', async () => {
    const reason = 'Advanced research is off for this project: its privacy mode keeps everything on this machine'
    render_(makeApi({ '/research/search': keySet, '/scoping': new ApiError(409, 'conflict', { detail: reason }) }))
    idea()
    fireEvent.click(screen.getByRole('checkbox', { name: /Look things up on the web/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /I understand: researchers may search the web/ }))
    await screen.findByText(/A search key is set/)
    fireEvent.click(screen.getByRole('button', { name: 'Start scoping' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('privacy mode')
  })

  it('shows the research in the scoping screen once the session has it', async () => {
    const api = makeApi({ '/research/search': keySet, '/scoping': session({ research: true, research_notes: NOTES }) })
    render_(api)
    idea()
    fireEvent.click(screen.getByRole('checkbox', { name: /Look things up on the web/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /I understand: researchers may search the web/ }))
    await screen.findByText(/A search key is set/)
    fireEvent.click(screen.getByRole('button', { name: 'Start scoping' }))

    const region = await screen.findByRole('region', { name: 'Research' })
    expect(within(region).getByText('Sessions live on the server.')).toBeInTheDocument()
    await waitFor(() => expect(api.post).toHaveBeenCalled())
  })
})

describe('the research notes', () => {
  it('show answers with the sources actually read, what was not found, and counts', () => {
    render(<ResearchNotes notes={NOTES} />)

    expect(screen.getByText('Sessions live on the server.')).toBeInTheDocument()
    const sources = screen.getByRole('list', { name: 'Sources' })
    expect(within(sources).getByText('https://expressjs.com/en/resources/middleware/session')).toBeInTheDocument()
    expect(screen.getByText(/the researcher never saw them/)).toBeInTheDocument()
    expect(screen.getByText(/1 search\(es\), 2 page\(s\) read, 1 credit/)).toBeInTheDocument()
    expect(screen.getByText(/summaries of web pages written by an AI/)).toBeInTheDocument()
  })

  it('show a failed question as not answered, and unknown credits as n/a (never zero)', () => {
    render(<ResearchNotes notes={NOTES} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Not answered: the researcher could not finish')
    expect(screen.getByText(/3 search\(es\), 0 page\(s\) read, n\/a credit/)).toBeInTheDocument()
    expect(screen.getByText(/Search cost: n\/a Tavily credit/)).toBeInTheDocument()
  })

  it('say so when the PM named nothing to look up, and when no source was read', () => {
    const { rerender } = render(<ResearchNotes notes={{ ...NOTES, findings: [], credits: 0 }} />)
    expect(screen.getByText(/found nothing it needed to look up/)).toBeInTheDocument()

    rerender(
      <ResearchNotes
        notes={{ ...NOTES, findings: [{ ...NOTES.findings[0], sources: [], gaps: '' }], credits: 1 }}
      />
    )
    expect(screen.getByText('No source was read.')).toBeInTheDocument()
  })
})
