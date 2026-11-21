#!/usr/bin/env node
// One-time setup for H.E.X Mind on macOS, Windows or Linux: `npm run setup`.
// Checks the tools it needs, creates .env with fresh random secrets (never printed), installs
// the desktop and backend dependencies, starts the database, applies migrations, pulls the
// sandbox images, and writes the installed app's connection file (port and token only).
// Safe to run again: it never overwrites an existing .env.
import { spawnSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const windows = process.platform === 'win32'
const SANDBOX_IMAGES = ['node:22-alpine', 'python:3.11-slim']
const skipImages = process.argv.includes('--skip-images')

const say = (text) => console.log(`\x1b[36m›\x1b[0m ${text}`)
const ok = (text) => console.log(`\x1b[32m✓\x1b[0m ${text}`)
function fail(text, help) {
  console.error(`\x1b[31m✗ ${text}\x1b[0m`)
  if (help) console.error(`  ${help}`)
  process.exit(1)
}

function run(command, args, { quiet = false, cwd = root } = {}) {
  const result = spawnSync(command, args, { cwd, stdio: quiet ? 'pipe' : 'inherit', shell: windows, encoding: 'utf8' })
  return result.status === 0 ? (result.stdout ?? '').trim() || 'ok' : null
}

// ---------- 1. Tools ----------
const [major, minor] = process.versions.node.split('.').map(Number)
if (major < 20 || (major === 20 && minor < 12)) fail(`Node.js ${process.versions.node} is too old`, 'Install Node.js 20.12 or newer: https://nodejs.org')
ok(`Node.js ${process.versions.node}`)
if (!run('git', ['--version'], { quiet: true })) fail('Git is not installed', 'Install it from https://git-scm.com/downloads')
ok('Git')
if (!run('uv', ['--version'], { quiet: true }))
  fail('uv (the Python tool H.E.X uses) is not installed', 'Install it: https://docs.astral.sh/uv/getting-started/installation/ then run this again')
ok('uv')
if (!run('docker', ['info', '--format', '{{.ServerVersion}}'], { quiet: true }))
  fail('Docker is not running', 'Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it, then run this again')
ok('Docker')

// ---------- 2. .env with fresh secrets ----------
const envPath = join(root, '.env')
if (existsSync(envPath)) {
  ok('.env already exists (left unchanged)')
} else {
  const token = randomBytes(32).toString('base64url')
  const dbPassword = randomBytes(18).toString('base64url')
  const env = readFileSync(join(root, '.env.example'), 'utf8')
    .replace(/^HEXMIND_API_TOKEN=.*$/m, `HEXMIND_API_TOKEN=${token}`)
    .replace(/^HEXMIND_DB_PASSWORD=.*$/m, `HEXMIND_DB_PASSWORD=${dbPassword}`)
    .replace(/^(HEXMIND_DATABASE_URL=postgresql\+asyncpg:\/\/hexmind:)[^@]*@/m, `$1${dbPassword}@`)
  writeFileSync(envPath, env, { mode: 0o600 })
  ok('Created .env with a new access token and database password (add model keys in the app, not here)')
}

// Read only the two values the desktop app needs; nothing is printed.
const envText = readFileSync(envPath, 'utf8')
// Same leniency as the backend: optional `export`, spaces around =, optional quotes.
const value = (name) =>
  envText.match(new RegExp(`^\\s*(?:export\\s+)?${name}\\s*=\\s*(.*)$`, 'm'))?.[1]?.trim().replace(/^(['"])(.*)\1$/, '$2') ?? ''
const port = value('HEXMIND_PORT') || '8765'
const token = value('HEXMIND_API_TOKEN')
if (!token) fail('.env has no HEXMIND_API_TOKEN', 'Delete .env and run `npm run setup` again to create a fresh one')

// ---------- 3. Dependencies ----------
say('Installing the desktop app (npm)…')
if (!run('npm', ['install', '--no-audit', '--no-fund'])) fail('npm install failed (see above)')
ok('Desktop dependencies')
say('Installing the backend (Python, through uv)…')
if (!run('uv', ['--directory', 'apps/backend', 'sync'])) fail('uv sync failed (see above)')
ok('Backend dependencies')

// ---------- 4. Database ----------
say('Starting the database (PostgreSQL in Docker)…')
if (!run('docker', ['compose', 'up', '-d', '--wait'])) fail('The database did not start (see above)')
if (!run('uv', ['--directory', 'apps/backend', 'run', 'alembic', 'upgrade', 'head'])) fail('Database migrations failed (see above)')
ok('Database ready')

// ---------- 5. Sandbox images ----------
if (!skipImages) {
  for (const image of SANDBOX_IMAGES) {
    say(`Pulling sandbox image ${image}…`)
    if (!run('docker', ['pull', '-q', image])) fail(`Could not pull ${image}`)
  }
  ok('Sandbox images')
}

// ---------- 6. Connection file for the installed app ----------
// Same folder Electron calls appData on each system (see apps/desktop/src/main/connection.ts).
const appData = windows
  ? process.env.APPDATA || join(homedir(), 'AppData', 'Roaming')
  : process.platform === 'darwin'
    ? join(homedir(), 'Library', 'Application Support')
    : process.env.XDG_CONFIG_HOME || join(homedir(), '.config')
const connection = join(appData, 'hexmind', 'desktop.env')
mkdirSync(dirname(connection), { recursive: true })
writeFileSync(connection, `# Written by npm run setup: how the desktop app reaches the local backend.\nHEXMIND_PORT=${port}\nHEXMIND_API_TOKEN=${token}\n`, { mode: 0o600 })
if (!windows) chmodSync(connection, 0o600)
ok('Desktop app connection saved')

console.log(`
\x1b[1mH.E.X Mind is set up.\x1b[0m
  Start it:            npm start
  Build an installer:  npm run package   (then start the backend with: npm run backend)
  Add a model key:     in the app, Models & Keys → Connections (free Groq or Gemini keys work)
`)
