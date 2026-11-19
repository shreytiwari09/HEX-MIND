import type { ApiClient } from '../../lib/api'
import { ConnectionsPanel } from './ConnectionsPanel'
import { TeamPanel } from './TeamPanel'
import { useModelsData } from './useModelsData'

export type ModelsTab = 'connections' | 'team'

interface Props {
  api: ApiClient
  tab: ModelsTab
}

/** Models & Keys (PRD S3): the providers you connect, and which model each persona uses. */
export function ModelsScreen({ api, tab }: Props) {
  const data = useModelsData(api)
  return (
    <section className="models" aria-label="Models and keys">
      <h2 className="mission__title">{tab === 'connections' ? 'Connections' : 'Team models'}</h2>
      {data.error && (
        <p role="alert" className="mission__error">
          Could not load: {data.error}
        </p>
      )}
      {!data.loaded ? (
        <p className="mission__muted">Loading…</p>
      ) : tab === 'connections' ? (
        <ConnectionsPanel api={api} data={data} />
      ) : (
        <TeamPanel api={api} data={data} />
      )}
    </section>
  )
}
