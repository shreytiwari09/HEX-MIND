import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { answerNeed, describeError } from './actions'
import type { Mission, Need } from './types'

const OPTION_LABEL: Record<string, string> = {
  retry: 'Retry',
  skip: 'Skip this feature',
  stop: 'Stop the mission',
  raise_budget: 'Raise budget',
  accept: 'Accept and continue'
}

const KIND_TITLE: Record<Need['kind'], string> = {
  feature_failed: 'A feature could not be finished',
  provider_unavailable: 'No model could answer',
  budget_reached: 'The budget is used up',
  persona_budget_reached: 'A persona reached its budget',
  milestone_failed: 'A milestone did not pass validation',
  validator_unavailable: 'A validator could not check the milestone'
}

interface Props {
  api: ApiClient
  needs: Need[]
  onAnswered: (mission: Mission) => void
}

/** The queue of decisions the mission is waiting on (PRD S5). */
export function NeedsYou({ api, needs, onAnswered }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [budget, setBudget] = useState('')

  const answer = async (need: Need, action: string) => {
    setBusy(need.id)
    setError(null)
    try {
      const amount = action === 'raise_budget' ? Number(budget) : undefined
      if (action === 'raise_budget' && !(amount && amount > 0)) {
        setError('Enter the new budget in dollars.')
        return
      }
      onAnswered(await answerNeed(api, need.id, action, amount))
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(null)
    }
  }

  if (needs.length === 0) return null
  return (
    <section className="needs-you" aria-label="Needs you">
      <h3 className="needs-you__title">Needs you ({needs.length})</h3>
      {needs.map((need) => {
        const findings = typeof need.evidence.last_findings === 'string' ? need.evidence.last_findings : ''
        return (
          <article key={need.id} className="needs-you__item">
            <h4 className="needs-you__kind">{KIND_TITLE[need.kind] ?? need.kind}</h4>
            <p className="needs-you__summary">{need.summary}</p>
            {findings && <pre className="needs-you__evidence">{findings}</pre>}
            {Array.isArray(need.evidence.findings) && need.evidence.findings.length > 0 && (
              <ul className="needs-you__findings" aria-label="Findings">
                {need.evidence.findings.map((item) => (
                  <li key={String(item)}>{String(item)}</li>
                ))}
              </ul>
            )}
            {(need.kind === 'budget_reached' || need.kind === 'persona_budget_reached') && (
              <label className="needs-you__field">
                {need.kind === 'persona_budget_reached' ? 'New budget for this persona (USD)' : 'New budget (USD)'}
                <input
                  type="number"
                  min="0"
                  step="0.5"
                  value={budget}
                  onChange={(event) => setBudget(event.target.value)}
                />
              </label>
            )}
            <div className="needs-you__options">
              {need.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={option === 'stop' ? 'button button--small' : 'button button--small button--primary'}
                  disabled={busy !== null}
                  onClick={() => void answer(need, option)}
                >
                  {OPTION_LABEL[option] ?? option}
                </button>
              ))}
            </div>
          </article>
        )
      })}
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
    </section>
  )
}
