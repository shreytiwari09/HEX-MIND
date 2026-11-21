import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { shortPath } from '../workspace/Welcome'
import { CommandPalette } from './CommandPalette'
import { filterCommands, score, type Command } from './commands'

const cmd = (id: string, title: string, extra: Partial<Command> = {}): Command => ({
  id, title, group: 'Project', run: vi.fn(), ...extra
})

describe('command palette', () => {
  it('finds commands by letters in order, best matches first', () => {
    const list = [cmd('a', 'Toggle chat panel'), cmd('b', 'Run the app and get a link'), cmd('c', 'Open terminal in the sandbox')]

    expect(filterCommands(list, 'run').map((c) => c.id)).toEqual(['b'])
    expect(filterCommands(list, 'term')[0].id).toBe('c')
    expect(filterCommands(list, 'tcp').map((c) => c.id)).toContain('a') // T-oggle C-hat P-anel
    expect(score('xyz', 'Run the app')).toBeNull()
    expect(filterCommands(list, '')).toHaveLength(3)
  })

  it('finds a command by its keywords', () => {
    const list = [cmd('run', 'Run the app', { keywords: 'localhost preview' })]
    expect(filterCommands(list, 'localhost')).toHaveLength(1)
  })

  it('runs the chosen command with the keyboard and closes', () => {
    const first = cmd('a', 'Open folder')
    const second = cmd('b', 'New mission')
    const onClose = vi.fn()
    render(<CommandPalette commands={[first, second]} onClose={onClose} />)

    const input = screen.getByRole('combobox')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(second.run).toHaveBeenCalledOnce()
    expect(first.run).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('does not run a disabled command and says when nothing matches', () => {
    const off = cmd('a', 'Stop the app', { disabled: true })
    render(<CommandPalette commands={[off]} onClose={vi.fn()} />)

    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' })
    expect(off.run).not.toHaveBeenCalled()

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'qqq' } })
    expect(screen.getByText(/No command matches/)).toBeInTheDocument()
  })
})

describe('recent project paths', () => {
  it('shows the home folder as ~ and shortens long paths in the middle', () => {
    expect(shortPath('/Users/ana/projects/calc')).toBe('~/projects/calc')
    expect(shortPath('/home/ana/calc')).toBe('~/calc')
    const long = shortPath('/private/tmp/' + 'a'.repeat(100) + '/calc', 40)
    expect(long.length).toBeLessThanOrEqual(40)
    expect(long.endsWith('/calc')).toBe(true)
  })
})
