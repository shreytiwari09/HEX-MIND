// Mirror of the backend's model APIs: apps/backend/app/api/{connections,assignments,budgets,
// catalog,personas}.py. Keep in sync by hand. Secrets never appear here: a key is only ever sent
// to the backend, and every response lists keys by label.

export interface ProviderType {
  type: string
  label: string
  base_url: string | null
  requires_key: boolean
  local: boolean
}

export interface KeyInfo {
  id: string
  label: string
  position: number
  disabled: boolean
}

export interface Connection {
  id: string
  name: string
  provider_type: string
  base_url: string
  extra_headers: Record<string, string>
  enabled: boolean
  requires_key: boolean
  keys: KeyInfo[]
  models: string[]
  last_test: { ok: boolean | null; error: string | null; tested_at: string | null }
}

export interface ProbeResult {
  ok: boolean
  error: string | null
  models: string[]
  latency_ms: number
  auth_rejected: boolean
}

export interface ConnectionResult {
  connection: Connection
  test: ProbeResult | null
}

export interface ModelRef {
  connection_id: string
  model: string
}

export interface Assignment {
  persona_id: string
  primary: ModelRef
  fallbacks: ModelRef[]
  escalate: ModelRef | null
  set_by: 'user' | 'auto'
  reason: string | null
  updated_at: string
}

export type Preset = 'balanced' | 'best' | 'cheapest' | 'private'

export interface Proposal {
  persona_id: string
  primary: ModelRef | null
  fallbacks: ModelRef[]
  escalate: ModelRef | null
  reason: string
  verified: boolean
  outcome: 'saved' | 'would_save' | 'kept_manual' | 'none'
}

export interface AutoResult {
  preset: Preset
  proposals: Proposal[]
}

export interface Persona {
  id: string
  name: string
  kind: 'orchestrator' | 'worker' | 'validator' | 'research'
  skills: string[]
  plugins: string[]
}

export interface PersonaBudget {
  persona_id: string
  budget_usd: number
}

/** A model a connection can reach, with what is known about it (null: unknown, never guessed). */
export interface CatalogEntry {
  connection_id: string
  connection_name: string
  provider_type: string
  model: string
  name: string
  local: boolean
  context_window: number | null
  input_per_mtok: string | null
  output_per_mtok: string | null
  tool_call: boolean | null
  deprecated: boolean
  tiers: { reasoning: number; coding: number; ui: number; tool_use: number } | null
  has_profile: boolean
  in_models_dev: boolean
  /** A `:free` model, a local one, or a known price of zero. */
  free?: boolean
  /** From this account's own call log: its last call answered, or the provider refused it. */
  access?: 'works' | 'refused' | 'unknown'
  /** Measured on this account (D71). */
  calls?: number
  ok_calls?: number
  median_latency_ms?: number | null
  /** The provider's stated token limits, read from its refusals. */
  tpm_limit?: number | null
  tpd_limit?: number | null
}
