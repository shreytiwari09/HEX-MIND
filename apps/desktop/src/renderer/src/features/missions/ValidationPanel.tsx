import { useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import type { ValidatorReportView } from './types'

interface Props {
  api: ApiClient
  missionId: string
  /** Changes when a validator reported, to fetch again. */
  refreshKey: string
}

const VERDICT_LABEL = { pass: 'Passed', fail: 'Found problems', needs_user: 'Could not check' } as const
const VERDICT_TONE = { pass: 'success', fail: 'danger', needs_user: 'warning' } as const

/**
 * What the validators found at the end of each milestone (PRD §8.5). "Could not check" is shown as
 * what it is: nothing was verified, and the milestone is not marked as passed.
 */
export function ValidationPanel({ api, missionId, refreshKey }: Props) {
  const [reports, setReports] = useState<ValidatorReportView[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<ValidatorReportView[]>(`/missions/${missionId}/validation`)
      .then((list) => {
        if (!cancelled) {
          setReports(Array.isArray(list) ? list : []) // never let a bad answer break the screen
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [api, missionId, refreshKey])

  if (error) {
    return (
      <p role="alert" className="mission__error">
        Could not load validation: {error}
      </p>
    )
  }
  if (reports === null) return <p className="mission__muted">Loading validation…</p>
  if (reports.length === 0) {
    return <p className="mission__muted">No validators have run yet. They check each milestone once its features are done.</p>
  }
  return (
    <ol className="validation" aria-label="Validator reports">
      {reports.map((report) => (
        <li key={`${report.milestone_id}|${report.validator}|${report.round}`} className="validation__report">
          <div className="validation__head">
            <strong>{report.validator}</strong>
            <span className="mission__muted">
              {report.milestone_id}, round {report.round}
            </span>
            <span className="status-pill" data-tone={VERDICT_TONE[report.verdict]}>
              <span className="status-dot" aria-hidden="true" />
              {VERDICT_LABEL[report.verdict]}
            </span>
          </div>
          {report.commands.length > 0 && (
            <ul className="validation__commands" aria-label="Commands run">
              {report.commands.map((command) => (
                <li key={command.command}>
                  <code>{command.command}</code>{' '}
                  <span data-ok={command.exit_code === 0}>{command.exit_code === 0 ? 'passed' : `exit ${command.exit_code}`}</span>
                </li>
              ))}
            </ul>
          )}
          {report.findings.length > 0 && (
            <ul className="validation__findings" aria-label="Findings">
              {report.findings.map((finding, index) => (
                <li key={index} data-severity={finding.severity}>
                  <span className="validation__severity">{finding.severity}</span>
                  {finding.file && (
                    <code>
                      {finding.file}
                      {finding.line ? `:${finding.line}` : ''}
                    </code>
                  )}{' '}
                  {finding.message}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  )
}
