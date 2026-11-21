import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from '../../lib/api'
import { MissionList } from './MissionList'
import { isOpenPlanning, planningState } from './planning'
import type { ScopingSession } from './types'

function session(extra: Partial<ScopingSession> = {}): ScopingSession {
  return {
    id: 's1', project_id: 'p1', run_id: 'r1', idea: 'A Streamlit calculator', status: 'asking', messages: [],
    plan: null, prd: null, error: null, budget_usd: null, mission_id: null, cost_usd: 0,
    created_at: '2026-11-22T00:00:00Z', updated_at: '2026-11-22T00:00:00Z', ...extra
  }
}

const pm = { role: 'pm' as const, content: 'A few questions', questions: ['Who is it for?'], at: '' }
const you = { role: 'user' as const, content: 'Students', at: '' }

describe('ideas being planned', () => {
  it('says whether the PM is working, waiting for you, done, or stopped', () => {
    expect(planningState(session())).toBe('thinking')
    expect(planningState(session({ messages: [pm] }))).toBe('asking')
    expect(planningState(session({ messages: [pm, you] }))).toBe('thinking')
    expect(planningState(session({ status: 'planned', messages: [pm] }))).toBe('planned')
    expect(planningState(session({ error: 'model failed' }))).toBe('failed')
  })

  it('lists only ideas not yet started or abandoned', () => {
    expect(isOpenPlanning(session())).toBe(true)
    expect(isOpenPlanning(session({ status: 'started', mission_id: 'm1' }))).toBe(false)
    expect(isOpenPlanning(session({ status: 'abandoned' }))).toBe(false)
  })

  it('shows an idea the PM is planning in the missions list, and opens it on click', async () => {
    const api = {
      get: vi.fn(async (path: string) => (path === '/scoping' ? [session({ messages: [pm] })] : []))
    } as unknown as ApiClient
    const onSelectPlanning = vi.fn()

    render(
      <MissionList api={api} projectId="p1" selectedId={null} refreshKey={0} onSelect={vi.fn()} onSelectPlanning={onSelectPlanning} onNew={vi.fn()} />
    )

    await waitFor(() => expect(screen.getByText('Being planned')).toBeInTheDocument())
    expect(screen.getByText('Waiting for your answers')).toBeInTheDocument()
    expect(screen.queryByText('No missions yet')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('A Streamlit calculator'))
    expect(onSelectPlanning).toHaveBeenCalledWith('s1')
  })
})
