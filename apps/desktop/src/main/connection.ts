import { existsSync } from 'node:fs'
import { join } from 'node:path'

/** Where `npm run setup` writes the backend connection for the installed app: only the
 * backend's port and its access token (never a provider key). One per user, same path on
 * every OS family: ~/Library/Application Support/hexmind (macOS), %APPDATA%\hexmind
 * (Windows), ~/.config/hexmind (Linux). Keep in sync with scripts/setup.mjs. */
export function connectionFile(appData: string): string {
  return join(appData, 'hexmind', 'desktop.env')
}

/** Files to read, first match wins for each variable: the repository's .env when running
 * from source, then the per-user connection file (the installed app). */
export function envFiles(appPath: string, appData: string): string[] {
  return [join(appPath, '..', '..', '.env'), connectionFile(appData)].filter((f) => existsSync(f))
}

export function loadEnvFiles(files: string[], load: (file: string) => void = process.loadEnvFile): void {
  for (const file of files) {
    try {
      load(file)
    } catch {
      // An unreadable file is skipped: the renderer shows "not configured".
    }
  }
}
