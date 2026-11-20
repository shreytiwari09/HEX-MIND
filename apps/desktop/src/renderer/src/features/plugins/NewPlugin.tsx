import { useState } from 'react'

import type { ApiClient } from '../../lib/api'
import { describeError } from '../missions/actions'
import type { Plugin } from './types'
import type { PluginsData } from './usePlugins'

interface Props {
  api: ApiClient
  data: PluginsData
  onCreated: (plugin: Plugin) => void
  onCancel: () => void
}

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)

/** Add a plugin (an MCP server). It starts off, and nothing runs until you turn it on. */
export function NewPlugin({ api, data, onCreated, onCancel }: Props) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [transport, setTransport] = useState<'stdio' | 'http'>('stdio')
  const [image, setImage] = useState('')
  const [command, setCommand] = useState('')
  const [mount, setMount] = useState<'none' | 'read' | 'write'>('none')
  const [network, setNetwork] = useState(false)
  const [hosts, setHosts] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const hostList = hosts
      .split(/[\s,]+/)
      .map((h) => h.trim())
      .filter(Boolean)
    const config =
      transport === 'stdio'
        ? {
            transport,
            image: image || data.options.images[0],
            command,
            mount,
            network: network ? 'allowlist' : 'none',
            allow_hosts: network ? hostList : []
          }
        : { transport, url }
    try {
      const created = await api.post<Plugin>('/plugins', { id: slug(name), name: name.trim(), description, config })
      await data.reload()
      onCreated(created)
    } catch (err) {
      setError(describeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="persona-editor" onSubmit={(event) => void submit(event)}>
      <h2 className="mission__title">Add a plugin</h2>
      <p className="mission__muted">
        A plugin is third-party code, so it runs in the same locked-down sandbox as your project&apos;s checks, with only
        what you give it here. It starts off.
      </p>
      <label className="new-mission__field">
        Name
        <input required minLength={2} value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="new-mission__field">
        What it does (optional)
        <input value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      <label className="new-mission__field">
        Where it runs
        <select value={transport} onChange={(event) => setTransport(event.target.value as 'stdio' | 'http')}>
          <option value="stdio">In the sandbox (a command)</option>
          <option value="http">A remote server (https)</option>
        </select>
      </label>

      {transport === 'stdio' ? (
        <>
          <label className="new-mission__field">
            Image
            <select value={image || data.options.images[0] || ''} onChange={(event) => setImage(event.target.value)}>
              {data.options.images.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="new-mission__field">
            Command
            <input required value={command} onChange={(event) => setCommand(event.target.value)} placeholder="node /work/server.js" />
          </label>
          <label className="new-mission__field">
            Project files it can see
            <select value={mount} onChange={(event) => setMount(event.target.value as 'none' | 'read' | 'write')}>
              <option value="none">None</option>
              <option value="read">Read only</option>
              <option value="write">Read and write (needs your approval)</option>
            </select>
          </label>
          <label className="persona-editor__skill">
            <input type="checkbox" checked={network} onChange={(event) => setNetwork(event.target.checked)} />
            <span>It needs the internet (needs your approval)</span>
          </label>
          {network && (
            <label className="new-mission__field">
              Hosts it may reach
              <input
                required
                value={hosts}
                onChange={(event) => setHosts(event.target.value)}
                placeholder="api.example.com, cdn.example.com"
              />
            </label>
          )}
        </>
      ) : (
        <label className="new-mission__field">
          Address
          <input required type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://mcp.example.com/mcp" />
        </label>
      )}

      {error && (
        <p role="alert" className="mission__error">
          {error}
        </p>
      )}
      <div className="new-mission__actions">
        <button type="submit" className="button button--primary" disabled={busy || slug(name).length < 2}>
          Add plugin
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
