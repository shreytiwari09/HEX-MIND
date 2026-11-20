import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import type { SkillDetail } from '../agents/types'
import type { TeamData } from '../agents/useTeam'
import { describeError } from '../missions/actions'

interface Props {
  api: ApiClient
  team: TeamData
  name: string
  onRemoved: () => void
}

/** One skill: what it says, where it came from and who has it. */
export function SkillPanel({ api, team, name, onRemoved }: Props) {
  const [skill, setSkill] = useState<SkillDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let current = true
    setSkill(null)
    setError(null)
    api
      .get<SkillDetail>(`/skills/${name}`)
      .then((loaded) => current && setSkill(loaded))
      .catch((err) => current && setError(describeError(err).message))
    return () => {
      current = false
    }
  }, [api, name, team.skills])

  const remove = async () => {
    if (!window.confirm(`Remove ${name}?`)) return
    setBusy(true)
    setError(null)
    try {
      await api.delete(`/skills/${name}`)
      await team.reload()
      onRemoved()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="persona-editor" aria-label={`Skill ${name}`}>
      <h2 className="mission__title">{name}</h2>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {skill && (
        <>
          <p className="mission__muted">
            {skill.source === 'builtin' ? 'Built in' : skill.origin ? 'From GitHub' : 'Your own'} · {skill.version}
          </p>
          <p>{skill.description}</p>
          {skill.origin && (
            <p className="mission__muted">
              {skill.origin.url} · pinned to commit <code>{skill.origin.commit.slice(0, 10)}</code>
            </p>
          )}
          <p className="mission__muted">
            {skill.personas.length > 0
              ? `Given to: ${skill.personas.join(', ')}`
              : 'Not given to anyone yet: tick it on a team member in Agents.'}
          </p>
          {skill.files.length > 0 && <p className="mission__muted">Files: {skill.files.join(', ')}</p>}
          <h3 className="mission__section-title">Instructions</h3>
          <pre className="skill__body" aria-label="Instructions">
            {skill.body}
          </pre>
          {skill.source === 'user' && (
            <div className="new-mission__actions">
              <button type="button" className="button" disabled={busy} onClick={() => void remove()}>
                Remove
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
