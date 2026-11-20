import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import type { SkillsResponse, TeamPersona } from '../agents/types'
import { describeError } from '../missions/actions'

/** What a variant changes for one persona (mirrors apps/backend/app/agents/variants.py). */
export interface PersonaOverride {
  instructions: string | null
  skills: string[] | null // [] turns the persona's skills off
}

export interface Variant {
  id: string
  name: string
  description: string
  personas: Record<string, PersonaOverride>
  missions: number
  updated_at: string
}

type SkillsMode = 'unchanged' | 'none' | 'these'

interface Row {
  persona: string
  instructions: string
  mode: SkillsMode
  skills: string[]
}

const ID = /^[a-z0-9][a-z0-9-]{1,31}$/

function rowsOf(variant: Variant): Row[] {
  return Object.entries(variant.personas).map(([persona, o]) => ({
    persona,
    instructions: o.instructions ?? '',
    mode: o.skills === null ? 'unchanged' : o.skills.length === 0 ? 'none' : 'these',
    skills: o.skills ?? []
  }))
}

export function describeOverride(o: PersonaOverride): string {
  const parts: string[] = []
  if (o.instructions) parts.push('own instructions')
  if (o.skills !== null) parts.push(o.skills.length === 0 ? 'skills off' : `skills: ${o.skills.join(', ')}`)
  return parts.join('; ') || 'no change'
}

