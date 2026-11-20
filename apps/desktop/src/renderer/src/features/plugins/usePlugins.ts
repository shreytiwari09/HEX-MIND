import { useCallback, useEffect, useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import type { Plugin, PluginOptions } from './types'

export interface PluginsData {
  plugins: Plugin[]
  options: PluginOptions
  loaded: boolean
  error: string | null
  reload: () => Promise<void>
}

/** The installed plugins and what a new one may use. */
export function usePlugins(api: ApiClient): PluginsData {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [options, setOptions] = useState<PluginOptions>({ images: [] })
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [list, available] = await Promise.all([
        api.get<Plugin[]>('/plugins'),
        api.get<PluginOptions>('/plugins/options')
      ])
      setPlugins(Array.isArray(list) ? list : [])
      setOptions(available && Array.isArray(available.images) ? available : { images: [] })
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

  return { plugins, options, loaded, error, reload }
}
