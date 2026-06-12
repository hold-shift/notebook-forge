import { useEffect, useState } from 'react'
import { api } from '../api'

export function Settings({ onBack }: { onBack: () => void }) {
  const [secrets, setSecrets] = useState<Record<string, boolean>>({})
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [faceGate, setFaceGate] = useState('block')
  const [sketchState, setSketchState] = useState('')
  const [polishModel, setPolishModel] = useState('')
  const [polishRules, setPolishRules] = useState('')
  const [polishState, setPolishState] = useState('')

  useEffect(() => {
    api.settings().then((s) => {
      setSecrets(s.secrets)
      setModel(s.sketch.model)
      setPrompt(s.sketch.default_prompt)
      setFaceGate(s.sketch.face_gate)
      setPolishModel(s.polish.model)
      setPolishRules(s.polish.extra_rules)
    })
  }, [])

  const savePolish = () => {
    setPolishState('saving')
    api.savePolishSettings({ model: polishModel, extra_rules: polishRules }).then(
      () => setPolishState('saved'),
      (e) => setPolishState(`save failed: ${e}`),
    )
  }

  const saveSketch = () => {
    setSketchState('saving')
    api.saveSketchSettings({ model, default_prompt: prompt, face_gate: faceGate }).then(
      () => setSketchState('saved'),
      (e) => setSketchState(`save failed: ${e}`),
    )
  }

  return (
    <div className="settings">
      <button type="button" onClick={onBack}>
        ← Library
      </button>
      <h1>Settings</h1>

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

      <h3>Text polish</h3>
      <p className="muted">
        Gemini Flash mechanical cleanup — typography, whitespace, and obvious spelling typos. Run
        via ✨ Polish text in the editor. Flags any word-level change for review; never auto-applies
        prose edits.
      </p>
      <label>
        Gemini text model (default: <code>gemini-2.5-flash</code>)
        <input value={polishModel} onChange={(e) => setPolishModel(e.target.value)} />
      </label>
      <label>
        Extra rules (appended after the built-in scope rules; blank = defaults only)
        <textarea rows={4} value={polishRules} onChange={(e) => setPolishRules(e.target.value)} />
      </label>
      <div className="settings-actions">
        <button type="button" onClick={savePolish}>
          Save polish settings
        </button>
        <span className="muted">{polishState}</span>
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
