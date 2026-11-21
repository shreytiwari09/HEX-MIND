import type { CatalogEntry } from './types'

function priced(entry: CatalogEntry): boolean {
  return entry.input_per_mtok !== null && entry.output_per_mtok !== null
}

/** Free first, then models that already worked on this account, then paid, then unknown price,
 * then models the provider refused (shown, marked, not selectable). PRD D69. */
function rank(entry: CatalogEntry): number {
  if (entry.access === 'refused') return 4
  if (entry.free) return 0
  if (entry.access === 'works') return 1
  if (priced(entry)) return 2
  return 3
}

export function modelLabel(entry: CatalogEntry): string {
  const tags: string[] = []
  if (entry.free) tags.push('free')
  else if (priced(entry))
    tags.push(`paid · $${entry.input_per_mtok} in / $${entry.output_per_mtok} out per Mtok`)
  else tags.push('price unknown')
  if (entry.access === 'works') tags.push('works on your account')
  if (entry.access === 'refused') tags.push('refused: needs a plan or key')
  if (entry.median_latency_ms) tags.push(`answers in ~${Math.max(1, Math.round(entry.median_latency_ms / 1000))} s`)
  if (entry.tpm_limit) tags.push(`limit ${entry.tpm_limit.toLocaleString('en-US')} tokens/min`)
  if (entry.tpd_limit) tags.push(`${entry.tpd_limit.toLocaleString('en-US')} tokens/day`)
  if (entry.calls && entry.calls >= 3 && (entry.ok_calls ?? 0) / entry.calls < 0.5)
    tags.push(`answered only ${entry.ok_calls ?? 0} of ${entry.calls} calls`)
  return `${entry.connection_name} · ${entry.model} (${tags.join(', ')})`
}

export function sortedModels(entries: CatalogEntry[]): CatalogEntry[] {
  return entries
    .filter((e) => !e.deprecated)
    .sort(
      (a, b) =>
        rank(a) - rank(b) ||
        a.connection_name.localeCompare(b.connection_name) ||
        a.model.localeCompare(b.model)
    )
}

export function isRefused(entry: CatalogEntry): boolean {
  return entry.access === 'refused'
}
