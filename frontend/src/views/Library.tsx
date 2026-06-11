import { useEffect, useRef, useState } from 'react'
import { api, type DocSummary, type TargetState } from '../api'

function Badge({ t }: { t: TargetState }) {
  const cls = t.dirty ? 'badge dirty' : t.status === 'PUBLISHED' ? 'badge clean' : 'badge never'
  const label = t.dirty
    ? `${t.target}: pending changes`
    : t.status === 'PUBLISHED'
      ? `${t.target}: published · clean`
      : `${t.target}: never published`
  return <span className={cls}>{label}</span>
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

  return (
    <div className="library">
      <p className="overline">The Skitch Family Archive · Notebook Forge</p>
      <div className="library-head">
        <h1>Library</h1>
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
          {ingesting ? 'Ingesting…' : '+ Add document'}
        </button>
        {onSettings && (
          <button type="button" className="add-doc" onClick={onSettings}>
            ⚙ Settings
          </button>
        )}
      </div>
      <input
        className="library-search"
        placeholder="Search the memoirs…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {hits !== null && (
        <div className="search-hits">
          {hits.length === 0 && <p className="muted">No matches.</p>}
          {hits.map((h) => (
            <button key={h.slug} className="search-hit" onClick={() => onOpen(h.slug)}>
              <span className="doc-title">{h.title}</span>
              <span
                className="snip"
                dangerouslySetInnerHTML={{ __html: h.snip }}
              />
            </button>
          ))}
        </div>
      )}
      {docs.map((d) => (
        <button key={d.slug} className="doc-card" onClick={() => onOpen(d.slug)}>
          <span className="era">{d.year_display}</span>
          <span className="doc-title">{d.title}</span>
          <span className="standfirst">{d.standfirst}</span>
          <span className="badges">
            {d.targets.map((t) => (
              <Badge key={t.target} t={t} />
            ))}
          </span>
        </button>
      ))}
    </div>
  )
}
