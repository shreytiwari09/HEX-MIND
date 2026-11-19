import { useCallback, useEffect, useRef, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import type {
  Assignment,
  CatalogEntry,
  Connection,
  Persona,
  PersonaBudget,
  ProviderType
} from './types'

export interface ModelsData {
  types: ProviderType[]
  connections: Connection[]
  personas: Persona[]
  assignments: Assignment[]
  budgets: PersonaBudget[]
  catalog: CatalogEntry[]
  loaded: boolean
  error: string | null
  /** Fetch everything again (after any change). */
  reload(): Promise<void>
}

const EMPTY = {
  types: [] as ProviderType[],
  connections: [] as Connection[],
  personas: [] as Persona[],
  assignments: [] as Assignment[],
  budgets: [] as PersonaBudget[],
  catalog: [] as CatalogEntry[]
}

/** Everything the Models & Keys screen shows, loaded together so the views never disagree. */
export function useModelsData(api: ApiClient): ModelsData {
  const [data, setData] = useState(EMPTY)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const alive = useRef(true)

  const reload = useCallback(async () => {
    try {
      const [types, connections, personas, assignments, budgets, catalog] = await Promise.all([
        api.get<ProviderType[]>('/provider-types'),
        api.get<Connection[]>('/connections'),
        api.get<Persona[]>('/personas'),
        api.get<Assignment[]>('/assignments'),
        api.get<PersonaBudget[]>('/budgets/personas'),
        api.get<CatalogEntry[]>('/catalog')
      ])
      if (!alive.current) return
      setData({ types, connections, personas, assignments, budgets, catalog })
      setError(null)
      setLoaded(true)
    } catch (err) {
      if (!alive.current) return
      setError(err instanceof Error ? err.message : String(err))
      setLoaded(true)
    }
  }, [api])

  useEffect(() => {
    alive.current = true
    void reload()
    return () => {
      alive.current = false
    }
  }, [reload])

  return { ...data, loaded, error, reload }
}
