import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import type { TeamPersona } from './types'
import type { TeamData } from './useTeam'

interface Props {
  api: ApiClient
  team: TeamData
  onCreated: (persona: TeamPersona) => void
  onCancel: () => void
}

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)

/** A new team member: a worker with your instructions and skills. */
export function NewPersona({ api, team, onCreated, onCancel }: Props) {
  const [name, setName] = useState('')
  const [instructions, setInstructions] = useState('')
  const [skills, setSkills] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await api.post<TeamPersona>('/personas', {
        id: slug(name),
        name: name.trim(),
        instructions: instructions.trim(),
        skills
      })
      await team.reload()
      onCreated(created)
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="persona-editor" onSubmit={(event) => void submit(event)}>
      <h2 className="mission__title">New persona</h2>
      <p className="mission__muted">
        A builder that works on features like the others. The PM can give it features, and you choose its model
        under Models &amp; Keys.
      </p>
      <label className="new-mission__field">
        Name
        <input required minLength={2} value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="new-mission__field">
        Instructions
        <textarea
          required
          minLength={20}
          rows={8}
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
          placeholder="You are the motion designer on this team. You add animation that helps, never decoration."
        />
      </label>
      <fieldset className="persona-editor__skills">
        <legend>Skills</legend>
        {team.skills.skills.map((skill) => (
          <label key={skill.name} className="persona-editor__skill">
            <input
              type="checkbox"
              checked={skills.includes(skill.name)}
              onChange={() =>
                setSkills((current) =>
                  current.includes(skill.name) ? current.filter((s) => s !== skill.name) : [...current, skill.name]
                )
              }
            />
            <span>
              <strong>{skill.name}</strong> <span className="mission__muted">{skill.description}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      <div className="new-mission__actions">
        <button type="submit" className="button button--primary" disabled={busy || slug(name).length < 2}>
          Create persona
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
