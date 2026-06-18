import { useEffect, useRef, useState } from 'react'
import { api, type DocSummary, type GroupInfo, type ReportState, type TargetState } from '../api'
import {
  bucketDocs,
  effectiveSort,
  sortDocs,
  type Bucket,
  type GroupBy,
  type SortMode,
} from '../lib/librarySort'
import { ManageGroupsModal } from './ManageGroupsModal'
import { Button, InfoTip, StatusBadge, SectionLabel, SerifTitle } from '../ui'

const LS_GROUPBY = 'nf-library-groupby'
const LS_SORT = 'nf-library-sort'

export function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 90) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400 * 2) return `${Math.round(s / 3600)} hr ago`
  return `${Math.round(s / 86400)} days ago`
}

function TargetPill({ t }: { t: TargetState }) {
  const labels: Record<string, string> = {
    'github-pages': 'HTML',
    'local-folder': 'Local',
    drive: 'Drive',
  }
  const name = labels[t.target] ?? t.target
  if (t.status !== 'PUBLISHED') {
    return <StatusBadge variant="unpublished" label={`${name} unpublished`} />
  }
  return t.dirty ? (
    <StatusBadge variant="changes" label={`${name} changes to push`} />
  ) : (
    <StatusBadge variant="live" label={`${name} live`} />
  )
}

function ReportPill({ report }: { report?: ReportState }) {
  if (!report || !report.exists) {
    return <StatusBadge variant="never-run" label="No report" />
  }
  if (report.status === 'failed') {
    return <StatusBadge variant="flagged" label="Report failed" />
  }
  if (report.stale) {
    return <StatusBadge variant="stale" label="Report stale" />
  }
  return <StatusBadge variant="live" label="Report" />
}

type StatusFilter = 'all' | 'pending' | 'clean' | 'unpublished'

function matchesFilter(d: DocSummary, f: StatusFilter): boolean {
  if (f === 'all') return true
  const published = d.targets.filter((t) => t.status === 'PUBLISHED')
  if (f === 'unpublished') return published.length === 0
  if (f === 'pending') return d.targets.some((t) => t.dirty)
  return published.length > 0 && !d.targets.some((t) => t.dirty)
}

function fileIcon(sourceType: string): string {
  if (sourceType === 'PDF') return 'ti-file-type-pdf'
  if (sourceType === 'DOCX') return 'ti-file-type-docx'
  return 'ti-file-text'
}

