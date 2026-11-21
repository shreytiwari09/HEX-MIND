import { Command as CommandIcon, ExternalLink, FolderGit2, Folder } from 'lucide-react'

import { shortcutLabel } from '../features/palette/commands'
import type { BackendStatus } from '../hooks/useBackendHealth'
import type { Project } from '../lib/api'

interface Props {
  status: BackendStatus
  project: Project | null
  appUrl: string | null
  onOpenPalette: () => void
}

const STATUS_TEXT: Record<BackendStatus['kind'], string> = {
  connected: 'Backend ready',
  connecting: 'Connecting…',
  unreachable: 'Backend offline',
  misconfigured: 'Backend not configured',
  unauthorized: 'Backend refused the token'
}

/** The thin bar along the bottom: what is connected, which project, and the running app. */
export function StatusBar({ status, project, appUrl, onOpenPalette }: Props) {
  return (
    <footer className="statusbar" aria-label="Status">
      <span className="statusbar__item" data-state={status.kind}>
        <span className="statusbar__dot" aria-hidden="true" />
        {STATUS_TEXT[status.kind]}
      </span>
      {project && (
        <span className="statusbar__item" title={project.workspace_path}>
          {project.git_enabled ? <FolderGit2 size={12} aria-hidden="true" /> : <Folder size={12} aria-hidden="true" />}
          {project.name}
          {!project.git_enabled && <span className="statusbar__muted">no git</span>}
        </span>
      )}
      {appUrl && (
        <a className="statusbar__item statusbar__link" href={appUrl} target="_blank" rel="noreferrer" title="Open the running app">
          <span className="statusbar__dot statusbar__dot--live" aria-hidden="true" />
          App running · {appUrl.replace(/^https?:\/\//, '')}
          <ExternalLink size={11} aria-hidden="true" />
        </a>
      )}
      <span className="statusbar__spacer" />
      <button type="button" className="statusbar__item statusbar__button" onClick={onOpenPalette}>
        <CommandIcon size={12} aria-hidden="true" />
        Commands <kbd className="kbd kbd--quiet">{shortcutLabel('Mod+K')}</kbd>
      </button>
    </footer>
  )
}
