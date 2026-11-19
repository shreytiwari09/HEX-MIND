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
