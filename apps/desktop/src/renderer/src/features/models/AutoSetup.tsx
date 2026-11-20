import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import { ProposalRow } from './TeamPanel'
import type { AutoResult, ModelRef } from './types'
import type { ModelsData } from './useModelsData'

interface Props {
  api: ApiClient
  data: ModelsData
  onClose: () => void
}

/** After a key works: let the app pick a model for every team member, so nobody needs to know
 * model names. It shows what it would pick (and why) before saving, never replaces a model you
 * chose yourself, and every choice can be changed later on the Team models tab. */
export function AutoSetup({ api, data, onClose }: Props) {
  const [preview, setPreview] = useState<AutoResult | null>(null)
  const [done, setDone] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const label = (ref: ModelRef | null) => {
    if (!ref) return null
    const connection = data.connections.find((c) => c.id === ref.connection_id)
    return `${connection?.name ?? 'removed connection'} · ${ref.model}`
  }
  const personaName = (id: string) => data.personas.find((p) => p.id === id)?.name ?? id

  const run = async (dryRun: boolean) => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.post<AutoResult>('/assignments/auto', {
        preset: 'balanced',
        dry_run: dryRun,
        overwrite_manual: false
      })
      if (dryRun) {
        setPreview(result)
      } else {
        setPreview(null)
        setDone(result.proposals.filter((p) => p.outcome === 'saved').length)
        await data.reload()
      }
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const pickable = preview?.proposals.some((p) => p.outcome === 'would_save') ?? false
  return (
    <section className="team__auto" aria-label="Set up your team">
      <h3 className="mission__section-title">Set up your team automatically</h3>
      {done === null ? (
        <>
          <p className="mission__muted">
            You do not need to know any model names. The app looks at the models your keys can use and picks one for
            each team member, with the reason. It saves nothing until you say so, and you can change any member’s
            model later on the Team models tab.
          </p>
          {error && (
            <p role="alert" className="mission__error">
              {error}
            </p>
          )}
          {preview && (
            <>
              <ol className="team__preview" aria-label="What it would pick">
                {preview.proposals.map((p) => (
                  <ProposalRow key={p.persona_id} proposal={p} persona={personaName(p.persona_id)} label={label(p.primary)} />
                ))}
              </ol>
              {!pickable && (
                <p className="mission__muted">Nothing new to pick: every team member already has a model you chose.</p>
              )}
            </>
          )}
          <div className="new-mission__actions">
            {preview === null ? (
              <button type="button" className="button button--primary" disabled={busy} onClick={() => void run(true)}>
                Show me what it would pick
              </button>
            ) : (
              <button
                type="button"
                className="button button--primary"
                disabled={busy || !pickable}
                onClick={() => void run(false)}
              >
                Use this setup
              </button>
            )}
            <button type="button" className="button" disabled={busy} onClick={onClose}>
              Not now
            </button>
          </div>
        </>
      ) : (
        <>
          <p role="status">
            Your team is set up: {done} member{done === 1 ? '' : 's'} now have a model. To pick a model yourself, open
            the Team models tab.
          </p>
          <div className="new-mission__actions">
            <button type="button" className="button button--primary" onClick={onClose}>
              Done
            </button>
          </div>
        </>
      )}
    </section>
  )
}
