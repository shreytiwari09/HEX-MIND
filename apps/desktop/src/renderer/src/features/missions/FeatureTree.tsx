import { Circle, CircleCheck, CircleMinus, CircleX, LoaderCircle, type LucideIcon } from 'lucide-react'

import type { FeatureStatus, Mission, MilestoneStatus } from './types'

const FEATURE_ICON: Record<FeatureStatus, LucideIcon> = {
  pending: Circle,
  in_progress: LoaderCircle,
  done: CircleCheck,
  failed: CircleX,
  skipped: CircleMinus
}

const FEATURE_LABEL: Record<FeatureStatus, string> = {
  pending: 'Waiting',
  in_progress: 'Working',
  done: 'Done',
  failed: 'Failed',
  skipped: 'Skipped'
}

const MILESTONE_LABEL: Record<MilestoneStatus, string> = {
  pending: 'Waiting',
  active: 'In progress',
  completed: 'Features done',
  passed: 'Validated',
  accepted: 'Accepted by you',
  failed: 'Failed'
}

export function FeatureTree({ mission }: { mission: Mission }) {
  return (
    <ol className="feature-tree" aria-label="Milestones and features">
      {mission.milestones.map((milestone, index) => (
        <li key={milestone.id} className="feature-tree__milestone" data-status={milestone.status}>
          <div className="feature-tree__milestone-head">
            <span className="feature-tree__milestone-title">
              M{index + 1} {milestone.title}
            </span>
            <span className="feature-tree__milestone-status">{MILESTONE_LABEL[milestone.status]}</span>
          </div>
          <ul className="feature-tree__features">
            {milestone.features.map((feature) => {
              const Icon = FEATURE_ICON[feature.status]
              return (
                <li key={feature.id} className="feature-tree__feature" data-status={feature.status}>
                  <Icon size={14} aria-hidden="true" className="feature-tree__icon" />
                  <span className="feature-tree__title">{feature.title}</span>
                  <span className="feature-tree__meta">
                    {feature.persona}
                    {feature.attempts > 1 ? ` · ${feature.attempts} attempts` : ''}
                  </span>
                  <span className="visually-hidden">{FEATURE_LABEL[feature.status]}</span>
                </li>
              )
            })}
          </ul>
        </li>
      ))}
    </ol>
  )
}
