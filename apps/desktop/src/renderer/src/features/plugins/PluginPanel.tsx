import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import type { TeamData } from '../agents/useTeam'
import { describeError } from '../missions/actions'
import { STATUS_LABEL } from './PluginList'
import type { Plugin } from './types'
import type { PluginsData } from './usePlugins'

interface Props {
  api: ApiClient
  data: PluginsData
  team: TeamData
  plugin: Plugin
  onRemoved: () => void
}

/** One plugin: what it can do, your approval, and which team members have it. */
export function PluginPanel({ api, data, team, plugin, onRemoved }: Props) {
  const [reviewing, setReviewing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const config = plugin.config

  const attempt = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
      await data.reload()
      await team.reload()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const approve = () =>
    attempt(async () => {
      await api.post(`/plugins/${plugin.id}/approve`, { permissions: plugin.permissions })
      setReviewing(false)
    })
  const toggle = () => attempt(async () => void (await api.post(`/plugins/${plugin.id}/${plugin.enabled ? 'disable' : 'enable'}`)))
  const remove = () => {
    if (!window.confirm(`Delete ${plugin.name}?`)) return
    return attempt(async () => {
      await api.delete(`/plugins/${plugin.id}`)
      onRemoved()
    })
  }

  // Only builders can have plugins for now (the backend refuses the rest).
  const builders = team.personas.filter((p) => p.kind === 'worker')
  const attach = (personaId: string, on: boolean) => {
    const persona = team.personas.find((p) => p.id === personaId)
    if (!persona) return
    const plugins = on ? [...persona.plugins, plugin.id] : persona.plugins.filter((id) => id !== plugin.id)
    return attempt(async () => void (await api.put(`/personas/${personaId}`, { plugins })))
  }

  return (
    <section className="persona-editor" aria-label={`Plugin ${plugin.name}`}>
      <h2 className="mission__title">{plugin.name}</h2>
      <p className="mission__muted">
        {STATUS_LABEL[plugin.status]} · {config.transport === 'stdio' ? 'runs in the sandbox' : 'remote server'}
      </p>
      {plugin.description && <p>{plugin.description}</p>}

      <h3 className="mission__section-title">What it can do</h3>
      <ul className="plugin__labels" aria-label="Permissions">
        {plugin.permissions.map((label) => (
          <li key={label} className="plugin__label">
            {label}
          </li>
        ))}
      </ul>
      <dl className="plugin__config">
        {config.transport === 'stdio' ? (
          <>
            <dt>Image</dt>
            <dd>{config.image}</dd>
            <dt>Command</dt>
            <dd>
              <code>{config.command}</code>
            </dd>
            <dt>Project files</dt>
            <dd>{config.mount === 'none' ? 'none' : config.mount === 'read' ? 'read only' : 'read and write'}</dd>
          </>
        ) : (
          <>
            <dt>Address</dt>
            <dd>{config.url}</dd>
          </>
        )}
        <dt>Network</dt>
        <dd>{config.network === 'none' ? 'none' : `only ${config.allow_hosts.join(', ')}`}</dd>
      </dl>

      {plugin.needs_approval && !plugin.approved && (
        <div className="plugin__approval" role="region" aria-label="Approval">
          <p>
            <strong>Needs your approval.</strong> {plugin.reasons.map((r) => r.charAt(0).toUpperCase() + r.slice(1)).join('. ')}.
          </p>
          {reviewing ? (
            <>
              <p className="mission__muted">
                You are approving exactly this: {plugin.permissions.join(', ')}. If you change anything that matters
                later, you will be asked again.
              </p>
              <div className="new-mission__actions">
                <button type="button" className="button button--primary" disabled={busy} onClick={() => void approve()}>
                  Approve
                </button>
                <button type="button" className="button" onClick={() => setReviewing(false)}>
                  Not now
                </button>
              </div>
            </>
          ) : (
            <button type="button" className="button" onClick={() => setReviewing(true)}>
              Review and approve
            </button>
          )}
        </div>
      )}
      {plugin.needs_approval && plugin.approved && (
        <p className="mission__muted">
          Approved{plugin.approved_at ? ` on ${new Date(plugin.approved_at).toLocaleDateString()}` : ''} for this exact
          configuration.
        </p>
      )}

      <div className="new-mission__actions">
        <button
          type="button"
          className="button button--primary"
          disabled={busy || (!plugin.enabled && plugin.status === 'needs_approval')}
          onClick={() => void toggle()}
        >
          {plugin.enabled ? 'Turn off' : 'Turn on'}
        </button>
        <button type="button" className="button" disabled={busy || plugin.personas.length > 0} onClick={() => void remove()}>
          Delete
        </button>
      </div>
      {plugin.personas.length > 0 && <p className="mission__muted">Detach it from the team before deleting it.</p>}

      <fieldset className="persona-editor__skills">
        <legend>Team members who get its tools</legend>
        <p className="mission__muted">
          A plugin runs only when it is on{plugin.needs_approval ? ' and approved' : ''}, and only for the people ticked here.
        </p>
        {builders.map((persona) => (
          <label key={persona.id} className="persona-editor__skill">
            <input
              type="checkbox"
              checked={persona.plugins.includes(plugin.id)}
              disabled={busy}
              onChange={(event) => void attach(persona.id, event.target.checked)}
            />
            <span>{persona.name}</span>
          </label>
        ))}
      </fieldset>

      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
    </section>
  )
}
