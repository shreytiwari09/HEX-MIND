import { CheckCircle2, ExternalLink, GitBranch, PackageCheck } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { useToast } from '../../components/Toasts'
import { describeError } from '../missions/actions'

const message = (err: unknown): string => describeError(err).message

interface Status {
  stack: string
  missing: string[]
  gh_installed: boolean
  gh_logged_in: boolean
  gh_account: string | null
  remote: string | null
  problems: string[]
}

interface Props {
  api: ApiClient
  projectId: string
  projectName: string
}

const DEPLOY_HINT: Record<string, string> = {
  streamlit: 'Free hosting: Streamlit Community Cloud (share.streamlit.io) deploys straight from the GitHub repository.',
  python: 'Hosting: Render or Google Cloud Run run Python apps; set your settings there, never in the code.',
  node: 'Free hosting: Netlify, Vercel or Cloudflare Pages deploy straight from the GitHub repository.',
  unknown: 'Once it is on GitHub, most hosts can deploy it straight from the repository.'
}

/** A repository name GitHub accepts, from the folder name. */
export function repoName(folder: string): string {
  return folder.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'my-app'
}

/** After a build: make the project a normal repository, then publish it (PRD D84). */
export function HandoffPanel({ api, projectId, projectName }: Props) {
  const toast = useToast()
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'prepare' | 'publish' | null>(null)
  const [name, setName] = useState(() => repoName(projectName))
  const [isPrivate, setPrivate] = useState(true)
  const [url, setUrl] = useState<string | null>(null)

  const load = useCallback(() => {
    api
      .get<Status>(`/projects/${projectId}/handoff`)
      .then((s) => {
        setStatus(s)
        setError(null)
      })
      .catch((err: unknown) => setError(message(err)))
  }, [api, projectId])
  useEffect(load, [load])

  const prepare = async () => {
    setBusy('prepare')
    try {
      const done = await api.post<{ created: string[]; updated: string[] }>(`/projects/${projectId}/handoff/prepare`)
      const count = done.created.length + done.updated.length
      toast(count ? `Added or updated ${count} file(s) in one commit.` : 'Nothing to add: the project already has them.', 'success')
      load()
    } catch (err) {
      toast(message(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  const publish = async () => {
    const visibility = isPrivate ? 'private' : 'PUBLIC (anyone can see the code)'
    if (!window.confirm(`Create a ${visibility} GitHub repository "${name}" and push this project to it?`)) return
    setBusy('publish')
    try {
      const done = await api.post<{ url: string }>(`/projects/${projectId}/handoff/publish`, { name, private: isPrivate })
      setUrl(done.url)
      toast('Published to GitHub.', 'success')
      load()
    } catch (err) {
      toast(message(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  if (error) return <p className="mission__muted">{error}</p>
  if (!status) return <p className="mission__muted">Checking the project…</p>
  const ready = status.missing.length === 0
  const published = url ?? (status.remote?.includes('github.com') ? status.remote.replace(/\.git$/, '') : null)

  return (
    <section className="handoff" aria-label="Next steps">
      <h3 className="mission__section-title">Next steps: share and deploy</h3>
      <ol className="handoff__steps">
        <li data-done={ready}>
          <div className="handoff__step-head">
            {ready ? <CheckCircle2 size={16} className="handoff__ok" aria-hidden="true" /> : <PackageCheck size={16} aria-hidden="true" />}
            <strong>Make it a normal project</strong>
          </div>
          {ready ? (
            <p className="mission__muted">It has tests on every push (GitHub Actions), dependency updates, a settings template and deploy notes.</p>
          ) : (
            <>
              <p className="mission__muted">Adds, in one commit you can undo: {status.missing.join(', ')}. Nothing you wrote is overwritten.</p>
              <button type="button" className="button button--small" disabled={busy !== null} onClick={() => void prepare()}>
                {busy === 'prepare' ? 'Adding…' : 'Prepare for GitHub'}
              </button>
            </>
          )}
        </li>
        <li data-done={published !== null}>
          <div className="handoff__step-head">
            {published ? <CheckCircle2 size={16} className="handoff__ok" aria-hidden="true" /> : <GitBranch size={16} aria-hidden="true" />}
            <strong>Put it on GitHub</strong>
          </div>
          {published ? (
            <p>
              <a href={published} target="_blank" rel="noreferrer">
                {published.replace(/^https:\/\//, '')} <ExternalLink size={12} aria-hidden="true" />
              </a>
            </p>
          ) : status.remote ? (
            <p className="mission__muted">It already has a remote ({status.remote}). Push changes with <code>git push</code>.</p>
          ) : !status.gh_installed ? (
            <p className="mission__muted">
              Install the GitHub CLI from <a href="https://cli.github.com" target="_blank" rel="noreferrer">cli.github.com</a>, then
              run <code>gh auth login</code> in a terminal. H.E.X uses your own login and never sees your GitHub password or token.
            </p>
          ) : !status.gh_logged_in ? (
            <p className="mission__muted">Run <code>gh auth login</code> in a terminal once, then come back.</p>
          ) : (
            <>
              {status.problems.length > 0 && (
                <ul className="handoff__problems" role="alert">
                  {status.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              )}
              <div className="handoff__publish">
                <label>
                  Repository name
                  <input value={name} onChange={(e) => setName(e.target.value)} spellCheck={false} />
                </label>
                <label className="handoff__check">
                  <input type="checkbox" checked={isPrivate} onChange={(e) => setPrivate(e.target.checked)} />
                  Private (only you can see it)
                </label>
                <button
                  type="button"
                  className="button button--primary button--small"
                  disabled={busy !== null || status.problems.length > 0 || !name.trim()}
                  onClick={() => void publish()}
                >
                  {busy === 'publish' ? 'Publishing…' : `Publish as ${status.gh_account ?? 'you'}`}
                </button>
              </div>
            </>
          )}
        </li>
        <li>
          <div className="handoff__step-head">
            <ExternalLink size={16} aria-hidden="true" />
            <strong>Deploy it</strong>
          </div>
          <p className="mission__muted">{DEPLOY_HINT[status.stack] ?? DEPLOY_HINT.unknown} The README now explains the steps.</p>
        </li>
      </ol>
    </section>
  )
}
