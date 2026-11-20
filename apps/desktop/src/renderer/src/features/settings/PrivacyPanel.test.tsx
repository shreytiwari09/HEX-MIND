import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { PrivacyPanel } from './PrivacyPanel'

const privacy = (extra: object = {}) => ({
  mode: 'any',
  trusted_connections: [] as string[],
  connections: [
    { id: 'c1', name: 'OpenAI', local: false },
    { id: 'c2', name: 'LM Studio', local: true },
    { id: 'c3', name: 'Anthropic', local: false }
  ],
  ...extra
})

function makeApi(get: unknown, put: unknown = undefined) {
  return {
    get: vi.fn(async () => {
      if (get instanceof Error) throw get
      return get
    }),
    put: vi.fn(async (_path: string, _body: unknown) => {
      if (put instanceof Error) throw put
      return put
    })
  } as unknown as ApiClient & { put: ReturnType<typeof vi.fn>; get: ReturnType<typeof vi.fn> }
}

describe('PrivacyPanel', () => {
  it("shows the project's mode and what each option means, with Save off until something changes", async () => {
    render(<PrivacyPanel api={makeApi(privacy({ mode: 'local' }))} projectId="p1" projectName="Todo app" />)

    expect(await screen.findByRole('heading', { name: 'Privacy for Todo app' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Local models only/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /Any provider/ })).not.toBeChecked()
    expect(screen.getByText(/Plugins with network access do not run/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.queryByText('Trusted connections')).toBeNull()
  })

  it('lets you trust some connections and saves the choice; local ones are not listed', async () => {
    const saved = privacy({ mode: 'trusted', trusted_connections: ['c1'] })
    const api = makeApi(privacy(), saved)
    render(<PrivacyPanel api={api} projectId="p1" projectName="Todo app" />)
    fireEvent.click(await screen.findByRole('radio', { name: /Trusted providers/ }))

    expect(screen.getByRole('checkbox', { name: 'OpenAI' })).not.toBeChecked()
    expect(screen.queryByRole('checkbox', { name: 'LM Studio' })).toBeNull() // always allowed
    fireEvent.click(screen.getByRole('checkbox', { name: 'OpenAI' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('/projects/p1/privacy', { mode: 'trusted', trusted_connections: ['c1'] })
    )
    expect(await screen.findByRole('status')).toHaveTextContent('applies to the next model call')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('does not send a trusted list for any other mode', async () => {
    const api = makeApi(privacy({ mode: 'trusted', trusted_connections: ['c1'] }), privacy({ mode: 'local' }))
    render(<PrivacyPanel api={api} projectId="p1" projectName="Todo app" />)

    fireEvent.click(await screen.findByRole('radio', { name: /Local models only/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.put).toHaveBeenCalledWith('/projects/p1/privacy', { mode: 'local', trusted_connections: [] }))
  })

  it('says so when there are no remote connections to trust', async () => {
    const api = makeApi(privacy({ connections: [{ id: 'c2', name: 'LM Studio', local: true }] }))
    render(<PrivacyPanel api={api} projectId="p1" projectName="Todo app" />)

    fireEvent.click(await screen.findByRole('radio', { name: /Trusted providers/ }))

    expect(screen.getByText(/no remote connections yet/)).toBeInTheDocument()
  })

  it('reports a failed load and a refused save', async () => {
    const { unmount } = render(
      <PrivacyPanel api={makeApi(new ApiError(404, 'x', { detail: 'project not found' }))} projectId="p1" projectName="Todo app" />
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('project not found')
    unmount()

    const api = makeApi(privacy(), new ApiError(422, 'x', { detail: 'no such connection: c9' }))
    render(<PrivacyPanel api={api} projectId="p1" projectName="Todo app" />)
    fireEvent.click(await screen.findByRole('radio', { name: /Local models only/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('no such connection: c9')
    expect(screen.getByRole('radio', { name: /Local models only/ })).toBeChecked() // what you chose stays
  })
})
