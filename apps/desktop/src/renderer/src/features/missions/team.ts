import type { AgentEvent } from '../../generated/events'

/** Who on the team is doing what, worked out only from the mission's real events (never
 * estimated): the roster at the top of the mission screen and the drawer behind each card. */

export type MemberState = 'working' | 'done' | 'failed' | 'idle'

export interface Step {
  seq: number
  ts: string
  text: string
  tone: 'normal' | 'good' | 'bad'
}

export interface Member {
  id: string
  name: string
  state: MemberState
  /** What it is doing now, or what it did last. */
  doing: string
  /** When its current stretch of work began (for the elapsed clock). */
  since: string | null
  /** Its latest event (for "last activity N s ago"). */
  lastAt: string | null
  calls: number
  tokensIn: number
  tokensOut: number
  files: string[]
  steps: Step[]
}

export const PERSONA_NAMES: Record<string, string> = {
  pm: 'PM',
  researcher: 'Researcher',
  backend: 'Backend',
  frontend: 'Frontend',
  data: 'Data',
  designer: 'Designer',
  devops: 'DevOps',
  qa: 'QA',
  'code-reviewer': 'Reviewer',
  security: 'Security'
}

/** Infrastructure ids: their events belong to whoever is working at that moment. */
const SHARED = new Set(['persona_crew', 'mission_runner', 'sandbox'])

/** The persona behind an agent id: "backend_01" → backend, "qa_acceptance_01" → qa,
 * "review_calc_ui" → code-reviewer, "pm_scoping" → pm. Null for shared infrastructure. */
export function personaOf(agentId: string | null): string | null {
  if (!agentId || SHARED.has(agentId)) return null
  const id = agentId.toLowerCase()
  if (id.startsWith('security')) return 'security'
  if (id.startsWith('review') || id.startsWith('code-reviewer') || id.startsWith('code_reviewer')) return 'code-reviewer'
  if (id.startsWith('qa')) return 'qa'
  if (id.startsWith('pm')) return 'pm'
  if (id.startsWith('research')) return 'researcher'
  return id.replace(/[_-]\d+$/, '').replace(/[_-].*$/, '')
}

const TOOL_VERBS: Record<string, string> = {
  write_file: 'Writing',
  replace_in_file: 'Editing',
  read_file: 'Reading',
  list_files: 'Looking through files',
  list_features: 'Reading the plan',
  git_status: 'Checking changed files',
  load_skill: 'Reading the skill'
}

function firstWord(summary: string | null): string {
  if (!summary) return ''
  return summary.split(/[:\s]/)[0] ?? ''
}

/** A plain sentence for one event, or null when the event says nothing a person needs. */
export function stepText(event: AgentEvent): { text: string; tone: Step['tone'] } | null {
  switch (event.type) {
    case 'llm_call_started':
      return { text: `Thinking (${event.payload.model})`, tone: 'normal' }
    case 'llm_call_completed': {
      const p = event.payload
      if (!p.ok) return { text: `A model call failed: ${p.error ?? 'no answer'}`, tone: 'bad' }
      return null
    }
    case 'tool_called': {
      const p = event.payload
      const failed = p.ok ? '' : ' (it failed)'
      const target = firstWord(p.summary)
      if (p.tool === 'run_check') return { text: `Running the "${target || 'project'}" check${failed}`, tone: p.ok ? 'normal' : 'bad' }
      const verb = TOOL_VERBS[p.tool]
      if (!verb) return { text: `Using ${p.tool.replace(/_/g, ' ')}${failed}`, tone: p.ok ? 'normal' : 'bad' }
      const named = p.tool === 'list_features' || p.tool === 'git_status' || p.tool === 'list_files' ? '' : target
      return { text: `${verb}${named ? ` ${named}` : ''}${failed}`, tone: p.ok ? 'normal' : 'bad' }
    }
    case 'check_started':
      return { text: `Running "${event.payload.name}" in the sandbox`, tone: 'normal' }
    case 'check_completed': {
      const p = event.payload
      const secs = p.duration_ms ? ` in ${(p.duration_ms / 1000).toFixed(1)} s` : ''
      if (p.exit_code === 0) return { text: `"${p.name}" passed${secs}`, tone: 'good' }
      return { text: `"${p.name}" ${p.exit_code === null ? 'did not finish' : 'failed'}${secs}`, tone: 'bad' }
    }
    case 'feature_status_changed': {
      const p = event.payload
      if (p.status === 'in_progress') return { text: `Started "${p.title}"${p.attempts > 1 ? ` (attempt ${p.attempts})` : ''}`, tone: 'normal' }
      if (p.status === 'done') return { text: `Finished "${p.title}"`, tone: 'good' }
      if (p.status === 'failed') return { text: `Could not finish "${p.title}"`, tone: 'bad' }
      return null
    }
    case 'validator_started':
      return { text: `Checking milestone ${event.payload.milestone_id}`, tone: 'normal' }
    case 'validator_reported': {
      const p = event.payload
      const findings = p.findings ? `, ${p.findings} finding${p.findings === 1 ? '' : 's'}` : ''
      return {
        text: `Verdict on ${p.milestone_id}: ${p.verdict === 'pass' ? 'pass' : p.verdict === 'fail' ? 'fail' : 'needs you'}${findings}`,
        tone: p.verdict === 'pass' ? 'good' : 'bad'
      }
    }
    case 'handoff_recorded':
      return { text: `Handed over ${event.payload.files_changed.length} changed file(s)`, tone: 'good' }
    case 'need_raised':
      return { text: `Needs you: ${event.payload.summary}`, tone: 'bad' }
    case 'escalated':
      return { text: 'Escalated to a stronger model', tone: 'normal' }
    default:
      return null
  }
}

