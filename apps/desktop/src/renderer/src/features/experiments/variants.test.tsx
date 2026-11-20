import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '../../lib/api'
import { VariantManager, describeOverride, type Variant } from './VariantManager'

const TEAM = [
  { id: 'backend', name: 'Backend', kind: 'worker', skills: [], plugins: [], instructions: '', version: 1, source: 'builtin', missing_skills: [] },
  { id: 'qa', name: 'QA', kind: 'worker', skills: [], plugins: [], instructions: '', version: 1, source: 'builtin', missing_skills: [] }
]
const SKILLS = { skills: [{ name: 'tdd', description: '', source: 'builtin', version: '1', files: [], personas: [], origin: null }], problems: {} }
const TERSE: Variant = {
  id: 'terse',
  name: 'Terse backend',
  description: 'shorter instructions',
  personas: { backend: { instructions: 'Be brief.', skills: [] } },
  missions: 0,
  updated_at: ''
}
const USED: Variant = { ...TERSE, id: 'used', name: 'Used', missions: 2 }

function makeApi(variants: Variant[]) {
  return {
    get: vi.fn(async (path: string) => (path === '/variants' ? variants : path === '/personas' ? TEAM : SKILLS)),
    post: vi.fn(async () => ({})),
    delete: vi.fn(async () => undefined)
  } as unknown as ApiClient & { post: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn> }
}

describe('describeOverride', () => {
  it('says what is changed in plain words', () => {
    expect(describeOverride({ instructions: 'x', skills: null })).toBe('own instructions')
    expect(describeOverride({ instructions: null, skills: [] })).toBe('skills off')
    expect(describeOverride({ instructions: null, skills: ['tdd'] })).toBe('skills: tdd')
    expect(describeOverride({ instructions: null, skills: null })).toBe('no change')
  })
})

describe('VariantManager', () => {
  it('lists variants with what they change, and does not offer to delete one that was used', async () => {
    render(<VariantManager api={makeApi([TERSE, USED])} />)

    expect(await screen.findByText('Terse backend')).toBeInTheDocument()
    expect(screen.getAllByText(/backend: own instructions; skills off/).length).toBe(2)
    expect(screen.getByRole('button', { name: 'Delete terse' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Delete used' })).toBeDisabled()
  })

  it('deletes an unused variant', async () => {
    const api = makeApi([TERSE])
    render(<VariantManager api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete terse' }))

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/variants/terse'))
  })

  it('creates a variant that changes one team member', async () => {
    const api = makeApi([])
    const changed = vi.fn()
    render(<VariantManager api={api} onChanged={changed} />)
    fireEvent.click(await screen.findByRole('button', { name: 'New variant' }))
    const form = screen.getByRole('form', { name: 'New variant' })

    fireEvent.change(within(form).getByLabelText('Id'), { target: { value: 'no-skills' } })
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'No skills' } })
    fireEvent.change(within(form).getByLabelText('Change a team member'), { target: { value: 'qa' } })
    fireEvent.change(within(form).getByLabelText('Skills'), { target: { value: 'none' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save variant' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/variants', {
        id: 'no-skills',
        name: 'No skills',
        description: '',
        personas: { qa: { instructions: null, skills: [] } }
      })
    )
    await waitFor(() => expect(changed).toHaveBeenCalled())
  })

  it('refuses a bad id, an empty variant and a row that changes nothing before calling the backend', async () => {
    const api = makeApi([])
    render(<VariantManager api={api} />)
    fireEvent.click(await screen.findByRole('button', { name: 'New variant' }))
    const form = screen.getByRole('form', { name: 'New variant' })

    fireEvent.change(within(form).getByLabelText('Id'), { target: { value: 'Bad Id' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save variant' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/lowercase letters/)

    fireEvent.change(within(form).getByLabelText('Id'), { target: { value: 'ok-id' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save variant' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/at least one team member/)

    fireEvent.change(within(form).getByLabelText('Change a team member'), { target: { value: 'qa' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save variant' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/write instructions or change the skills/)
    expect(api.post).not.toHaveBeenCalled()
  })

  it('copies a variant into a form prefilled with its changes', async () => {
    render(<VariantManager api={makeApi([USED])} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Copy used' }))
    const form = screen.getByRole('form', { name: 'New variant' })

    expect(within(form).getByLabelText('Id')).toHaveValue('used-2')
    expect(within(form).getByLabelText(/Instructions/)).toHaveValue('Be brief.')
  })
})
