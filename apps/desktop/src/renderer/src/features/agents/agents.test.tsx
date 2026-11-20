import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { NewPersona } from './NewPersona'
import { PersonaEditor } from './PersonaEditor'
import { PersonaList } from './PersonaList'
import type { SkillsResponse, TeamPersona } from './types'
import { useTeam, type TeamData } from './useTeam'

const persona = (extra: Partial<TeamPersona> = {}): TeamPersona => ({
  id: 'designer',
  name: 'Designer',
  kind: 'worker',
  skills: ['ui-ux-pro'],
  plugins: [],
  instructions: 'You are the product designer on this team.',
  version: 1,
  source: 'builtin',
  missing_skills: [],
  ...extra
})

const SKILLS: SkillsResponse = {
  skills: [
    { name: 'ui-ux-pro', description: 'Layout and hierarchy.', source: 'builtin', version: 'ui-ux-pro@aaa', files: [], personas: ['designer'], origin: null },
    { name: 'motion-graphics', description: 'Animate UIs.', source: 'user', version: 'motion-graphics@bbb', files: [], personas: [], origin: null }
  ],
  problems: { broken: 'broken: there is no SKILL.md' }
}

function makeTeam(extra: Partial<TeamData> = {}): TeamData {
  return { personas: [persona()], skills: SKILLS, loaded: true, error: null, reload: vi.fn(async () => {}), ...extra }
}

function makeApi(handlers: Record<string, unknown> = {}) {
  const respond = async (path: string) => {
    const value = handlers[path]
    if (value instanceof Error) throw value
    return value
  }
  return {
    get: vi.fn(respond),
    post: vi.fn(async (path: string, _body?: unknown) => respond(path)),
    put: vi.fn(async (path: string, _body?: unknown) => respond(path)),
    delete: vi.fn(async (path: string) => respond(path))
  } as unknown as ApiClient & {
    put: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
    get: ReturnType<typeof vi.fn>
  }
}

beforeEach(() => {
  window.confirm = vi.fn(() => true)
})

describe('useTeam', () => {
  it('loads the team and the skills together and keeps working when a call fails', async () => {
    const api = makeApi({ '/personas': [persona()], '/skills': SKILLS })
    const { result } = renderHook(() => useTeam(api))

    await waitFor(() => expect(result.current.loaded).toBe(true))
    expect(result.current.personas).toHaveLength(1)
    expect(result.current.skills.skills.map((s) => s.name)).toEqual(['ui-ux-pro', 'motion-graphics'])

    const failing = makeApi({ '/personas': new ApiError(500, 'boom', { detail: 'database down' }), '/skills': SKILLS })
    const { result: broken } = renderHook(() => useTeam(failing))
    await waitFor(() => expect(broken.current.loaded).toBe(true))
    expect(broken.current.error).toContain('database down')
    expect(broken.current.personas).toEqual([])
  })

  it('treats a malformed answer as empty rather than crashing', async () => {
    const api = makeApi({ '/personas': 'nonsense', '/skills': null })
    const { result } = renderHook(() => useTeam(api))

    await waitFor(() => expect(result.current.loaded).toBe(true))
    expect(result.current.personas).toEqual([])
    expect(result.current.skills.skills).toEqual([])
  })
})

describe('PersonaList', () => {
  it('lists the team with what you changed, selects and starts a new one', () => {
    const team = makeTeam({
      personas: [persona(), persona({ id: 'backend', name: 'Backend', source: 'customized' }), persona({ id: 'motion', name: 'Motion', source: 'custom' })]
    })
    const onSelect = vi.fn()
    const onNew = vi.fn()
    render(<PersonaList team={team} selectedId="backend" onSelect={onSelect} onNew={onNew} />)

    expect(screen.getByRole('button', { name: /Backend/ })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: /Backend/ })).toHaveTextContent('edited')
    expect(screen.getByRole('button', { name: /Motion/ })).toHaveTextContent('yours')
    expect(screen.getByRole('button', { name: /Designer/ })).not.toHaveTextContent('edited')
    fireEvent.click(screen.getByRole('button', { name: /Motion/ }))
    fireEvent.click(screen.getByRole('button', { name: 'New persona' }))
    expect(onSelect).toHaveBeenCalledWith('motion')
    expect(onNew).toHaveBeenCalled()
  })
})

