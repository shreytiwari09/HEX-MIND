import { fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import type { TeamData } from '../agents/useTeam'
import type { TeamPersona } from '../agents/types'
import { NewPlugin } from './NewPlugin'
import { PluginList } from './PluginList'
import { PluginPanel } from './PluginPanel'
import type { Plugin } from './types'
import { usePlugins, type PluginsData } from './usePlugins'

const plugin = (extra: Partial<Plugin> = {}): Plugin => ({
  id: 'notes',
  name: 'Notes',
  description: 'Keeps notes.',
  config: { transport: 'stdio', image: 'node:22-alpine', command: 'node /work/server.js', mount: 'read', network: 'none', allow_hosts: [], url: null },
  permissions: ['runs commands', 'reads files'],
  needs_approval: false,
  reasons: [],
  approved: false,
  approved_at: null,
  enabled: false,
  status: 'disabled',
  personas: [],
  config_hash: 'abc',
  ...extra
})

const risky = (extra: Partial<Plugin> = {}) =>
  plugin({
    id: 'web',
    name: 'Web helper',
    config: { transport: 'stdio', image: 'node:22-alpine', command: 'node s.js', mount: 'none', network: 'allowlist', allow_hosts: ['api.example.com'], url: null },
    permissions: ['runs commands', 'network'],
    needs_approval: true,
    reasons: ['it can send data to api.example.com'],
    status: 'needs_approval',
    ...extra
  })

const persona = (extra: Partial<TeamPersona> = {}): TeamPersona => ({
  id: 'backend',
  name: 'Backend engineer',
  kind: 'worker',
  skills: [],
  plugins: [],
  instructions: 'You are the backend engineer on this team.',
  version: 1,
  source: 'builtin',
  missing_skills: [],
  ...extra
})

function makeData(extra: Partial<PluginsData> = {}): PluginsData {
  return { plugins: [plugin()], options: { images: ['node:22-alpine', 'python:3.11-slim'] }, loaded: true, error: null, reload: vi.fn(async () => {}), ...extra }
}

function makeTeam(personas: TeamPersona[] = [persona(), persona({ id: 'qa', name: 'QA', kind: 'validator' })]): TeamData {
  return { personas, skills: { skills: [], problems: {} }, loaded: true, error: null, reload: vi.fn(async () => {}) }
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
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
  }
}

beforeEach(() => {
  window.confirm = vi.fn(() => true)
})

describe('usePlugins', () => {
  it('loads the plugins and the images a new one may use, and survives bad answers', async () => {
    const api = makeApi({ '/plugins': [plugin()], '/plugins/options': { images: ['node:22-alpine'] } })
    const { result } = renderHook(() => usePlugins(api))
    await waitFor(() => expect(result.current.loaded).toBe(true))
    expect(result.current.plugins).toHaveLength(1)
    expect(result.current.options.images).toEqual(['node:22-alpine'])

    const odd = makeApi({ '/plugins': 'nonsense', '/plugins/options': null })
    const { result: again } = renderHook(() => usePlugins(odd))
    await waitFor(() => expect(again.current.loaded).toBe(true))
    expect(again.current.plugins).toEqual([])
    expect(again.current.options.images).toEqual([])

    const failing = makeApi({ '/plugins': new ApiError(500, 'x', { detail: 'database down' }), '/plugins/options': { images: [] } })
    const { result: broken } = renderHook(() => usePlugins(failing))
    await waitFor(() => expect(broken.current.loaded).toBe(true))
    expect(broken.current.error).toContain('database down')
  })
})

