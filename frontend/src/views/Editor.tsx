import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Button, InfoTip, SectionLabel, SerifTitle } from '../ui'
import { BlockNoteView } from '@blocknote/mantine'
import {
  SuggestionMenuController,
  SideMenuController,
  SideMenu,
  DragHandleMenu,
  RemoveBlockItem,
  useComponentsContext,
  useCreateBlockNote,
  useSelectedBlocks,
} from '@blocknote/react'
import { insertOrUpdateBlockForSlashMenu } from '@blocknote/core'
import type { PartialBlock } from '@blocknote/core'
import '@blocknote/core/fonts/inter.css'
import '@blocknote/mantine/style.css'
import { useMemo } from 'react'
import { api, type DocDetail, type PolishLastRun, type PolishReport, type ReportState, type TargetState } from '../api'
import { StatusBadge, type BadgeVariant } from '../ui'
import { forgeSchema, docGroupSlashItem, dedicationSlashItem, narrativeSlashItem, footnoteSlashItem, filterSuggestionItems, getDefaultReactSlashMenuItems } from '../forge/schema'
import { stripItalic, addItalic } from '../forge/narrative'
import { imageSketchUpdates } from '../forge/sketchSync'
// forgeSchema used for PartialBlock type cast in updateBlock calls
import { OutlineNavigator } from '../forge/OutlineNavigator'
import { buildOutline, headingIds, type BlockLike } from '../forge/outline'
import { timeAgo } from './Library'
import { PolishProgress } from './PolishProgress'
import { PolishReview } from './PolishReview'

const AUTOSAVE_MS = 1200

/** Contains a render crash inside the editor canvas (e.g. a misbehaving
 * BlockNote menu) so it shows a recoverable message instead of blanking the
 * whole app. The surrounding page — outline, panels, save — keeps working. */
export class EditorErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Editor render error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="editor-error" role="alert">
          <p>Something in the editor hit a snag and this view was paused.</p>
          <p className="muted" style={{ fontSize: 12 }}>{String(this.state.error.message)}</p>
          <Button variant="secondary" onClick={() => this.setState({ error: null })}>
            Dismiss
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}

// ---- Polish badge state machine ----
export type PolishBadgeState = 'never-run' | 'polished' | 'stale' | 'flagged' | 'loading'

export function computePolishBadge(
  polishLast: PolishLastRun | null | 'loading',
  updatedAt: string | null,
): PolishBadgeState {
  if (polishLast === 'loading') return 'loading'
  if (polishLast === null) return 'never-run'
  if (polishLast.flagged_ids.length > 0) return 'flagged'
  if (updatedAt && polishLast.at <= updatedAt) return 'stale'
  return 'polished'
}

// ---- Report badge state machine ----
export function computeReportBadge(
  report: ReportState | null | 'loading',
): { variant: BadgeVariant; label: string } | 'loading' {
  if (report === 'loading') return 'loading'
  if (!report || !report.exists) return { variant: 'never-run', label: 'Not generated' }
  if (report.status === 'failed') return { variant: 'flagged', label: 'Failed' }
  if (report.stale) return { variant: 'stale', label: 'Stale' }
  return { variant: 'polished', label: 'Generated' }
}

const DRIVE_DOC_URL = (id: string) => `https://docs.google.com/document/d/${id}/edit`

function ReportPanel({ slug }: { slug: string }) {
  const [report, setReport] = useState<ReportState | null | 'loading'>('loading')
  const [generating, setGenerating] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setReport('loading')
    api.report(slug).then((r) => setReport(r), () => setReport(null))
  }, [slug])

  const onGenerate = useCallback(() => {
    setError('')
    setGenerating(true)
    api.generateReport(slug).then(
      (r) => setReport(r.report),
      (e) => setError(String(e)),
    ).finally(() => setGenerating(false))
  }, [slug])

  const onPush = useCallback(() => {
    setError('')
    setPushing(true)
    api.pushReport(slug).then(
      (r) => setReport(r.report),
      (e) => setError(String(e)),
    ).finally(() => setPushing(false))
  }, [slug])

  const exists = report !== 'loading' && report !== null && report.exists
  const needsPush = exists && (report as ReportState).needs_push
  const badge = computeReportBadge(report)
  const driveId = exists ? (report as ReportState).drive_file_id : null

  return (
    <>
      {generating && (
        <PolishProgress
          slug={slug}
          poll={api.reportProgress}
          heading="Generating report with Gemini…"
          prepLabel="Reading provenance and chunking chapters…"
          unit="chapter"
        />
      )}
      <div className="pending-panel">
        <div className="pending-panel-header">
          <h3><SectionLabel>Analytical report</SectionLabel></h3>
          <InfoTip label="About the analytical report" align="right">
            A derived navigational index of this document — executive summary, section-by-section
            digest, and people / places / glossary / chronology — built by a single-source LLM
            pass and pushed to Drive as a separate NotebookLM source (a Google Doc). It's a
            summary, not a primary record. “Stale” means the document changed since it was
            generated — regenerate to refresh. Push to Drive is enabled only when there are
            changes to push.
          </InfoTip>
        </div>
        <div className="target-rows">
          <div className="target-card">
            <div className="target-card-head">
              <span className={`dot ${exists && !(report as ReportState).stale ? 'clean' : 'dirty'}`} />
              <span className="pending-name" title="report → Drive">Report</span>
              {driveId && (
                <a
                  className="target-link-icon"
                  href={DRIVE_DOC_URL(driveId)}
                  target="_blank"
                  rel="noreferrer"
                  title="Open the report in Google Drive"
                >
                  <i className="ti ti-external-link" aria-hidden />
                </a>
              )}
              <Button
                variant="secondary"
                size="sm"
                disabled={generating}
                onClick={onGenerate}
              >
                {generating ? 'Generating…' : exists ? 'Regenerate' : 'Generate'}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!needsPush || generating || pushing}
                title={
                  needsPush
                    ? 'Push report_<source_name> to Drive'
                    : 'Already pushed — regenerate to push again'
                }
                onClick={onPush}
              >
                {pushing ? 'Pushing…' : 'Push to Drive'}
              </Button>
            </div>
            <div className="target-card-status">
              {badge !== 'loading' && <StatusBadge variant={badge.variant} label={badge.label} />}
              {error && <span className="pending-state" style={{ color: 'var(--color-danger, #b00)' }}>{error}</span>}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

