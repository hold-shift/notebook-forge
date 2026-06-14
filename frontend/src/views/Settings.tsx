import { useEffect, useState } from 'react'
import { api } from '../api'
import { Button } from '../ui'

export function Settings({ onBack }: { onBack: () => void }) {
  const [secrets, setSecrets] = useState<Record<string, boolean>>({})
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [faceGate, setFaceGate] = useState('block')
  const [sketchState, setSketchState] = useState('')
  const [polishModel, setPolishModel] = useState('')
  const [polishRules, setPolishRules] = useState('')
  const [polishState, setPolishState] = useState('')
  const [narrativeLabel, setNarrativeLabel] = useState('')
  const [narrativeState, setNarrativeState] = useState('')
  const [footerNotice, setFooterNotice] = useState('')
  const [footerLicenseLabel, setFooterLicenseLabel] = useState('')
  const [footerLicenseUrl, setFooterLicenseUrl] = useState('')
  const [footerState, setFooterState] = useState('')

  useEffect(() => {
    api.settings().then((s) => {
      setSecrets(s.secrets)
      setModel(s.sketch.model)
      setPrompt(s.sketch.default_prompt)
      setFaceGate(s.sketch.face_gate)
      setPolishModel(s.polish.model)
      setPolishRules(s.polish.extra_rules)
      setNarrativeLabel(s.narrative.label)
      setFooterNotice(s.footer.notice)
      setFooterLicenseLabel(s.footer.license_label)
      setFooterLicenseUrl(s.footer.license_url)
    })
  }, [])

  const saveSketch = () => {
    setSketchState('saving')
    api.saveSketchSettings({ model, default_prompt: prompt, face_gate: faceGate }).then(
      () => setSketchState('Saved'),
      (e) => setSketchState(`Failed: ${e}`),
    )
  }

  const savePolish = () => {
    setPolishState('saving')
    api.savePolishSettings({ model: polishModel, extra_rules: polishRules }).then(
      () => setPolishState('Saved'),
      (e) => setPolishState(`Failed: ${e}`),
    )
  }

  const saveNarrative = () => {
    setNarrativeState('saving')
    api.saveNarrativeSettings({ label: narrativeLabel }).then(
      () => setNarrativeState('Saved'),
      (e) => setNarrativeState(`Failed: ${e}`),
    )
  }

  const saveFooter = () => {
    setFooterState('saving')
    api
      .saveFooterSettings({
        notice: footerNotice,
        license_label: footerLicenseLabel,
        license_url: footerLicenseUrl,
      })
      .then(
        () => setFooterState('Saved'),
        (e) => setFooterState(`Failed: ${e}`),
      )
  }

  return (
    <div className="settings-page">
      <button type="button" className="settings-back" onClick={onBack}>
        ← Library
      </button>

      <h1 className="settings-title">Settings</h1>

      {/* Sketch generation */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Sketch generation</h2>
          <p>Production defaults for every figure sketch. Override per-figure via the Regenerate button in the editor.</p>
        </div>
        <div className="settings-fields">
          <div className="settings-row">
            <label htmlFor="sketch-model">Image model</label>
            <div className="settings-control">
              <input
                id="sketch-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="gemini-3-pro-image"
              />
              <span className="settings-hint">
                Alternatives: <code>gemini-3.1-flash-image-preview</code>, <code>gemini-2.5-flash-image</code>
              </span>
            </div>
          </div>
          <div className="settings-row settings-row-tall">
            <label htmlFor="sketch-prompt">Silhouette prompt</label>
            <textarea
              id="sketch-prompt"
              rows={8}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>
          <div className="settings-row">
            <label htmlFor="face-gate">Face gate</label>
            <div className="settings-control">
              <select id="face-gate" value={faceGate} onChange={(e) => setFaceGate(e.target.value)}>
                <option value="block">block</option>
                <option value="warn">warn</option>
              </select>
              <span className="settings-hint">
                block = refuse sketches with visible faces after retries · warn = allow but flag
              </span>
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={saveSketch}>Save sketch settings</Button>
            {sketchState && <span className="settings-state muted">{sketchState}</span>}
          </div>
        </div>
      </section>

      {/* Text polish */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Text polish</h2>
          <p>Mechanical cleanup — typography, whitespace, obvious spelling typos. Flags any word-level change for review; never auto-applies prose edits.</p>
        </div>
        <div className="settings-fields">
          <div className="settings-row">
            <label htmlFor="polish-model">Text model</label>
            <div className="settings-control">
              <input
                id="polish-model"
                value={polishModel}
                onChange={(e) => setPolishModel(e.target.value)}
                placeholder="gemini-2.5-flash"
              />
            </div>
          </div>
          <div className="settings-row settings-row-tall">
            <label htmlFor="polish-rules">Extra rules</label>
            <div className="settings-control">
              <textarea
                id="polish-rules"
                rows={4}
                value={polishRules}
                onChange={(e) => setPolishRules(e.target.value)}
                placeholder="Appended after the built-in scope rules. Leave blank to use defaults only."
              />
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={savePolish}>Save polish settings</Button>
            {polishState && <span className="settings-state muted">{polishState}</span>}
          </div>
        </div>
      </section>

      {/* Narrative voice */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Narrative voice</h2>
          <p>
            Optional small-caps label above each narrative panel on published pages (e.g. 'From
            the author'). Leave blank for none — the recommended default. Per-document override
            lives in the document's meta bar.
          </p>
        </div>
        <div className="settings-fields">
          <div className="settings-row">
            <label htmlFor="narrative-label">Panel label</label>
            <div className="settings-control">
              <input
                id="narrative-label"
                value={narrativeLabel}
                onChange={(e) => setNarrativeLabel(e.target.value)}
                placeholder="e.g. From the author (leave blank for none)"
              />
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={saveNarrative}>
              Save narrative settings
            </Button>
            {narrativeState && <span className="settings-state muted">{narrativeState}</span>}
          </div>
        </div>
      </section>

      {/* Footer & licence */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Footer &amp; licence</h2>
          <p>
            The copyright and licence line printed at the foot of every published HTML page, the
            homepage, and every Google Doc. The licence label links to the URL below when set.
          </p>
        </div>
        <div className="settings-fields">
          <div className="settings-row">
            <label htmlFor="footer-notice">Copyright notice</label>
            <div className="settings-control">
              <input
                id="footer-notice"
                value={footerNotice}
                onChange={(e) => setFooterNotice(e.target.value)}
                placeholder="© Christopher M.R. Skitch · The Skitch Family Archive"
              />
            </div>
          </div>
          <div className="settings-row settings-row-tall">
            <label htmlFor="footer-license-label">Licence label</label>
            <div className="settings-control">
              <textarea
                id="footer-license-label"
                rows={3}
                value={footerLicenseLabel}
                onChange={(e) => setFooterLicenseLabel(e.target.value)}
                placeholder="Licensed CC BY-NC-ND 4.0 — read and share with attribution; no commercial use or adaptations."
              />
              <span className="settings-hint">
                This text becomes the clickable link to the licence URL.
              </span>
            </div>
          </div>
          <div className="settings-row">
            <label htmlFor="footer-license-url">Licence URL</label>
            <div className="settings-control">
              <input
                id="footer-license-url"
                value={footerLicenseUrl}
                onChange={(e) => setFooterLicenseUrl(e.target.value)}
                placeholder="https://creativecommons.org/licenses/by-nc-nd/4.0/"
              />
              <span className="settings-hint">
                Leave blank to print the licence label as plain text (no link).
              </span>
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={saveFooter}>Save footer settings</Button>
            {footerState && <span className="settings-state muted">{footerState}</span>}
          </div>
        </div>
      </section>

      {/* Connections */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Connections</h2>
          <p>Secrets live in the macOS keychain. Set them from a terminal: <code>uv run keyring set notebook-forge &lt;name&gt;</code></p>
        </div>
        <div className="settings-fields">
          <ul className="secret-list">
            {Object.entries(secrets).map(([name, present]) => (
              <li key={name}>
                <span className={`dot ${present ? 'clean' : 'dirty'}`} />
                <span className="secret-name">{name}</span>
                <span className={`secret-status ${present ? 'ok' : 'missing'}`}>
                  {present ? 'Configured' : 'Not configured'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  )
}
