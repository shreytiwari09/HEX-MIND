import type { PluginStatus } from './types'
import type { PluginsData } from './usePlugins'

interface Props {
  data: PluginsData
  selectedId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}

export const STATUS_LABEL: Record<PluginStatus, string> = {
  disabled: 'off',
  needs_approval: 'needs your approval',
  ready: 'on'
}

/** The sidebar of the Plugins view. */
export function PluginList({ data, selectedId, onSelect, onNew }: Props) {
  return (
    <nav className="mission-list" aria-label="Plugins">
      <button type="button" className="button button--small" onClick={onNew}>
        Add plugin
      </button>
      {data.error && (
        <p role="alert" className="mission__error">
          Could not load plugins: {data.error}
        </p>
      )}
      {data.loaded && data.plugins.length === 0 && (
        <p className="mission__muted">No plugins yet. The H.E.X workspace tools are always on.</p>
      )}
      {data.plugins.map((plugin) => (
        <button
          key={plugin.id}
          type="button"
          className="mission-list__item"
          aria-current={selectedId === plugin.id ? 'true' : undefined}
          onClick={() => onSelect(plugin.id)}
        >
          <strong>{plugin.name}</strong>
          <span className="mission__muted"> · {STATUS_LABEL[plugin.status]}</span>
        </button>
      ))}
    </nav>
  )
}
