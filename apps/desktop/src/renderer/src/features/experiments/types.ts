// Mirrors apps/backend/app/api/experiments.py and app/evaluation/results.py. A figure that could
// not be measured is null, never zero.

export interface ExperimentInfo {
  id: string
  title: string
  question: string
  varies: string
  conditions: { id: string; label: string }[]
  /** Why it cannot run yet; null when it can. */
  blocked: string | null
  /** What the comparison does and does not cover. */
  note?: string | null
}

export interface Listing {
  benchmark_version: string
  apps: { id: string; idea: string; features: string[] }[]
  experiments: ExperimentInfo[]
}

export interface Sweep {
  id: string
  experiment: string
  total: number
  skipped: number
  done: number
  current: string | null
  state: 'running' | 'finished' | 'stopped'
}

export interface ConditionSummary {
  condition: string
  trials: number
  errors: number
  completed: number
  passed: number
  pass_rate: number | null
  interval: [number, number] | null
  pass_k: number | null
  k: number | null
  needs_you_mean: number | null
  retries_mean: number | null
  escalations_mean: number | null
  duration_s_mean: number | null
  duration_s_sd: number | null
  cost_usd_mean: number | null
  cost_usd_sd: number | null
  cost_trials: number
  tokens_in_mean: number | null
  tokens_out_mean: number | null
  by_app: Record<string, [number, number]>
}

export interface ExperimentResults {
  experiment: string
  title: string
  blocked: string | null
  trials: number
  benchmark_versions: string[]
  conditions: ConditionSummary[]
  errors: { condition: string | null; app: string; repeat: number; error: string | null }[]
}

export interface SafetyReport {
  summary: { cases: number; blocked: number; got_through: number; not_run: number }
  cases: { id: string; category: string; attack: string; blocked: boolean | null; evidence: string }[]
}