function VariantForm({
  api,
  team,
  skills,
  start,
  onDone,
  onCancel
}: {
  api: ApiClient
  team: TeamPersona[]
  skills: SkillsResponse['skills']
  start: Variant | null
  onDone: () => void
  onCancel: () => void
}) {
  const [id, setId] = useState(start ? `${start.id}-2`.slice(0, 32) : '')
  const [name, setName] = useState(start ? `${start.name} (copy)` : '')
  const [description, setDescription] = useState(start?.description ?? '')
  const [rows, setRows] = useState<Row[]>(start ? rowsOf(start) : [])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const update = (index: number, change: Partial<Row>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...change } : row)))
  const free = team.filter((p) => !rows.some((r) => r.persona === p.id))

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    if (!ID.test(id)) {
      setError('The id is 2 to 32 characters: lowercase letters, digits and "-".')
      return
    }
    if (rows.length === 0) {
      setError('Change something for at least one team member, or there is nothing to compare.')
      return
    }
    const personas: Record<string, PersonaOverride> = {}
    for (const row of rows) {
      const instructions = row.instructions.trim()
      const skillsChange = row.mode === 'unchanged' ? null : row.mode === 'none' ? [] : row.skills
      if (!instructions && skillsChange === null) {
        setError(`${row.persona}: write instructions or change the skills, or remove the row.`)
        return
      }
      if (row.mode === 'these' && row.skills.length === 0) {
        setError(`${row.persona}: pick at least one skill, or choose "no skills".`)
        return
      }
      personas[row.persona] = { instructions: instructions || null, skills: skillsChange }
    }
    setBusy(true)
    try {
      await api.post('/variants', { id, name, description, personas })
      onDone()
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="experiments__card" onSubmit={(event) => void submit(event)} aria-label="New variant">
      <h4 className="mission__section-title">{start ? `Copy of ${start.name}` : 'New variant'}</h4>
      <label className="new-mission__field">
        Id
        <input value={id} onChange={(event) => setId(event.target.value)} placeholder="terse-backend" />
      </label>
      <label className="new-mission__field">
        Name
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="new-mission__field">
        What is different (optional)
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      {rows.map((row, index) => (
        <fieldset key={row.persona} className="experiments__override">
          <legend>{team.find((p) => p.id === row.persona)?.name ?? row.persona}</legend>
          <label className="new-mission__field">
            Instructions (replace; empty keeps the current ones)
            <textarea
              rows={3}
              value={row.instructions}
              onChange={(event) => update(index, { instructions: event.target.value })}
            />
          </label>
          <label className="new-mission__field">
            Skills
            <select value={row.mode} onChange={(event) => update(index, { mode: event.target.value as SkillsMode })}>
              <option value="unchanged">Keep its skills</option>
              <option value="none">No skills</option>
              <option value="these">Only these skills</option>
            </select>
          </label>
          {row.mode === 'these' &&
            skills.map((skill) => (
              <label key={skill.name} className="experiments__check">
                <input
                  type="checkbox"
                  checked={row.skills.includes(skill.name)}
                  onChange={(event) =>
                    update(index, {
                      skills: event.target.checked
                        ? [...row.skills, skill.name]
                        : row.skills.filter((s) => s !== skill.name)
                    })
                  }
                />
                {skill.name}
              </label>
            ))}
          <button type="button" className="button" onClick={() => setRows((cur) => cur.filter((_, i) => i !== index))}>
            Remove {row.persona}
          </button>
        </fieldset>
      ))}
      {free.length > 0 && (
        <label className="new-mission__field">
          Change a team member
          <select
            value=""
            onChange={(event) => {
              if (event.target.value)
                setRows((cur) => [...cur, { persona: event.target.value, instructions: '', mode: 'unchanged', skills: [] }])
            }}
          >
            <option value="">Add…</option>
            {free.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      <div className="new-mission__actions">
        <button type="submit" className="button button--primary" disabled={busy}>
          Save variant
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

/** Prompt and skill variants (PRD §11.5): named changes to the team that experiment E5 compares. */
export function VariantManager({ api, onChanged }: { api: ApiClient; onChanged?: () => void }) {
  const [variants, setVariants] = useState<Variant[] | null>(null)
  const [team, setTeam] = useState<TeamPersona[]>([])
  const [skills, setSkills] = useState<SkillsResponse['skills']>([])
  const [form, setForm] = useState<{ start: Variant | null } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [listed, personas, available] = await Promise.all([
        api.get<Variant[]>('/variants'),
        api.get<TeamPersona[]>('/personas'),
        api.get<SkillsResponse>('/skills')
      ])
      setVariants(Array.isArray(listed) ? listed : [])
      setTeam(Array.isArray(personas) ? personas : [])
      setSkills(available?.skills ?? [])
      setError(null)
    } catch (err) {
      setError(describeError(err).message)
    }
  }, [api])

  useEffect(() => {
    void load()
  }, [load])

  const remove = async (variant: Variant) => {
    try {
      await api.delete(`/variants/${variant.id}`)
      await load()
      onChanged?.()
    } catch (err) {
      setError(describeError(err).message)
    }
  }

  return (
    <section className="experiments__card" aria-label="Prompt variants">
      <h3 className="mission__section-title">Prompt and skill variants</h3>
      <p className="mission__muted">
        A variant changes the instructions or skills of some team members. Experiment E5 compares each variant with the
        team as it is. A variant that missions ran under cannot be changed or deleted, so old results keep their meaning:
        copy it instead.
      </p>
      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      {variants === null ? (
        <p className="mission__muted">Loading…</p>
      ) : variants.length === 0 ? (
        <p className="mission__muted">No variants yet.</p>
      ) : (
        <ul className="experiments__variants">
          {variants.map((variant) => (
            <li key={variant.id}>
              <strong>{variant.name}</strong> <span className="mission__muted">({variant.id}, used by {variant.missions} missions)</span>
              {variant.description && <p>{variant.description}</p>}
              <ul>
                {Object.entries(variant.personas).map(([persona, o]) => (
                  <li key={persona}>
                    {persona}: {describeOverride(o)}
                  </li>
                ))}
              </ul>
              <button type="button" className="button" onClick={() => setForm({ start: variant })}>
                Copy {variant.id}
              </button>{' '}
              <button type="button" className="button" disabled={variant.missions > 0} onClick={() => void remove(variant)}>
                Delete {variant.id}
              </button>
            </li>
          ))}
        </ul>
      )}
      {form ? (
        <VariantForm
          key={form.start?.id ?? 'new'}
          api={api}
          team={team}
          skills={skills}
          start={form.start}
          onCancel={() => setForm(null)}
          onDone={() => {
            setForm(null)
            void load()
            onChanged?.()
          }}
        />
      ) : (
        <button type="button" className="button" onClick={() => setForm({ start: null })}>
          New variant
        </button>
      )}
    </section>
  )
}
