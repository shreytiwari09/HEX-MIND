import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { applyMission, describeError, postAction, type ErrorText } from './actions'
import { actionsFor } from './progress'
import type { Mission, MissionDiff } from './types'

interface Props {
  api: ApiClient
  mission: Mission
  onChanged: (mission: Mission) => void
}

const CHANGE_LABEL = { added: 'new', modified: 'changed', deleted: 'removed' } as const

/**
 * Finish a mission (PRD F4): review the changes, then apply them to the project, keep them on
 * the mission branch, or discard them. Revert is available after applying. Nothing touches the
 * user's files until Apply.
 */
export function ApplyPanel({ api, mission, onChanged }: Props) {
  const actions = actionsFor(mission.status)
  const [diff, setDiff] = useState<MissionDiff | null>(null)
  const [includeMissionFiles, setIncludeMissionFiles] = useState(true)
  const [commit, setCommit] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ErrorText | null>(null)

  const run = async (work: () => Promise<Mission>) => {
    setBusy(true)
    setError(null)
    try {
      onChanged(await work())
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  const loadDiff = async () => {
    setError(null)
    try {
      setDiff(await api.get<MissionDiff>(`/missions/${mission.id}/diff`))
    } catch (err) {
      setError(describeError(err))
    }
  }

  const discard = () => {
    if (window.confirm('Discard this mission? Its branch and working copy are deleted.')) {
      void run(() => postAction(api, mission.id, 'discard'))
    }
  }

  const revert = () => {
    if (window.confirm('Revert the changes this mission made to your project?')) {
      void run(() => postAction(api, mission.id, 'revert'))
    }
  }

  return (
    <section className="apply-panel" aria-label="Finish the mission">
      {mission.apply?.state === 'applied' ? (
        <p className="apply-panel__summary">
          Applied to your project: {mission.apply.files.length} file(s)
          {mission.apply.commit ? ` in commit ${mission.apply.commit.slice(0, 7)}` : ', not committed'}.
          {mission.apply.commit_error && ` The commit failed: ${mission.apply.commit_error}`}
        </p>
      ) : (
        <p className="apply-panel__summary">
          {mission.apply?.state === 'reverted' ? 'Reverted. You can apply it again. ' : ''}
          The team is finished. Nothing in your project has changed yet.
        </p>
      )}

      <div className="apply-panel__actions">
        <button type="button" className="button button--small" onClick={() => void loadDiff()}>
          {diff ? 'Refresh changes' : 'Review changes'}
        </button>
        {actions.apply && (
          <button
            type="button"
            className="button button--small button--primary"
            disabled={busy}
            onClick={() =>
              void run(() =>
                applyMission(api, mission.id, { include_mission_files: includeMissionFiles, commit })
              )
            }
          >
            Apply to my project
          </button>
        )}
        {actions.keep && (
          <button
            type="button"
            className="button button--small"
            disabled={busy}
            onClick={() => void run(() => postAction(api, mission.id, 'keep'))}
          >
            Keep on branch
          </button>
        )}
        {actions.revert && (
          <button type="button" className="button button--small" disabled={busy} onClick={revert}>
            Revert
          </button>
        )}
        {actions.discard && (
          <button type="button" className="button button--small" disabled={busy} onClick={discard}>
            Discard
          </button>
        )}
      </div>

      {actions.apply && (
        <div className="apply-panel__options">
          <label>
            <input
              type="checkbox"
              checked={includeMissionFiles}
              onChange={(event) => setIncludeMissionFiles(event.target.checked)}
            />
            Include the mission&apos;s notes and plan (.hex/)
          </label>
          <label>
            <input type="checkbox" checked={commit} onChange={(event) => setCommit(event.target.checked)} />
            Save as a commit on my current branch
          </label>
        </div>
      )}

      {error && (
        <div role="alert" className="mission__error">
          <p>{error.message}</p>
          {error.paths.length > 0 && (
            <ul>
              {error.paths.map((path) => (
                <li key={path}>
                  <code>{path}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {diff && (
        <ul className="apply-panel__files" aria-label="Changed files">
          {diff.files.map((file) => (
            <li key={file.path}>
              <details>
                <summary>
                  <code>{file.path}</code>
                  <span className="apply-panel__change" data-change={file.change_type}>
                    {CHANGE_LABEL[file.change_type]}
                  </span>
                </summary>
                <pre className="apply-panel__diff">{file.diff}</pre>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
