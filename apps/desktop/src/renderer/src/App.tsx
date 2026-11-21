import {
  Activity,
  BarChart3,
  Bot,
  BookOpen,
  Files,
  FlaskConical,
  FolderOpen,
  History,
  KeyRound,
  PanelBottom,
  PanelRight,
  Plug,
  RefreshCw,
  Rocket,
  Settings,
  type LucideIcon
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { BackendStatusPill } from './components/BackendStatusPill'
import { BrandMark } from './components/BrandMark'
import { StatusBar } from './components/StatusBar'
import { useToast } from './components/Toasts'
import { CommandPalette } from './features/palette/CommandPalette'
import { matches, type Command } from './features/palette/commands'
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
import { ExperimentsView } from './features/experiments/ExperimentsView'
import { MetricsScope, MetricsView } from './features/metrics/MetricsView'
import { NotificationsPanel } from './features/notifications/NotificationsPanel'
import { notificationsEnabled, useMissionNotifications } from './features/notifications/useMissionNotifications'
import { NewPlugin } from './features/plugins/NewPlugin'
import { AddFromGithub } from './features/skills/AddFromGithub'
import { SkillList } from './features/skills/SkillList'
import { SkillPanel } from './features/skills/SkillPanel'
import { PluginList } from './features/plugins/PluginList'
import { PluginPanel } from './features/plugins/PluginPanel'
import { usePlugins } from './features/plugins/usePlugins'
import { PrivacyPanel } from './features/settings/PrivacyPanel'
import { SearchKeyPanel } from './features/settings/SearchKeyPanel'
import { ProvidersPanel } from './features/settings/ProvidersPanel'
import { DiffView } from './features/runs/DiffView'
import { RunEventsPanel } from './features/runs/RunEventsPanel'
import { TasksPanel } from './features/runs/TasksPanel'
import { Welcome } from './features/workspace/Welcome'
import { useWorkspace } from './features/workspace/useWorkspace'
import { useBackendHealth } from './hooks/useBackendHealth'
import { useBackend } from './lib/backend'

type View = 'explorer' | 'missions' | 'models' | 'observability' | 'agents' | 'skills' | 'plugins' | 'metrics' | 'experiments' | 'runs' | 'settings'

const VIEWS: { id: View; label: string; icon: LucideIcon }[] = [
  { id: 'explorer', label: 'Explorer', icon: Files },
  { id: 'missions', label: 'Missions', icon: Rocket },
  { id: 'models', label: 'Models & Keys', icon: KeyRound },
  { id: 'observability', label: 'Observability', icon: Activity },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'skills', label: 'Skills', icon: BookOpen },
  { id: 'plugins', label: 'Plugins', icon: Plug },
  { id: 'metrics', label: 'Metrics', icon: BarChart3 },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical },
  { id: 'runs', label: 'Runs', icon: History },
  { id: 'settings', label: 'Settings', icon: Settings }
]

const BOTTOM_TABS = ['Problems', 'Tasks', 'Agent Events', 'Logs'] as const
type BottomTab = (typeof BOTTOM_TABS)[number]

