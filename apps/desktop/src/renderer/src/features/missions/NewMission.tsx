import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { SearchKeyPanel, type SearchStatus } from '../settings/SearchKeyPanel'
import { describeError } from './actions'
import { planningState } from './planning'
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
  /** Reopen an idea that is being planned (picked from the missions list). */
  initialSessionId?: string | null
}

const THINKING_POLL_MS = 4000

/** Describe the idea; the PM scopes it with you and proposes a plan. */
export function NewMission({ api, projectId, onCreated, onCancel, initialSessionId }: Props) {
  const [session, setSession] = useState<ScopingSession | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Reopen a session from the list, then keep it fresh while the PM is still working on it
  // (it answers in the background, so leaving this screen never loses the idea).
  useEffect(() => {
    if (!initialSessionId) return
    api
      .get<ScopingSession>(`/scoping/${initialSessionId}`)
      .then(setSession)
      .catch((err: unknown) => setLoadError(describeError(err).message))
  }, [api, initialSessionId])
  const thinking = session !== null && planningState(session) === 'thinking'
  useEffect(() => {
    if (!thinking || !session) return
    const timer = window.setInterval(() => {
      api
        .get<ScopingSession>(`/scoping/${session.id}`)
        .then(setSession)
        .catch(() => {})
    }, THINKING_POLL_MS)
    return () => window.clearInterval(timer)
  }, [api, thinking, session?.id])
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
  const [research, setResearch] = useState(false)
  const [researchOk, setResearchOk] = useState(false)
  const [searchKey, setSearchKey] = useState<SearchStatus | null>(null)
  const [own, setOwn] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (own) {
    return <PlanJsonForm api={api} projectId={projectId} onCreated={onCreated} onCancel={() => setOwn(false)} />
  }
  if (session && thinking) {
    return <PmWorking idea={session.idea} />
  }
  if (session) {
    return <Scoping api={api} session={session} onSession={setSession} onCreated={onCreated} onClose={onCancel} />
  }
  if (initialSessionId && !loadError) {
    return <p className="mission__muted new-mission">Loading…</p>
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
          coordination: coordination === 'messaging' ? coordination : undefined,
          research: research ? true : undefined,
          research_confirmed: research ? true : undefined
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
          disabled={busy}
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
      <fieldset className="new-mission__field new-mission__research">
        <legend>Advanced research (optional)</legend>
        <label className="persona-editor__skill">
          <input type="checkbox" checked={research} onChange={(event) => setResearch(event.target.checked)} />
          <span>
            <strong>Look things up on the web before planning</strong>{' '}
            <span className="mission__muted">
              Researchers search the web and read public pages, and the PM uses what they find. Off by default;
              it costs a little more time and a few search credits.
            </span>
          </span>
        </label>
        {research && (
          <>
            <p className="mission__muted">
              The researchers can only read public websites. They cannot change your files. Your idea may shape the
              words they search for (anything that looks like a secret is removed first), and those searches go to
              Tavily. Projects whose privacy mode keeps everything on this machine cannot use it.
            </p>
            <label className="persona-editor__skill">
              <input type="checkbox" checked={researchOk} onChange={(event) => setResearchOk(event.target.checked)} />
              <span>I understand: researchers may search the web and read public websites for this mission.</span>
            </label>
            <SearchKeyPanel api={api} onStatus={setSearchKey} />
          </>
        )}
      </fieldset>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {busy && (
        <p role="status" className="new-mission__working">
          <span className="spinner" aria-hidden="true" />
          The PM is reading your idea and preparing questions or a plan. On free models this can take one to three
          minutes. You can leave this screen: the idea stays under <strong>Being planned</strong> in the list, and
          every step shows live in <strong>Agent Events</strong> below.
        </p>
      )}
      {loadError && (
        <p role="alert" className="mission__error">
          {loadError}
        </p>
      )}
      <div className="new-mission__actions">
        <button
          type="submit"
          className="button button--primary"
          disabled={
            busy || idea.trim().length < 3 || (research && (!researchOk || searchKey?.configured !== true))
          }
          title={
            research && searchKey?.configured !== true
              ? 'Add a search key first'
              : research && !researchOk
                ? 'Confirm that researchers may use the web'
                : undefined
          }
        >
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

/** Shown while the PM works on an idea, before its first answer. */
function PmWorking({ idea }: { idea: string }) {
  return (
    <section className="new-mission" aria-label="Scoping">
      <h2 className="mission__title">Scoping with the PM</h2>
      <p className="mission__muted">{idea}</p>
      <p role="status" className="new-mission__working">
        <span className="spinner" aria-hidden="true" />
        The PM is reading your idea and preparing questions or a plan. On free models this can take one to three
        minutes. This page updates by itself; every step shows live in <strong>Agent Events</strong> below.
      </p>
    </section>
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
