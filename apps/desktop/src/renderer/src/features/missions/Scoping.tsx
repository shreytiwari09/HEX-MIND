import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from './actions'
import { formatUsd } from './progress'
import { ResearchNotes } from './ResearchNotes'
import type { Mission, MissionPlanDoc, ScopingSession } from './types'

interface Props {
  api: ApiClient
  session: ScopingSession
  onSession: (session: ScopingSession) => void
  onCreated: (mission: Mission) => void
  onClose: () => void
}

/** The PM scoping chat, and once the PM has a plan, the plan review (PRD F2). */
export function Scoping({ api, session, onSession, onCreated, onClose }: Props) {
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (what: string, action: () => Promise<void>) => {
    setBusy(what)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(null)
    }
  }

  const send = (event: React.FormEvent) => {
    event.preventDefault()
    const content = reply.trim()
    if (!content) return
    void run('PM is thinking…', async () => {
      onSession(await api.post<ScopingSession>(`/scoping/${session.id}/messages`, { content }))
      setReply('')
    })
  }

  const planned = session.status === 'planned' && session.plan !== null
  return (
    <section className="new-mission" aria-label="Scoping">
      <h2 className="mission__title">{planned ? 'Review the plan' : 'Scoping with the PM'}</h2>
      <p className="mission__muted">
        {session.idea} · cost so far {formatUsd(session.cost_usd)}
        {(session.unpriced_calls ?? 0) > 0 &&
          ` (not counting ${session.unpriced_calls} call${session.unpriced_calls === 1 ? '' : 's'} with no known price)`}
      </p>

      <ol className="scoping__chat" aria-label="Conversation">
        {session.messages.map((message, index) => (
          <li key={index} className={`scoping__message scoping__message--${message.role}`}>
            <span className="scoping__who">{message.role === 'user' ? 'You' : 'PM'}</span>
            <p>{message.content}</p>
            {message.questions && message.questions.length > 0 && (
              <ul>
                {message.questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      {session.research && session.research_notes && <ResearchNotes notes={session.research_notes} />}

      {session.error && (
        <div role="alert" className="mission__error">
          <p>The PM could not answer: {session.error}</p>
          <button
            type="button"
            className="button"
            disabled={busy !== null}
            onClick={() =>
              void run('PM is thinking…', async () =>
                onSession(await api.post<ScopingSession>(`/scoping/${session.id}/retry`))
              )
            }
          >
            Try again
          </button>
        </div>
      )}

      {planned && (
        <PlanReview
          key={session.updated_at}
          api={api}
          session={session}
          onSession={onSession}
          onCreated={onCreated}
        />
      )}

      <form className="scoping__reply" onSubmit={send}>
        <label className="new-mission__field">
          {planned ? 'Ask the PM to change the plan' : 'Your answer'}
          <textarea rows={3} value={reply} onChange={(event) => setReply(event.target.value)} />
        </label>
        <div className="new-mission__actions">
          <button type="submit" className="button" disabled={busy !== null || reply.trim() === ''}>
            Send
          </button>
          <button
            type="button"
            className="button"
            disabled={busy !== null}
            onClick={() =>
              void run('Discarding…', async () => {
                await api.post(`/scoping/${session.id}/abandon`)
                onClose()
              })
            }
          >
            Discard
          </button>
        </div>
      </form>
      {busy && (
        <p role="status" className="mission__muted">
          {busy}
        </p>
      )}
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
    </section>
  )
}

function PlanReview({
  api,
  session,
  onSession,
  onCreated
}: {
  api: ApiClient
  session: ScopingSession
  onSession: (session: ScopingSession) => void
  onCreated: (mission: Mission) => void
}) {
  const plan = session.plan as MissionPlanDoc
  const [prd, setPrd] = useState(session.prd ?? '')
  const [budget, setBudget] = useState(session.budget_usd === null ? '' : String(session.budget_usd))
  const [planText, setPlanText] = useState(() => JSON.stringify(plan, null, 2))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty =
    prd !== (session.prd ?? '') ||
    budget !== (session.budget_usd === null ? '' : String(session.budget_usd)) ||
    planText !== JSON.stringify(plan, null, 2)

  const save = async () => {
    setError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(planText)
    } catch (err) {
      setError(`The plan is not valid JSON: ${err instanceof Error ? err.message : String(err)}`)
      return
    }
    const amount = budget.trim() === '' ? null : Number(budget)
    if (amount !== null && !(amount > 0)) {
      setError('The budget must be a positive number of dollars, or empty for none.')
      return
    }
    setBusy(true)
    try {
      onSession(
        await api.put<ScopingSession>(`/scoping/${session.id}/plan`, {
          plan: parsed,
          prd: prd.trim() === '' ? null : prd,
          budget_usd: amount
        })
      )
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      onCreated(await api.post<Mission>(`/scoping/${session.id}/mission`))
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const contract = plan.validation_contract ?? []
  return (
    <div className="plan-review" role="region" aria-label="Plan">
      <h3>{plan.title}</h3>

      <label className="new-mission__field">
        What will be built (PRD)
        <textarea rows={8} value={prd} onChange={(event) => setPrd(event.target.value)} />
      </label>

      <h4>Milestones and features</h4>
      <ol className="plan-review__milestones">
        {plan.milestones.map((milestone) => (
          <li key={milestone.id}>
            <strong>{milestone.title}</strong>
            <span className="mission__muted">
              {' '}
              · checked by {milestone.validators.length > 0 ? milestone.validators.join(', ') : 'nobody'}
            </span>
            <ul>
              {milestone.features.map((feature) => (
                <li key={feature.id}>
                  {feature.title} <span className="mission__muted">({feature.persona})</span>
                  <ul>
                    {feature.expected_behavior.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>

      <h4>Validation contract</h4>
      {contract.length === 0 ? (
        <p className="mission__muted">No criteria: the milestones are checked by tests and reviews only.</p>
      ) : (
        <ul className="plan-review__contract">
          {contract.map((criterion) => (
            <li key={criterion.id}>
              <code>{criterion.id}</code> {criterion.text}{' '}
              <span className="mission__muted">[{criterion.how}]</span>
              {criterion.how === 'browser' && (
                <span className="mission__muted"> · not checked automatically yet</span>
              )}
            </li>
          ))}
        </ul>
      )}

      <label className="new-mission__field">
        Budget in USD (optional)
        <input type="number" min="0" step="0.5" value={budget} onChange={(event) => setBudget(event.target.value)} />
      </label>

      <details>
        <summary>Edit the plan as JSON</summary>
        <label className="new-mission__field">
          Plan (JSON)
          <textarea
            className="new-mission__plan"
            rows={14}
            spellCheck={false}
            value={planText}
            onChange={(event) => setPlanText(event.target.value)}
          />
        </label>
      </details>

      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      <div className="new-mission__actions">
        <button type="button" className="button" disabled={busy || !dirty} onClick={() => void save()}>
          Save changes
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={busy || dirty}
          title={dirty ? 'Save your changes first' : undefined}
          onClick={() => void create()}
        >
          Create mission
        </button>
      </div>
      <p className="mission__muted">
        The mission opens waiting for your approval; nothing is built until you approve it.
      </p>
    </div>
  )
}
