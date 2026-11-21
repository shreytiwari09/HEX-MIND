import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import { isRefused, modelLabel, sortedModels } from './modelOptions'
import type { Assignment, AutoResult, ModelRef, Persona, Preset, Proposal } from './types'
import type { ModelsData } from './useModelsData'

const PRESETS: { id: Preset; label: string; help: string }[] = [
  { id: 'balanced', label: 'Balanced', help: 'Strongest model for PM and Security, the cheapest that qualifies elsewhere.' },
  { id: 'best', label: 'Best quality', help: 'The strongest model you have for every role.' },
  { id: 'cheapest', label: 'Cheapest', help: 'The lowest-cost model that still meets each role’s minimum.' },
  { id: 'private', label: 'Private', help: 'Local models only: nothing leaves your machine.' }
]

interface Props {
  api: ApiClient
  data: ModelsData
}

/** The team and the model each persona uses (PRD S2, S3): Auto with reasons, or your own choice. */
export function TeamPanel({ api, data }: Props) {
  const [preset, setPreset] = useState<Preset>('balanced')
  const [overwrite, setOverwrite] = useState(false)
  const [preview, setPreview] = useState<AutoResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const name = (ref: ModelRef | null) => {
    if (!ref) return null
    const connection = data.connections.find((c) => c.id === ref.connection_id)
    return `${connection?.name ?? 'removed connection'} · ${ref.model}`
  }
  const personaName = (id: string) => data.personas.find((p) => p.id === id)?.name ?? id

  const runAuto = async (dryRun: boolean) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await api.post<AutoResult>('/assignments/auto', {
        preset,
        dry_run: dryRun,
        overwrite_manual: overwrite
      })
      if (dryRun) {
        setPreview(result)
      } else {
        setPreview(null)
        const saved = result.proposals.filter((p) => p.outcome === 'saved').length
        setNotice(`Assigned ${saved} persona${saved === 1 ? '' : 's'} with the ${preset} preset.`)
        await data.reload()
      }
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const noModels = data.loaded && data.catalog.length === 0

  return (
    <div className="team">
      <section className="team__auto" aria-label="Auto assignment">
        <h3 className="mission__section-title">Auto assignment</h3>
        <p className="mission__muted">
          Picks a model for each persona from the models you can reach, and says why. Quality ratings are curated
          estimates, not measurements.
        </p>
        <div className="team__controls">
          <label className="new-mission__field">
            Preset
            <select value={preset} onChange={(event) => setPreset(event.target.value as Preset)}>
              {PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="team__check">
            <input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} />
            Replace my own choices too
          </label>
          <button type="button" className="button button--small" disabled={busy || noModels} onClick={() => void runAuto(true)}>
            Preview
          </button>
          <button type="button" className="button button--small button--primary" disabled={busy || noModels} onClick={() => void runAuto(false)}>
            Apply
          </button>
        </div>
        <p className="mission__muted">{PRESETS.find((p) => p.id === preset)?.help}</p>
        {noModels && <p className="mission__muted">Add and test a connection first: there are no models to choose from.</p>}
        {error && (
          <p role="alert" className="mission__error">
            {error}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {preview && (
          <ol className="team__preview" aria-label="Preview">
            {preview.proposals.map((p) => (
              <ProposalRow key={p.persona_id} proposal={p} persona={personaName(p.persona_id)} label={name(p.primary)} />
            ))}
          </ol>
        )}
      </section>

      <table className="team__table" aria-label="Team">
        <thead>
          <tr>
            <th>Persona</th>
            <th>Model</th>
            <th>Set by</th>
            <th>Budget per mission</th>
          </tr>
        </thead>
        <tbody>
          {data.personas.map((persona) => (
            <TeamRow
              key={persona.id}
              api={api}
              data={data}
              persona={persona}
              assignment={data.assignments.find((a) => a.persona_id === persona.id)}
              describe={name}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ProposalRow({ proposal, persona, label }: { proposal: Proposal; persona: string; label: string | null }) {
  return (
    <li className="team__proposal" data-outcome={proposal.outcome}>
      <strong>{persona}</strong>{' '}
      {proposal.outcome === 'kept_manual' ? (
        <span className="mission__muted">kept: you chose this one</span>
      ) : proposal.primary ? (
        <span>→ {label}</span>
      ) : (
        <span className="mission__muted">no model</span>
      )}
      {proposal.outcome !== 'kept_manual' && <p className="mission__muted">{proposal.reason}</p>}
      {proposal.primary && !proposal.verified && <span className="team__unverified">unverified</span>}
    </li>
  )
}

function TeamRow({
  api,
  data,
  persona,
  assignment,
  describe
}: {
  api: ApiClient
  data: ModelsData
  persona: Persona
  assignment: Assignment | undefined
  describe: (ref: ModelRef | null) => string | null
}) {
  const saved = data.budgets.find((b) => b.persona_id === persona.id)?.budget_usd
  const [budget, setBudget] = useState(saved === undefined ? '' : String(saved))
  const [error, setError] = useState<string | null>(null)

  // Follow the saved value when it changes (after a reload), so the field never shows stale text.
  useEffect(() => {
    setBudget(saved === undefined ? '' : String(saved))
  }, [saved])

  const attempt = async (work: () => Promise<unknown>) => {
    setError(null)
    try {
      await work()
      await data.reload()
    } catch (err) {
      setError(describeError(err).message)
    }
  }

  const saveBudget = () => {
    const text = budget.trim()
    if (text === (saved === undefined ? '' : String(saved))) return
    if (text === '') {
      void attempt(() => api.delete(`/budgets/personas/${persona.id}`))
      return
    }
    const amount = Number(text)
    if (!(amount > 0)) {
      setError('A budget is a positive number of dollars, or empty for none.')
      return
    }
    void attempt(() => api.put(`/budgets/personas/${persona.id}`, { budget_usd: amount }))
  }

  const change = (value: string) => {
    if (!value) return
    const [connectionId, ...rest] = value.split('|')
    void attempt(() =>
      api.put(`/assignments/${persona.id}`, {
        primary: { connection_id: connectionId, model: rest.join('|') },
        fallbacks: assignment?.fallbacks ?? [],
        escalate: assignment?.escalate ?? null
      })
    )
  }

  return (
    <tr>
      <td>
        <strong>{persona.name}</strong>
        <div className="mission__muted">{persona.kind}</div>
      </td>
      <td>
        {assignment ? (
          <>
            <div>{describe(assignment.primary)}</div>
            <div className="mission__muted">
              {assignment.fallbacks.length > 0 && `${assignment.fallbacks.length} fallback${assignment.fallbacks.length === 1 ? '' : 's'}`}
              {assignment.fallbacks.length > 0 && assignment.escalate && ' · '}
              {assignment.escalate && `escalates to ${describe(assignment.escalate)}`}
            </div>
          </>
        ) : (
          <span className="mission__muted">Default routing (the global provider order)</span>
        )}
        <select
          aria-label={`Model for ${persona.name}`}
          value=""
          onChange={(event) => change(event.target.value)}
          disabled={data.catalog.length === 0}
        >
          <option value="">Change model…</option>
          {sortedModels(data.catalog).map((entry) => (
            <option
              key={`${entry.connection_id}|${entry.model}`}
              value={`${entry.connection_id}|${entry.model}`}
              disabled={isRefused(entry)}
            >
              {modelLabel(entry)}
            </option>
          ))}
        </select>
        {assignment && (
          <button
            type="button"
            className="button button--small"
            onClick={() => void attempt(() => api.delete(`/assignments/${persona.id}`))}
          >
            Use default routing
          </button>
        )}
      </td>
      <td>
        {assignment ? (
          <>
            <span className="team__set-by" data-set-by={assignment.set_by}>
              {assignment.set_by === 'user' ? 'You' : 'Auto'}
            </span>
            {assignment.reason && <p className="mission__muted">{assignment.reason}</p>}
          </>
        ) : (
          <span className="mission__muted">-</span>
        )}
      </td>
      <td>
        <input
          type="number"
          min="0"
          step="0.25"
          value={budget}
          aria-label={`Budget for ${persona.name} in USD`}
          placeholder="none"
          onChange={(event) => setBudget(event.target.value)}
          onBlur={saveBudget}
          onKeyDown={(event) => {
            if (event.key === 'Enter') saveBudget()
          }}
        />
        {error && (
          <p role="alert" className="mission__error">
            {error}
          </p>
        )}
      </td>
    </tr>
  )
}