function KebabMenu({
  doc,
  groups,
  onMove,
}: {
  doc: DocSummary
  groups: GroupInfo[]
  onMove: (groupId: number | null) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const fn = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', fn)
    return () => document.removeEventListener('mousedown', fn)
  }, [open])
  useEffect(() => {
    if (!open) return
    const fn = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', fn)
    return () => document.removeEventListener('keydown', fn)
  }, [open])

  return (
    <div className="kebab-wrap" ref={ref}>
      <button
        type="button"
        className="kebab-btn"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
        title="Move to group…"
      >
        <i className="ti ti-dots-vertical" />
      </button>
      {open && (
        <div className="kebab-menu" onClick={(e) => e.stopPropagation()}>
          {groups.map((g) => (
            <button
              key={g.id}
              type="button"
              className="kebab-item"
              onClick={() => { onMove(g.id); setOpen(false) }}
            >
              <span className="group-dot" style={{ background: g.color }} />
              Move to {g.name}
            </button>
          ))}
          {doc.group_id != null && (
            <button
              type="button"
              className="kebab-item"
              onClick={() => { onMove(null); setOpen(false) }}
            >
              Remove from group
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function DocCard({
  doc,
  groups,
  showHandle,
  onOpen,
  onDragStart,
  onDragOver,
  onDrop,
  onMove,
}: {
  doc: DocSummary
  groups: GroupInfo[]
  showHandle: boolean
  onOpen: (slug: string) => void
  onDragStart: (slug: string) => void
  onDragOver: (e: React.DragEvent, slug: string) => void
  onDrop: (e: React.DragEvent, targetSlug: string, bucket: Bucket) => void
  onMove: (slug: string, groupId: number | null) => void
  bucket: Bucket
}) {
  const [dropBefore, setDropBefore] = useState(false)

  return (
    <div
      className={`doc-card-wrap${dropBefore ? ' drop-before' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDropBefore(true); onDragOver(e, doc.slug) }}
      onDragLeave={() => setDropBefore(false)}
      onDrop={(e) => { setDropBefore(false); onDrop(e, doc.slug, (window as unknown as { _nfBucket: Bucket })._nfBucket) }}
    >
      {showHandle && (
        <span
          className="drag-handle"
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData('text/nf-slug', doc.slug)
            onDragStart(doc.slug)
          }}
        >
          <i className="ti ti-grip-vertical" />
        </span>
      )}
      <button className="doc-card" onClick={() => onOpen(doc.slug)}>
        <div className="doc-thumb">
          <i className={`ti ${fileIcon(doc.source_type)}`} aria-hidden />
        </div>
        <div className="doc-main">
          <SerifTitle as="p" className="doc-title">
            {doc.title}
            {doc.year_display ? ` · ${doc.year_display}` : ''}
          </SerifTitle>
          <p className="doc-meta">
            {doc.source_type} · {doc.figures} images · {doc.sketched} sketched
            {doc.pending_review > 0 ? ` · ${doc.pending_review} awaiting review` : ''}
            {doc.updated_at ? ` · updated ${timeAgo(doc.updated_at)}` : ''}
          </p>
        </div>
        <span className="badges">
          {doc.targets
            .filter((t) => t.target !== 'local-folder')
            .map((t) => (
              <TargetPill key={t.target} t={t} />
            ))}
          <ReportPill report={doc.report} />
          <InfoTip label="About the status badges" align="right">
            Status badges for this document. Publish targets — HTML (public site) and Drive
            (the NotebookLM-safe Google Doc) — show live, changes to push, or unpublished. The
            Report badge shows the analytical report: generated, stale (the document changed
            since it was generated), failed, or none yet.
          </InfoTip>
        </span>
      </button>
      <KebabMenu doc={doc} groups={groups} onMove={(gid) => onMove(doc.slug, gid)} />
    </div>
  )
}

export function Library({
  onOpen,
  onSettings,
  onHomepage,
}: {
  onOpen: (slug: string) => void
  onSettings?: () => void
  onHomepage?: () => void
}) {
  const [docs, setDocs] = useState<DocSummary[] | null>(null)
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [error, setError] = useState('')
  const [ingesting, setIngesting] = useState(false)
  const [creating, setCreating] = useState(false)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [hits, setHits] = useState<{ slug: string; title: string; snip: string }[] | null>(null)
  const [groupBy, setGroupBy] = useState<GroupBy>(
    () => (localStorage.getItem(LS_GROUPBY) as GroupBy | null) ?? 'group',
  )
  const [sort, setSort] = useState<SortMode>(
    () => (localStorage.getItem(LS_SORT) as SortMode | null) ?? 'manual',
  )
  const [showManageGroups, setShowManageGroups] = useState(false)
  const [dragOver, setDragOver] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const reload = () => {
    api.listDocuments().then(setDocs, (e) => setError(String(e)))
    api.groups().then(setGroups)
  }

  useEffect(() => { reload() }, [])

  useEffect(() => {
    if (!query.trim()) { setHits(null); return }
    const t = setTimeout(() => {
      api.search(query).then(setHits, () => setHits([]))
    }, 300)
    return () => clearTimeout(t)
  }, [query])

  const onGroupByChange = (v: GroupBy) => {
    setGroupBy(v)
    localStorage.setItem(LS_GROUPBY, v)
  }
  const onSortChange = (v: SortMode) => {
    setSort(v)
    localStorage.setItem(LS_SORT, v)
  }

  const onFile = (file: File | undefined) => {
    if (!file) return
    setIngesting(true)
    api.ingest(file).then(
      (resp) => { setIngesting(false); onOpen(resp.slug) },
      (e) => { setIngesting(false); alert(`Ingest failed: ${e}`) },
    )
  }

  const onNew = () => {
    setCreating(true)
    api.createDocument().then(
      (resp) => { setCreating(false); onOpen(resp.slug) },
      (e) => { setCreating(false); alert(`Could not create document: ${e}`) },
    )
  }

  if (error) return <p className="error">Backend unreachable: {error}</p>
  if (!docs) return <p className="muted">Loading library…</p>

  const eSort = effectiveSort(groupBy, sort)
  const visible = docs.filter((d) => matchesFilter(d, filter))
  const buckets = bucketDocs(visible, groupBy, groups)

  const handleDrop = (
    e: React.DragEvent,
    targetSlug: string | null,
    bucket: Bucket,
  ) => {
    e.preventDefault()
    const draggedSlug = e.dataTransfer.getData('text/nf-slug')
    if (!draggedSlug) return
    const draggedDoc = docs.find((d) => d.slug === draggedSlug)
    if (!draggedDoc) return
    const destGroupId = bucket.groupId !== undefined ? bucket.groupId : null

    const moveAndReorder = (newBucketDocs: DocSummary[]) => {
      const newSlugs = newBucketDocs.map((d) => d.slug)
      api.setPositions(destGroupId, newSlugs).then(reload)
    }

    if (draggedDoc.group_id !== destGroupId) {
      api.setDocumentGroup(draggedSlug, destGroupId).then(() => {
        if (targetSlug) {
          const bucketAfterMove = bucket.docs.filter((d) => d.slug !== draggedSlug)
          const idx = bucketAfterMove.findIndex((d) => d.slug === targetSlug)
          const newBucketDocs = [...bucketAfterMove]
          newBucketDocs.splice(idx === -1 ? newBucketDocs.length : idx, 0, { ...draggedDoc, group_id: destGroupId })
          moveAndReorder(newBucketDocs)
        } else {
          reload()
        }
      })
    } else if (targetSlug) {
      const sorted = sortDocs(bucket.docs, eSort)
      const withoutDragged = sorted.filter((d) => d.slug !== draggedSlug)
      const idx = withoutDragged.findIndex((d) => d.slug === targetSlug)
      withoutDragged.splice(idx === -1 ? withoutDragged.length : idx, 0, draggedDoc)
      moveAndReorder(withoutDragged)
    }
  }

  const handleHeaderDrop = (e: React.DragEvent, bucket: Bucket) => {
    e.preventDefault()
    const draggedSlug = e.dataTransfer.getData('text/nf-slug')
    if (!draggedSlug) return
    const destGroupId = bucket.groupId !== undefined ? bucket.groupId : null
    api.setDocumentGroup(draggedSlug, destGroupId).then(reload)
  }

  const handleMove = (slug: string, groupId: number | null) => {
    api.setDocumentGroup(slug, groupId).then(reload)
  }

  return (
    <div className="shell">
      <div className="topnav">
        <span className="brand">
          <img src="/icon.png" alt="" className="brand-icon" aria-hidden />
          <SerifTitle as="span" style={{ fontSize: 15 }}>Notebook Forge</SerifTitle>
          <a
            className="brand-version"
            href="https://github.com/hold-shift/notebook-forge"
            target="_blank"
            rel="noreferrer"
            title="View Notebook Forge on GitHub"
          >
            <i className="ti ti-brand-github" aria-hidden /> v{__APP_VERSION__}
          </a>
        </span>
        <button type="button" className="navlink active">
          Library
        </button>
        <button type="button" className="navlink" onClick={onHomepage}>
          Homepage
        </button>
        <button type="button" className="navlink" onClick={onSettings}>
          Settings
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.docx"
          style={{ display: 'none' }}
          onChange={(e) => onFile(e.target.files?.[0])}
        />
        <Button
          variant="primary"
          disabled={creating}
          onClick={onNew}
          style={{ marginLeft: 'auto' }}
        >
          <i className="ti ti-plus" aria-hidden /> {creating ? 'Creating…' : 'New'}
        </Button>
        <Button
          variant="secondary"
          disabled={ingesting}
          onClick={() => fileInput.current?.click()}
          title="Create a document by importing a PDF or Word file"
        >
          <i className="ti ti-upload" aria-hidden /> {ingesting ? 'Importing…' : 'Import PDF/DOCX'}
        </Button>
      </div>
      <div className="toolbar">
        <input
          type="text"
          placeholder="Search documents…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={filter} onChange={(e) => setFilter(e.target.value as StatusFilter)}>
          <option value="all">All statuses</option>
          <option value="pending">Changes to push</option>
          <option value="clean">Published · clean</option>
          <option value="unpublished">Never published</option>
        </select>
        <select value={groupBy} onChange={(e) => onGroupByChange(e.target.value as GroupBy)}>
          <option value="group">Group</option>
          <option value="none">None</option>
          <option value="status">Status</option>
          <option value="format">Format</option>
        </select>
        <select value={sort} onChange={(e) => onSortChange(e.target.value as SortMode)}>
          <option value="manual" disabled={groupBy !== 'group'}>Manual order</option>
          <option value="date_range">Date range</option>
          <option value="title_az">Title A–Z</option>
          <option value="last_updated">Last updated</option>
          <option value="attention">Needs attention first</option>
        </select>
        <InfoTip label="About sort order">
          Sort order within each group. “Manual order” (drag the handle to arrange) is available
          only when grouping by Group. “Needs attention first” surfaces documents with unpushed
          changes, sketches awaiting review, or unconfirmed dates.
        </InfoTip>
        <Button variant="secondary" onClick={() => setShowManageGroups(true)}>
          Manage groups
        </Button>
        <InfoTip label="About groups">
          Groups are colour-coded collections for organising the library; they also drive the
          homepage's document lists. Create, rename, recolour, reorder, or delete them here —
          deleting a group simply ungroups its documents.
        </InfoTip>
      </div>
      {hits !== null && (
        <div className="search-hits" style={{ paddingTop: 12 }}>
          {hits.length === 0 && <p className="muted">No matches.</p>}
          {hits.map((h) => (
            <button key={h.slug} className="search-hit" onClick={() => onOpen(h.slug)}>
              <span className="doc-title">{h.title}</span>
              <span className="snip" dangerouslySetInnerHTML={{ __html: h.snip }} />
            </button>
          ))}
        </div>
      )}
      <div className="doc-list">
        {buckets.map((bucket) => (
          <div key={bucket.key}>
            {groupBy !== 'none' && (
              <div
                className={`group-header${dragOver === bucket.key ? ' dragover' : ''}`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(bucket.key) }}
                onDragLeave={() => setDragOver(null)}
                onDrop={(e) => { setDragOver(null); handleHeaderDrop(e, bucket) }}
              >
                {bucket.color && (
                  <span className="group-dot" style={{ background: bucket.color }} />
                )}
                <SectionLabel>{bucket.label}</SectionLabel>
                <span className="muted" style={{ marginLeft: 6 }}>({bucket.docs.length})</span>
              </div>
            )}
            {sortDocs(bucket.docs, eSort).map((d) => (
              <DocCard
                key={d.slug}
                doc={d}
                groups={groups}
                bucket={bucket}
                showHandle={eSort === 'manual'}
                onOpen={onOpen}
                onDragStart={() => {
                  ;(window as unknown as { _nfBucket: Bucket })._nfBucket = bucket
                }}
                onDragOver={() => {}}
                onDrop={(e, targetSlug) => handleDrop(e, targetSlug, bucket)}
                onMove={handleMove}
              />
            ))}
            {bucket.docs.length === 0 && groupBy === 'group' && (
              <p className="muted" style={{ paddingLeft: 16, fontSize: '0.85rem' }}>
                No documents in this group.
              </p>
            )}
          </div>
        ))}
        {visible.length === 0 && <p className="muted">No documents match this filter.</p>}
      </div>
      {showManageGroups && (
        <ManageGroupsModal
          onClose={() => setShowManageGroups(false)}
          onChanged={reload}
        />
      )}
    </div>
  )
}
