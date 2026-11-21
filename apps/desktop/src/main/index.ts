import { join } from 'node:path'

import { app, BrowserWindow, dialog, ipcMain, net, protocol, shell, type IpcMainInvokeEvent } from 'electron'

import { IPC, type AppInfo, type BackendConfig } from '../preload/api'
import { APP_ORIGIN, APP_SCHEME, fileUrl, resolveAppFile } from './appProtocol'
import { envFiles, loadEnvFiles } from './connection'
import { openableInBrowser } from './links'

/** Set by electron-vite while running `electron-vite dev`. */
const devServerUrl = process.env['ELECTRON_RENDERER_URL']

function loadRootEnv(): void {
  // From source the backend and the desktop app share the repository-root .env; the
  // installed app reads the connection file `npm run setup` writes (port and token only).
  // process.loadEnvFile never overrides a variable that is already set, so the first wins.
  loadEnvFiles(envFiles(app.getAppPath(), app.getPath('appData')))
}

function backendConfig(): BackendConfig {
  const port = Number(process.env['HEXMIND_PORT'] ?? 8765)
  return { url: `http://127.0.0.1:${port}`, token: process.env['HEXMIND_API_TOKEN'] || null }
}

function isAppUrl(url: string): boolean {
  if (devServerUrl) return url.startsWith(devServerUrl)
  return url.startsWith(`${APP_ORIGIN}/`)
}

/** Only our own renderer may call privileged IPC handlers. */
function assertTrustedSender(event: IpcMainInvokeEvent): void {
  const url = event.senderFrame?.url ?? ''
  if (!isAppUrl(url)) throw new Error(`Rejected IPC from untrusted frame: ${url}`)
}

function registerIpc(): void {
  ipcMain.handle(IPC.getBackend, (event) => {
    assertTrustedSender(event)
    return backendConfig()
  })
  ipcMain.handle(IPC.appInfo, (event): AppInfo => {
    assertTrustedSender(event)
    return { version: app.getVersion(), platform: process.platform }
  })
  // Main only picks the folder; the backend validates it and owns all file access.
  ipcMain.handle(IPC.pickWorkspace, async (event): Promise<string | null> => {
    assertTrustedSender(event)
    const owner = BrowserWindow.fromWebContents(event.sender)
    const options = {
      title: 'Open or create a project folder',
      buttonLabel: 'Open',
      // createDirectory: the New Folder button on macOS; promptToCreate: typing a new name on Windows
      properties: ['openDirectory' as const, 'createDirectory' as const, 'promptToCreate' as const]
    }
    const result = owner
      ? await dialog.showOpenDialog(owner, options)
      : await dialog.showOpenDialog(options)
    return result.canceled ? null : (result.filePaths[0] ?? null)
  })
}

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    show: false,
    title: 'H.E.X Mind',
    backgroundColor: '#0f1115',
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

  win.once('ready-to-show', () => win.show())

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (openableInBrowser(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return
    event.preventDefault() // the app window never leaves the app
    if (openableInBrowser(url)) void shell.openExternal(url)
  })

  if (devServerUrl) {
    void win.loadURL(devServerUrl)
  } else {
    void win.loadURL(`${APP_ORIGIN}/index.html`)
  }
}

loadRootEnv()

// Must run before the app is ready. "standard" gives app:// pages a real origin.
protocol.registerSchemesAsPrivileged([
  { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } }
])

function serveRenderer(): void {
  const root = join(__dirname, '../renderer')
  protocol.handle(APP_SCHEME, (request) => {
    const file = resolveAppFile(root, request.url)
    if (!file) return new Response('Not found', { status: 404 })
    return net.fetch(fileUrl(file))
  })
}

app.whenReady().then(() => {
  if (!devServerUrl) serveRenderer()
  registerIpc()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
