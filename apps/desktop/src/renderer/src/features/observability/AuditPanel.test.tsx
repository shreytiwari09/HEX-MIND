import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient } from '../../lib/api'
import { AuditPanel } from './AuditPanel'

const HEAD = 'a'.repeat(64)
const run = (extra: object = {}) => ({ run_id: 'r1', ok: true, events: 42, head: HEAD, legacy: 0, broken: null, ...extra })

function makeApi(answer: unknown) {
  return {
    get: vi.fn(async () => {
      if (answer instanceof Error) throw answer
      return answer
    })
  } as unknown as ApiClient & { get: ReturnType<typeof vi.fn> }
}

describe('AuditPanel', () => {
  it('verifies the run when it opens and shows the head hash to keep', async () => {
    const api = makeApi({ ok: true, runs: [run()] })
    render(<AuditPanel api={api} runId="r1" />)

    expect(await screen.findByRole('status')).toHaveTextContent('Intact. 42 events')
    expect(screen.getByText(HEAD)).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/audit/verify', { run_id: 'r1' })
  })

  it('says where the log was changed and what happened', async () => {
    const api = makeApi({
      ok: false,
      runs: [run({ ok: false, broken: { seq: 7, reason: 'its content was changed after it was written' } })]
    })
    render(<AuditPanel api={api} runId="r1" />)

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('Not intact. At event 7: its content was changed after it was written.')
    expect(status).toHaveAttribute('data-ok', 'false')
  })

  it('mentions events from before the chain existed', async () => {
    render(<AuditPanel api={makeApi({ ok: true, runs: [run({ legacy: 3 })] })} runId="r1" />)

    expect(await screen.findByRole('status')).toHaveTextContent('3 older events are from before the chain existed')
  })

  it('checks against a head hash you recorded, only when it is a real hash', async () => {
    const api = makeApi({ ok: true, runs: [run()] })
    render(<AuditPanel api={api} runId="r1" />)
    await screen.findByRole('status')
    const button = screen.getByRole('button', { name: 'Check against it' })
    expect(button).toBeDisabled()

    fireEvent.change(screen.getByLabelText('A head hash you recorded earlier'), { target: { value: 'not a hash' } })
    expect(button).toBeDisabled()
    fireEvent.change(screen.getByLabelText('A head hash you recorded earlier'), { target: { value: ` ${'b'.repeat(64)} ` } })
    expect(button).toBeEnabled()
    fireEvent.click(button)

    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/verify', { run_id: 'r1', expected_head: 'b'.repeat(64) }))
  })

  it('reports a failed check in words', async () => {
    render(<AuditPanel api={makeApi(new ApiError(404, 'x', { detail: 'run not found' }))} runId="r1" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('run not found')
  })
})
