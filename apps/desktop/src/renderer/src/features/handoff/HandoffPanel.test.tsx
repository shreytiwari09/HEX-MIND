import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ToastProvider } from '../../components/Toasts'
import type { ApiClient } from '../../lib/api'
import { HandoffPanel, repoName } from './HandoffPanel'

const status = (extra: object = {}) => ({
  stack: 'streamlit', missing: [], gh_installed: true, gh_logged_in: true, gh_account: 'ana', remote: null, problems: [], ...extra
})

function setup(get: object, post = vi.fn(async () => ({ url: 'https://github.com/ana/calc' }))) {
  const api = { get: vi.fn(async () => get), post } as unknown as ApiClient
  render(<ToastProvider><HandoffPanel api={api} projectId="p1" projectName="My Calc App" /></ToastProvider>)
  return { api, post }
}

describe('next steps after a build', () => {
  it('turns a folder name into a name GitHub accepts', () => {
    expect(repoName('My Calc App!')).toBe('my-calc-app')
    expect(repoName('  ')).toBe('my-app')
  })

  it('offers to add the missing files, and only then to publish', async () => {
    const { post } = setup(status({ missing: ['.env.example', '.github/workflows/ci.yml'] }), vi.fn(async () => ({ created: ['.env.example'], updated: [] })) as never)
    fireEvent.click(await screen.findByRole('button', { name: 'Prepare for GitHub' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/projects/p1/handoff/prepare'))
  })

  it('asks before publishing, with the visibility named, and shows the link', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { post } = setup(status())
    expect(await screen.findByDisplayValue('my-calc-app')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Publish as ana' }))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('private GitHub repository "my-calc-app"'))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/projects/p1/handoff/publish', { name: 'my-calc-app', private: true }))
    expect(await screen.findByRole('link', { name: /github.com\/ana\/calc/ })).toBeInTheDocument()
  })

  it('blocks publishing when secrets are found, and explains a missing GitHub CLI', async () => {
    setup(status({ problems: ['.env looks like a secrets file'] }))
    expect(await screen.findByRole('alert')).toHaveTextContent('.env looks like a secrets file')
    expect(screen.getByRole('button', { name: 'Publish as ana' })).toBeDisabled()
  })

  it('says how to install and sign in to the GitHub CLI', async () => {
    setup(status({ gh_installed: false }))
    expect(await screen.findByText(/never sees your GitHub password or token/)).toBeInTheDocument()
  })
})
