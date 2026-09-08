import { useEffect, useRef, useState } from 'react'
import { BlockNoteView } from '@blocknote/mantine'
import { useCreateBlockNote } from '@blocknote/react'
import type { PartialBlock } from '@blocknote/core'
import '@blocknote/core/fonts/inter.css'
import '@blocknote/mantine/style.css'
import { api, type MasterStatus } from '../api'
import { Button, InfoTip } from '../ui'

type TargetInfo = { name: string; kind: string }

// Short labels + display order for the per-target Re-publish buttons.
const TARGET_LABEL: Record<string, string> = {
  'github-pages': 'HTML',
  'local-folder': 'Local',
  drive: 'Drive',
}
const TARGET_ORDER = ['github-pages', 'local-folder', 'drive']

/** Block editor for the workspace footer. Owns its own BlockNote instance and
 * save state; mounted only once the initial blocks have loaded so the editor
 * is seeded with them. Saves the full block document to the footer setting. */
function FooterEditor({ initialBlocks }: { initialBlocks: unknown[] }) {
  const editor = useCreateBlockNote({
    initialContent: initialBlocks.length ? (initialBlocks as PartialBlock[]) : undefined,
  })
  const [state, setState] = useState('')

  const save = () => {
    setState('saving')
    api.saveFooterSettings({ blocks: editor.document }).then(
      () => setState('Saved'),
      (e) => setState(`Failed: ${e}`),
    )
  }

  return (
    <>
      <div className="footer-editor">
        <BlockNoteView editor={editor} />
      </div>
      <div className="settings-save-row">
        <Button variant="primary" onClick={save}>Save footer</Button>
        {state && <span className="settings-state muted">{state}</span>}
      </div>
    </>
  )
}

