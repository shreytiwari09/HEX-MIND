import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { resolveAppFile } from './appProtocol'

describe('app:// protocol for the installed app', () => {
  const root = join('/opt', 'hex', 'renderer')

  it('serves files from the renderer folder', () => {
    expect(resolveAppFile(root, 'app://hexmind/index.html')).toBe(join(root, 'index.html'))
    expect(resolveAppFile(root, 'app://hexmind/')).toBe(join(root, 'index.html'))
    expect(resolveAppFile(root, 'app://hexmind/assets/a%20b.js')).toBe(join(root, 'assets', 'a b.js'))
  })

  it('never serves anything outside it or for another host', () => {
    // the URL parser already folds ../ away, so these stay inside the renderer folder
    expect(resolveAppFile(root, 'app://hexmind/../../etc/passwd')).toBe(join(root, 'etc', 'passwd'))
    // an encoded slash would escape after decoding: refused
    expect(resolveAppFile(root, 'app://hexmind/a%2F..%2F..%2F..%2Fetc%2Fpasswd')).toBeNull()
    expect(resolveAppFile(root, 'app://other/index.html')).toBeNull()
    expect(resolveAppFile(root, 'not a url')).toBeNull()
  })
})
