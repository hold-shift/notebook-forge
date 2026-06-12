import { useEffect, useRef, useState } from 'react'
import { api, type DocSummary, type TargetState } from '../api'

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
    return (
      <span className="pill neutral">
        <i className="ti ti-circle-dashed" aria-hidden /> {name} unpublished
      </span>
    )
  }
  return t.dirty ? (
    <span className="pill warn">
      <i className="ti ti-refresh" aria-hidden /> {name} changes to push
    </span>
  ) : (
    <span className="pill ok">
      <i className="ti ti-check" aria-hidden /> {name} live
    </span>
  )
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

export function Library({
  onOpen,
  onSettings,
}: {
  onOpen: (slug: string) => void
  onSettings?: () => void
}) {
  const [docs, setDocs] = useState<DocSummary[] | null>(null)
  const [error, setError] = useState('')
  const [ingesting, setIngesting] = useState(false)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [hits, setHits] = useState<{ slug: string; title: string; snip: string }[] | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.listDocuments().then(setDocs, (e) => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setHits(null)
      return
    }
    const t = setTimeout(() => {
      api.search(query).then(setHits, () => setHits([]))
    }, 300)
    return () => clearTimeout(t)
  }, [query])

  const onFile = (file: File | undefined) => {
    if (!file) return
    setIngesting(true)
    api.ingest(file).then(
      (resp) => {
        setIngesting(false)
        onOpen(resp.slug)
      },
      (e) => {
        setIngesting(false)
        alert(`Ingest failed: ${e}`)
      },
    )
  }

  if (error) return <p className="error">Backend unreachable: {error}</p>
  if (!docs) return <p className="muted">Loading library…</p>

  const visible = docs.filter((d) => matchesFilter(d, filter))

  return (
    <div className="shell">
      <div className="topnav">
        <span className="brand">
          <i className="ti ti-anvil" aria-hidden /> Notebook Forge
        </span>
        <button type="button" className="navlink active">
          Library
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
        <button
          type="button"
          className="add-doc"
          disabled={ingesting}
          onClick={() => fileInput.current?.click()}
        >
          <i className="ti ti-plus" aria-hidden /> {ingesting ? 'Ingesting…' : 'Add document'}
        </button>
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
        {visible.map((d) => (
          <button key={d.slug} className="doc-card" onClick={() => onOpen(d.slug)}>
            <div className="doc-thumb">
              <i className={`ti ${fileIcon(d.source_type)}`} aria-hidden />
            </div>
            <div className="doc-main">
              <p className="doc-title">
                {d.title}
                {d.year_display ? ` · ${d.year_display}` : ''}
              </p>
              <p className="doc-meta">
                {d.source_type} · {d.figures} images · {d.sketched} sketched
                {d.pending_review > 0 ? ` · ${d.pending_review} awaiting review` : ''}
                {d.updated_at ? ` · updated ${timeAgo(d.updated_at)}` : ''}
              </p>
            </div>
            <span className="badges">
              {d.targets
                .filter((t) => t.target !== 'local-folder')
                .map((t) => (
                  <TargetPill key={t.target} t={t} />
                ))}
            </span>
          </button>
        ))}
        {visible.length === 0 && <p className="muted">No documents match this filter.</p>}
      </div>
    </div>
  )
}
