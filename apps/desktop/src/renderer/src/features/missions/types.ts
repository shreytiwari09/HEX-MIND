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

export interface Criterion {
  id: string
  text: string
  how: 'unit test' | 'api test' | 'browser' | 'typecheck' | 'security review'
  feature: string | null
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
  validation_contract: Criterion[]
  apply: MissionApply | null
  /** The prompt variant it ran under, if any. */
  variant_id?: string | null
  /** How the team shares state: the mission board, or only the messages it is sent. */
  coordination?: 'blackboard' | 'messaging'
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

// ---------- PM scoping chat and plan review (PRD F2; mirrors api/scoping.py) ----------

export interface ScopingMessage {
  role: 'user' | 'pm'
  content: string
  questions?: string[]
  at: string
}

export interface PlanFeature {
  id: string
  title: string
  persona: string
  description?: string
  expected_behavior: string[]
}

export interface PlanMilestone {
  id: string
  title: string
  validators: string[]
  features: PlanFeature[]
}

export interface MissionPlanDoc {
  title: string
  milestones: PlanMilestone[]
  validation_contract?: Criterion[]
}

export interface ScopingSession {
  id: string
  project_id: string
  run_id: string
  idea: string
  /** asking: the PM wants answers. planned: a plan is ready. started/abandoned: closed. */
  status: 'asking' | 'planned' | 'started' | 'abandoned'
  messages: ScopingMessage[]
  plan: MissionPlanDoc | null
  prd: string | null
  /** Why the last PM turn gave no usable answer, if it did not. */
  error: string | null
  budget_usd: number | null
  mission_id: string | null
  /** Advanced research: researchers looked things up on the web before the PM planned. */
  research?: boolean
  research_notes?: ResearchNotes | null
  /** What the calls cost so far, from the provider layer: only calls with a known price. */
  cost_usd: number
  /** Calls that answered with no known price, so `cost_usd` does not include them. */
  unpriced_calls?: number
  created_at: string
  updated_at: string
}

/** What one researcher found for one question. `sources` are only addresses its tools really
 * showed it; `credits` is Tavily's own figure, null when unknown. */
export interface ResearchFinding {
  question: string
  answer: string
  sources: { title: string; url: string; read?: boolean }[]
  /** Each fact with its source and the quote the backend looked for in what the researcher read. */
  claims?: ResearchClaim[]
  gaps: string
  searches: number
  pages: number
  credits: number | null
  error: string | null
}

export interface ResearchClaim {
  claim: string
  url: string
  title: string
  quote: string
  /** verified: the quote is on the page it read. snippet: only in a search snippet. */
  status: 'verified' | 'snippet' | 'unverified'
}

export interface ResearchNotes {
  at: string
  questions: string[]
  findings: ResearchFinding[]
  credits: number | null
}