export function Settings({ onBack }: { onBack: () => void }) {
  const [secrets, setSecrets] = useState<Record<string, boolean>>({})
  const [model, setModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [faceGate, setFaceGate] = useState('block')
  const [sketchState, setSketchState] = useState('')
  const [polishModel, setPolishModel] = useState('')
  const [polishRules, setPolishRules] = useState('')
  const [polishState, setPolishState] = useState('')
  const [reportModel, setReportModel] = useState('')
  const [reportRules, setReportRules] = useState('')
  const [reportState, setReportState] = useState('')
  const [master, setMaster] = useState<MasterStatus | null>(null)
  const [masterState, setMasterState] = useState('')
  const [narrativeLabel, setNarrativeLabel] = useState('')
  const [narrativeState, setNarrativeState] = useState('')
  const [safeNote, setSafeNote] = useState('')
  const [safeNoteState, setSafeNoteState] = useState('')
  const [footerBlocks, setFooterBlocks] = useState<unknown[] | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(false)
  const [ttsState, setTtsState] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [baseUrlState, setBaseUrlState] = useState('')
  const [headHtml, setHeadHtml] = useState('')
  const [headState, setHeadState] = useState('')
  const [faviconId, setFaviconId] = useState<string | null>(null)
  const [ogImageId, setOgImageId] = useState<string | null>(null)
  const [siteImgState, setSiteImgState] = useState('')
  const faviconInput = useRef<HTMLInputElement>(null)
  const ogImageInput = useRef<HTMLInputElement>(null)
  const [targets, setTargets] = useState<TargetInfo[]>([])
  const [republishState, setRepublishState] = useState<Record<string, string>>({})

  useEffect(() => {
    api.settings().then((s) => {
      setSecrets(s.secrets)
      setModel(s.sketch.model)
      setPrompt(s.sketch.default_prompt)
      setFaceGate(s.sketch.face_gate)
      setPolishModel(s.polish.model)
      setPolishRules(s.polish.extra_rules)
      setReportModel(s.reports.model)
      setReportRules(s.reports.rules)
      setNarrativeLabel(s.narrative.label)
      setSafeNote(s.safe_edition.illustrations_note)
      setTtsEnabled(s.tts.enabled)
      setBaseUrl(s.publishing.base_url)
      setHeadHtml(s.publishing.head_html || '')
      setFaviconId(s.publishing.favicon_asset_id)
      setOgImageId(s.publishing.og_image_asset_id)
      setFooterBlocks(s.footer.blocks)
      setTargets(s.targets || [])
    })
    api.masterStatus().then(setMaster, () => setMaster(null))
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

  const saveReport = () => {
    setReportState('saving')
    api.saveReportSettings({ model: reportModel, rules: reportRules }).then(
      () => setReportState('Saved'),
      (e) => setReportState(`Failed: ${e}`),
    )
  }

  const generateMaster = () => {
    setMasterState('Building & pushing…')
    api.generateMaster().then(
      (r) => {
        setMaster(r.master)
        setMasterState('Pushed to Drive')
      },
      (e) => setMasterState(`Failed: ${e}`),
    )
  }

  const saveNarrative = () => {
    setNarrativeState('saving')
    api.saveNarrativeSettings({ label: narrativeLabel }).then(
      () => setNarrativeState('Saved'),
      (e) => setNarrativeState(`Failed: ${e}`),
    )
  }

  const saveSafeNote = () => {
    setSafeNoteState('saving')
    api.saveSafeEditionSettings({ illustrations_note: safeNote }).then(
      (r) => { setSafeNote(r.safe_edition.illustrations_note); setSafeNoteState('Saved — push to Drive to apply') },
      (e) => setSafeNoteState(`Failed: ${e}`),
    )
  }

  const onToggleTts = (enabled: boolean) => {
    setTtsEnabled(enabled)
    setTtsState('saving')
    api.saveTtsSetting(enabled).then(
      () => setTtsState('Saved'),
      (e) => setTtsState(`Failed: ${e}`),
    )
  }

  const saveBaseUrl = () => {
    setBaseUrlState('saving')
    api.savePublishingSettings({ base_url: baseUrl }).then(
      (r) => { setBaseUrl(r.base_url); setBaseUrlState('Saved — run the URL migration, then re-publish') },
      (e) => setBaseUrlState(`Failed: ${e}`),
    )
  }

  const saveHeadHtml = () => {
    setHeadState('saving')
    api.savePublishingSettings({ head_html: headHtml }).then(
      (r) => { setHeadHtml(r.head_html); setHeadState('Saved — re-publish to apply') },
      (e) => setHeadState(`Failed: ${e}`),
    )
  }

  const uploadSiteImage = (kind: 'favicon' | 'og_image', file: File) => {
    setSiteImgState(`Uploading ${kind === 'favicon' ? 'favicon' : 'social image'}…`)
    api.uploadSiteImage(kind, file).then(
      ({ asset_id }) => {
        if (kind === 'favicon') setFaviconId(asset_id)
        else setOgImageId(asset_id)
        setSiteImgState('Uploaded — re-publish the homepage to apply')
      },
      (e) => setSiteImgState(`Failed: ${e}`),
    )
  }

  const removeSiteImage = (kind: 'favicon' | 'og_image') => {
    setSiteImgState('Removing…')
    api.removeSiteImage(kind).then(
      () => {
        if (kind === 'favicon') setFaviconId(null)
        else setOgImageId(null)
        setSiteImgState('Removed — re-publish the homepage to apply')
      },
      (e) => setSiteImgState(`Failed: ${e}`),
    )
  }

  const republish = (target: TargetInfo) => {
    const label = TARGET_LABEL[target.kind] ?? target.kind
    const ridesHomepage = target.kind !== 'drive'
    if (
      !window.confirm(
        `Re-publish every document currently live on ${label}${ridesHomepage ? ' (and the homepage)' : ''} ` +
          `to apply the latest content and settings (footer, head script, …)?\n\n` +
          `Documents that have never been published (drafts) are not affected.`,
      )
    )
      return
    setRepublishState((s) => ({ ...s, [target.name]: 'Re-publishing…' }))
    api.publishAll(target.name, true).then(
      (r) =>
        setRepublishState((s) => ({
          ...s,
          [target.name]: r.failed.length
            ? `Re-published ${r.published.length} · ${r.failed.length} failed: ${r.failed.map((f) => f.slug).join(', ')}`
            : `Re-published ${r.published.length} · all succeeded`,
        })),
      (e) => setRepublishState((s) => ({ ...s, [target.name]: `Failed: ${e}` })),
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
            <label htmlFor="sketch-model">
              Image model{' '}
              <InfoTip label="About the image model">
                The image model used to generate every figure's faceless sketch. Override the
                prompt per figure in the editor.
              </InfoTip>
            </label>
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
            <label htmlFor="sketch-prompt">
              Silhouette prompt{' '}
              <InfoTip label="About the silhouette prompt">
                The instruction sent to the image model for every sketch — edit it to change the
                silhouette style across all figures. Per-figure overrides live in the editor.
              </InfoTip>
            </label>
            <textarea
              id="sketch-prompt"
              rows={8}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>
          <div className="settings-row">
            <label htmlFor="face-gate">
              Face gate{' '}
              <InfoTip label="About the face gate">
                What happens when a generated sketch still shows a detectable face: “block”
                refuses it and retries; “warn” keeps it but flags it for your review before
                approval.
              </InfoTip>
            </label>
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
            <label htmlFor="polish-model">
              Text model{' '}
              <InfoTip label="About the text model">
                The model id used for the mechanical text-polish pass.
              </InfoTip>
            </label>
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
            <label htmlFor="polish-rules">
              Extra rules{' '}
              <InfoTip label="About polish extra rules">
                Extra guidance appended after the built-in polish scope rules. Leave blank to use
                the defaults only.
              </InfoTip>
            </label>
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

      {/* Tools — analytical reports & master tracks */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Tools</h2>
          <p>
            Analytical reports — a per-document navigational index pushed to Drive as a separate
            NotebookLM source — and the corpus-wide master reference tracks.
          </p>
        </div>
        <div className="settings-fields">
          <h3>Report configuration</h3>
          <div className="settings-row">
            <label htmlFor="report-model">
              Report model{' '}
              <InfoTip label="About the report model">
                The model id used to generate analytical reports (default gemini-3.5-flash).
                The chunked, single-source pass means one call per chapter.
              </InfoTip>
            </label>
            <div className="settings-control">
              <input
                id="report-model"
                value={reportModel}
                onChange={(e) => setReportModel(e.target.value)}
                placeholder="gemini-3.5-flash"
              />
            </div>
          </div>
          <div className="settings-row settings-row-tall">
            <label htmlFor="report-rules">
              Extra rules{' '}
              <InfoTip label="About report extra rules">
                Extra guidance appended after the built-in report fidelity rules. Leave blank to
                use the defaults only.
              </InfoTip>
            </label>
            <div className="settings-control">
              <textarea
                id="report-rules"
                rows={4}
                value={reportRules}
                onChange={(e) => setReportRules(e.target.value)}
                placeholder="Appended after the built-in fidelity rules. Leave blank to use defaults only."
              />
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={saveReport}>Save report settings</Button>
            {reportState && <span className="settings-state muted">{reportState}</span>}
          </div>

          <h3 style={{ marginTop: 24 }}>
            Master reference tracks{' '}
            <InfoTip label="About master reference tracks">
              Pools every document's report rows (people, geography, glossary, chronology) into
              four Google Sheets that NotebookLM ingests as syncing Data Tables. Generate a
              per-document report first; regenerate here after reports change. Each row keeps a
              source column so it stays traceable across documents.
            </InfoTip>
          </h3>
          <p className="settings-hint" style={{ marginBottom: 12 }}>
            Pools every document's report rows into four Google Sheets (people · geography ·
            glossary · chronology) and pushes them to Drive as NotebookLM Data Tables.
          </p>
          <div className="settings-save-row">
            <Button variant="primary" onClick={generateMaster}>
              {master?.built_at ? 'Regenerate master tracks' : 'Generate master tracks'}
            </Button>
            {masterState && <span className="settings-state muted">{masterState}</span>}
          </div>
          <p className="settings-hint" style={{ marginTop: 8 }}>
            {master && master.built_at
              ? `Last built ${new Date(master.built_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })} · ${master.documents} doc${master.documents === 1 ? '' : 's'} · ${master.rows} row${master.rows === 1 ? '' : 's'}`
              : master
                ? `Never built · ${master.documents} doc${master.documents === 1 ? '' : 's'} with reports · ${master.rows} row${master.rows === 1 ? '' : 's'} available`
                : 'Master status unavailable.'}
          </p>
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

      {/* NotebookLM-safe edition */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>NotebookLM-safe edition</h2>
          <p>
            A note inserted after the title block of every safe edition pushed to Drive, explaining
            why its figures are sketches rather than photographs. Only added to documents that
            actually contain figures.
          </p>
        </div>
        <div className="settings-fields">
          <div className="settings-row settings-row-tall">
            <label htmlFor="safe-note">
              Illustrations note{' '}
              <InfoTip label="About the illustrations note">
                Markdown. Appears between the title block and the body of the Google Doc, so a
                reader — and NotebookLM itself — can see that the sketches are substitutes rather
                than the original photographs. Documents with no figures never receive it. Leave
                blank for none. Applied on the next push to Drive.
              </InfoTip>
            </label>
            <div className="settings-control">
              <textarea
                id="safe-note"
                rows={10}
                value={safeNote}
                onChange={(e) => setSafeNote(e.target.value)}
                placeholder="Leave blank for no note"
              />
              <span className="settings-hint">
                Markdown supported. Re-push a document to Drive to apply.
              </span>
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={saveSafeNote}>Save note</Button>
            {safeNoteState && <span className="settings-state muted">{safeNoteState}</span>}
          </div>
        </div>
      </section>

      {/* Publishing — site base URL */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Publishing</h2>
          <p>
            The base URL of the published site. It drives canonical URLs, the
            homepage link, the sitemap and JSON-LD. After changing it, run the URL
            migration to rewrite existing documents' stored links, then re-publish.
          </p>
        </div>
        <div className="settings-fields">
          <div className="settings-row">
            <label htmlFor="base-url">
              Site base URL{' '}
              <InfoTip label="About the site base URL">
                e.g. <code>https://history.skitch.me</code>. Memoir pages live under
                <code>/rfs/&lt;slug&gt;.html</code> and the homepage at <code>/index.html</code>.
                Existing pages keep their stored URLs until you run{' '}
                <code>uv run python -m notebook_forge.cli site-url-migrate --apply</code>{' '}
                and re-publish.
              </InfoTip>
            </label>
            <div className="settings-control">
              <input
                id="base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://history.skitch.me"
              />
              <span className="settings-hint">No trailing slash. Must be an http(s) URL.</span>
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={saveBaseUrl}>Save base URL</Button>
            {baseUrlState && <span className="settings-state muted">{baseUrlState}</span>}
          </div>

          <div className="settings-row settings-row-tall" style={{ marginTop: 16 }}>
            <label htmlFor="head-html">
              Custom &lt;head&gt; script{' '}
              <InfoTip label="About the custom head script">
                Raw HTML injected into the <code>&lt;head&gt;</code> of every published page and the
                homepage — typically an analytics <code>&lt;script&gt;</code> tag. Saved verbatim
                and only applied on the next publish, so re-publish (or “Publish all pending”) after
                changing it. Leave blank for none.
              </InfoTip>
            </label>
            <div className="settings-control">
              <textarea
                id="head-html"
                rows={3}
                value={headHtml}
                onChange={(e) => setHeadHtml(e.target.value)}
                placeholder='<script defer src="https://analytics.example.com/script.js" data-website-id="…"></script>'
                style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
              />
              <span className="settings-hint">
                Inserted as-is into every page&apos;s &lt;head&gt;. Re-publish to apply.
              </span>
            </div>
          </div>
          <div className="settings-save-row">
            <Button variant="primary" onClick={saveHeadHtml}>Save head script</Button>
            {headState && <span className="settings-state muted">{headState}</span>}
          </div>

          <h3 style={{ marginTop: 24 }}>
            Site images{' '}
            <InfoTip label="About site images">
              The <strong>favicon</strong> is the small icon shown in browser tabs and bookmarks —
              it appears on every published page. Leave it unset to use the NotebookForge icon.
              The <strong>social share image</strong> is the
              OpenGraph/Twitter card image used when the homepage is shared on social media or in
              chat apps (ideally ~1200×630). Both are uploaded here and pushed to the site root on
              the next homepage publish, so re-publish the homepage (or “Publish all”) after
              changing them.
            </InfoTip>
          </h3>
          {([
            {
              kind: 'favicon', label: 'Favicon', id: faviconId, ref: faviconInput, square: true,
              // No custom favicon → the published site falls back to the NotebookForge icon.
              fallbackSrc: '/icon.png', fallbackLabel: 'NotebookForge icon (default)',
            },
            {
              kind: 'og_image', label: 'Social share image', id: ogImageId, ref: ogImageInput,
              square: false, fallbackSrc: '', fallbackLabel: 'None set',
            },
          ] as const).map(({ kind, label, id, ref, square, fallbackSrc, fallbackLabel }) => {
            const imgStyle = {
              height: 48,
              width: square ? 48 : 'auto',
              maxWidth: 96,
              objectFit: 'contain' as const,
              borderRadius: 4,
              border: '1px solid var(--color-border-tertiary)',
              background: 'var(--color-bg-secondary)',
            }
            return (
            <div key={kind} className="settings-row" style={{ marginTop: 12 }}>
              <label>{label}</label>
              <div className="settings-control">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {id ? (
                    <img src={`/api/assets/${id}`} alt={label} style={imgStyle} />
                  ) : fallbackSrc ? (
                    <>
                      <img src={fallbackSrc} alt={fallbackLabel} style={{ ...imgStyle, opacity: 0.85 }} />
                      <span className="settings-hint">{fallbackLabel}</span>
                    </>
                  ) : (
                    <span className="settings-hint">{fallbackLabel}</span>
                  )}
                  <input
                    ref={ref}
                    type="file"
                    accept={kind === 'favicon' ? 'image/png,image/x-icon,image/svg+xml,image/*' : 'image/*'}
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) uploadSiteImage(kind, f)
                      e.target.value = ''
                    }}
                  />
                  <Button onClick={() => ref.current?.click()}>{id ? 'Replace' : 'Upload'}</Button>
                  {id && (
                    <Button variant="secondary" onClick={() => removeSiteImage(kind)}>
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            </div>
            )
          })}
          {siteImgState && (
            <div className="settings-save-row">
              <span className="settings-state muted">{siteImgState}</span>
            </div>
          )}

          <h3 style={{ marginTop: 24 }}>
            Re-publish{' '}
            <InfoTip label="About re-publishing">
              Re-pushes every document already live on a target — applying the latest content and
              any workspace-wide change such as the footer or the custom &lt;head&gt; script — even
              when a document has no pending edits of its own. Documents that have never been
              published (drafts) are NOT affected; publish those individually first. The homepage is
              included for the HTML and Local targets.
            </InfoTip>
          </h3>
          <p className="settings-hint" style={{ marginBottom: 12 }}>
            Re-publishes the documents already live on a target so workspace-wide changes (footer,
            head script, base URL) take effect. Unpublished drafts are never re-published.
          </p>
          <div className="settings-republish-row">
            {[...targets]
              .sort((a, b) => TARGET_ORDER.indexOf(a.kind) - TARGET_ORDER.indexOf(b.kind))
              .map((t) => (
                <div key={t.name} className="settings-republish-item">
                  <Button variant="secondary" onClick={() => republish(t)}>
                    Re-publish {TARGET_LABEL[t.kind] ?? t.kind}
                  </Button>
                  {republishState[t.name] && (
                    <span className="settings-state muted">{republishState[t.name]}</span>
                  )}
                </div>
              ))}
          </div>
        </div>
      </section>

      {/* Audio narration (TTS) */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Audio narration</h2>
          <p>
            Master switch for text-to-speech narration. When on, every document
            gains a Narration panel for exporting a manifest and pasting the audio URL,
            and any document with a published audio URL renders a listen-along
            player on its page. NotebookForge produces no audio itself — the
            forge-narrator tool on the Mac does (ElevenLabs), from the exported manifest.
          </p>
        </div>
        <div className="settings-fields">
          <div className="settings-row">
            <label htmlFor="tts-enabled">
              Enable narration{' '}
              <InfoTip label="About audio narration">
                Turns on the whole TTS feature. Export a manifest from a document's Narration
                panel, generate the audio with the forge-narrator tool on the Mac (ElevenLabs),
                upload the three files to S3, and paste the base URL back into the panel. The
                published page then shows a synced listen-along player.
              </InfoTip>
            </label>
            <div className="settings-control">
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  id="tts-enabled"
                  type="checkbox"
                  checked={ttsEnabled}
                  onChange={(e) => onToggleTts(e.target.checked)}
                />
                <span>{ttsEnabled ? 'On' : 'Off'}</span>
                {ttsState && <span className="settings-state muted">{ttsState}</span>}
              </label>
            </div>
          </div>
        </div>
      </section>

      {/* Footer & licence */}
      <section className="settings-section">
        <div className="settings-section-head">
          <h2>Footer &amp; licence</h2>
          <p>
            The footer printed at the foot of every published HTML page, the homepage, and every
            Google Doc. Edit it as a block document — paragraphs, headings, lists and links — for
            full control over the copyright and licence text.
          </p>
        </div>
        <div className="settings-fields">
          {footerBlocks === null ? (
            <p className="settings-hint">Loading…</p>
          ) : (
            <FooterEditor initialBlocks={footerBlocks} />
          )}
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
