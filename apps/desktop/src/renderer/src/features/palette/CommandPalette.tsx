import { CornerDownLeft, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { filterCommands, shortcutLabel, type Command } from './commands'

interface Props {
  commands: Command[]
  onClose: () => void
}

/** Every view, recent project and action, one keystroke away (⌘K / Ctrl+K). */
export function CommandPalette({ commands, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const results = useMemo(() => filterCommands(commands, query), [commands, query])

  useEffect(() => {
    input.current?.focus()
  }, [])
  useEffect(() => {
    setIndex(0)
  }, [query])
  useEffect(() => {
    list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest' })
  }, [index])

  const run = (command: Command | undefined) => {
    if (!command || command.disabled) return
    onClose()
    command.run()
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setIndex((i) => Math.min(i + 1, results.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setIndex((i) => Math.max(i - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      run(results[index])
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    }
  }

  let lastGroup = ''
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="palette__search">
          <Search size={16} aria-hidden="true" />
          <input
            ref={input}
            className="palette__input"
            placeholder="Type a command, view or project…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-activedescendant={results[index] ? `palette-${results[index].id}` : undefined}
          />
        </div>
        <ul ref={list} id="palette-results" className="palette__results" role="listbox">
          {results.length === 0 && <li className="palette__empty">No command matches “{query}”</li>}
          {results.map((c, i) => {
            const header = !query && c.group !== lastGroup ? c.group : null
            lastGroup = c.group
            return (
              <li key={c.id} role="presentation">
                {header && <div className="palette__group">{header}</div>}
                <div
                  id={`palette-${c.id}`}
                  role="option"
                  aria-selected={i === index}
                  aria-disabled={c.disabled || undefined}
                  className="palette__item"
                  onMouseMove={() => setIndex(i)}
                  onClick={() => run(c)}
                >
                  <span className="palette__title">{c.title}</span>
                  {query && <span className="palette__meta">{c.group}</span>}
                  {c.shortcut && <kbd className="kbd">{shortcutLabel(c.shortcut)}</kbd>}
                  {i === index && <CornerDownLeft size={14} className="palette__enter" aria-hidden="true" />}
                </div>
              </li>
            )
          })}
        </ul>
        <div className="palette__footer">
          <span><kbd className="kbd">↑</kbd><kbd className="kbd">↓</kbd> move</span>
          <span><kbd className="kbd">↵</kbd> run</span>
          <span><kbd className="kbd">esc</kbd> close</span>
        </div>
      </div>
    </div>
  )
}
