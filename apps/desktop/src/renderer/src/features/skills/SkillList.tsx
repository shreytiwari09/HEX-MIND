import type { TeamData } from '../agents/useTeam'

interface Props {
  team: TeamData
  selectedName: string | null
  onSelect: (name: string) => void
  onAdd: () => void
}

/** The sidebar of the Skills view: every skill an agent can be given. */
export function SkillList({ team, selectedName, onSelect, onAdd }: Props) {
  const mine = team.skills.skills.filter((s) => s.source === 'user')
  const builtin = team.skills.skills.filter((s) => s.source === 'builtin')
  const row = (name: string, note: string) => (
    <button
      key={name}
      type="button"
      className="mission-list__item"
      aria-current={selectedName === name ? 'true' : undefined}
      onClick={() => onSelect(name)}
    >
      <strong>{name}</strong>
      {note && <span className="mission__muted"> · {note}</span>}
    </button>
  )
  return (
    <nav className="mission-list" aria-label="Skills">
      <button type="button" className="button button--small" onClick={onAdd}>
        Add from GitHub
      </button>
      {team.error && (
        <p role="alert" className="mission__error">
          Could not load skills: {team.error}
        </p>
      )}
      {mine.length > 0 && <h3 className="mission__section-title">Yours</h3>}
      {mine.map((skill) => row(skill.name, skill.origin ? 'from GitHub' : 'your own'))}
      <h3 className="mission__section-title">Built in</h3>
      {builtin.map((skill) => row(skill.name, ''))}
    </nav>
  )
}
