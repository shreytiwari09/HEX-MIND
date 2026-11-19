import {
  Activity,
  Bot,
  Files,
  FolderOpen,
  History,
  KeyRound,
  PanelBottom,
  PanelRight,
  RefreshCw,
  Rocket,
  Settings,
  type LucideIcon
} from 'lucide-react'
import { useState } from 'react'

import { BackendStatusPill } from './components/BackendStatusPill'
import { EmptyState, PanelHeader } from './components/Panel'
import { ChatPanel } from './features/chat/ChatPanel'
import { useChat } from './features/chat/useChat'
import { EditorArea } from './features/editor/EditorArea'
import { disposeModel } from './features/editor/monaco'
import { useEditorTabs } from './features/editor/useEditorTabs'
import { FileTree } from './features/explorer/FileTree'
import { ObservabilityView, RunList } from './features/observability/ObservabilityView'
import { ModelsScreen, type ModelsTab } from './features/models/ModelsScreen'
import { MissionControl } from './features/missions/MissionControl'
import { MissionList } from './features/missions/MissionList'
import { NewMission } from './features/missions/NewMission'
import { NewPersona } from './features/agents/NewPersona'
import { PersonaEditor } from './features/agents/PersonaEditor'
import { PersonaList } from './features/agents/PersonaList'
import { useTeam } from './features/agents/useTeam'
import { ProvidersPanel } from './features/settings/ProvidersPanel'
import { DiffView } from './features/runs/DiffView'
import { RunEventsPanel } from './features/runs/RunEventsPanel'
import { TasksPanel } from './features/runs/TasksPanel'
import { Welcome } from './features/workspace/Welcome'
import { useWorkspace } from './features/workspace/useWorkspace'
import { useBackendHealth } from './hooks/useBackendHealth'
import { useBackend } from './lib/backend'

type View = 'explorer' | 'missions' | 'models' | 'observability' | 'agents' | 'runs' | 'settings'

const VIEWS: { id: View; label: string; icon: LucideIcon }[] = [
  { id: 'explorer', label: 'Explorer', icon: Files },
  { id: 'missions', label: 'Missions', icon: Rocket },
  { id: 'models', label: 'Models & Keys', icon: KeyRound },
  { id: 'observability', label: 'Observability', icon: Activity },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'runs', label: 'Runs', icon: History },
  { id: 'settings', label: 'Settings', icon: Settings }
]

const BOTTOM_TABS = ['Problems', 'Tasks', 'Agent Events', 'Logs'] as const
type BottomTab = (typeof BOTTOM_TABS)[number]

const SIDEBAR_EMPTY: Record<Exclude<View, 'explorer' | 'missions' | 'models' | 'observability' | 'agents' | 'runs'>, string> = {
  settings: ''
}