describe('PluginList', () => {
  it('shows each plugin with its state and says the built-in tools are always on', () => {
    const onSelect = vi.fn()
    const onNew = vi.fn()
    const { rerender } = render(
      <PluginList data={makeData({ plugins: [plugin(), risky(), plugin({ id: 'on', name: 'On one', enabled: true, status: 'ready' })] })} selectedId="web" onSelect={onSelect} onNew={onNew} />
    )

    expect(screen.getByRole('button', { name: /Web helper/ })).toHaveTextContent('needs your approval')
    expect(screen.getByRole('button', { name: /Web helper/ })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: /On one/ })).toHaveTextContent('on')
    fireEvent.click(screen.getByRole('button', { name: /Notes/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Add plugin' }))
    expect(onSelect).toHaveBeenCalledWith('notes')
    expect(onNew).toHaveBeenCalled()

    rerender(<PluginList data={makeData({ plugins: [] })} selectedId={null} onSelect={onSelect} onNew={onNew} />)
    expect(screen.getByText(/workspace tools are always on/)).toBeInTheDocument()
  })
})

describe('PluginPanel', () => {
  it('shows what a low-risk plugin can do and turns it on without any approval step', async () => {
    const api = makeApi({ '/plugins/notes/enable': plugin({ enabled: true, status: 'ready' }) })
    const data = makeData()
    render(<PluginPanel api={api} data={data} team={makeTeam()} plugin={plugin()} onRemoved={vi.fn()} />)

    const labels = screen.getByRole('list', { name: 'Permissions' })
    expect(within(labels).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['runs commands', 'reads files'])
    expect(screen.getByText('node /work/server.js')).toBeInTheDocument()
    expect(screen.getByText('read only')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Approval' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Turn on' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/plugins/notes/enable'))
    await waitFor(() => expect(data.reload).toHaveBeenCalled())
  })

  it('blocks a risky plugin until you review and approve exactly its permissions', async () => {
    const api = makeApi({ '/plugins/web/approve': risky({ approved: true, status: 'disabled' }) })
    const data = makeData({ plugins: [risky()] })
    render(<PluginPanel api={api} data={data} team={makeTeam()} plugin={risky()} onRemoved={vi.fn()} />)

    const approval = screen.getByRole('region', { name: 'Approval' })
    expect(approval).toHaveTextContent('Needs your approval')
    expect(approval).toHaveTextContent('It can send data to api.example.com')
    expect(screen.getByText('only api.example.com')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Turn on' })).toBeDisabled() // blocked

    fireEvent.click(screen.getByRole('button', { name: 'Review and approve' }))
    expect(screen.getByText(/You are approving exactly this: runs commands, network/)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled() // reviewing is not approving
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/plugins/web/approve', { permissions: ['runs commands', 'network'] })
    )
    await waitFor(() => expect(data.reload).toHaveBeenCalled())
  })

  it('can decline to approve', () => {
    const api = makeApi()
    render(<PluginPanel api={api} data={makeData()} team={makeTeam()} plugin={risky()} onRemoved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Review and approve' }))
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }))

    expect(screen.getByRole('button', { name: 'Review and approve' })).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('says it is approved for this exact configuration and lets an approved plugin be turned on', () => {
    render(
      <PluginPanel
        api={makeApi()}
        data={makeData()}
        team={makeTeam()}
        plugin={risky({ approved: true, approved_at: '2026-11-20T10:00:00Z', status: 'disabled' })}
        onRemoved={vi.fn()}
      />
    )

    expect(screen.getByText(/Approved on .* for this exact configuration/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Approval' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Turn on' })).toBeEnabled()
  })

  it('attaches the plugin to builders only, and detaching keeps the others', async () => {
    const api = makeApi({ '/personas/backend': persona() })
    const team = makeTeam([persona({ plugins: ['other'] }), persona({ id: 'qa', name: 'QA', kind: 'validator' })])
    render(<PluginPanel api={api} data={makeData()} team={team} plugin={plugin()} onRemoved={vi.fn()} />)

    expect(screen.queryByRole('checkbox', { name: 'QA' })).toBeNull() // validators cannot have plugins yet
    fireEvent.click(screen.getByRole('checkbox', { name: 'Backend engineer' }))

    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/personas/backend', { plugins: ['other', 'notes'] }))
    await waitFor(() => expect(team.reload).toHaveBeenCalled())
  })

  it('detaches, and cannot delete while it is attached', async () => {
    const api = makeApi({ '/personas/backend': persona() })
    const team = makeTeam([persona({ plugins: ['notes'] })])
    render(<PluginPanel api={api} data={makeData()} team={team} plugin={plugin({ personas: ['backend'] })} onRemoved={vi.fn()} />)

    expect(screen.getByRole('checkbox', { name: 'Backend engineer' })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
    expect(screen.getByText(/Detach it from the team before deleting/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Backend engineer' }))

    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/personas/backend', { plugins: [] }))
  })

  it('deletes an unattached plugin after confirming', async () => {
    const api = makeApi({ '/plugins/notes': undefined })
    const onRemoved = vi.fn()
    render(<PluginPanel api={api} data={makeData()} team={makeTeam()} plugin={plugin()} onRemoved={onRemoved} />)

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(onRemoved).toHaveBeenCalled())
    expect(api.delete).toHaveBeenCalledWith('/plugins/notes')
  })

  it("shows the server's reason when an action is refused", async () => {
    const api = makeApi({ '/plugins/notes/enable': new ApiError(409, 'x', { detail: 'it needs your approval first' }) })
    render(<PluginPanel api={api} data={makeData()} team={makeTeam()} plugin={plugin()} onRemoved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Turn on' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('it needs your approval first')
  })

  it('shows a remote plugin by its address', () => {
    const remote = plugin({
      id: 'remote',
      name: 'Remote',
      config: { transport: 'http', image: null, command: null, mount: 'none', network: 'allowlist', allow_hosts: ['mcp.example.com'], url: 'https://mcp.example.com/mcp' },
      permissions: ['network']
    })
    render(<PluginPanel api={makeApi()} data={makeData()} team={makeTeam()} plugin={remote} onRemoved={vi.fn()} />)

    expect(screen.getByText('https://mcp.example.com/mcp')).toBeInTheDocument()
    expect(screen.getByText(/remote server/)).toBeInTheDocument()
    expect(screen.queryByText('Image')).toBeNull()
  })
})

describe('NewPlugin', () => {
  it('adds a sandboxed plugin with the first allowed image and no network by default', async () => {
    const created = plugin({ id: 'my-notes', name: 'My notes' })
    const api = makeApi({ '/plugins': created })
    const onCreated = vi.fn()
    const data = makeData()
    render(<NewPlugin api={api} data={data} onCreated={onCreated} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My notes' } })
    fireEvent.change(screen.getByLabelText('Command'), { target: { value: 'node /work/server.js' } })
    fireEvent.change(screen.getByLabelText('Project files it can see'), { target: { value: 'read' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add plugin' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created))
    expect(api.post).toHaveBeenCalledWith('/plugins', {
      id: 'my-notes',
      name: 'My notes',
      description: '',
      config: { transport: 'stdio', image: 'node:22-alpine', command: 'node /work/server.js', mount: 'read', network: 'none', allow_hosts: [] }
    })
    expect(data.reload).toHaveBeenCalled()
  })

  it('asks for the hosts when it needs the internet and sends them as a list', async () => {
    const api = makeApi({ '/plugins': plugin() })
    render(<NewPlugin api={api} data={makeData()} onCreated={vi.fn()} onCancel={vi.fn()} />)

    expect(screen.queryByLabelText('Hosts it may reach')).toBeNull()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Web' } })
    fireEvent.change(screen.getByLabelText('Command'), { target: { value: 'node s.js' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /needs the internet/ }))
    fireEvent.change(screen.getByLabelText('Hosts it may reach'), { target: { value: 'api.example.com, cdn.example.com' } })
    fireEvent.change(screen.getByLabelText('Image'), { target: { value: 'python:3.11-slim' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add plugin' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post.mock.calls[0][1]).toMatchObject({
      config: { image: 'python:3.11-slim', network: 'allowlist', allow_hosts: ['api.example.com', 'cdn.example.com'] }
    })
  })

  it('adds a remote plugin by its address only', async () => {
    const api = makeApi({ '/plugins': plugin() })
    render(<NewPlugin api={api} data={makeData()} onCreated={vi.fn()} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Remote' } })
    fireEvent.change(screen.getByLabelText('Where it runs'), { target: { value: 'http' } })
    expect(screen.queryByLabelText('Command')).toBeNull()
    fireEvent.change(screen.getByLabelText('Address'), { target: { value: 'https://mcp.example.com/mcp' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add plugin' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post.mock.calls[0][1]).toMatchObject({ config: { transport: 'http', url: 'https://mcp.example.com/mcp' } })
  })

  it("reports the server's refusal and keeps what you typed", async () => {
    const api = makeApi({ '/plugins': new ApiError(422, 'x', { detail: "image 'ubuntu' is not allowed" }) })
    render(<NewPlugin api={api} data={makeData()} onCreated={vi.fn()} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Notes' } })
    fireEvent.change(screen.getByLabelText('Command'), { target: { value: 'node s.js' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add plugin' }))

    expect(await screen.findByRole('alert')).toHaveTextContent("image 'ubuntu' is not allowed")
    expect(screen.getByLabelText('Command')).toHaveValue('node s.js')
  })
})
