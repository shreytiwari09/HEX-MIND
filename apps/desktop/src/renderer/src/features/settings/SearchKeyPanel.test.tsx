import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { SearchKeyPanel } from './SearchKeyPanel'

const KEY = 'tvly-secret-key-0123456789'

function makeApi(handlers: Record<string, unknown>) {
  const respond = async (path: string) => {
    const value = handlers[path]
    if (value instanceof Error) throw value
    return value
  }
  return {
    get: vi.fn(respond),
    post: vi.fn(async (path: string) => respond(path)),
    put: vi.fn(async (path: string, _body: unknown) => respond(path)),
    delete: vi.fn(async (path: string) => respond(path))
  } as unknown as ApiClient & Record<'get' | 'post' | 'put' | 'delete', ReturnType<typeof vi.fn>>
}

const status = (configured: boolean, source: 'keychain' | 'env' | null) => ({ provider: 'tavily', configured, source })

describe('SearchKeyPanel', () => {
  it('says there is no key, and only lets you save once something is typed', async () => {
    render(<SearchKeyPanel api={makeApi({ '/research/search': status(false, null) })} />)

    expect(await screen.findByText('No search key is set yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save key' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Test search/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Remove key' })).toBeNull()
    expect(screen.getByLabelText('Tavily API key')).toHaveAttribute('type', 'password')
  })

  it('saves the key, clears the field and never shows the key again', async () => {
    const api = makeApi({
      '/research/search': status(false, null),
      '/research/search/key': status(true, 'keychain')
    })
    const seen: string[] = []
    render(<SearchKeyPanel api={api} onStatus={(s) => seen.push(String(s.configured))} />)
    fireEvent.change(await screen.findByLabelText('Tavily API key'), { target: { value: KEY } })
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }))

    expect(await screen.findByText(/A search key is set \(saved in your computer’s key store\)/)).toBeInTheDocument()
    expect(api.put).toHaveBeenCalledWith('/research/search/key', { api_key: KEY })
    expect(screen.getByLabelText('Tavily API key')).toHaveValue('')
    expect(document.body.textContent).not.toContain(KEY)
    expect(seen).toEqual(['false', 'true'])
    expect(screen.getByRole('button', { name: 'Remove key' })).toBeInTheDocument()
  })

  it('a key from the .env file is shown as such and cannot be removed here', async () => {
    render(<SearchKeyPanel api={makeApi({ '/research/search': status(true, 'env') })} />)

    expect(await screen.findByText(/read from the backend’s \.env file/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove key' })).toBeNull()
    expect(screen.getByRole('button', { name: /Test search/ })).toBeEnabled()
  })

  it('removes a saved key', async () => {
    const api = makeApi({
      '/research/search': status(true, 'keychain'),
      '/research/search/key': status(false, null)
    })
    render(<SearchKeyPanel api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Remove key' }))

    expect(await screen.findByText('No search key is set yet.')).toBeInTheDocument()
    expect(api.delete).toHaveBeenCalledWith('/research/search/key')
  })

  it('tests the search and reports what Tavily counted, or n/a-style wording when it did not say', async () => {
    const api = makeApi({
      '/research/search': status(true, 'env'),
      '/research/search/test': { ok: true, error: null, credits: 1 }
    })
    const { unmount } = render(<SearchKeyPanel api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: /Test search/ }))
    expect(await screen.findByText(/The search works. Tavily counted 1 credit/)).toBeInTheDocument()
    unmount()

    const unknown = makeApi({
      '/research/search': status(true, 'env'),
      '/research/search/test': { ok: true, error: null, credits: null }
    })
    render(<SearchKeyPanel api={unknown} />)
    fireEvent.click(await screen.findByRole('button', { name: /Test search/ }))
    expect(await screen.findByText(/counted an unknown number of credit/)).toBeInTheDocument()
  })

  it('shows why a test failed, and a failed save', async () => {
    const api = makeApi({
      '/research/search': status(true, 'env'),
      '/research/search/test': { ok: false, error: 'the search key was rejected: check it or set a new one', credits: null },
      '/research/search/key': new ApiError(503, 'failed', { detail: 'no secure key store is available' })
    })
    render(<SearchKeyPanel api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: /Test search/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('the search key was rejected')

    fireEvent.change(screen.getByLabelText('Tavily API key'), { target: { value: KEY } })
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }))
    await waitFor(() => expect(screen.getByText('no secure key store is available')).toBeInTheDocument())
    expect(document.body.textContent).not.toContain(KEY)
  })
})
