import { describe, expect, it } from 'vitest'

import { isRefused, modelLabel, sortedModels } from './modelOptions'
import type { CatalogEntry } from './types'

function entry(model: string, extra: Partial<CatalogEntry> = {}): CatalogEntry {
  return {
    connection_id: 'c1', connection_name: 'Harbor', provider_type: 'custom', model, name: model,
    local: false, context_window: null, input_per_mtok: null, output_per_mtok: null,
    tool_call: true, deprecated: false, tiers: null, has_profile: false, in_models_dev: false,
    ...extra
  }
}

describe('model options', () => {
  it('lists free first, then what worked, then paid, then unknown, then refused', () => {
    const list = sortedModels([
      entry('claude', { access: 'refused' }),
      entry('mystery'),
      entry('gpt', { input_per_mtok: '1', output_per_mtok: '4' }),
      entry('glm', { access: 'works' }),
      entry('deepseek:free', { free: true }),
      entry('old', { deprecated: true })
    ])

    expect(list.map((e) => e.model)).toEqual(['deepseek:free', 'glm', 'gpt', 'mystery', 'claude'])
  })

  it('says in brackets what each model costs and what this account saw', () => {
    expect(modelLabel(entry('deepseek:free', { free: true }))).toBe('Harbor · deepseek:free (free)')
    expect(modelLabel(entry('gpt', { input_per_mtok: '1', output_per_mtok: '4' }))).toBe(
      'Harbor · gpt (paid · $1 in / $4 out per Mtok)'
    )
    expect(modelLabel(entry('glm', { access: 'works' }))).toBe(
      'Harbor · glm (price unknown, works on your account)'
    )
    const refused = entry('claude', { access: 'refused' })
    expect(modelLabel(refused)).toBe('Harbor · claude (price unknown, refused: needs a plan or key)')
    expect(isRefused(refused)).toBe(true)
  })
})
