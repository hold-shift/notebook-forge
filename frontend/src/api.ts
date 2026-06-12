export interface TargetState {
  target: string
  kind: string
  status: string
  dirty: boolean
  published_at: string | null
  snapshot_id: number | null
  /** Where this target's published output lives (live page / exported file
   * served at /site/ / Google Doc). Absent until first published. */
  url: string | null
}

export interface DocSummary {
  slug: string
  title: string
  year_display: string
  standfirst: string
  updated_at: string | null
  source_type: string
  figures: number
  sketched: number
  pending_review: number
  targets: TargetState[]
}

export interface DocDetail {
  slug: string
  title: string
  blocks: unknown[]
  meta: Record<string, unknown>
  targets: TargetState[]
}

export interface DiffSegment {
  op: 'equal' | 'delete' | 'insert' | 'replace'
  a: string
  b: string
}

export interface FlaggedBlock {
  block_id: string
  original: string
  polished: string
  summary: string
  polished_content: unknown[]
  diff: DiffSegment[]
}

export interface PolishReport {
  blocks_polished: number
  blocks_unchanged: number
  flagged: FlaggedBlock[]
  failed_chunks: string[]
  model: string
  targets: TargetState[]
}

export interface ChangeEntry {
  id: number
  kind: string
  summary: string
  detail: Record<string, unknown>
  created_at: string | null
}

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`)
  return resp.json() as Promise<T>
}

export const api = {
  listDocuments: () => fetch('/api/documents').then((r) => json<DocSummary[]>(r)),
  getDocument: (slug: string) =>
    fetch(`/api/documents/${slug}`).then((r) => json<DocDetail>(r)),
  saveBlocks: (slug: string, blocks: unknown[], summary = 'edited in editor') =>
    fetch(`/api/documents/${slug}/blocks`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks, summary }),
    }).then((r) => json<{ ok: boolean; targets: TargetState[] }>(r)),
  changes: (slug: string) =>
    fetch(`/api/documents/${slug}/changes`).then((r) => json<ChangeEntry[]>(r)),
  publish: (slug: string, target: string) =>
    fetch(`/api/documents/${slug}/publish/${target}`, { method: 'POST' }).then((r) =>
      json<{ ok: boolean; targets: TargetState[] }>(r),
    ),
  unpublish: (slug: string, target: string) =>
    fetch(`/api/documents/${slug}/publish/${target}`, { method: 'DELETE' }).then((r) =>
      json<{ ok: boolean; targets: TargetState[] }>(r),
    ),
  deleteDocument: (slug: string) =>
    fetch(`/api/documents/${slug}`, { method: 'DELETE' }).then((r) =>
      json<{ ok: boolean; deleted: string }>(r),
    ),
  generateSketch: (slug: string, blockId: string, prompt?: string, force = false) =>
    fetch(`/api/documents/${slug}/figures/${blockId}/generate-sketch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prompt ?? null, force }),
    }).then((r) =>
      json<{ ok: boolean; detail: { sketchAssetId: string; face_gate: string } }>(r),
    ),
  assetUrl: (sha: string) => (sha ? `/api/assets/${sha}` : ''),
  saveMeta: (slug: string, blocks: unknown[], meta: Record<string, unknown>, summary: string) =>
    fetch(`/api/documents/${slug}/blocks`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocks, meta, summary }),
    }).then((r) => json<{ ok: boolean; targets: TargetState[] }>(r)),
  renameSlug: (slug: string, newSlug: string) =>
    fetch(`/api/documents/${slug}/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: newSlug }),
    }).then((r) => json<{ ok: boolean; slug: string }>(r)),
  reingest: (slug: string) =>
    fetch(`/api/documents/${slug}/reingest`, { method: 'POST' }).then((r) =>
      json<{
        ok: boolean
        detail: { blocks: number; figures: number; figures_matched: number; figures_new: number }
      }>(r),
    ),
  search: (q: string) =>
    fetch(`/api/search?q=${encodeURIComponent(q)}`).then((r) =>
      json<{ slug: string; title: string; snip: string }[]>(r),
    ),
  snapshots: (slug: string) =>
    fetch(`/api/documents/${slug}/snapshots`).then((r) =>
      json<{ id: number; note: string; created_at: string | null }[]>(r),
    ),
  rollback: (slug: string, snapshotId: number) =>
    fetch(`/api/documents/${slug}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ snapshot_id: snapshotId }),
    }).then((r) => json<{ ok: boolean; targets: TargetState[] }>(r)),
  polish: (slug: string) =>
    fetch(`/api/documents/${slug}/polish`, { method: 'POST' }).then((r) =>
      json<PolishReport>(r),
    ),
  polishProgress: (slug: string) =>
    fetch(`/api/documents/${slug}/polish/progress`, { cache: 'no-store' }).then((r) =>
      json<{ running: boolean; done: number; total: number; failed: number }>(r),
    ),
  savePolishSettings: (polish: { model: string; extra_rules: string }) =>
    fetch('/api/settings/polish', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(polish),
    }).then((r) => json<{ ok: boolean }>(r)),
  settings: () =>
    fetch('/api/settings').then((r) =>
      json<{
        homepage: { title?: string; welcome?: string; dedication?: string }
        sketch: { model: string; default_prompt: string; face_gate: string }
        polish: { model: string; extra_rules: string }
        secrets: Record<string, boolean>
        targets: { name: string; kind: string }[]
      }>(r),
    ),
  saveSketchSettings: (sketch: { model: string; default_prompt: string; face_gate: string }) =>
    fetch('/api/settings/sketch', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sketch),
    }).then((r) => json<{ ok: boolean }>(r)),
  saveHomepage: (homepage: { title: string; welcome: string; dedication: string }) =>
    fetch('/api/settings/homepage', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(homepage),
    }).then((r) => json<{ ok: boolean }>(r)),
  rebuildIndex: (target: string) =>
    fetch(`/api/rebuild-index/${target}`, { method: 'POST' }).then((r) =>
      json<{ ok: boolean; detail: { commit: string | null } }>(r),
    ),
  ingest: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/ingest', { method: 'POST', body: form }).then((r) =>
      json<{ ok: boolean; slug: string; title: string; detected_date: string; figures: number }>(r),
    )
  },
}
