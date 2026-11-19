// Shared test data for the mission tests.
import type { Mission, MissionFeature } from './types'

export function feature(
  id: string,
  status: MissionFeature['status'],
  extra: Partial<MissionFeature> = {}
): MissionFeature {
  return {
    id,
    title: `Feature ${id}`,
    persona: 'backend',
    status,
    attempts: 0,
    commit: null,
    description: '',
    preconditions: [],
    expected_behavior: ['it works'],
    contract_refs: [],
    extra_skills: [],
    target_files: [],
    ...extra
  }
}

/** Four features across two milestones: one done, one skipped, one in progress, one waiting. */
export function mission(extra: Partial<Mission> = {}): Mission {
  return {
    id: 'm1',
    project_id: 'p1',
    run_id: 'r1',
    title: 'Todo app',
    idea: 'A todo app',
    status: 'running',
    branch: 'hex/mission-abc',
    budget_usd: null,
    spent_usd: 0,
    tokens_in: 0,
    tokens_out: 0,
    created_at: '2026-11-19T10:00:00Z',
    started_at: '2026-11-19T10:00:00Z',
    finished_at: null,
    apply: null,
    validation_contract: [],
    milestones: [
      {
        id: 'm1-a',
        title: 'Model',
        status: 'completed',
        validators: [],
        features: [feature('a', 'done'), feature('b', 'skipped')]
      },
      {
        id: 'm2-b',
        title: 'Filter',
        status: 'active',
        validators: [],
        features: [feature('c', 'in_progress', { attempts: 1 }), feature('d', 'pending')]
      }
    ],
    ...extra
  }
}
