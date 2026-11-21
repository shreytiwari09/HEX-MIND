export interface Command {
  id: string
  title: string
  group: string
  /** Extra words that should find this command (e.g. "keys" for Models & Keys). */
  keywords?: string
  shortcut?: string
  disabled?: boolean
  run: () => void
}

/** Subsequence match with a score: consecutive letters and word starts rank higher.
 * Returns null when the query's letters do not all appear in order. */
export function score(query: string, text: string): number | null {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const t = text.toLowerCase()
  if (t.includes(q)) return 1000 - t.indexOf(q)
  let at = 0
  let total = 0
  let run = 0
  for (const ch of q) {
    if (ch === ' ') continue
    const found = t.indexOf(ch, at)
    if (found === -1) return null
    run = found === at ? run + 1 : 0
    const wordStart = found === 0 || /[\s\-_/&.]/.test(t[found - 1])
    total += 1 + run * 2 + (wordStart ? 3 : 0)
    at = found + 1
  }
  return total
}

export function filterCommands(commands: Command[], query: string): Command[] {
  return commands
    .map((c) => ({ c, s: score(query, `${c.title} ${c.group} ${c.keywords ?? ''}`) }))
    .filter((x): x is { c: Command; s: number } => x.s !== null)
    .sort((a, b) => b.s - a.s)
    .map((x) => x.c)
}

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)

/** "Mod+K" shown as ⌘K on macOS and Ctrl+K elsewhere. */
export function shortcutLabel(shortcut: string): string {
  if (!isMac) return shortcut.replace('Mod', 'Ctrl')
  return shortcut
    .replace('Mod+', '⌘')
    .replace('Shift+', '⇧')
    .replace('Alt+', '⌥')
}

/** Does this key event match "Mod+Shift+P" style shortcuts? Mod is ⌘ on macOS, Ctrl elsewhere. */
export function matches(event: KeyboardEvent, shortcut: string): boolean {
  const parts = shortcut.split('+')
  const key = parts[parts.length - 1].toLowerCase()
  const mod = isMac ? event.metaKey : event.ctrlKey
  return (
    mod === parts.includes('Mod') &&
    event.shiftKey === parts.includes('Shift') &&
    event.altKey === parts.includes('Alt') &&
    event.key.toLowerCase() === key
  )
}
