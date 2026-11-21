// Mirrors apps/backend/app/api/personas.py and api/skills.py.

export type PersonaKind = 'orchestrator' | 'worker' | 'validator' | 'research'

export interface TeamPersona {
  id: string
  name: string
  kind: PersonaKind
  skills: string[]
  plugins: string[]
  instructions: string
  version: number
  /** builtin: as shipped. customized: a built-in one you edited. custom: one you made. */
  source: 'builtin' | 'customized' | 'custom'
  /** Skills it lists that do not exist (never offered to the agent). */
  missing_skills: string[]
}

export interface SkillInfo {
  name: string
  description: string
  source: 'builtin' | 'user'
  version: string
  files: string[]
  personas: string[]
  /** Where an installed skill came from; null for built-in skills and ones you wrote. */
  origin: { url: string; commit: string; installed_at: string } | null
}

export interface SkillDetail extends SkillInfo {
  body: string
}

export interface GithubPreview {
  name: string
  description: string
  body: string
  files: string[]
  version: string
  hash: string
  url: string
  commit: string
  /** Why the text may be trying to steer an AI; empty if nothing was found. */
  signals: string[]
  /** A skill with this name already exists: 'user' (it would be replaced) or 'builtin' (overridden). */
  exists: 'user' | 'builtin' | null
  /** Roughly what loading the skill adds to an agent's request (4 characters a token). */
  approx_tokens?: number
}

export interface SkillsResponse {
  skills: SkillInfo[]
  /** Skill folders that failed validation, with the reason. */
  problems: Record<string, string>
}

export interface PersonaVersionInfo {
  version: number
  snapshot: { name?: string; instructions?: string; skills?: string[] }
  created_at: string
}
