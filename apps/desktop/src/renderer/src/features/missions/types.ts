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
export type MilestoneStatus = 'pending' | 'active' | 'completed' | 'failed'

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
  kind: 'feature_failed' | 'provider_unavailable' | 'budget_reached'
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
