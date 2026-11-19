import type { TeamData } from './useTeam'

interface Props {
  team: TeamData
  selectedId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}

const SOURCE_LABEL = { builtin: '', customized: 'edited', custom: 'yours' } as const

/** The sidebar of the Agents view: every persona on the team. */
export function PersonaList({ team, selectedId, onSelect, onNew }: Props) {
  return (
    <nav className="mission-list" aria-label="Team">
      <button type="button" className="button button--small" onClick={onNew}>
        New persona
      </button>
      {team.error && (
        <p role="alert" className="mission__error">
          Could not load the team: {team.error}
        </p>
      )}
      {!team.loaded && <p className="mission__muted">Loading…</p>}
      {team.personas.map((persona) => (
        <button
          key={persona.id}
          type="button"
          className="mission-list__item"
          aria-current={selectedId === persona.id ? 'true' : undefined}
          onClick={() => onSelect(persona.id)}
        >
          <strong>{persona.name}</strong>
          <span className="mission__muted">
            {' '}
            {persona.kind}
            {SOURCE_LABEL[persona.source] && ` · ${SOURCE_LABEL[persona.source]}`}
          </span>
        </button>
      ))}
    </nav>
  )
}
