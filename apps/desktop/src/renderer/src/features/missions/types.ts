// Mirror of apps/backend/app/api/missions.py. Keep in sync by hand; the event types are generated.

export type MissionStatus =
  | 'draft'
  | 'scoping'
  | 'awaiting_approval'
  | 'running'
  | 'paused'
  | 'needs_user'
  | 'completed'
  | 'applied'
  | 'kept'
  | 'discarded'
  | 'cancelled'
  | 'failed'

export type FeatureStatus = 'pending' | 'in_progress' | 'done' | 'failed' | 'skipped'
// completed: every feature is done. passed: every required validator passed it. failed: validators
// still found problems after the team's fixes. accepted: you chose to go on despite that.
export type MilestoneStatus = 'pending' | 'active' | 'completed' | 'passed' | 'failed' | 'accepted'

export interface MissionFeature {
  id: string
  title: string
  persona: string
  status: FeatureStatus
  attempts: number
  commit: string | null
  description: string
  preconditions: string[]
  expected_behavior: string[]
  contract_refs: string[]
  extra_skills: string[]
  target_files: string[]
}

export interface MissionMilestone {
  id: string
  title: string
  status: MilestoneStatus
  validators: string[]
  features: MissionFeature[]
}

export interface MissionApply {
  state: 'applied' | 'reverted'
  files: string[]
  commit: string | null
  commit_error: string | null
  include_mission_files: boolean
}

export interface Mission {
  id: string
  project_id: string
  run_id: string
  title: string
  idea: string
  status: MissionStatus
  branch: string
  budget_usd: number | null
  spent_usd: number
  tokens_in: number
  tokens_out: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  milestones: MissionMilestone[]
  apply: MissionApply | null
}

export interface Need {
  id: string
  mission_id: string
  feature_id: string | null
  kind:
    | 'feature_failed'
    | 'provider_unavailable'
    | 'budget_reached'
    | 'persona_budget_reached'
    | 'milestone_failed'
    | 'validator_unavailable'
  summary: string
  evidence: Record<string, unknown>
  options: string[]
  status: 'open' | 'answered'
  created_at: string
}

export interface Checkpoint {
  commit: string
  label: string
  feature_id: string | null
  created_at: string
}

export interface MissionDiffFile {
  path: string
  change_type: 'added' | 'modified' | 'deleted'
  status: string
  original: string | null
  modified: string | null
  diff: string
}

export interface MissionDiff {
  run_id: string
  base_commit: string | null
  files: MissionDiffFile[]
}

export interface CostRow {
  spent_usd: number
  calls: number
  tokens_in: number
  tokens_out: number
}

export interface PersonaCost extends CostRow {
  persona_id: string | null
  budget_usd: number | null
}

export interface ModelCost extends CostRow {
  provider: string
  model: string
}

export interface Costs {
  total_usd: number
  budget_usd: number | null
  tokens_in: number
  tokens_out: number
  calls: number
  /** Successful calls whose model has no known price: their cost is not in the totals. */
  unpriced_calls: number
  by_persona: PersonaCost[]
  by_model: ModelCost[]
}

export interface DelegationAssignment {
  persona_id: string
  connection: string | null
  model: string
  set_by: 'user' | 'auto'
  reason: string | null
  escalate_model: string | null
  budget_usd: number | null
}

export interface Delegation {
  assignments: DelegationAssignment[]
  /** Fallbacks, key rotations, escalations, budget warnings and Needs-you items, oldest first. */
  events: import('../../generated/events').AgentEvent[]
}

export interface ValidatorFinding {
  feature_id: string | null
  file: string | null
  line: number | null
  severity: 'info' | 'minor' | 'major' | 'critical'
  message: string
  evidence: string | null
}

export interface ValidatorReportView {
  milestone_id: string
  validator: string
  round: number
  verdict: 'pass' | 'fail' | 'needs_user'
  findings: ValidatorFinding[]
  commands: { command: string; exit_code: number; duration_s: number; summary: string }[]
  created_at: string
}