function PolishPopover({
  run,
  onClose,
  onRestore,
  onReviewFlagged,
}: {
  run: PolishLastRun
  onClose: () => void
  onRestore: () => void
  onReviewFlagged: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const fn = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', fn)
    return () => document.removeEventListener('mousedown', fn)
  }, [onClose])

  const at = new Date(run.at)
  const timeStr = at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

  return (
    <div
      ref={ref}
      style={{
        position: 'absolute',
        zIndex: 100,
        background: 'var(--color-background-primary)',
        border: '0.5px solid var(--color-border-tertiary)',
        borderRadius: 'var(--border-radius-lg)',
        padding: '14px 16px',
        minWidth: 280,
        boxShadow: '0 4px 16px rgba(0,0,0,.12)',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        top: '100%',
        left: 0,
        marginTop: 4,
      }}
    >
      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
        {timeStr} · <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{run.model}</span>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <div style={{
          flex: 1, textAlign: 'center', padding: '8px 10px',
          background: 'var(--color-background-secondary)', borderRadius: 'var(--border-radius-md)',
        }}>
          <div style={{ fontSize: 18, fontWeight: 500 }}>{run.blocks_changed}</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>Cleaned</div>
        </div>
        <div style={{
          flex: 1, textAlign: 'center', padding: '8px 10px',
          background: 'var(--color-background-secondary)', borderRadius: 'var(--border-radius-md)',
        }}>
          <div style={{ fontSize: 18, fontWeight: 500 }}>{run.blocks_unchanged}</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>Unchanged</div>
        </div>
      </div>
      {run.flagged_ids.length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
          <span style={{ color: 'var(--color-tan)' }}>{run.flagged_ids.length} flagged</span>
          {' '}
          <button
            type="button"
            style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                     fontSize: 12, color: 'var(--color-text-info)', textDecoration: 'underline' }}
            onClick={() => { onReviewFlagged(); onClose() }}
          >
            Review flagged
          </button>
        </div>
      )}
      <button
        type="button"
        style={{
          background: 'none', border: '0.5px solid var(--color-border-tertiary)',
          borderRadius: 'var(--border-radius-md)', cursor: 'pointer',
          fontSize: 12, padding: '4px 10px', color: 'var(--color-text-secondary)',
        }}
        onClick={() => { onRestore(); onClose() }}
      >
        Restore pre-polish snapshot
      </button>
    </div>
  )
}

interface ChangeRow {
  id: number
  kind: string
  summary: string
  created_at: string | null
}

function changeIcon(c: ChangeRow): string {
  if (c.summary.includes('sketch')) return 'ti-photo'
  if (c.summary.includes('caption')) return 'ti-text-caption'
  if (c.kind === 'publish') return 'ti-upload'
  if (c.kind === 'rollback') return 'ti-arrow-back-up'
  if (c.kind === 'import') return 'ti-file-import'
  return 'ti-edit'
}

