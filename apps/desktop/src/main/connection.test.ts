import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { connectionFile, envFiles, loadEnvFiles } from './connection'

describe('backend connection for the desktop app', () => {
  it('reads the repository .env first and the per-user file second, skipping missing ones', () => {
    const root = mkdtempSync(join(tmpdir(), 'hex-'))
    const appPath = join(root, 'apps', 'desktop')
    mkdirSync(appPath, { recursive: true })
    const appData = join(root, 'appdata')

    expect(envFiles(appPath, appData)).toEqual([])

    mkdirSync(join(appData, 'hexmind'), { recursive: true })
    writeFileSync(connectionFile(appData), 'HEXMIND_PORT=8770\n')
    expect(envFiles(appPath, appData)).toEqual([join(appData, 'hexmind', 'desktop.env')])

    writeFileSync(join(root, '.env'), 'HEXMIND_PORT=8765\n')
    expect(envFiles(appPath, appData)).toEqual([join(root, '.env'), connectionFile(appData)])
  })

  it('keeps going when a file cannot be read', () => {
    const read: string[] = []
    loadEnvFiles(['a', 'b'], (file) => {
      read.push(file)
      if (file === 'a') throw new Error('unreadable')
    })
    expect(read).toEqual(['a', 'b'])
  })
})
