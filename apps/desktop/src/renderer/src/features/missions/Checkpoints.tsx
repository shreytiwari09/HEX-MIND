import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError, restoreCheckpoint } from './actions'
import type { Checkpoint, Mission } from './types'

interface Props {
  api: ApiClient
  missionId: string
  checkpoints: Checkpoint[]
  canRestore: boolean
  onRestored: (mission: Mission) => void
}

/** One commit per finished feature, with "Restore to here" (PRD S7). */
export function Checkpoints({ api, missionId, checkpoints, canRestore, onRestored }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const restore = async (checkpoint: Checkpoint) => {
    const sure = window.confirm(
      `Restore the mission to “${checkpoint.label}”? Features after it start over, and the mission pauses so you can resume.`
    )
    if (!sure) return
    setBusy(true)
    setError(null)
    try {
      onRestored(await restoreCheckpoint(api, missionId, checkpoint.commit))
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  if (checkpoints.length === 0) return <p className="mission__muted">No checkpoints yet. One is saved after each feature.</p>
  return (
    <>
      <ol className="checkpoints" aria-label="Checkpoints">
        {checkpoints.map((checkpoint) => (
          <li key={checkpoint.commit} className="checkpoints__item">
            <span className="checkpoints__label">{checkpoint.label}</span>
            <code className="checkpoints__commit">{checkpoint.commit.slice(0, 7)}</code>
            {canRestore && checkpoint.feature_id !== null && (
              <button
                type="button"
                className="button button--small"
                disabled={busy}
                onClick={() => void restore(checkpoint)}
              >
                Restore to here
              </button>
            )}
          </li>
        ))}
      </ol>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
    </>
  )
}
