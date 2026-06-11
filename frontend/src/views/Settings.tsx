import { useEffect, useState } from 'react'
import { api } from '../api'

export function Settings({ onBack }: { onBack: () => void }) {
  const [title, setTitle] = useState('')
  const [welcome, setWelcome] = useState('')
  const [dedication, setDedication] = useState('')
  const [secrets, setSecrets] = useState<Record<string, boolean>>({})
  const [targets, setTargets] = useState<{ name: string; kind: string }[]>([])
  const [state, setState] = useState('')
  const [rebuilding, setRebuilding] = useState('')

  useEffect(() => {
    api.settings().then((s) => {
      setTitle(s.homepage.title ?? '')
      setWelcome(s.homepage.welcome ?? '')
      setDedication(s.homepage.dedication ?? '')
      setSecrets(s.secrets)
      setTargets(s.targets.filter((t) => t.kind !== 'drive'))
    })
  }, [])

  const save = () => {
    setState('saving')
    api.saveHomepage({ title, welcome, dedication }).then(
      () => setState('saved — use Rebuild index to publish'),
      (e) => setState(`save failed: ${e}`),
    )
  }

  const rebuild = (target: string) => {
    setRebuilding(target)
    api.rebuildIndex(target).then(
      (r) => {
        setRebuilding('')
        setState(
          r.detail.commit
            ? `index pushed to ${target} (${r.detail.commit.slice(0, 7)})`
            : `index rebuilt for ${target}`,
        )
      },
      (e) => {
        setRebuilding('')
        setState(`rebuild failed: ${e}`)
      },
    )
  }

  return (
    <div className="settings">
      <button type="button" onClick={onBack}>
        ← Library
      </button>
      <h1>Settings</h1>

      <h3>Homepage (collection index)</h3>
      <p className="muted">
        The index page is generated from these fields plus the document catalogue. Saving here
        does not publish — use Rebuild index below.
      </p>
      <label>
        Site title
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Welcome (blank line separates paragraphs)
        <textarea rows={6} value={welcome} onChange={(e) => setWelcome(e.target.value)} />
      </label>
      <label>
        Dedication (optional)
        <input value={dedication} onChange={(e) => setDedication(e.target.value)} />
      </label>
      <div className="settings-actions">
        <button type="button" onClick={save}>
          Save homepage
        </button>
        {targets.map((t) => (
          <button
            key={t.name}
            type="button"
            disabled={rebuilding === t.name}
            onClick={() => rebuild(t.name)}
          >
            {rebuilding === t.name ? 'Rebuilding…' : `Rebuild index → ${t.name}`}
          </button>
        ))}
        <span className="muted">{state}</span>
      </div>

      <h3>Connections</h3>
      <ul className="secret-list">
        {Object.entries(secrets).map(([name, present]) => (
          <li key={name}>
            <span className={`dot ${present ? 'clean' : 'dirty'}`} /> {name}:{' '}
            {present ? 'configured' : 'not configured'}
          </li>
        ))}
      </ul>
      <p className="muted">
        Secrets live in the macOS keychain — set them from a terminal, e.g.{' '}
        <code>uv run keyring set notebook-forge gemini-api-key</code>.
      </p>
    </div>
  )
}