export function App() {
  const { config, api } = useBackend()
  const { status, retry } = useBackendHealth(config)
  const workspace = useWorkspace(api, status.kind === 'connected')
  const project = workspace.project
  const editor = useEditorTabs(api, project?.id ?? null, disposeModel)
  const chat = useChat(api, project?.id ?? null)

  const [view, setView] = useState<View>('explorer')
  const [rightOpen, setRightOpen] = useState(true)
  const [bottomOpen, setBottomOpen] = useState(true)
  const [bottomTab, setBottomTab] = useState<BottomTab>('Problems')
  const [treeRefresh, setTreeRefresh] = useState(0)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [diffRunId, setDiffRunId] = useState<string | null>(null)
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null)
  const [creatingMission, setCreatingMission] = useState(false)
  const team = useTeam(api)
  const [selectedPersonaId, setSelectedPersonaId] = useState<string | null>(null)
  const [creatingPersona, setCreatingPersona] = useState(false)
  const [missionsRefresh, setMissionsRefresh] = useState(0)
  const [modelsTab, setModelsTab] = useState<ModelsTab>('connections')

  const openRun = (runId: string) => {
    setSelectedRunId(runId)
    setBottomTab('Agent Events')
    setBottomOpen(true)
  }

  const chatDisabledReason =
    status.kind !== 'connected'
      ? 'The backend is not connected.'
      : !project
        ? 'Open a workspace to start a conversation with the agents.'
        : ''

  const viewLabel = VIEWS.find((v) => v.id === view)?.label ?? ''

  return (
    <div className="app" data-right={rightOpen} data-bottom={bottomOpen}>
      <header className="topbar">
        <div className="topbar__brand">
          <span className="brand-mark" aria-hidden="true">
            HX
          </span>
          <span className="brand-name">H.E.X Mind</span>
          <span className="topbar__divider" aria-hidden="true" />
          <span className="topbar__workspace" title={project?.workspace_path}>
            {project ? project.name : 'No workspace'}
          </span>
          {project && !project.git_enabled && (
            <button
              type="button"
              className="badge badge--button"
              title="Agents need Git to work in an isolated, revertible copy. Click to initialize."
              onClick={() => {
                if (
                  window.confirm(
                    `Initialize a Git repository in ${project.workspace_path} and commit the current files?`
                  )
                ) {
                  void workspace.initGit()
                }
              }}
            >
              No Git: initialize
            </button>
          )}
        </div>
        <div className="topbar__actions">
          <BackendStatusPill status={status} onRetry={retry} />
          <button
            type="button"
            className="icon-button"
            aria-label="Toggle bottom panel"
            aria-pressed={bottomOpen}
            title="Toggle bottom panel"
            onClick={() => setBottomOpen((open) => !open)}
          >
            <PanelBottom size={16} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Toggle chat panel"
            aria-pressed={rightOpen}
            title="Toggle chat panel"
            onClick={() => setRightOpen((open) => !open)}
          >
            <PanelRight size={16} />
          </button>
        </div>
      </header>

      <nav className="activitybar" aria-label="Views">
        {VIEWS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className="activitybar__item"
            aria-label={label}
            aria-current={view === id ? 'page' : undefined}
            title={label}
            onClick={() => setView(id)}
          >
            <Icon size={20} />
          </button>
        ))}
      </nav>

      <aside className="sidebar" aria-label={viewLabel}>
        {view === 'explorer' ? (
          <>
            <PanelHeader
              title={project ? project.name : 'Explorer'}
              actions={
                <>
                  {project && (
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Refresh explorer"
                      title="Refresh"
                      onClick={() => setTreeRefresh((n) => n + 1)}
                    >
                      <RefreshCw size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Open folder"
                    title="Open folder"
                    disabled={status.kind !== 'connected'}
                    onClick={() => void workspace.pickAndOpen()}
                  >
                    <FolderOpen size={14} />
                  </button>
                </>
              }
            />
            {project ? (
              <FileTree
                api={api}
                projectId={project.id}
                activePath={editor.state.active}
                onOpenFile={(path) => void editor.openFile(path)}
                refreshKey={treeRefresh}
              />
            ) : (
              <EmptyState title="No workspace open" />
            )}
          </>
        ) : (
          <>
            <PanelHeader title={viewLabel} />
            {view === 'settings' ? (
              <ProvidersPanel api={api} />
            ) : view === 'models' ? (
              <nav className="mission-list" aria-label="Models and keys sections">
                {(['connections', 'team'] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className="mission-list__item"
                    aria-current={modelsTab === tab ? 'true' : undefined}
                    onClick={() => setModelsTab(tab)}
                  >
                    {tab === 'connections' ? 'Connections' : 'Team models'}
                  </button>
                ))}
              </nav>
            ) : view === 'missions' ? (
              <MissionList
                api={api}
                projectId={project?.id ?? null}
                selectedId={selectedMissionId}
                refreshKey={missionsRefresh}
                onSelect={(id) => {
                  setCreatingMission(false)
                  setSelectedMissionId(id)
                }}
                onNew={() => setCreatingMission(true)}
              />
            ) : view === 'agents' ? (
              <PersonaList
                team={team}
                selectedId={selectedPersonaId}
                onSelect={(id) => {
                  setCreatingPersona(false)
                  setSelectedPersonaId(id)
                }}
                onNew={() => setCreatingPersona(true)}
              />
            ) : view === 'observability' || view === 'runs' ? (
              <RunList
                api={api}
                projectId={project?.id ?? null}
                selectedRunId={selectedRunId}
                onSelect={view === 'runs' ? openRun : setSelectedRunId}
              />
            ) : (
              <EmptyState title={SIDEBAR_EMPTY[view]} />
            )}
          </>
        )}
      </aside>

      <main className="editor">
        {diffRunId ? (
          <DiffView api={api} runId={diffRunId} onClose={() => setDiffRunId(null)} />
        ) : view === 'models' ? (
          <ModelsScreen api={api} tab={modelsTab} />
        ) : view === 'missions' ? (
          creatingMission && project ? (
            <NewMission
              api={api}
              projectId={project.id}
              onCancel={() => setCreatingMission(false)}
              onCreated={(mission) => {
                setCreatingMission(false)
                setSelectedMissionId(mission.id)
                setMissionsRefresh((n) => n + 1)
              }}
            />
          ) : selectedMissionId ? (
            <MissionControl
              key={selectedMissionId}
              api={api}
              config={config}
              missionId={selectedMissionId}
              onChanged={() => setMissionsRefresh((n) => n + 1)}
            />
          ) : (
            <EmptyState title={project ? 'Pick a mission, or start a new one' : 'Open a workspace to start a mission'} />
          )
        ) : view === 'agents' ? (
          creatingPersona ? (
            <NewPersona
              api={api}
              team={team}
              onCancel={() => setCreatingPersona(false)}
              onCreated={(persona) => {
                setCreatingPersona(false)
                setSelectedPersonaId(persona.id)
              }}
            />
          ) : team.personas.find((p) => p.id === selectedPersonaId) ? (
            <PersonaEditor
              api={api}
              team={team}
              persona={team.personas.find((p) => p.id === selectedPersonaId)!}
              onRemoved={() => setSelectedPersonaId(null)}
            />
          ) : (
            <EmptyState title="Pick a team member to edit, or add a new one" />
          )
        ) : view === 'observability' ? (
          <ObservabilityView api={api} runId={selectedRunId} />
        ) : project && editor.state.tabs.length > 0 ? (
          <EditorArea projectId={project.id} editor={editor} />
        ) : (
          <Welcome status={status} workspace={workspace} />
        )}
      </main>

      {rightOpen && (
        <aside className="rightpanel" aria-label="Agent chat">
          <ChatPanel
            chat={chat}
            enabled={chatDisabledReason === ''}
            disabledReason={chatDisabledReason}
            onOpenRun={openRun}
            onOpenFile={(path) => void editor.openFile(path)}
          />
        </aside>
      )}

      {bottomOpen && (
        <section className="bottompanel" aria-label="Panels">
          <div className="tabs" role="tablist">
            {BOTTOM_TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                className="tabs__tab"
                aria-selected={bottomTab === tab}
                onClick={() => setBottomTab(tab)}
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="bottompanel__body" role="tabpanel" aria-label={bottomTab}>
            {bottomTab === 'Agent Events' ? (
              <RunEventsPanel api={api} runId={selectedRunId} onReview={setDiffRunId} />
            ) : bottomTab === 'Tasks' ? (
              <TasksPanel api={api} runId={selectedRunId} />
            ) : (
              <EmptyState title={`No ${bottomTab.toLowerCase()} to show`} />
            )}
          </div>
        </section>
      )}
    </div>
  )
}
