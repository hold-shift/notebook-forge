export interface TargetState {
  target: string
  kind: string
  status: string
  dirty: boolean
  published_at: string | null
  snapshot_id: number | null
}

export interface DocSummary {
  slug: string
  title: string
  year_display: string
  standfirst: string
  updated_at: string | null
  targets: TargetState[]
}

export interface DocDetail {
  slug: string
  title: string
  blocks: unknown[]
  meta: Record<string, unknown>
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
  generateSketch: (slug: string, blockId: string, prompt?: string) =>
    fetch(`/api/documents/${slug}/figures/${blockId}/generate-sketch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prompt ?? null }),
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
  ingest: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/ingest', { method: 'POST', body: form }).then((r) =>
      json<{ ok: boolean; slug: string; title: string; detected_date: string; figures: number }>(r),
    )
  },
}
