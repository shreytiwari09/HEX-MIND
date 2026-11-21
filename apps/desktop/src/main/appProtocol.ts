import { join, normalize, sep } from 'node:path'
import { pathToFileURL } from 'node:url'

/** The installed app serves its screens from app://hexmind/ instead of file:// so its requests
 * carry a real origin the backend can allow by name (file:// pages send the origin "null",
 * which any sandboxed page on the web can also send). */
export const APP_SCHEME = 'app'
export const APP_ORIGIN = 'app://hexmind'

/** The file under `root` that an app:// URL names, or null for anything outside it. */
export function resolveAppFile(root: string, url: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }
  if (`${parsed.protocol}//${parsed.host}` !== APP_ORIGIN) return null
  const path = decodeURIComponent(parsed.pathname)
  const file = normalize(join(root, path === '/' ? 'index.html' : path))
  const base = normalize(root.endsWith(sep) ? root : root + sep)
  return file.startsWith(base) ? file : null
}

export function fileUrl(file: string): string {
  return pathToFileURL(file).toString()
}