describe('PersonaEditor', () => {
  it('shows the persona, its skills with the ones it has ticked, and any skill folder that failed', () => {
    render(<PersonaEditor api={makeApi()} team={makeTeam()} persona={persona()} onRemoved={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'Designer' })).toBeInTheDocument()
    expect(screen.getByText(/worker · version 1 · as shipped/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /ui-ux-pro/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /motion-graphics/ })).not.toBeChecked()
    expect(screen.getByText(/Skipped broken: broken: there is no SKILL.md/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled() // nothing changed
    expect(screen.queryByRole('button', { name: 'Reset to default' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
  })

  it('saves new instructions and an added skill, then reloads the team', async () => {
    const api = makeApi({ '/personas/designer': persona({ version: 2, source: 'customized' }) })
    const team = makeTeam()
    render(<PersonaEditor api={api} team={team} persona={persona()} onRemoved={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Instructions'), { target: { value: 'You are the motion designer.' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /motion-graphics/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(team.reload).toHaveBeenCalled())
    expect(api.put).toHaveBeenCalledWith('/personas/designer', {
      name: 'Designer',
      instructions: 'You are the motion designer.',
      skills: ['ui-ux-pro', 'motion-graphics']
    })
    expect(await screen.findByRole('status')).toHaveTextContent('The next job uses this version')
  })

  it("shows the server's reason when a save is refused and keeps what you typed", async () => {
    const api = makeApi({ '/personas/designer': new ApiError(422, 'invalid', { detail: 'no such skill: ghost' }) })
    render(<PersonaEditor api={api} team={makeTeam()} persona={persona()} onRemoved={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Motion' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('no such skill: ghost')
    expect(screen.getByLabelText('Name')).toHaveValue('Motion')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  })

  it('warns about a skill that no longer exists so it can be unticked', () => {
    const team = makeTeam()
    render(
      <PersonaEditor
        api={makeApi()}
        team={team}
        persona={persona({ skills: ['ui-ux-pro', 'ghost'], missing_skills: ['ghost'] })}
        onRemoved={vi.fn()}
      />
    )

    expect(screen.getByRole('alert')).toHaveTextContent('Not found, so never offered: ghost')
  })

  it('resets an edited built-in persona to its default after confirming', async () => {
    const api = makeApi({ '/personas/designer': persona() })
    const team = makeTeam()
    render(<PersonaEditor api={api} team={team} persona={persona({ source: 'customized', version: 3 })} onRemoved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Reset to default' }))

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/personas/designer'))
    expect(window.confirm).toHaveBeenCalled()
    await waitFor(() => expect(team.reload).toHaveBeenCalled())

    vi.mocked(window.confirm).mockReturnValueOnce(false)
    fireEvent.click(screen.getByRole('button', { name: 'Reset to default' }))
    expect(api.delete).toHaveBeenCalledTimes(1) // declined: nothing happens
  })

  it('deletes a persona you made and tells the screen it is gone', async () => {
    const api = makeApi({ '/personas/motion': undefined })
    const onRemoved = vi.fn()
    render(<PersonaEditor api={api} team={makeTeam()} persona={persona({ id: 'motion', name: 'Motion', source: 'custom' })} onRemoved={onRemoved} />)

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(onRemoved).toHaveBeenCalled())
    expect(api.delete).toHaveBeenCalledWith('/personas/motion')
  })

  it('shows the version history', async () => {
    const api = makeApi({
      '/personas/designer/versions': [
        { version: 2, snapshot: { skills: ['a', 'b'] }, created_at: '2026-11-20T10:00:00Z' },
        { version: 1, snapshot: { skills: ['a'] }, created_at: '2026-11-19T10:00:00Z' }
      ]
    })
    render(<PersonaEditor api={api} team={makeTeam()} persona={persona({ version: 2, source: 'customized' })} onRemoved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Version history' }))

    const list = await screen.findByRole('list', { name: 'Versions' })
    expect(list).toHaveTextContent('Version 2')
    expect(list).toHaveTextContent('2 skills')
    expect(list).toHaveTextContent('Version 1')
  })

  it('follows the saved persona when another one is picked', () => {
    const { rerender } = render(<PersonaEditor api={makeApi()} team={makeTeam()} persona={persona()} onRemoved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Half typed' } })

    rerender(<PersonaEditor api={makeApi()} team={makeTeam()} persona={persona({ id: 'backend', name: 'Backend', instructions: 'Backend text here, long enough.' })} onRemoved={vi.fn()} />)

    expect(screen.getByLabelText('Name')).toHaveValue('Backend')
    expect(screen.getByLabelText('Instructions')).toHaveValue('Backend text here, long enough.')
  })
})

describe('NewPersona', () => {
  it('creates a worker with an id made from its name and the skills you ticked', async () => {
    const created = persona({ id: 'motion-designer', name: 'Motion designer', source: 'custom' })
    const api = makeApi({ '/personas': created })
    const onCreated = vi.fn()
    const team = makeTeam()
    render(<NewPersona api={api} team={team} onCreated={onCreated} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Motion designer' } })
    fireEvent.change(screen.getByLabelText('Instructions'), { target: { value: 'You are the motion designer on this team.' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /motion-graphics/ }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Create persona' }))
    })

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created))
    expect(api.post).toHaveBeenCalledWith('/personas', {
      id: 'motion-designer',
      name: 'Motion designer',
      instructions: 'You are the motion designer on this team.',
      skills: ['motion-graphics']
    })
    expect(team.reload).toHaveBeenCalled()
  })

  it('needs a name, and reports a refusal', async () => {
    const api = makeApi({ '/personas': new ApiError(409, 'exists', { detail: "a persona 'backend' already exists" }) })
    render(<NewPersona api={api} team={makeTeam()} onCreated={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Create persona' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Backend' } })
    fireEvent.change(screen.getByLabelText('Instructions'), { target: { value: 'You are another backend engineer.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create persona' }))

    expect(await screen.findByRole('alert')).toHaveTextContent("a persona 'backend' already exists")
  })
})
