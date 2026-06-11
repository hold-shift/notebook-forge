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
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [faceGate, setFaceGate] = useState('block')
  const [sketchState, setSketchState] = useState('')

  useEffect(() => {
    api.settings().then((s) => {
      setTitle(s.homepage.title ?? '')
      setWelcome(s.homepage.welcome ?? '')
      setDedication(s.homepage.dedication ?? '')
      setSecrets(s.secrets)
      setTargets(s.targets.filter((t) => t.kind !== 'drive'))
      setModel(s.sketch.model)
      setPrompt(s.sketch.default_prompt)
      setFaceGate(s.sketch.face_gate)
    })
  }, [])

  const saveSketch = () => {
    setSketchState('saving')
    api.saveSketchSettings({ model, default_prompt: prompt, face_gate: faceGate }).then(
      () => setSketchState('saved'),
      (e) => setSketchState(`save failed: ${e}`),
    )
  }

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

      <h3>Sketch generation</h3>
      <p className="muted">
        Defaults are the production values that generated every published sketch. A figure-level
        prompt override is available on each Regenerate button in the editor.
      </p>
      <label>
        Gemini image model (production used <code>gemini-3-pro-image</code>; alternatives per the
        PRD: <code>gemini-3.1-flash-image-preview</code>, <code>gemini-2.5-flash-image</code>)
        <input value={model} onChange={(e) => setModel(e.target.value)} />
      </label>
      <label>
        Default silhouette prompt
        <textarea rows={10} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </label>
      <label>
        Face gate (block = refuse a sketch that still shows a face after retries; warn = allow
        but flag)
        <select value={faceGate} onChange={(e) => setFaceGate(e.target.value)}>
          <option value="block">block</option>
          <option value="warn">warn</option>
        </select>
      </label>
      <div className="settings-actions">
        <button type="button" onClick={saveSketch}>
          Save sketch settings
        </button>
        <span className="muted">{sketchState}</span>
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
