import { describe, expect, it } from 'vitest'

import { openableInBrowser } from './links'

describe('links opened in the browser', () => {
  it('opens secure pages and apps running on this computer', () => {
    expect(openableInBrowser('https://github.com/heydamir/unslop')).toBe(true)
    expect(openableInBrowser('http://localhost:8501')).toBe(true)
    expect(openableInBrowser('http://localhost:3000/health')).toBe(true)
    expect(openableInBrowser('http://127.0.0.1:41234/')).toBe(true)
  })

  it('opens nothing else', () => {
    for (const url of [
      'http://example.com',
      'http://localhost.evil.com:80',
      'http://localhost',
      'file:///etc/passwd',
      'javascript:alert(1)',
      'http://192.168.1.10:8501'
    ]) {
      expect(openableInBrowser(url)).toBe(false)
    }
  })
})
