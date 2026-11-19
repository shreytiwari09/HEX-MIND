import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import type { SkillsResponse, TeamPersona } from './types'

export interface TeamData {
  personas: TeamPersona[]
  skills: SkillsResponse
  loaded: boolean
  error: string | null
  reload: () => Promise<void>
}

const EMPTY: SkillsResponse = { skills: [], problems: {} }

/** The team and the skills available to it, loaded together so the views never disagree. */
export function useTeam(api: ApiClient): TeamData {
  const [personas, setPersonas] = useState<TeamPersona[]>([])
  const [skills, setSkills] = useState<SkillsResponse>(EMPTY)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [team, available] = await Promise.all([
        api.get<TeamPersona[]>('/personas'),
        api.get<SkillsResponse>('/skills')
      ])
      setPersonas(Array.isArray(team) ? team : [])
      setSkills(available && Array.isArray(available.skills) ? available : EMPTY)
      setError(null)
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setLoaded(true)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  return { personas, skills, loaded, error, reload }
}
