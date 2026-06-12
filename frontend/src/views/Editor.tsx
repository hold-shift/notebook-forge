import { useCallback, useEffect, useRef, useState } from 'react'
import { BlockNoteView } from '@blocknote/mantine'
import { SuggestionMenuController, getDefaultReactSlashMenuItems, useCreateBlockNote } from '@blocknote/react'
import type { PartialBlock } from '@blocknote/core'
import '@blocknote/core/fonts/inter.css'
import '@blocknote/mantine/style.css'
import { useMemo } from 'react'
import { api, type DocDetail, type PolishReport, type TargetState } from '../api'
import { forgeSchema } from '../forge/schema'
// forgeSchema used for PartialBlock type cast in updateBlock calls
import { OutlineNavigator } from '../forge/OutlineNavigator'
import { buildOutline, headingIds, type BlockLike } from '../forge/outline'
import { timeAgo } from './Library'
import { PolishProgress } from './PolishProgress'
import { PolishReview } from './PolishReview'

const AUTOSAVE_MS = 1200

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

function PendingPanel({
  slug,
  targets,
  onPush,
  onUnpublish,
  pushing,
  unpublishing,
}: {
  slug: string
  targets: TargetState[]
  onPush: (target: string) => void
  onUnpublish: (target: string) => void
  pushing: string | null
  unpublishing: string | null
}) {
  const [changes, setChanges] = useState<ChangeRow[]>([])
  const [showHistory, setShowHistory] = useState(false)

  useEffect(() => {
    api.changes(slug).then(
      (rows) => setChanges(rows as ChangeRow[]),
      () => setChanges([]),
    )
  }, [slug, targets])

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
          <h3>Pending changes</h3>
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
          return (
            <div key={t.target} className="pending-row">
              <span className={`dot ${t.dirty ? 'dirty' : 'clean'}`} />
              <span className="pending-name">{t.target}</span>
              {t.url && (
                <a
                  className="target-link"
                  href={t.url}
                  target="_blank"
                  rel="noreferrer"
                  title={`Open the published ${t.kind} output`}
                >
                  ↗
                </a>
              )}
              <span className="pending-state">
                {t.status !== 'PUBLISHED'
                  ? 'never published'
                  : t.dirty
                    ? `${behind || 'some'} change${behind === 1 ? '' : 's'} behind`
                    : 'up to date'}
              </span>
              <button
                type="button"
                disabled={!t.dirty || pushing === t.target}
                onClick={() => onPush(t.target)}
              >
                {pushing === t.target ? 'Pushing…' : 'Push'}
              </button>
              {t.status === 'PUBLISHED' && (
                <button
                  type="button"
                  className="btn-danger-sm"
                  disabled={!!pushing || unpublishing === t.target}
                  title={`Remove this document from ${t.target}`}
                  onClick={() => onUnpublish(t.target)}
                >
                  {unpublishing === t.target ? 'Removing…' : 'Unpublish'}
                </button>
              )}
            </div>
          )
        })}
      </div>
      {targets.filter((t) => t.dirty).length > 1 && (
        <button
          type="button"
          className="btn-primary push-all"
          disabled={!!pushing}
          onClick={() => onPush('__all__')}
        >
          {pushing === '__all__' ? 'Pushing all…' : 'Push to all targets'}
        </button>
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
  onApproveAll,
  onGenerateCaptions,
  generatingCaptions,
}: {
  doc: DocDetail
  onSaved: (targets: TargetState[]) => void
  editorDoc: () => unknown[]
  onPolish: () => void
  polishing: boolean
  onApproveAll: () => void
  onGenerateCaptions: () => Promise<void>
  generatingCaptions: boolean
}) {
  const meta = doc.meta as Record<string, string | boolean>
  const [title, setTitle] = useState(String(meta.title ?? ''))
  const [author, setAuthor] = useState(String(meta.author ?? ''))
  const [years, setYears] = useState(String(meta.year_display ?? ''))
  const [standfirst, setStandfirst] = useState(String(meta.standfirst ?? ''))
  const tocInitial =
    meta.show_toc === undefined || meta.show_toc === null ? 'auto' : meta.show_toc ? 'on' : 'off'
  const [toc, setToc] = useState(tocInitial)
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
    toc !== tocInitial

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
      <label className="meta-standfirst">
        Standfirst
        <input value={standfirst} onChange={(e) => setStandfirst(e.target.value)} />
      </label>
      <label title="Contents nav on the published HTML page. Auto = on when the document has more than 15 headings. Always rebuilt from current headings at publish.">
        Contents
        <select value={toc} onChange={(e) => setToc(e.target.value)}>
          <option value="auto">Auto</option>
          <option value="on">On</option>
          <option value="off">Off</option>
        </select>
      </label>
      <label className="meta-slug" title="Internal library ID and URL path segment. Changing it makes the old URL a dead link until re-published.">
        Slug
        <span className="meta-slug-row">
          <input
            value={slug}
            onChange={(e) => { setSlug(e.target.value); setSlugError('') }}
            onKeyDown={(e) => e.key === 'Enter' && saveSlug()}
            className="meta-slug-input"
          />
          <button
            type="button"
            disabled={!slugDirty || slugState === 'saving'}
            onClick={saveSlug}
          >
            {slugState === 'saving' ? 'Renaming…' : 'Rename'}
          </button>
        </span>
        {slugError && <span className="error meta-slug-error">{slugError}</span>}
      </label>
      <button type="button" disabled={(!dirty && !needsConfirm) || state === 'saving'} onClick={save}>
        {state === 'saving' ? 'Saving…' : needsConfirm ? 'Confirm details' : 'Save details'}
      </button>
      {Boolean(meta.source_asset_id) && (
        <button
          type="button"
          disabled={state === 'saving'}
          title="Re-run extraction from the archived source file"
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
      <button
        type="button"
        disabled={polishing || state === 'saving'}
        title="Run Gemini mechanical cleanup (typography, whitespace, obvious typos). A snapshot is taken first."
        onClick={onPolish}
      >
        {polishing ? 'Polishing…' : '✨ Polish text'}
      </button>
      {(() => {
        const blocks = editorDoc() as { type: string; props?: Record<string, unknown> }[]
        const images = blocks.filter((b) => b.type === 'forgeImage')
        const pendingCount = images.filter((b) => b.props?.approval === 'pending').length
        const missingCount = images.filter((b) => !b.props?.caption).length
        return (
          <>
            <button
              type="button"
              disabled={pendingCount === 0}
              title="Mark all pending images as approved"
              onClick={onApproveAll}
            >
              {pendingCount > 0 ? `🖼️ Approve all (${pendingCount})` : '🖼️ Approve all'}
            </button>
            <button
              type="button"
              disabled={missingCount === 0 || generatingCaptions}
              title="Generate AI captions for images without one"
              onClick={() => void onGenerateCaptions()}
            >
              {generatingCaptions ? 'Captioning…' : missingCount > 0 ? `Caption images (${missingCount})` : 'Caption images'}
            </button>
          </>
        )
      })()}
      {needsConfirm && (
        <span className="confirm-hint">
          Detected from the source — please confirm title and years before publishing.
        </span>
      )}
      {state === 'error' && <span className="error">save failed</span>}
    </div>
  )
}

function SnapshotsPanel({ slug }: { slug: string }) {
  const [snaps, setSnaps] = useState<{ id: number; note: string; created_at: string | null }[]>([])
  const [restoring, setRestoring] = useState<number | null>(null)

  useEffect(() => {
    api.snapshots(slug).then(setSnaps, () => setSnaps([]))
  }, [slug])

  const restore = (id: number) => {
    if (!confirm(`Restore snapshot #${id}? Current unpublished edits are replaced.`)) return
    setRestoring(id)
    api.rollback(slug, id).then(
      () => window.location.reload(), // editor remounts with restored blocks
      (e) => {
        setRestoring(null)
        alert(`Restore failed: ${e}`)
      },
    )
  }

  if (!snaps.length) return null
  return (
    <div className="pending-panel snapshots-panel">
      <h3>Snapshots</h3>
      {snaps.slice(0, 8).map((s) => (
        <div key={s.id} className="pending-row">
          <span className="pending-name">#{s.id}</span>
          <span className="pending-state">
            {s.note || 'snapshot'}
            {s.created_at ? ` · ${s.created_at.slice(0, 16).replace('T', ' ')}` : ''}
          </span>
          <button type="button" disabled={restoring === s.id} onClick={() => restore(s.id)}>
            {restoring === s.id ? 'Restoring…' : 'Restore'}
          </button>
        </div>
      ))}
    </div>
  )
}

function EditorInner({ doc, onBack }: { doc: DocDetail; onBack: () => void }) {
  const [targets, setTargets] = useState<TargetState[]>(doc.targets)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [pushing, setPushing] = useState<string | null>(null)
  const [unpublishing, setUnpublishing] = useState<string | null>(null)
  const [polishing, setPolishing] = useState(false)
  const [generatingCaptions, setGeneratingCaptions] = useState(false)
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
    window.location.reload()
  }, [])

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
        <button type="button" className="crumb" onClick={onBack}>
          Library
        </button>
        <i className="ti ti-chevron-right crumb-sep" aria-hidden />
        <div className="editor-titles">
          <h2>{doc.title}</h2>
          <span className="muted">{String(doc.meta.year_display ?? '')}</span>
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
        <MetaBar
          doc={doc}
          onSaved={setTargets}
          editorDoc={() => editor.document}
          onPolish={onPolish}
          polishing={polishing}
          onApproveAll={onApproveAll}
          onGenerateCaptions={onGenerateMissingCaptions}
          generatingCaptions={generatingCaptions}
        />
        <div className="editor-body with-outline">
          {outlineOpen ? (
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
          )}
          <div className="editor-canvas">
            <BlockNoteView editor={editor} onChange={onChange} theme="light" slashMenu={false}>
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
                    group: 'Media',
                    onItemClick: () => {
                      editor.insertBlocks(
                        [{ type: 'forgeImage', props: {} }],
                        editor.getTextCursorPosition().block,
                        'after',
                      )
                    },
                  }
                  const all = [...defaults, photoItem]
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
            </BlockNoteView>
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
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => setPolishReviewOpen(true)}
                  >
                    Resume review
                  </button>
                  <button type="button" onClick={onPolishDone}>
                    Done — reload editor
                  </button>
                </div>
              </div>
            )}
            <PendingPanel
              slug={doc.slug}
              targets={targets}
              onPush={onPush}
              onUnpublish={onUnpublish}
              pushing={pushing}
              unpublishing={unpublishing}
            />
            <SnapshotsPanel slug={doc.slug} />
            <div className="danger-panel">
              <button type="button" className="btn-danger" onClick={onDelete}>
                <i className="ti ti-trash" aria-hidden /> Delete document
              </button>
            </div>
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
