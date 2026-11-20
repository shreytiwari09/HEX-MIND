// Mirrors apps/backend/app/metrics/service.py. Figures that cannot be measured are null.

export interface Group {
  calls: number
  failed: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  avg_latency_ms: number
}

export interface Metrics {
  missions: { count: number; by_status: Record<string, number>; avg_duration_s: number | null }
  calls: {
    count: number
    failed: number
    error_rate: number | null
    input_tokens: number
    output_tokens: number
    cost_usd: number
    without_cost: number
    /** Answered from the response cache: their figures are those measured when first made. */
    replayed?: number
    avg_latency_ms: number
    p50_latency_ms: number | null
    p95_latency_ms: number | null
  }
  by_persona: (Group & { persona: string | null })[]
  by_model: (Group & { provider: string; model: string })[]
  by_variant: { variant_id: string | null; missions: number; completed: number; cost_usd: number }[]
  features: { by_status: Record<string, number>; attempts: number; retried: number; first_try_rate: number | null }
  process: {
    fallbacks: number
    key_rotations: number
    escalations: number
    budget_warnings: number
    guardrail_triggers: number
    needs_raised: number
    guardrails: Record<string, number>
  }
  validators: {
    milestones: number
    checks: number
    caught: number
    caught_and_fixed: number
    unavailable: number
    catch_rate: number | null
    false_positive_rate: number | null
  }
  edit_format_compliance: number | null
}