function ChangesModal({
  changes,
  onClose,
}: {
  changes: ChangeRow[]
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box changes-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Change history</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <i className="ti ti-x" aria-hidden />
          </button>
        </div>
        <div className="changes-modal-list">
          {changes.length === 0 ? (
            <p className="muted">No changes recorded.</p>
          ) : (
            changes.map((c) => (
              <div key={c.id} className="changes-modal-row">
                <i className={`ti ${changeIcon(c)}`} aria-hidden />
                <span className="changes-modal-summary">{c.summary}</span>
                <span className="change-when">{timeAgo(c.created_at)}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

type ImageBlock = { id: string; type: string; props: Record<string, unknown>; children: unknown[] }

function figureBlocks(doc: unknown[]): ImageBlock[] {
  return (doc as ImageBlock[]).filter((b) => b.type === 'forgeImage')
}

function ImagesPanel({
  slug,
  editorDoc,
  onApproveAll,
  onGenerateCaptions,
  onSketchesGenerated,
  generatingCaptions,
}: {
  slug: string
  editorDoc: () => unknown[]
  onApproveAll: () => void
  onGenerateCaptions: () => Promise<void>
  /** Called when a batch sketch job finishes, so the editor can pull the
   * newly-generated sketches into its in-memory blocks (otherwise they only
   * appear after a manual reload). */
  onSketchesGenerated: () => void
  generatingCaptions: boolean
}) {
  const [stepIndex, setStepIndex] = useState(0)
  const [batchFaceGate, setBatchFaceGate] = useState<'warn' | 'block'>('warn')
  const [jobStatus, setJobStatus] = useState<{
    status: 'running' | 'done' | 'failed'
    done: number
    total: number
    failed: number
    results: { block_id: string; ok: boolean; face_gate: string; error?: string }[]
  } | null>(null)
  const [flaggedStep, setFlaggedStep] = useState(0)
  const [showFlaggedStepper, setShowFlaggedStepper] = useState(false)
  const pollTimer = useRef<ReturnType<typeof setInterval>>(null)

  const figs = figureBlocks(editorDoc())
  const total = figs.length
  const sketched = figs.filter((b) => b.props.sketchAssetId).length
  const pendingCount = figs.filter((b) => b.props.approval === 'pending' && b.props.sketchAssetId).length
  const missingCaption = figs.filter((b) => !b.props.caption).length
  // Mirrors backend eligible_figure_block_ids: needs an original photo, still
  // wants a sketch in the safe edition (Safe: original / omit are skipped), and
  // isn't already an approved sketch.
  const eligible = figs.filter(
    (b) =>
      b.props.assetId &&
      (b.props.safeMode ?? 'sketch') === 'sketch' &&
      !(b.props.sketchAssetId && b.props.approval === 'approved'),
  ).length

  const scrollToFigure = (idx: number, ids?: string[]) => {
    const list = ids ?? figs.map((b) => b.id)
    const id = list[idx]
    if (!id) return
    const el = document.getElementById(`figure-${id}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('nf-flash')
    setTimeout(() => el.classList.remove('nf-flash'), 900)
  }

  const startPoll = (id: string) => {
    if (pollTimer.current) clearInterval(pollTimer.current)
    pollTimer.current = setInterval(async () => {
      try {
        const s = await api.sketchJobStatus(slug, id)
        setJobStatus(s)
        if (s.status !== 'running') {
          clearInterval(pollTimer.current!)
          pollTimer.current = null
          // The job persisted sketches server-side; pull them into the editor
          // so they show without a manual reload.
          onSketchesGenerated()
        }
      } catch {
        // ignore transient poll errors
      }
    }, 800)
  }

  useEffect(() => () => { if (pollTimer.current) clearInterval(pollTimer.current) }, [])

  const startGenerate = async () => {
    setJobStatus(null)
    setShowFlaggedStepper(false)
    try {
      const resp = await api.generateAllSketches(slug, batchFaceGate)
      setJobStatus({ status: 'running', done: 0, total: resp.eligible, failed: 0, results: [] })
      startPoll(resp.job_id)
    } catch (e) {
      alert(`Failed to start batch: ${e}`)
    }
  }

  if (total === 0) return null

  // Derive flagged figures from persisted block props — survives refresh.
  const flaggedIds = figs
    .filter((b) => b.props.faceGate === 'flagged' && b.props.approval !== 'approved')
    .map((b) => b.id)
  const running = jobStatus?.status === 'running'
  const done = jobStatus?.status === 'done'

  return (
    <div className="pending-panel images-panel">
      <div className="pending-panel-header">
        <h3><SectionLabel>Images</SectionLabel></h3>
        <InfoTip label="About the image tools" align="right">
          Per-figure tools for the NotebookLM-safe edition. “Generate all sketches” makes a
          faceless silhouette for every eligible figure (has an original photo, Safe mode is
          “sketch”, and isn't already approved). The face gate decides what to do if a face is
          still detected — “block” retries, “warn” flags it. “Caption” auto-writes captions for
          figures missing one. “Approve all” marks sketches final so future batch runs skip them.
        </InfoTip>
      </div>

      <div className="images-summary">
        <span>{total} figure{total !== 1 ? 's' : ''}</span>
        <span className="sep">·</span>
        <span>{sketched} sketched</span>
        {pendingCount > 0 && (
          <>
            <span className="sep">·</span>
            <span className="pending-badge">{pendingCount} pending review</span>
          </>
        )}
      </div>

      {total > 0 && (
        <div className="images-stepper">
          <button
            type="button"
            className="stepper-prev"
            aria-label="Previous figure"
            onClick={() => {
              const next = (stepIndex - 1 + total) % total
              setStepIndex(next)
              scrollToFigure(next)
            }}
          >
            ‹
          </button>
          <span className="stepper-label">Figure {stepIndex + 1} of {total}</span>
          <button
            type="button"
            className="stepper-next"
            aria-label="Next figure"
            onClick={() => {
              const next = (stepIndex + 1) % total
              setStepIndex(next)
              scrollToFigure(next)
            }}
          >
            ›
          </button>
        </div>
      )}

      {running ? (
        <div className="images-job-card">
          <span className="images-job-label">
            Generating sketches… ({jobStatus!.done} / {jobStatus!.total})
          </span>
          <div className="images-job-bar">
            <div
              className="images-job-fill"
              style={{ width: `${jobStatus!.total > 0 ? Math.round((jobStatus!.done / jobStatus!.total) * 100) : 0}%` }}
            />
          </div>
        </div>
      ) : (
        <>
          <div className="images-generate-row">
            <Button
              variant="secondary"
              size="sm"
              disabled={eligible === 0}
              onClick={() => void startGenerate()}
            >
              ✏ Generate all sketches
            </Button>
            <span className="eligible-badge">{eligible} eligible</span>
          </div>

          {eligible > 0 && (
            <div className="images-gate-row">
              <label>
                <input
                  type="radio"
                  name={`batchFaceGate-${slug}`}
                  value="warn"
                  checked={batchFaceGate === 'warn'}
                  onChange={() => setBatchFaceGate('warn')}
                />
                {' '}warn
              </label>
              <label>
                <input
                  type="radio"
                  name={`batchFaceGate-${slug}`}
                  value="block"
                  checked={batchFaceGate === 'block'}
                  onChange={() => setBatchFaceGate('block')}
                />
                {' '}block
              </label>
              <span className="images-gate-label">face gate</span>
            </div>
          )}

          {done && (
            <div className="images-result">
              Generated {(jobStatus?.results ?? []).filter((r) => r.ok).length} sketches
              {jobStatus!.failed > 0 && (
                <span className="images-gen-error"> ({jobStatus!.failed} failed)</span>
              )}
            </div>
          )}

          {flaggedIds.length > 0 && (
            <div className="images-result">
              <span className="images-face-flag-summary">
                ⚠ {flaggedIds.length} face flag{flaggedIds.length !== 1 ? 's' : ''} — review before approving
              </span>
              {' '}
              <button
                type="button"
                className="images-review-link"
                onClick={() => { setShowFlaggedStepper((s) => !s); setFlaggedStep(0) }}
              >
                {showFlaggedStepper ? 'hide' : 'step through ›'}
              </button>
            </div>
          )}

          {showFlaggedStepper && flaggedIds.length > 0 && (
            <div className="images-stepper images-flagged-stepper">
              <button
                type="button"
                className="stepper-prev"
                aria-label="Previous flagged figure"
                onClick={() => {
                  const next = (flaggedStep - 1 + flaggedIds.length) % flaggedIds.length
                  setFlaggedStep(next)
                  scrollToFigure(next, flaggedIds)
                }}
              >
                ‹
              </button>
              <span className="stepper-label">
                Flagged {flaggedStep + 1} of {flaggedIds.length}
              </span>
              <button
                type="button"
                className="stepper-next"
                aria-label="Next flagged figure"
                onClick={() => {
                  const next = (flaggedStep + 1) % flaggedIds.length
                  setFlaggedStep(next)
                  scrollToFigure(next, flaggedIds)
                }}
              >
                ›
              </button>
            </div>
          )}
        </>
      )}

      <div className="images-actions-row">
        <Button
          variant="secondary"
          size="sm"
          disabled={missingCaption === 0 || generatingCaptions}
          title="Generate AI captions for images without one"
          onClick={() => void onGenerateCaptions()}
        >
          {generatingCaptions ? '✨ Captioning…' : missingCaption > 0 ? `✨ Caption (${missingCaption})` : '✨ Caption images'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={pendingCount === 0}
          title="Mark all pending images as approved"
          onClick={onApproveAll}
        >
          {pendingCount > 0 ? `🖼️ Approve all (${pendingCount})` : '🖼️ Approve all'}
        </Button>
      </div>

      <p className="images-helper">Approved sketches are skipped.</p>
    </div>
  )
}

function PendingPanel({
  slug,
  targets,
  onPush,
  onUnpublish,
  pushing,
  unpublishing,
  hideUnpublish,
}: {
  slug: string
  targets: TargetState[]
  onPush: (target: string) => void
  onUnpublish: (target: string) => void
  pushing: string | null
  unpublishing: string | null
  hideUnpublish?: boolean
}) {
  const [changes, setChanges] = useState<ChangeRow[]>([])
  const [showHistory, setShowHistory] = useState(false)

  useEffect(() => {
    api.changes(slug).then(
      (rows) => setChanges(rows as ChangeRow[]),
      () => setChanges([]),
    )
  }, [slug, targets])

  const targetLabel = (id: string) =>
    ({ 'github-pages': 'HTML', 'local-folder': 'Local', drive: 'Drive' }[id] ?? id)

  const behindCount = (t: TargetState): number =>
    changes.filter(
      (c) =>
        c.kind !== 'publish' &&
        c.created_at &&
        (!t.published_at || c.created_at > t.published_at),
    ).length

  const edits = changes.filter((c) => c.kind !== 'publish')
  const recentEdits = edits.slice(0, 3)
  const anyDirty = targets.some((t) => t.dirty)

  return (
    <>
      {showHistory && <ChangesModal changes={changes} onClose={() => setShowHistory(false)} />}
      <div className="pending-panel">
        <div className="pending-panel-header">
          <h3><SectionLabel>Pending changes</SectionLabel></h3>
          <InfoTip label="About publishing" align="right">
            Where this document publishes. HTML = the public GitHub Pages site (which also hosts
            the original photos); Drive = the NotebookLM-safe Google Doc (faceless sketches);
            Local = an offline static mirror. A filled dot and “N changes behind” mean there are
            edits since that target was last pushed. Unpublish removes the document from a target
            without deleting it.
          </InfoTip>
          {edits.length > 0 && (
            <button type="button" className="changes-history-btn" onClick={() => setShowHistory(true)}>
              History
            </button>
          )}
        </div>
        {anyDirty && recentEdits.length > 0 && (
          <div className="change-list">
            {recentEdits.map((c) => (
              <div key={c.id} className="change-row">
                <i className={`ti ${changeIcon(c)}`} aria-hidden />
                <span className="change-summary" title={c.summary}>{c.summary}</span>
                <span className="change-when">{timeAgo(c.created_at)}</span>
              </div>
            ))}
          </div>
        )}
        <div className="target-rows">
          {targets.map((t) => {
            const behind = behindCount(t)
            const statusLine = t.status !== 'PUBLISHED'
              ? <span className="pending-state">Never published</span>
              : <>
                  <span className="pending-state">
                    Published{t.published_at ? ` · ${timeAgo(t.published_at)}` : ''}
                  </span>
                  {t.dirty && behind > 0 && (
                    <span className="pending-behind">{behind} change{behind === 1 ? '' : 's'} behind</span>
                  )}
                </>
            return (
              <div key={t.target} className="target-card">
                <div className="target-card-head">
                  <span className={`dot ${t.dirty ? 'dirty' : 'clean'}`} />
                  <span className="pending-name" title={t.target}>{targetLabel(t.target)}</span>
                  {t.url && (
                    <a
                      className="target-link-icon"
                      href={t.url}
                      target="_blank"
                      rel="noreferrer"
                      title={`Open the published ${t.kind} output`}
                    >
                      <i className="ti ti-external-link" aria-hidden />
                    </a>
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={!t.dirty || pushing === t.target}
                    onClick={() => onPush(t.target)}
                  >
                    {pushing === t.target ? 'Pushing…' : 'Push'}
                  </Button>
                  {t.status === 'PUBLISHED' && !hideUnpublish && (
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={!!pushing || unpublishing === t.target}
                      title={`Remove this document from ${t.target}`}
                      onClick={() => onUnpublish(t.target)}
                    >
                      {unpublishing === t.target ? 'Removing…' : 'Unpublish'}
                    </Button>
                  )}
                </div>
                <div className="target-card-status">
                  {statusLine}
                </div>
              </div>
            )
          })}
        </div>
      {targets.filter((t) => t.dirty).length > 1 && (
        <Button
          variant="primary"
          className="push-all"
          disabled={!!pushing}
          onClick={() => onPush('__all__')}
          style={{ width: '100%', marginTop: 4, justifyContent: 'center' }}
        >
          {pushing === '__all__' ? 'Pushing all…' : 'Push to all targets'}
        </Button>
      )}
      </div>
    </>
  )
}

function MetaBar({
  doc,
  onSaved,
  editorDoc,
  onPolish,
  polishing,
  polishBadge,
}: {
  doc: DocDetail
  onSaved: (targets: TargetState[]) => void
  editorDoc: () => unknown[]
  onPolish: () => void
  polishing: boolean
  polishBadge?: React.ReactNode
}) {
  const meta = doc.meta as Record<string, string | boolean>
  const [title, setTitle] = useState(String(meta.title ?? ''))
  const [author, setAuthor] = useState(String(meta.author ?? ''))
  const [years, setYears] = useState(String(meta.year_display ?? ''))
  const [standfirst, setStandfirst] = useState(String(meta.standfirst ?? ''))
  const tocInitial =
    meta.show_toc === undefined || meta.show_toc === null ? 'auto' : meta.show_toc ? 'on' : 'off'
  const [toc, setToc] = useState(tocInitial)
  const hasNarrativeBlocks = doc.blocks.some(
    (b) => (b as { type: string }).type === 'forgeNarrative',
  )
  const narrativeLabelInitial = 'narrative_label' in meta
  const narrativeLabelValueInitial = String(meta.narrative_label ?? '')
  const [narrativeOverride, setNarrativeOverride] = useState(narrativeLabelInitial)
  const [narrativeLabelValue, setNarrativeLabelValue] = useState(narrativeLabelValueInitial)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const needsConfirm = meta.date_confirmed === false

  const [slug, setSlug] = useState(doc.slug)
  const [slugState, setSlugState] = useState<'idle' | 'saving' | 'error'>('idle')
  const [slugError, setSlugError] = useState('')
  const slugDirty = slug !== doc.slug

  const saveSlug = () => {
    const trimmed = slug.trim()
    if (!trimmed || trimmed === doc.slug) return
    if (!/^[a-z0-9][a-z0-9\-_]*$/.test(trimmed)) {
      setSlugError('Lowercase letters, digits, hyphens and underscores only')
      return
    }
    setSlugError('')
    setSlugState('saving')
    api.renameSlug(doc.slug, trimmed).then(
      (r) => {
        window.location.hash = `#/doc/${encodeURIComponent(r.slug)}`
      },
      (e: Error) => {
        setSlugState('error')
        setSlugError(e.message.includes('409') ? 'Slug already in use' : e.message)
      },
    )
  }

  const dirty =
    title !== String(meta.title ?? '') ||
    author !== String(meta.author ?? '') ||
    years !== String(meta.year_display ?? '') ||
    standfirst !== String(meta.standfirst ?? '') ||
    toc !== tocInitial ||
    narrativeOverride !== narrativeLabelInitial ||
    (narrativeOverride && narrativeLabelValue !== narrativeLabelValueInitial)

  const save = () => {
    setState('saving')
    const updated: Record<string, unknown> = {
      ...doc.meta,
      title,
      author,
      year_display: years,
      standfirst,
      meta_description: standfirst,
      date_confirmed: true,
    }
    if (toc === 'auto') delete updated.show_toc
    else updated.show_toc = toc === 'on'
    if (narrativeOverride) updated.narrative_label = narrativeLabelValue
    else delete updated.narrative_label
    api.saveMeta(doc.slug, editorDoc(), updated as Record<string, unknown>, 'edited document metadata').then(
      (resp) => {
        doc.meta = updated as DocDetail['meta']
        setState('saved')
        onSaved(resp.targets)
      },
      () => setState('error'),
    )
  }

  return (
    <div className={`meta-bar ${needsConfirm ? 'needs-confirm' : ''}`}>
      <label>
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Author
        <input value={author} onChange={(e) => setAuthor(e.target.value)} />
      </label>
      <label>
        Years
        <input value={years} onChange={(e) => setYears(e.target.value)} className="meta-years" />
      </label>
      <label className="meta-toc">
        <span className="meta-field-label">
          ToC
          <InfoTip label="About the table of contents">
            Table of contents on the published HTML page. Auto shows it only when the document has
            15+ headings; On/Off force it. Rebuilt from your current headings on every publish.
          </InfoTip>
        </span>
        <select value={toc} onChange={(e) => setToc(e.target.value)}>
          <option value="auto">Auto</option>
          <option value="on">On</option>
          <option value="off">Off</option>
        </select>
      </label>
      <div className="meta-second-row">
        {hasNarrativeBlocks && (
          <label className="meta-narrative">
            <span className="meta-field-label">
              Narrative label
              <InfoTip label="About the narrative label">
                Narrative panels can show a small-caps label (e.g. “From the author”). Tick to
                override the workspace default for this document only; unticked inherits the
                Settings value.
              </InfoTip>
            </span>
            <span className="meta-narrative-row">
              <input
                type="checkbox"
                checked={narrativeOverride}
                onChange={(e) => setNarrativeOverride(e.target.checked)}
              />
              <input
                value={narrativeLabelValue}
                disabled={!narrativeOverride}
                onChange={(e) => setNarrativeLabelValue(e.target.value)}
                placeholder="e.g. From the author"
              />
            </span>
          </label>
        )}
        <label className="meta-standfirst">
          <span className="meta-field-label">
            Standfirst
            <InfoTip label="About the standfirst">
              A one-line summary shown under the title on the published page and in the library
              listings. Optional.
            </InfoTip>
          </span>
          <input value={standfirst} onChange={(e) => setStandfirst(e.target.value)} />
        </label>
      </div>
      <label className="meta-slug">
        <span className="meta-field-label">
          Slug
          <InfoTip label="About the slug">
            The document's identifier — used in its public URL and as its NotebookLM/Drive source
            name. “Update” regenerates it from the title and years. Changing it breaks the old URL
            until you republish.
          </InfoTip>
        </span>
        <span className="meta-slug-row">
          <input
            value={slug}
            onChange={(e) => { setSlug(e.target.value); setSlugError('') }}
            onKeyDown={(e) => e.key === 'Enter' && saveSlug()}
            className="meta-slug-input"
          />
          <button
            type="button"
            title="Regenerate slug from current title and years"
            onClick={() => {
              const toSlug = (s: string) =>
                s.toLowerCase()
                  .replace(/[–—]/g, '-')
                  .replace(/[^a-z0-9\s-]/g, '')
                  .trim()
                  .replace(/\s+/g, '-')
                  .replace(/-+/g, '-')
                  .replace(/^-|-$/g, '')
              const yearPart = toSlug(years)
              const titlePart = toSlug(title)
              const suggested = yearPart ? `${yearPart}_${titlePart}` : titlePart
              setSlug(suggested)
              setSlugError('')
            }}
          >
            Update
          </button>
          <button
            type="button"
            disabled={!slugDirty || slugState === 'saving'}
            onClick={saveSlug}
          >
            {slugState === 'saving' ? 'Renaming…' : '💾 Slug'}
          </button>
        </span>
        {slugError && <span className="error meta-slug-error">{slugError}</span>}
      </label>
      <Button variant="primary" disabled={(!dirty && !needsConfirm) || state === 'saving'} onClick={save}>
        {state === 'saving' ? 'Saving…' : 'Save'}
      </Button>
      {Boolean(meta.source_asset_id) && (
        <button
          type="button"
          disabled={state === 'saving'}
          onClick={() => {
            if (
              !confirm(
                'Re-ingest from the source file?\n\nThe document TEXT is rebuilt from the ' +
                  'archived PDF/DOCX (prose edits are replaced). Figure work — sketches, ' +
                  'approvals, caption edits — carries over. A snapshot is taken first, so ' +
                  'Restore undoes this.',
              )
            )
              return
            setState('saving')
            api.reingest(doc.slug).then(
              (r) => {
                alert(
                  `Re-ingested: ${r.detail.blocks} blocks, ${r.detail.figures} figures ` +
                    `(${r.detail.figures_matched} kept their sketches/edits, ${r.detail.figures_new} new).`,
                )
                window.location.reload()
              },
              (e) => {
                setState('error')
                alert(`Re-ingest failed: ${e}`)
              },
            )
          }}
        >
          ⟳ Re-ingest from source
        </button>
      )}
      {Boolean(meta.source_asset_id) && (
        <InfoTip label="About re-ingest">
          Re-extracts the prose from the original imported PDF/DOCX (e.g. after correcting the
          source). The text is rebuilt, but your figure work — sketches, approvals, caption
          edits — carries over. A snapshot is taken first, so Restore undoes it.
        </InfoTip>
      )}
      <button
        type="button"
        disabled={polishing || state === 'saving'}
        onClick={onPolish}
      >
        {polishing ? '✨ Polishing…' : '✨ Polish text'}
      </button>
      <InfoTip label="About text polish">
        A mechanical clean-up pass — typography, whitespace, obvious typos. Safe fixes apply
        automatically; every word-level change is held for your review with a diff. It never
        rewrites prose, and a snapshot is taken first.
      </InfoTip>
      {polishBadge}
      {needsConfirm && (
        <span className="confirm-hint">
          Detected from the source — please confirm title and years before publishing.
        </span>
      )}
      {state === 'error' && <span className="error">save failed</span>}
    </div>
  )
}

type Snap = { id: number; note: string; created_at: string | null }

function SnapshotRow({
  s,
  restoring,
  onRestore,
}: {
  s: Snap
  restoring: number | null
  onRestore: (id: number) => void
}) {
  return (
    <div className="pending-row">
      <span className="pending-name" style={{ fontVariantNumeric: 'tabular-nums' }}>#{s.id}</span>
      <span className="pending-state">
        {s.note || 'snapshot'}
        {s.created_at ? ` · ${timeAgo(s.created_at)}` : ''}
      </span>
      <Button variant="secondary" size="sm" disabled={restoring === s.id} onClick={() => onRestore(s.id)}>
        {restoring === s.id ? 'Restoring…' : 'Restore'}
      </Button>
    </div>
  )
}

function SnapshotsModal({
  snaps,
  restoring,
  onRestore,
  onClose,
}: {
  snaps: Snap[]
  restoring: number | null
  onRestore: (id: number) => void
  onClose: () => void
}) {
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', fn)
    return () => document.removeEventListener('keydown', fn)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>All snapshots</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <i className="ti ti-x" aria-hidden />
          </button>
        </div>
        <div className="changes-modal-list">
          {snaps.map((s) => (
            <SnapshotRow key={s.id} s={s} restoring={restoring} onRestore={onRestore} />
          ))}
        </div>
      </div>
    </div>
  )
}

function SnapshotsPanel({ slug }: { slug: string }) {
  const [snaps, setSnaps] = useState<Snap[]>([])
  const [restoring, setRestoring] = useState<number | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    api.snapshots(slug).then(setSnaps, () => setSnaps([]))
  }, [slug])

  const restore = (id: number) => {
    if (!confirm(`Restore snapshot #${id}? Current unpublished edits are replaced.`)) return
    setRestoring(id)
    api.rollback(slug, id).then(
      () => window.location.reload(),
      (e) => { setRestoring(null); alert(`Restore failed: ${e}`) },
    )
  }

  if (!snaps.length) return null
  return (
    <>
      {showAll && (
        <SnapshotsModal
          snaps={snaps}
          restoring={restoring}
          onRestore={restore}
          onClose={() => setShowAll(false)}
        />
      )}
      <div className="pending-panel snapshots-panel">
        <div className="pending-panel-header">
          <h3><SectionLabel>Snapshots</SectionLabel></h3>
          <InfoTip label="About snapshots" align="right">
            Point-in-time copies of the document, taken automatically before risky actions
            (polish, re-ingest, publish) and on every publish. Restore rolls the document back to
            that state.
          </InfoTip>
          {snaps.length > 3 && (
            <button type="button" className="changes-history-btn" onClick={() => setShowAll(true)}>
              All {snaps.length}
            </button>
          )}
        </div>
        {snaps.slice(0, 3).map((s) => (
          <SnapshotRow key={s.id} s={s} restoring={restoring} onRestore={restore} />
        ))}
      </div>
    </>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ConvertNarrativeItem({ editor }: { editor: any }) {
  const Components = useComponentsContext()
  // BlockNote's dragHandleMenu render-prop never receives the block as a prop;
  // read it from the selection instead (opening the drag menu selects the
  // hovered block). Falls back to nothing when 0/many blocks are selected.
  const selected = useSelectedBlocks(editor)
  if (!Components) return null
  // Loosely typed: stripItalic/addItalic operate on the inline-content JSON,
  // which a typed Block models as a union (incl. undefined / table content).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const block: any = selected.length === 1 ? selected[0] : undefined
  if (block?.type === 'paragraph') {
    return (
      <Components.Generic.Menu.Item
        onClick={() =>
          editor.updateBlock(block, { type: 'forgeNarrative', content: stripItalic(block.content) })
        }
      >
        Convert to narrative
      </Components.Generic.Menu.Item>
    )
  }
  if (block?.type === 'forgeNarrative') {
    return (
      <Components.Generic.Menu.Item
        onClick={() =>
          editor.updateBlock(block, { type: 'paragraph', content: addItalic(block.content) })
        }
      >
        Convert to paragraph
      </Components.Generic.Menu.Item>
    )
  }
  return null
}

function EditorInner({ doc, onBack }: { doc: DocDetail; onBack: () => void }) {
  const isHomepage = doc.kind === 'homepage'
  const [targets, setTargets] = useState<TargetState[]>(doc.targets)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [pushing, setPushing] = useState<string | null>(null)
  const [unpublishing, setUnpublishing] = useState<string | null>(null)
  const [polishing, setPolishing] = useState(false)
  const [generatingCaptions, setGeneratingCaptions] = useState(false)
  const [polishLast, setPolishLast] = useState<PolishLastRun | null | 'loading'>('loading')
  const [polishPopoverOpen, setPolishPopoverOpen] = useState(false)
  const [polishReport, setPolishReport] = useState<PolishReport | null>(null)
  const [polishRemaining, setPolishRemaining] = useState<Set<string>>(new Set())
  const [polishReviewOpen, setPolishReviewOpen] = useState(false)
  const [outlineOpen, setOutlineOpen] = useState(true)
  const [outlineVersion, setOutlineVersion] = useState(0)
  const [activeHeading, setActiveHeading] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(null)
  const outlineTimer = useRef<ReturnType<typeof setTimeout>>(null)

  const editor = useCreateBlockNote({
    schema: forgeSchema,
    initialContent: doc.blocks as PartialBlock<typeof forgeSchema.blockSchema>[],
  })

  // Memoised heading tree; rebuilt only when the debounced version bumps,
  // so 100+ heading documents don't re-walk the tree on every keystroke.
  const outline = useMemo(
    () => buildOutline(editor.document as unknown as BlockLike[]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor, outlineVersion],
  )

  const save = useCallback(() => {
    setSaveState('saving')
    api.saveBlocks(doc.slug, editor.document).then(
      (resp) => {
        setTargets(resp.targets)
        setSaveState('saved')
      },
      () => setSaveState('error'),
    )
  }, [doc.slug, editor])

  const onChange = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(save, AUTOSAVE_MS)
    if (outlineTimer.current) clearTimeout(outlineTimer.current)
    outlineTimer.current = setTimeout(() => setOutlineVersion((v) => v + 1), 300)
  }, [save])

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
    if (outlineTimer.current) clearTimeout(outlineTimer.current)
  }, [])

  // Fetch polish last-run data
  useEffect(() => {
    if (isHomepage) { setPolishLast(null); return }
    api.polishLast(doc.slug).then(setPolishLast, () => setPolishLast(null))
  }, [doc.slug, isHomepage])

  // Homepage: re-fetch targets on window focus so group changes elsewhere
  // (Library reorder) mark the homepage dirty without a manual reload.
  useEffect(() => {
    if (!isHomepage) return
    const onFocus = () => {
      api.getDocument(doc.slug).then(
        (fresh) => setTargets(fresh.targets),
        () => {},
      )
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [isHomepage, doc.slug])

  const selectHeading = useCallback((id: string) => {
    const el = document.querySelector<HTMLElement>(`.editor-canvas [data-id="${id}"]`)
    if (!el) return
    setActiveHeading(id)
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    el.classList.add('nf-flash')
    setTimeout(() => el.classList.remove('nf-flash'), 900)
  }, [])

  // Scrollspy: highlight the heading currently near the top of the
  // viewport. Re-armed whenever the outline rebuilds.
  useEffect(() => {
    const ids = new Set(headingIds(outline))
    const els = [...document.querySelectorAll<HTMLElement>('.editor-canvas [data-id]')].filter(
      (el) => ids.has(el.dataset.id ?? ''),
    )
    if (els.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        const hit = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        if (hit) setActiveHeading((hit.target as HTMLElement).dataset.id ?? null)
      },
      { rootMargin: '0px 0px -70% 0px' },
    )
    els.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [outline])

  const onPush = useCallback(
    async (target: string) => {
      // '__all__' pushes every dirty target sequentially (git clones and
      // Drive uploads don't love racing each other).
      const names =
        target === '__all__'
          ? targets.filter((t) => t.dirty).map((t) => t.target)
          : [target]
      setPushing(target)
      try {
        for (const name of names) {
          const resp = await api.publish(doc.slug, name)
          setTargets(resp.targets)
          const warns = resp.detail?.warnings
          if (warns && warns.length > 0) {
            alert('Published with warnings:\n' + warns.join('\n'))
          }
        }
      } catch (e) {
        alert(`Publish failed: ${e}`)
      } finally {
        setPushing(null)
      }
    },
    [doc.slug, targets],
  )

  const onUnpublish = useCallback(
    async (target: string) => {
      if (
        !confirm(
          `Unpublish from ${target}?\n\nThe document will be removed from this target. ` +
            'You can republish at any time.',
        )
      )
        return
      setUnpublishing(target)
      try {
        const resp = await api.unpublish(doc.slug, target)
        setTargets(resp.targets)
      } catch (e) {
        alert(`Unpublish failed: ${e}`)
      } finally {
        setUnpublishing(null)
      }
    },
    [doc.slug],
  )

  const onDelete = useCallback(() => {
    if (
      !confirm(
        `Delete "${doc.title}"?\n\nThis removes the document and all its history from the ` +
          'library. Published copies on targets are not removed. This cannot be undone.',
      )
    )
      return
    api.deleteDocument(doc.slug).then(
      () => onBack(),
      (e) => alert(`Delete failed: ${e}`),
    )
  }, [doc.slug, doc.title, onBack])

  const onPolish = useCallback(() => {
    if (
      !confirm(
        'Polish text with Gemini?\n\n' +
          'Runs a mechanical Gemini cleanup — typography, whitespace, and obvious spelling typos. ' +
          'Fixes that only change punctuation/spacing are applied automatically. ' +
          'Anything that changes words is held for your review.\n\n' +
          'A snapshot is taken first so Restore can undo the whole pass.',
      )
    )
      return
    setPolishing(true)
    api.polish(doc.slug).then(
      (report) => {
        setPolishing(false)
        setTargets(report.targets)
        // Refresh polish last-run badge
        api.polishLast(doc.slug).then(setPolishLast, () => {})
        if (report.flagged.length === 0) {
          window.location.reload()
        } else {
          setPolishReport(report)
          setPolishRemaining(new Set(report.flagged.map((f) => f.block_id)))
          setPolishReviewOpen(true)
        }
      },
      (e) => {
        setPolishing(false)
        alert(`Polish failed: ${e}`)
      },
    )
  }, [doc.slug])

  const onPolishDone = useCallback(() => {
    setPolishReport(null)
    setPolishRemaining(new Set())
    setPolishReviewOpen(false)
    // The flags have now been reviewed (applied and/or skipped), so clear the
    // run's flagged record before reloading — otherwise the badge stays stuck
    // on "flagged". Reload regardless of whether the call succeeds.
    api.polishResolveFlags(doc.slug).finally(() => window.location.reload())
  }, [doc.slug])

  const onApplyAll = useCallback(() => {
    if (!polishReport) return
    const pending = polishReport.flagged.filter((f) => polishRemaining.has(f.block_id))
    if (pending.length === 0) return
    if (
      !confirm(
        `Apply all ${pending.length} remaining change${pending.length !== 1 ? 's' : ''}? Each replaces the block text with the polished version.`,
      )
    )
      return
    for (const f of pending) {
      editor.updateBlock(f.block_id, { content: f.polished_content as PartialBlock['content'] })
    }
    setPolishRemaining(new Set())
    save()
  }, [polishReport, polishRemaining, editor, save])

  const onSkipAll = useCallback(() => {
    setPolishRemaining(new Set())
  }, [])

  const onApproveAll = useCallback(() => {
    type ImageBlock = { id: string; type: string; props: Record<string, unknown>; children: unknown[] }
    const pending = (editor.document as unknown as ImageBlock[]).filter(
      (b) => b.type === 'forgeImage' && b.props.approval === 'pending',
    )
    if (pending.length === 0) return
    for (const b of pending) {
      editor.updateBlock(b.id, {
        props: { ...b.props, approval: 'approved' },
      } as PartialBlock<typeof forgeSchema.blockSchema>)
    }
    save()
  }, [editor, save])

  const onGenerateMissingCaptions = useCallback(async () => {
    type ImageBlock = { id: string; type: string; props: Record<string, unknown>; children: unknown[] }
    const missing = (editor.document as unknown as ImageBlock[]).filter(
      (b) => b.type === 'forgeImage' && !b.props.caption,
    )
    if (missing.length === 0) return
    setGeneratingCaptions(true)
    try {
      for (const b of missing) {
        try {
          const result = await api.generateCaption(doc.slug, b.id)
          editor.updateBlock(b.id, {
            props: { ...b.props, caption: result.caption },
          } as PartialBlock<typeof forgeSchema.blockSchema>)
        } catch {
          // skip failed images silently
        }
      }
      save()
    } finally {
      setGeneratingCaptions(false)
    }
  }, [editor, doc.slug, save])

  const refreshImageBlocks = useCallback(() => {
    // Pull the sketch-related props the batch job persisted server-side into
    // the editor's in-memory blocks. Surgical (only forgeImage sketch props) so
    // any unsaved prose edits survive; a follow-up save reconciles the rest.
    api.getDocument(doc.slug).then((fresh) => {
      const updates = imageSketchUpdates(
        editor.document as unknown[],
        fresh.blocks as unknown[],
      )
      for (const u of updates) {
        editor.updateBlock(u.id, {
          props: u.props,
        } as PartialBlock<typeof forgeSchema.blockSchema>)
      }
    }, () => {})
  }, [editor, doc.slug])

  const jumpToBlock = useCallback((blockId: string) => {
    const el = document.querySelector<HTMLElement>(`.editor-canvas [data-id="${blockId}"]`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    el.classList.add('nf-flash')
    setTimeout(() => el.classList.remove('nf-flash'), 900)
  }, [])

  return (
    <div className="shell">
      {polishing && <PolishProgress slug={doc.slug} />}

      {polishReport && polishReviewOpen && (
        <PolishReview
          report={polishReport}
          remaining={polishRemaining}
          onApply={(blockId, content) => {
            editor.updateBlock(blockId, { content: content as PartialBlock['content'] })
            setPolishRemaining((prev) => {
              const next = new Set(prev)
              next.delete(blockId)
              return next
            })
          }}
          onSkip={(blockId) =>
            setPolishRemaining((prev) => {
              const next = new Set(prev)
              next.delete(blockId)
              return next
            })
          }
          onDone={onPolishDone}
          onClose={() => setPolishReviewOpen(false)}
          onApplyAll={onApplyAll}
          onSkipAll={onSkipAll}
          onJumpToBlock={jumpToBlock}
        />
      )}

      <header className="editor-header">
        {!isHomepage && (
          <button
            type="button"
            className="nf-ibtn"
            title={outlineOpen ? 'Hide outline' : 'Show outline'}
            onClick={() => setOutlineOpen((o) => !o)}
          >
            <i
              className={`ti ${outlineOpen ? 'ti-layout-sidebar-left-collapse' : 'ti-list-tree'}`}
              aria-hidden
            />
          </button>
        )}
        <button type="button" className="crumb" onClick={onBack}>
          Library
        </button>
        <i className="ti ti-chevron-right crumb-sep" aria-hidden />
        <div className="editor-titles">
          <SerifTitle>{isHomepage ? 'Homepage' : doc.title}</SerifTitle>
          <span className="muted">
            {isHomepage ? 'Site index — push to publish' : String(doc.meta.year_display ?? '')}
          </span>
        </div>
        <span className={`save-state ${saveState}`}>
          {saveState === 'saving'
            ? 'Saving…'
            : saveState === 'saved'
              ? 'Saved'
              : saveState === 'error'
                ? 'Save failed'
                : ''}
        </span>
      </header>
      <div className="editor-wrap">
        {!isHomepage && (
          <>
            <MetaBar
              doc={doc}
              onSaved={setTargets}
              editorDoc={() => editor.document}
              onPolish={onPolish}
              polishing={polishing}
              polishBadge={polishLast !== 'loading' ? (
                <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
                  <span style={{ cursor: 'pointer' }} onClick={() => setPolishPopoverOpen((o) => !o)}>
                    <StatusBadge
                      variant={(() => {
                        const s = computePolishBadge(polishLast, doc.updated_at ?? null)
                        return (s === 'loading' ? 'never-run' : s) as BadgeVariant
                      })()}
                    />
                  </span>
                  {polishPopoverOpen && polishLast !== null && (
                    <PolishPopover
                      run={polishLast}
                      onClose={() => setPolishPopoverOpen(false)}
                      onRestore={() => {
                        const confirmed = confirm('Restore to the pre-polish snapshot? Current edits will be replaced.')
                        if (!confirmed) return
                        api.snapshots(doc.slug).then((snaps) => {
                          const prePolish = snaps.find((s) => s.note === 'before polish')
                          if (!prePolish) { alert('No pre-polish snapshot found.'); return }
                          api.rollback(doc.slug, prePolish.id).then(
                            () => window.location.reload(),
                            (e) => alert(`Restore failed: ${e}`),
                          )
                        })
                      }}
                      onReviewFlagged={() => {
                        // The flagged review lives in the in-memory report; if
                        // it's gone (e.g. after a reload), re-run polish to
                        // regenerate it rather than opening an empty panel.
                        if (polishReport) setPolishReviewOpen(true)
                        else onPolish()
                      }}
                    />
                  )}
                </span>
              ) : undefined}
            />
          </>
        )}
        <div className={`editor-body${!isHomepage ? ' with-outline' : ''}`}>
          {!isHomepage && (outlineOpen ? (
            <OutlineNavigator nodes={outline} activeId={activeHeading} onSelect={selectHeading} />
          ) : (
            <div className="nf-rail">
              <button
                type="button"
                className="nf-ibtn"
                title="Show outline"
                onClick={() => setOutlineOpen(true)}
              >
                <i className="ti ti-list-tree" aria-hidden />
              </button>
            </div>
          ))}
          <div className="editor-canvas">
            <EditorErrorBoundary>
            <BlockNoteView editor={editor} onChange={onChange} theme="light" slashMenu={false}>
              {isHomepage ? (
                <SuggestionMenuController
                  triggerCharacter="/"
                  getItems={async (q) =>
                    filterSuggestionItems(
                      [...getDefaultReactSlashMenuItems(editor), dedicationSlashItem(editor), docGroupSlashItem(editor), narrativeSlashItem(editor)],
                      q,
                    )
                  }
                />
              ) : (
                <SuggestionMenuController
                  triggerCharacter="/"
                  getItems={async (query) => {
                    const defaults = getDefaultReactSlashMenuItems(editor).filter(
                      (i) => i.title !== 'Image',
                    )
                    const photoItem = {
                      title: 'Photo / Figure',
                      subtext: 'Insert a photo or illustration',
                      aliases: ['im', 'image', 'photo', 'figure', 'fig'],
                      group: 'Forge',
                      icon: <i className="ti ti-photo" />,
                      onItemClick: () => insertOrUpdateBlockForSlashMenu(editor, { type: 'forgeImage' }),
                    }
                    const all = [...defaults, photoItem, narrativeSlashItem(editor), footnoteSlashItem(editor)]
                    const q = query.toLowerCase()
                    return q
                      ? all.filter(
                          (i) =>
                            i.title.toLowerCase().includes(q) ||
                            i.aliases?.some((a) => a.includes(q)),
                        )
                      : all
                  }}
                />
              )}
              <SideMenuController
                sideMenu={(props) => (
                  <SideMenu
                    {...props}
                    dragHandleMenu={() => (
                      <DragHandleMenu>
                        <RemoveBlockItem>Delete</RemoveBlockItem>
                        <ConvertNarrativeItem editor={editor} />
                      </DragHandleMenu>
                    )}
                  />
                )}
              />
            </BlockNoteView>
            </EditorErrorBoundary>
          </div>
          <button
            type="button"
            className="scroll-top-btn"
            title="Scroll to top"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          >
            ↑
          </button>
          <div className="editor-side">
            {polishReport && !polishReviewOpen && (
              <div className="polish-review-stub">
                <span>
                  Polish review — {polishRemaining.size} pending
                </span>
                <div className="polish-review-stub-actions">
                  <Button variant="primary" onClick={() => setPolishReviewOpen(true)}>
                    Resume review
                  </Button>
                  <button type="button" onClick={onPolishDone}>
                    Done — reload editor
                  </button>
                </div>
              </div>
            )}
            {!isHomepage && (
              <ImagesPanel
                slug={doc.slug}
                editorDoc={() => editor.document}
                onApproveAll={onApproveAll}
                onGenerateCaptions={onGenerateMissingCaptions}
                onSketchesGenerated={refreshImageBlocks}
                generatingCaptions={generatingCaptions}
              />
            )}
            <PendingPanel
              slug={doc.slug}
              targets={targets}
              onPush={onPush}
              onUnpublish={onUnpublish}
              pushing={pushing}
              unpublishing={unpublishing}
              hideUnpublish={isHomepage}
            />
            {!isHomepage && <ReportPanel slug={doc.slug} />}
            <SnapshotsPanel slug={doc.slug} />
            {!isHomepage && (
              <div className="danger-panel">
                <button type="button" className="btn-danger" onClick={onDelete}>
                  <i className="ti ti-trash" aria-hidden /> Delete document
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export function Editor({ slug, onBack }: { slug: string; onBack: () => void }) {
  const [doc, setDoc] = useState<DocDetail | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setDoc(null)
    api.getDocument(slug).then(setDoc, (e) => setError(String(e)))
  }, [slug])

  if (error) return <p className="error">{error}</p>
  if (!doc) return <p className="muted">Loading {slug}…</p>
  return <EditorInner doc={doc} onBack={onBack} />
}
