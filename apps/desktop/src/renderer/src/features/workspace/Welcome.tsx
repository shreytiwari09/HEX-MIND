import { Check, FolderOpen, KeyRound, Rocket } from 'lucide-react'

import { BrandMark } from '../../components/BrandMark'
import type { BackendStatus } from '../../hooks/useBackendHealth'
import { shortcutLabel } from '../palette/commands'
import type { Workspace } from './useWorkspace'

interface Props {
  status: BackendStatus
  workspace: Workspace
  /** True once at least one model connection exists; null while unknown. */
  hasModels?: boolean | null
  onOpenModels?: () => void
  onStartMission?: () => void
}

export const PROVIDER_LABELS: Record<string, string> = {
  ollama: 'Ollama (local)',
  groq: 'Groq',
  gemini: 'Gemini'
}

/** "/Users/ana/projects/calc" → "~/projects/calc"; long paths keep their start and end. */
export function shortPath(path: string, max = 64): string {
  const home = path.replace(/^\/(Users|home)\/[^/]+/, '~').replace(/^[A-Z]:\\Users\\[^\\]+/i, '~')
  if (home.length <= max) return home
  const keep = Math.floor((max - 1) / 2)
  return `${home.slice(0, keep)}…${home.slice(home.length - keep)}`
}

export function Welcome({ status, workspace, hasModels = null, onOpenModels, onStartMission }: Props) {
  const connected = status.kind === 'connected'
  const health = connected ? status.health : null
  const providers = health ? Object.values(health.providers) : []
  const project = workspace.project

  const steps = [
    {
      done: hasModels === true,
      icon: KeyRound,
      title: 'Connect a model',
      text: 'Add a key for any provider (free ones work). Auto then picks a model for each agent.',
      action: onOpenModels && { label: 'Models & Keys', run: onOpenModels }
    },
    {
      done: project !== null,
      icon: FolderOpen,
      title: 'Open a project folder',
      text: 'An empty folder for a new app, or an existing project. Agents work in a copy until you apply.',
      action: { label: 'Open folder', run: () => void workspace.pickAndOpen() }
    },
    {
      done: false,
      icon: Rocket,
      title: 'Describe what to build',
      text: 'Start a mission: the PM plans it, the team builds and tests it, you review and apply.',
      action: project && onStartMission ? { label: 'New mission', run: onStartMission } : undefined
    }
  ]

  return (
    <div className="welcome">
      <div className="welcome__hero">
        <BrandMark size={56} />
        <div>
          <h1 className="welcome__title">H.E.X Mind</h1>
          <p className="welcome__subtitle">
            {project ? `${project.name} is open. Pick a file, ask the team in chat, or start a mission.` : 'Your AI software team: describe an idea, and a PM, engineers, QA and security build, test and hand it back.'}
          </p>
        </div>
      </div>

      <div className="welcome__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={!connected}
          title={connected ? undefined : 'Backend is not connected'}
          onClick={() => void workspace.pickAndOpen()}
        >
          <FolderOpen size={16} />
          Open folder
          <kbd className="kbd kbd--on-accent">{shortcutLabel('Mod+O')}</kbd>
        </button>
        <span className="welcome__hint">
          or press <kbd className="kbd">{shortcutLabel('Mod+K')}</kbd> for every command
        </span>
      </div>
      {workspace.error && (
        <p className="welcome__error" role="alert">
          Could not open workspace: {workspace.error}
        </p>
      )}

      <section className="welcome__section" aria-label="Get started">
        <h2 className="welcome__heading">Get started</h2>
        <ol className="steps">
          {steps.map((step, i) => (
            <li key={step.title} className="step" data-done={step.done}>
              <span className="step__marker" aria-hidden="true">
                {step.done ? <Check size={14} /> : i + 1}
              </span>
              <div className="step__body">
                <span className="step__title">
                  {step.title}
                  {step.done && <span className="visually-hidden"> (done)</span>}
                </span>
                <span className="step__text">{step.text}</span>
              </div>
              {step.action && !step.done && (
                <button type="button" className="button button--small" disabled={!connected} onClick={step.action.run}>
                  {step.action.label}
                </button>
              )}
            </li>
          ))}
        </ol>
      </section>

      {workspace.recent.length > 0 && (
        <section className="welcome__section" aria-label="Recent workspaces">
          <h2 className="welcome__heading">Recent</h2>
          <ul className="recent">
            {workspace.recent.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className="recent__item"
                  title={p.workspace_path}
                  onClick={() => void workspace.open(p.workspace_path)}
                >
                  <span className="recent__name">{p.name}</span>
                  <span className="recent__path">{shortPath(p.workspace_path)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="welcome__section" aria-label="Readiness">
        <h2 className="welcome__heading">Readiness</h2>
        <dl className="readiness">
          <ReadinessRow label="Backend" ok={connected} value={health ? `Ready (v${health.version})` : 'Not ready'} />
          <ReadinessRow
            label="Database"
            ok={health?.db === 'ok'}
            value={health ? (health.db === 'ok' ? 'Connected' : 'Unavailable') : 'Unknown'}
          />
          {providers.map((p) => (
            <ReadinessRow
              key={p.provider}
              label={PROVIDER_LABELS[p.provider] ?? p.provider}
              ok={p.available}
              value={p.available ? p.model : p.configured === false ? 'Not configured' : 'Unavailable'}
              detail={p.detail ?? undefined}
            />
          ))}
        </dl>
      </section>
    </div>
  )
}

function ReadinessRow({ label, ok, value, detail }: { label: string; ok: boolean; value: string; detail?: string }) {
  return (
    <div className="readiness__row">
      <dt>{label}</dt>
      <dd data-ok={ok} title={detail}>
        {value}
      </dd>
    </div>
  )
}
