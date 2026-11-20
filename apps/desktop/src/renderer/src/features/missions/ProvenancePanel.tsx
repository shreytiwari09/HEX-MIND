import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from './actions'

interface ModelCall {
  at: string
  purpose: string
  provider: string
  model: string
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
  request_sha256: string | null
}

interface Change {
  feature: { id: string; title: string; milestone: string | null }
  persona: { id: string; version: number }
  agent_id: string
  attempt: number
  model_used: string | null
  variant_id: string | null
  skills: { name: string; version: string; loaded: boolean }[]
  plugins: { id: string; config_hash: string; called: boolean }[]
  commit: string | null
  validated_by: { validator: string; round: number; verdict: string }[]
  model_calls: ModelCall[]
  handoff_event: { seq: number; hash: string | null } | null
}

interface Provenance {
  approval: { seq: number; ts: string; hash: string | null } | null
  files: { path: string; changes: Change[] }[]
  audit: { ok: boolean; events: number; broken: string | null }
}

interface Props {
  api: ApiClient
  missionId: string
  /** Changes when the mission's work did, to fetch again. */
  refreshKey: string
}

/** Where each changed file came from (PRD §14.2): the feature, persona version, skills, model and
 * checks behind it, and the approval it started from, read from what was recorded. */
export function ProvenancePanel({ api, missionId, refreshKey }: Props) {
  const [doc, setDoc] = useState<Provenance | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    api
      .get<Provenance>(`/missions/${missionId}/provenance`)
      .then((loaded) => {
        if (!current) return
        if (!loaded || !Array.isArray(loaded.files)) throw new Error('unexpected answer')
        setDoc(loaded)
        setError(null)
      })
      .catch((err) => current && setError(describeError(err).message))
    return () => {
      current = false
    }
  }, [api, missionId, refreshKey])

  const exportProv = async () => {
    try {
      const prov = await api.get<unknown>(`/missions/${missionId}/provenance`, { format: 'prov' })
      const url = URL.createObjectURL(new Blob([JSON.stringify(prov, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `provenance-${missionId.slice(0, 8)}.prov.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(describeError(err).message)
    }
  }

  if (error) return <p className="mission__muted">Could not load where the changes came from: {error}</p>
  if (!doc) return <p className="mission__muted">Loading…</p>
  if (doc.files.length === 0) return <p className="mission__muted">No files have been changed yet.</p>

  return (
    <div className="provenance">
      <p className="mission__muted">
        {doc.approval ? `Plan approved ${new Date(doc.approval.ts).toLocaleString()}. ` : ''}
        Audit log {doc.audit.ok ? 'intact' : `NOT intact (${doc.audit.broken ?? 'broken'})`}.
      </p>
      <ul className="provenance__files" aria-label="Changed files">
        {doc.files.map((file) => {
          const expanded = open === file.path
          const last = file.changes[file.changes.length - 1]
          return (
            <li key={file.path}>
              <button
                type="button"
                className="provenance__file"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : file.path)}
              >
                <code>{file.path}</code>{' '}
                <span className="mission__muted">
                  {last.feature.title} · {last.persona.id} v{last.persona.version}
                  {file.changes.length > 1 ? ` · +${file.changes.length - 1} earlier` : ''}
                </span>
              </button>
              {expanded && (
                <ol className="provenance__changes" aria-label={`History of ${file.path}`}>
                  {file.changes.map((change) => (
                    <li key={`${change.feature.id}:${change.attempt}`}>
                      <strong>{change.feature.title}</strong> ({change.feature.id})
                      <ul>
                        <li>
                          By {change.persona.id} version {change.persona.version}, {change.agent_id} (attempt {change.attempt})
                          {change.variant_id ? `, prompt variant ${change.variant_id}` : ''}
                        </li>
                        <li>Model: {change.model_used ?? 'unknown'} · {change.model_calls.length} model call(s)</li>
                        <li>
                          Skills offered:{' '}
                          {change.skills.length === 0
                            ? 'none'
                            : change.skills.map((s) => `${s.name}${s.loaded ? ' (loaded)' : ''}`).join(', ')}
                        </li>
                        {change.plugins.length > 0 && (
                          <li>Plugins: {change.plugins.map((p) => `${p.id}${p.called ? ' (used)' : ''}`).join(', ')}</li>
                        )}
                        <li>
                          Checked by:{' '}
                          {change.validated_by.length === 0
                            ? 'its own tests only'
                            : change.validated_by.map((v) => `${v.validator} ${v.verdict}`).join(', ')}
                        </li>
                        {change.commit && (
                          <li>
                            Commit <code>{change.commit.slice(0, 10)}</code>
                            {change.handoff_event?.hash && (
                              <>
                                {' '}
                                · audit <code>{change.handoff_event.hash.slice(0, 12)}</code>
                              </>
                            )}
                          </li>
                        )}
                      </ul>
                    </li>
                  ))}
                </ol>
              )}
            </li>
          )
        })}
      </ul>
      <button type="button" className="button button--small" onClick={() => void exportProv()}>
        Export as PROV-JSON
      </button>
    </div>
  )
}
