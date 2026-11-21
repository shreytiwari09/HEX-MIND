import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import type { GithubPreview, SkillInfo } from '../agents/types'
import type { TeamData } from '../agents/useTeam'
import { describeError } from '../missions/actions'

/** Above this a skill is called big in the preview (D70): it may not fit small free-plan limits. */
const BIG_SKILL_TOKENS = 5000

interface Props {
  api: ApiClient
  team: TeamData
  onInstalled: (skill: SkillInfo) => void
  onCancel: () => void
}

/** Add a skill from a GitHub address: you see exactly what it is, pinned to one commit, and only
 * that is installed. */
export function AddFromGithub({ api, team, onInstalled, onCancel }: Props) {
  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState<GithubPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPreview = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setPreview(null)
    try {
      setPreview(await api.post<GithubPreview>('/skills/github/preview', { url: url.trim() }))
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const install = async () => {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      const skill = await api.post<SkillInfo>('/skills/github/install', {
        url: preview.url,
        commit: preview.commit,
        hash: preview.hash,
        replace: preview.exists === 'user'
      })
      await team.reload()
      onInstalled(skill)
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="persona-editor" aria-label="Add a skill from GitHub">
      <h2 className="mission__title">Add a skill from GitHub</h2>
      <p className="mission__muted">
        Paste the address of a public repository with a SKILL.md, or of a folder in one. You will see what it
        contains before anything is saved. A skill is only text: it is never run, and agents treat it as guidance.
      </p>
      <form className="new-mission__field" onSubmit={(event) => void fetchPreview(event)}>
        <label className="new-mission__field">
          GitHub address
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://github.com/owner/repo/tree/main/skills/my-skill"
          />
        </label>
        <div className="new-mission__actions">
          <button type="submit" className="button" disabled={busy || url.trim().length < 10}>
            Look at it
          </button>
          <button type="button" className="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}

      {preview && (
        <div className="plan-review" role="region" aria-label="Preview">
          <h3>{preview.name}</h3>
          <p>{preview.description}</p>
          <p className="mission__muted">
            Pinned to commit <code>{preview.commit.slice(0, 10)}</code> of {preview.url}
            {preview.files.length > 0 && ` · also contains ${preview.files.join(', ')}`}
          </p>
          {preview.approx_tokens !== undefined && (
            <p className={preview.approx_tokens > BIG_SKILL_TOKENS ? 'mission__error' : 'mission__muted'}>
              About {preview.approx_tokens.toLocaleString('en-US')} tokens each time an agent loads it.
              {preview.approx_tokens > BIG_SKILL_TOKENS &&
                ' That is big: models with small limits (Groq’s free plan allows 8,000 tokens a minute) may not handle it, and every step costs more.'}
            </p>
          )}
          {preview.signals.length > 0 && (
            <p role="alert" className="mission__error">
              Be careful: this text looks like it is trying to give orders to an AI ({preview.signals.join(', ')}).
              Read it below before you install it.
            </p>
          )}
          {preview.exists === 'user' && (
            <p className="mission__muted">You already have a skill with this name; installing replaces it.</p>
          )}
          {preview.exists === 'builtin' && (
            <p className="mission__muted">
              A built-in skill has this name; yours will be used instead, and removing yours brings it back.
            </p>
          )}
          <pre className="skill__body" aria-label="Instructions">
            {preview.body}
          </pre>
          <div className="new-mission__actions">
            <button type="button" className="button button--primary" disabled={busy} onClick={() => void install()}>
              {preview.exists === 'user' ? 'Replace it' : 'Install'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