/** Build the roster. `missionActive` is false once the mission is no longer running, so
 * nobody is shown as still working on a stopped mission. */
export function teamActivity(events: AgentEvent[], missionActive: boolean): Member[] {
  const members = new Map<string, Member>()
  let current: string | null = null
  const member = (id: string): Member => {
    let m = members.get(id)
    if (!m) {
      m = {
        id, name: PERSONA_NAMES[id] ?? id, state: 'idle', doing: 'Waiting for its turn', since: null, lastAt: null,
        calls: 0, tokensIn: 0, tokensOut: 0, files: [], steps: []
      }
      members.set(id, m)
    }
    return m
  }

  for (const event of events) {
    let id = personaOf(event.agent_id)
    if (event.type === 'feature_status_changed') id = event.payload.persona
    if (event.type === 'validator_started' || event.type === 'validator_reported') id = event.payload.validator
    if (event.type === 'handoff_recorded') id = event.payload.persona
    if (!id) id = current
    if (!id) continue
    const m = member(id)
    m.lastAt = event.ts

    // start and end of a stretch of work
    if (event.type === 'feature_status_changed' && event.payload.status === 'in_progress') {
      m.state = 'working'
      m.since = event.ts
      current = id
    } else if (event.type === 'validator_started' || (event.type === 'agent_started' && m.state !== 'working')) {
      m.state = 'working'
      m.since = event.ts
      current = id
    } else if (event.type === 'feature_status_changed' && (event.payload.status === 'done' || event.payload.status === 'skipped')) {
      m.state = 'done'
    } else if (event.type === 'feature_status_changed' && event.payload.status === 'failed') {
      m.state = 'failed'
    } else if (event.type === 'validator_reported') {
      m.state = event.payload.verdict === 'pass' ? 'done' : 'failed'
    } else if (event.type === 'agent_finished' && personaOf(event.agent_id) === id && m.state === 'working' && !isFeatureOwner(events, id)) {
      m.state = event.payload.ok ? 'done' : 'failed'
    }

    if (event.type === 'llm_call_completed') {
      m.calls += 1
      m.tokensIn += event.payload.input_tokens ?? 0
      m.tokensOut += event.payload.output_tokens ?? 0
    }
    if (event.type === 'handoff_recorded') {
      for (const f of event.payload.files_changed) if (!m.files.includes(f)) m.files.push(f)
    }
    const step = stepText(event)
    if (step) m.steps.push({ seq: event.seq, ts: event.ts, ...step })
  }

  const list = [...members.values()]
  if (!missionActive) for (const m of list) if (m.state === 'working') m.state = 'done'
  for (const m of list) {
    // working: the very latest step, "Thinking" included; otherwise its last real result
    const shown = m.state === 'working' ? m.steps[m.steps.length - 1] : [...m.steps].reverse().find((s) => !s.text.startsWith('Thinking'))
    if (shown) m.doing = shown.text
    else if (m.state !== 'idle') m.doing = m.calls > 0 ? `Made ${m.calls} model call${m.calls === 1 ? '' : 's'}` : 'Done'
  }
  const order: Record<MemberState, number> = { working: 0, failed: 1, done: 2, idle: 3 }
  return list.sort((a, b) => order[a.state] - order[b.state] || (b.lastAt ?? '').localeCompare(a.lastAt ?? ''))
}

/** Personas that build features end their stretch with a feature status, not with their
 * crew finishing (a crew finishes several times per feature). */
function isFeatureOwner(events: AgentEvent[], id: string): boolean {
  return events.some((e) => e.type === 'feature_status_changed' && e.payload.persona === id)
}

export function ago(fromIso: string | null, now: number): string {
  if (!fromIso) return ''
  const secs = Math.max(0, Math.round((now - Date.parse(fromIso)) / 1000))
  if (secs < 60) return `${secs} s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins} min ${secs % 60} s`
  return `${Math.floor(mins / 60)} h ${mins % 60} min`
}