const SIDEBAR_EMPTY: Record<Exclude<View, 'explorer' | 'missions' | 'models' | 'observability' | 'agents' | 'skills' | 'plugins' | 'metrics' | 'experiments' | 'runs'>, string> = {
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
  const [planningId, setPlanningId] = useState<string | null>(null)
  const team = useTeam(api)
  const pluginsData = usePlugins(api)
  const [selectedPluginId, setSelectedPluginId] = useState<string | null>(null)
  const [creatingPlugin, setCreatingPlugin] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [addingSkill, setAddingSkill] = useState(false)
  const [metricsMission, setMetricsMission] = useState<string | null>(null)
  const [notify, setNotify] = useState(notificationsEnabled)
  useMissionNotifications({
    api,
    projectId: project?.id ?? null,
    enabled: notify,
    viewingMissionId: view === 'missions' ? selectedMissionId : null,
    onOpen: (id) => {
      setView('missions')
      setCreatingMission(false)
      setSelectedMissionId(id)
    }
  })
  const [selectedPersonaId, setSelectedPersonaId] = useState<string | null>(null)
  const [creatingPersona, setCreatingPersona] = useState(false)
  const [missionsRefresh, setMissionsRefresh] = useState(0)
  const [modelsTab, setModelsTab] = useState<ModelsTab>('connections')

  const toast = useToast()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [appUrl, setAppUrl] = useState<string | null>(null)
  const [hasModels, setHasModels] = useState<boolean | null>(null)
  const connected = status.kind === 'connected'

  // Is the project's app running? Shown in the status bar with its link.
  useEffect(() => {
    if (!connected || !project) {
      setAppUrl(null)
      return
    }
    let live = true
    const check = () =>
      api
        .get<{ status: string; url: string | null }>(`/projects/${project.id}/app`)
        .then((app) => live && setAppUrl(app.status === 'running' ? app.url : null))
        .catch(() => live && setAppUrl(null))
    void check()
    const timer = window.setInterval(check, 10000)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [api, connected, project])

  // Has the user connected any model yet? Drives the first getting-started step.
  useEffect(() => {
    if (!connected) return
    api
      .get<unknown[]>('/connections')
      .then((list) => setHasModels(list.length > 0))
      .catch(() => setHasModels(null))
  }, [api, connected, view])

  useEffect(() => {
    if (workspace.error) toast(`Could not open the folder: ${workspace.error}`, 'error')
  }, [workspace.error, toast])

  const startMission = () => {
    setView('missions')
    setSelectedMissionId(null)
    setPlanningId(null)
    setCreatingMission(true)
  }
  const askChat = (content: string, notice: string) => {
    setRightOpen(true)
    toast(notice, 'info')
    void chat.send(content, 'auto')
  }

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = [
      ...VIEWS.map((v, i) => ({
        id: `view-${v.id}`,
        title: `Go to ${v.label}`,
        group: 'Views',
        shortcut: i < 9 ? `Mod+${i + 1}` : undefined,
        run: () => setView(v.id)
      })),
      { id: 'open-folder', title: 'Open folder…', group: 'Project', shortcut: 'Mod+O', disabled: !connected, run: () => void workspace.pickAndOpen() },
      { id: 'new-mission', title: 'New mission', group: 'Project', keywords: 'build idea plan', disabled: !project, run: startMission },
      { id: 'run-app', title: 'Run the app and get a link', group: 'Project', keywords: 'start launch preview localhost', disabled: !project, run: () => askChat('run it', 'Starting the app in the sandbox…') },
      { id: 'stop-app', title: 'Stop the app', group: 'Project', disabled: !project || !appUrl, run: () => askChat('stop the app', 'Stopping the app…') },
      { id: 'terminal', title: 'Open terminal in the sandbox', group: 'Project', keywords: 'shell console', disabled: !project, run: () => askChat('open terminal', 'Opening a terminal in the project sandbox…') },
      { id: 'new-chat', title: 'New conversation', group: 'Chat', disabled: !project, run: () => { setRightOpen(true); chat.startNew() } },
      { id: 'toggle-chat', title: 'Toggle chat panel', group: 'Layout', shortcut: 'Mod+L', run: () => setRightOpen((o) => !o) },
      { id: 'toggle-bottom', title: 'Toggle bottom panel', group: 'Layout', shortcut: 'Mod+J', run: () => setBottomOpen((o) => !o) },
      { id: 'settings', title: 'Open settings', group: 'Layout', shortcut: 'Mod+,', run: () => setView('settings') },
      ...workspace.recent
        .filter((p) => p.id !== project?.id)
        .map((p) => ({ id: `recent-${p.id}`, title: `Open recent: ${p.name}`, group: 'Recent projects', keywords: p.workspace_path, disabled: !connected, run: () => void workspace.open(p.workspace_path) }))
    ]
    if (project && !project.git_enabled) {
      list.push({ id: 'init-git', title: 'Initialize Git for this project', group: 'Project', run: () => void workspace.initGit() })
    }
    const order = ['Project', 'Chat', 'Recent projects', 'Views', 'Layout']
    return list.sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, project, appUrl, workspace.recent, chat])

  // Global shortcuts. ⌘K / Ctrl+K and ⌘⇧P / Ctrl+Shift+P open the palette.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (matches(event, 'Mod+K') || matches(event, 'Mod+Shift+P')) {
        event.preventDefault()
        setPaletteOpen((o) => !o)
        return
      }
      const hit = commands.find((c) => c.shortcut && !c.disabled && matches(event, c.shortcut))
      if (hit) {
        event.preventDefault()
        hit.run()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [commands])

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
          <BrandMark />
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
              <ProvidersPanel api={api} onOpenModels={() => setView('models')} />
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
                  setPlanningId(null)
                  setSelectedMissionId(id)
                }}
                selectedPlanningId={planningId}
                onSelectPlanning={(id) => {
                  setSelectedMissionId(null)
                  setCreatingMission(false)
                  setPlanningId(id)
                }}
                onNew={() => {
                  setPlanningId(null)
                  setCreatingMission(true)
                }}
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
            ) : view === 'skills' ? (
              <SkillList
                team={team}
                selectedName={selectedSkill}
                onSelect={(name) => {
                  setAddingSkill(false)
                  setSelectedSkill(name)
                }}
                onAdd={() => setAddingSkill(true)}
              />
            ) : view === 'metrics' ? (
              <MetricsScope api={api} projectId={project?.id ?? null} selected={metricsMission} onSelect={setMetricsMission} />
            ) : view === 'experiments' ? (
              <EmptyState title="Runs of the mission benchmark under different conditions" />
            ) : view === 'plugins' ? (
              <PluginList
                data={pluginsData}
                selectedId={selectedPluginId}
                onSelect={(id) => {
                  setCreatingPlugin(false)
                  setSelectedPluginId(id)
                }}
                onNew={() => setCreatingPlugin(true)}
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
          (creatingMission || planningId) && project ? (
            <NewMission
              key={planningId ?? 'new'}
              api={api}
              projectId={project.id}
              initialSessionId={planningId}
              onCancel={() => {
                setCreatingMission(false)
                setPlanningId(null)
              }}
              onCreated={(mission) => {
                setCreatingMission(false)
                setPlanningId(null)
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
        ) : view === 'settings' && project ? (
          <div className="settings">
            <PrivacyPanel key={project.id} api={api} projectId={project.id} projectName={project.name} />
            <SearchKeyPanel api={api} />
            <NotificationsPanel onChange={setNotify} />
          </div>
        ) : view === 'skills' ? (
          addingSkill ? (
            <AddFromGithub
              api={api}
              team={team}
              onCancel={() => setAddingSkill(false)}
              onInstalled={(skill) => {
                setAddingSkill(false)
                setSelectedSkill(skill.name)
              }}
            />
          ) : selectedSkill ? (
            <SkillPanel key={selectedSkill} api={api} team={team} name={selectedSkill} onRemoved={() => setSelectedSkill(null)} />
          ) : (
            <EmptyState title="Pick a skill, or add one from GitHub" />
          )
        ) : view === 'metrics' ? (
          project ? (
            <MetricsView key={`${project.id}:${metricsMission}`} api={api} projectId={project.id} missionId={metricsMission} />
          ) : (
            <EmptyState title="Open a workspace to see its metrics" />
          )
        ) : view === 'experiments' ? (
          <ExperimentsView api={api} />
        ) : view === 'plugins' ? (
          creatingPlugin ? (
            <NewPlugin
              api={api}
              data={pluginsData}
              onCancel={() => setCreatingPlugin(false)}
              onCreated={(plugin) => {
                setCreatingPlugin(false)
                setSelectedPluginId(plugin.id)
              }}
            />
          ) : pluginsData.plugins.find((p) => p.id === selectedPluginId) ? (
            <PluginPanel
              api={api}
              data={pluginsData}
              team={team}
              plugin={pluginsData.plugins.find((p) => p.id === selectedPluginId)!}
              onRemoved={() => setSelectedPluginId(null)}
            />
          ) : (
            <EmptyState title="Pick a plugin, or add one" />
          )
        ) : view === 'observability' ? (
          <ObservabilityView api={api} runId={selectedRunId} />
        ) : project && editor.state.tabs.length > 0 ? (
          <EditorArea projectId={project.id} editor={editor} />
        ) : (
          <Welcome
            status={status}
            workspace={workspace}
            hasModels={hasModels}
            onOpenModels={() => setView('models')}
            onStartMission={startMission}
          />
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

      <StatusBar status={status} project={project} appUrl={appUrl} onOpenPalette={() => setPaletteOpen(true)} />
      {paletteOpen && <CommandPalette commands={commands} onClose={() => setPaletteOpen(false)} />}
    </div>
  )
}
