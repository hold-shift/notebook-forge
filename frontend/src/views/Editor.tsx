import { useCallback, useEffect, useRef, useState } from 'react'
import { BlockNoteView } from '@blocknote/mantine'
import { useCreateBlockNote } from '@blocknote/react'
import type { PartialBlock } from '@blocknote/core'
import '@blocknote/core/fonts/inter.css'
import '@blocknote/mantine/style.css'
import { useMemo } from 'react'
import { api, type DocDetail, type TargetState } from '../api'
import { forgeSchema } from '../forge/schema'
import { OutlineNavigator } from '../forge/OutlineNavigator'
import { buildOutline, headingIds, type BlockLike } from '../forge/outline'
import { timeAgo } from './Library'

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

function PendingPanel({
  slug,
  targets,
  onPush,
  pushing,
}: {
  slug: string
  targets: TargetState[]
  onPush: (target: string) => void
  pushing: string | null
}) {
  const [changes, setChanges] = useState<ChangeRow[]>([])

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

  const recentEdits = changes.filter((c) => c.kind !== 'publish').slice(0, 4)
  const anyDirty = targets.some((t) => t.dirty)

  return (
    <div className="pending-panel">
      <h3>Pending changes</h3>
      {anyDirty && recentEdits.length > 0 && (
        <div className="change-list">
          {recentEdits.map((c) => (
            <div key={c.id} className="change-row">
              <i className={`ti ${changeIcon(c)}`} aria-hidden />
              <span className="change-summary">{c.summary}</span>
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
  )
}

function MetaBar({
  doc,
  onSaved,
  editorDoc,
}: {
  doc: DocDetail
  onSaved: (targets: TargetState[]) => void
  editorDoc: () => unknown[]
}) {
  const meta = doc.meta as Record<string, string | boolean>
  const [title, setTitle] = useState(String(meta.title ?? ''))
  const [years, setYears] = useState(String(meta.year_display ?? ''))
  const [standfirst, setStandfirst] = useState(String(meta.standfirst ?? ''))
  const tocInitial =
    meta.show_toc === undefined || meta.show_toc === null ? 'auto' : meta.show_toc ? 'on' : 'off'
  const [toc, setToc] = useState(tocInitial)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const needsConfirm = meta.date_confirmed === false

  const dirty =
    title !== String(meta.title ?? '') ||
    years !== String(meta.year_display ?? '') ||
    standfirst !== String(meta.standfirst ?? '') ||
    toc !== tocInitial

  const save = () => {
    setState('saving')
    const updated: Record<string, unknown> = {
      ...doc.meta,
      title,
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

  return (
    <div className="shell">
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
        <MetaBar doc={doc} onSaved={setTargets} editorDoc={() => editor.document} />
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
            <BlockNoteView editor={editor} onChange={onChange} theme="light" />
          </div>
          <div className="editor-side">
            <PendingPanel slug={doc.slug} targets={targets} onPush={onPush} pushing={pushing} />
            <SnapshotsPanel slug={doc.slug} />
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
