import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from './actions'
import type { Mission } from './types'

/**
 * A small two-milestone plan to try the flow. Until the PM scoping chat arrives (P5), a mission
 * starts from a plan you write: milestones, each with features for a worker persona
 * (data, backend, designer, frontend, devops) and the validators to run (code-reviewer, security, qa).
 */
export const EXAMPLE_PLAN = {
  title: 'Todo module',
  milestones: [
    {
      id: 'm1-model',
      title: 'Todo model',
      validators: ['code-reviewer'],
      features: [
        {
          id: 'todo-model',
          title: 'Todo model',
          persona: 'backend',
          description: 'Pure functions to add and toggle todos, with tests (node:test).',
          expected_behavior: ['addTodo appends a trimmed, open todo', 'toggleTodo flips done for one id'],
          target_files: ['src/todos.js', 'src/todos.test.js']
        }
      ]
    },
    {
      id: 'm2-filter',
      title: 'Filtering',
      validators: ['code-reviewer'],
      features: [
        {
          id: 'filter-helper',
          title: 'Filter helper',
          persona: 'frontend',
          description: 'Filter todos by all, active or done, with tests.',
          expected_behavior: ['filterTodos supports all, active and done'],
          target_files: ['src/filter.js', 'src/filter.test.js']
        }
      ]
    }
  ]
}

interface Props {
  api: ApiClient
  projectId: string
  onCreated: (mission: Mission) => void
  onCancel: () => void
}

export function NewMission({ api, projectId, onCreated, onCancel }: Props) {
  const [idea, setIdea] = useState('')
  const [plan, setPlan] = useState(() => JSON.stringify(EXAMPLE_PLAN, null, 2))
  const [budget, setBudget] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(plan)
    } catch (err) {
      setError(`The plan is not valid JSON: ${err instanceof Error ? err.message : String(err)}`)
      return
    }
    const amount = budget.trim() === '' ? undefined : Number(budget)
    if (amount !== undefined && !(amount > 0)) {
      setError('The budget must be a positive number of dollars, or empty for none.')
      return
    }
    setBusy(true)
    try {
      onCreated(
        await api.post<Mission>('/missions', {
          project_id: projectId,
          idea: idea.trim(),
          plan: parsed,
          budget_usd: amount
        })
      )
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="new-mission" onSubmit={(event) => void submit(event)}>
      <h2 className="mission__title">New mission</h2>
      <p className="mission__muted">
        The team works in an isolated copy of your project. Nothing changes in your files until you apply the
        result.
      </p>
      <label className="new-mission__field">
        What do you want built?
        <textarea
          rows={3}
          required
          minLength={3}
          value={idea}
          onChange={(event) => setIdea(event.target.value)}
          placeholder="A todo list with filters"
        />
      </label>
      <label className="new-mission__field">
        Budget in USD (optional)
        <input type="number" min="0" step="0.5" value={budget} onChange={(event) => setBudget(event.target.value)} />
      </label>
      <label className="new-mission__field">
        Plan (JSON)
        <textarea
          className="new-mission__plan"
          rows={16}
          spellCheck={false}
          value={plan}
          onChange={(event) => setPlan(event.target.value)}
        />
      </label>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      <div className="new-mission__actions">
        <button type="submit" className="button button--primary" disabled={busy || idea.trim().length < 3}>
          Create mission
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
