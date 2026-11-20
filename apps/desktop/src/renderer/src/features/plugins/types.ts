// Mirrors apps/backend/app/api/plugins.py.

export type PluginStatus = 'disabled' | 'needs_approval' | 'ready'

export interface PluginConfig {
  transport: 'stdio' | 'http'
  image: string | null
  command: string | null
  mount: 'none' | 'read' | 'write'
  network: 'none' | 'allowlist'
  allow_hosts: string[]
  url: string | null
}

export interface Plugin {
  id: string
  name: string
  description: string
  config: PluginConfig
  /** Derived from the configuration by the backend, never from what the plugin says. */
  permissions: string[]
  needs_approval: boolean
  /** Why it needs approval, in words. */
  reasons: string[]
  /** Approved for exactly its current configuration. */
  approved: boolean
  approved_at: string | null
  enabled: boolean
  status: PluginStatus
  /** The personas it is attached to. */
  personas: string[]
  config_hash: string
}

export interface PluginOptions {
  images: string[]
}
