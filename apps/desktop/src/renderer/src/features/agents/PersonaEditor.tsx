import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import type { PersonaVersionInfo, TeamPersona } from './types'
import type { TeamData } from './useTeam'

interface Props {
  api: ApiClient
  team: TeamData
  persona: TeamPersona
  /** Called after a change that removed the persona (a custom one was deleted). */
  onRemoved: () => void
}

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((value, i) => value === b[i])

/** One persona (PRD S2): its instructions and skills. Every save is a new version, and the next
 * job uses it. */
export function PersonaEditor({ api, team, persona, onRemoved }: Props) {
  const [name, setName] = useState(persona.name)
  const [instructions, setInstructions] = useState(persona.instructions)
  const [skills, setSkills] = useState(persona.skills)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [history, setHistory] = useState<PersonaVersionInfo[] | null>(null)

  // Follow the saved persona (after a save, a reset, or picking another one).
  useEffect(() => {
    setName(persona.name)
    setInstructions(persona.instructions)
    setSkills(persona.skills)
    setHistory(null)
  }, [persona.id, persona.version, persona.name, persona.instructions, persona.skills])

  const dirty =
    name !== persona.name || instructions !== persona.instructions || !sameList(skills, persona.skills)

  const attempt = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await work()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    attempt(async () => {
      await api.put(`/personas/${persona.id}`, { name, instructions, skills })
      await team.reload()
      setNotice('Saved. The next job uses this version.')
    })

  const reset = () => {
    if (!window.confirm(`Reset ${persona.name} to its default instructions and skills?`)) return
    return attempt(async () => {
      await api.delete(`/personas/${persona.id}`)
      await team.reload()
      setNotice('Back to the default.')
    })
  }

  const remove = () => {
    if (!window.confirm(`Delete ${persona.name}?`)) return
    return attempt(async () => {
      await api.delete(`/personas/${persona.id}`)
      await team.reload()
      onRemoved()
    })
  }

  const showHistory = () =>
    attempt(async () => {
      setHistory(await api.get<PersonaVersionInfo[]>(`/personas/${persona.id}/versions`))
    })

  const toggle = (skill: string) =>
    setSkills((current) => (current.includes(skill) ? current.filter((s) => s !== skill) : [...current, skill]))

  const known = new Set(team.skills.skills.map((s) => s.name))
  const orphaned = skills.filter((s) => !known.has(s))

  return (
    <section className="persona-editor" aria-label={`Persona ${persona.name}`}>
      <h2 className="mission__title">{persona.name}</h2>
      <p className="mission__muted">
        {persona.kind} · version {persona.version} ·{' '}
        {persona.source === 'builtin' ? 'as shipped' : persona.source === 'customized' ? 'edited by you' : 'made by you'}
      </p>

      <label className="new-mission__field">
        Name
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="new-mission__field">
        Instructions
        <textarea rows={10} value={instructions} onChange={(event) => setInstructions(event.target.value)} />
      </label>

      <fieldset className="persona-editor__skills">
        <legend>Skills</legend>
        <p className="mission__muted">
          The agent sees one line per skill and loads the full text only when it needs it.
        </p>
        {team.skills.skills.map((skill) => (
          <label key={skill.name} className="persona-editor__skill">
            <input type="checkbox" checked={skills.includes(skill.name)} onChange={() => toggle(skill.name)} />
            <span>
              <strong>{skill.name}</strong>{' '}
              <span className="mission__muted">{skill.source === 'user' ? 'yours' : 'built-in'}</span>
              <span className="mission__muted"> · {skill.description}</span>
            </span>
          </label>
        ))}
        {orphaned.length > 0 && (
          <p role="alert" className="mission__error">
            Not found, so never offered: {orphaned.join(', ')}. Untick to remove.
          </p>
        )}
        {Object.entries(team.skills.problems).map(([folder, reason]) => (
          <p key={folder} className="mission__muted">
            Skipped {folder}: {reason}
          </p>
        ))}
      </fieldset>
      <p className="mission__muted">Plugins arrive with the plugin manager.</p>

      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mission__muted">
          {notice}
        </p>
      )}
      <div className="new-mission__actions">
        <button type="button" className="button button--primary" disabled={busy || !dirty} onClick={() => void save()}>
          Save changes
        </button>
        {persona.source === 'customized' && (
          <button type="button" className="button" disabled={busy} onClick={() => void reset()}>
            Reset to default
          </button>
        )}
        {persona.source === 'custom' && (
          <button type="button" className="button" disabled={busy} onClick={() => void remove()}>
            Delete
          </button>
        )}
        <button type="button" className="button" disabled={busy} onClick={() => void showHistory()}>
          Version history
        </button>
      </div>

      {history && (
        <ol className="persona-editor__history" aria-label="Versions">
          {history.length === 0 ? (
            <li className="mission__muted">No edits yet: this is the default.</li>
          ) : (
            history.map((version) => (
              <li key={version.version}>
                Version {version.version} · {new Date(version.created_at).toLocaleString()} ·{' '}
                {version.snapshot.skills?.length ?? 0} skills
              </li>
            ))
          )}
        </ol>
      )}
    </section>
  )
}
