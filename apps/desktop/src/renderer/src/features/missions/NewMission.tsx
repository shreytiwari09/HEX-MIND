import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from './actions'
import { Scoping } from './Scoping'
import type { Mission, ScopingSession } from './types'

/**
 * A small two-milestone plan for the "write the plan yourself" path: milestones, each with
 * features for a worker persona (data, backend, designer, frontend, devops) and the validators
 * to run (code-reviewer, security, qa).
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

/** Describe the idea; the PM scopes it with you and proposes a plan. */
export function NewMission({ api, projectId, onCreated, onCancel }: Props) {
  const [session, setSession] = useState<ScopingSession | null>(null)
  const [idea, setIdea] = useState('')
  const [budget, setBudget] = useState('')
  const [variantId, setVariantId] = useState('')
  const [coordination, setCoordination] = useState<'blackboard' | 'messaging'>('blackboard')
  const [variants, setVariants] = useState<{ id: string; name: string }[]>([])

  // Prompt variants (PRD §11.5): optional named configurations to run the mission under.
  useEffect(() => {
    api
      .get<{ id: string; name: string }[]>('/variants')
      .then((list) => setVariants(Array.isArray(list) ? list : []))
      .catch(() => setVariants([]))
  }, [api])
  const [own, setOwn] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (own) {
    return <PlanJsonForm api={api} projectId={projectId} onCreated={onCreated} onCancel={() => setOwn(false)} />
  }
  if (session) {
    return <Scoping api={api} session={session} onSession={setSession} onCreated={onCreated} onClose={onCancel} />
  }

  const start = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    const amount = budget.trim() === '' ? undefined : Number(budget)
    if (amount !== undefined && !(amount > 0)) {
      setError('The budget must be a positive number of dollars, or empty for none.')
      return
    }
    setBusy(true)
    try {
      setSession(
        await api.post<ScopingSession>('/scoping', {
          project_id: projectId,
          idea: idea.trim(),
          budget_usd: amount,
          variant_id: variantId || undefined,
          coordination: coordination === 'messaging' ? coordination : undefined
        })
      )
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="new-mission" onSubmit={(event) => void start(event)}>
      <h2 className="mission__title">New mission</h2>
      <p className="mission__muted">
        The PM asks a few questions, then proposes a plan you can review and edit. The team works in an
        isolated copy of your project: nothing changes in your files until you apply the result.
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
      {variants.length > 0 && (
        <label className="new-mission__field">
          Prompt variant (optional)
          <select value={variantId} onChange={(event) => setVariantId(event.target.value)}>
            <option value="">None: the team as it is</option>
            {variants.map((variant) => (
              <option key={variant.id} value={variant.id}>
                {variant.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="new-mission__field">
        How the team shares work
        <select
          value={coordination}
          onChange={(event) => setCoordination(event.target.value as 'blackboard' | 'messaging')}
        >
          <option value="blackboard">Shared board: everyone can read the plan and the handoffs</option>
          <option value="messaging">Messages only: each agent gets just what the orchestrator sends</option>
        </select>
      </label>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {busy && (
        <p role="status" className="mission__muted">
          The PM is reading your idea…
        </p>
      )}
      <div className="new-mission__actions">
        <button type="submit" className="button button--primary" disabled={busy || idea.trim().length < 3}>
          Start scoping
        </button>
        <button type="button" className="button" onClick={() => setOwn(true)}>
          Write the plan myself
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function PlanJsonForm({ api, projectId, onCreated, onCancel }: Props) {
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
