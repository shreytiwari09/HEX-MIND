#!/usr/bin/env node
// Start H.E.X Mind from source: the backend, then the desktop app. `npm start`.
// `npm start -- --backend-only` starts just the backend (for the installed app).
// Ctrl+C (or closing the app) stops both.
import { spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const windows = process.platform === 'win32'
const backendOnly = process.argv.includes('--backend-only')

if (!existsSync(join(root, '.env'))) {
  console.error('H.E.X is not set up yet. Run: npm run setup')
  process.exit(1)
}
const port = readFileSync(join(root, '.env'), 'utf8').match(/^\s*(?:export\s+)?HEXMIND_PORT\s*=\s*['"]?(\d+)/m)?.[1] ?? '8765'

const children = []
function start(name, command, args) {
  const env = { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE // some editors set it; Electron must not run as plain Node
  const child = spawn(command, args, { cwd: root, stdio: 'inherit', shell: windows, env })
  child.on('exit', (code) => {
    console.log(`${name} stopped${code ? ` (exit ${code})` : ''}`)
    stopAll(code ?? 0)
  })
  children.push(child)
  return child
}

let stopping = false
function stopAll(code = 0) {
  if (stopping) return
  stopping = true
  for (const child of children) if (child.exitCode === null) child.kill()
  setTimeout(() => process.exit(code), 500)
}
process.on('SIGINT', () => stopAll(0))
process.on('SIGTERM', () => stopAll(0))

async function backendUp() {
  for (let i = 0; i < 120; i++) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`)
      if (response.status === 200 || response.status === 401) return true // 401: up, needs the token
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  return false
}

console.log(`Starting the backend on http://127.0.0.1:${port} …`)
start('Backend', 'uv', ['--directory', 'apps/backend', 'run', 'python', '-m', 'app'])
if (!(await backendUp())) {
  console.error('The backend did not answer within 2 minutes. Is Docker running? Try: npm run setup')
  stopAll(1)
} else if (backendOnly) {
  console.log('Backend ready. Open the installed H.E.X Mind app. Ctrl+C stops the backend.')
} else {
  console.log('Backend ready. Opening the app…')
  start('Desktop app', 'npm', ['run', 'dev'])
}
