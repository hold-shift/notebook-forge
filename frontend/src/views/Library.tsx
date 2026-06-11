import { useEffect, useState } from 'react'
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

export function Library({ onOpen }: { onOpen: (slug: string) => void }) {
  const [docs, setDocs] = useState<DocSummary[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.listDocuments().then(setDocs, (e) => setError(String(e)))
  }, [])

  if (error) return <p className="error">Backend unreachable: {error}</p>
  if (!docs) return <p className="muted">Loading library…</p>

  return (
    <div className="library">
      <p className="overline">The Skitch Family Archive · Notebook Forge</p>
      <h1>Library</h1>
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
