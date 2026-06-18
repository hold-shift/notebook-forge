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

export interface GroupMember {
  slug: string
  title: string
  year_display: string
  standfirst: string
  description: string
  word_count: number
  group_position: number
}

export interface GroupInfo {
  id: number
  name: string
  color: string
  sort_order: number
  members: GroupMember[]
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
  group_id: number | null
  group_position: number
  date_confirmed: boolean
  targets: TargetState[]
  report: ReportState
}

export interface DocDetail {
  slug: string
  title: string
  kind: string
  blocks: unknown[]
  meta: Record<string, unknown>
  targets: TargetState[]
  updated_at?: string | null
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

export interface PolishLastRun {
  at: string
  model: string
  blocks_changed: number
  blocks_unchanged: number
  flagged_ids: string[]
  chunks: number
  failed_chunks: number
}

export interface ChangeEntry {
  id: number
  kind: string
  summary: string
  detail: Record<string, unknown>
  created_at: string | null
}

export interface ReportState {
  exists: boolean
  status: string
  stale: boolean
  /** True when the current generation has not yet been pushed to Drive
   * (never pushed, or regenerated since the last push). */
  needs_push: boolean
  model?: string
  source_name?: string
  generated_at?: string | null
  pushed_at?: string | null
  drive_file_id?: string | null
  tracks?: { people: number; geo: number; glossary: number; chronology: number }
}

export interface ReportProgress {
  running: boolean
  done: number
  total: number
  failed: number
}

export interface MasterStatus {
  documents: number
  rows: number
  by_track: { people: number; geo: number; glossary: number; chronology: number }
  built_at: string | null
  pushed_at: string | null
  drive_file_ids: Record<string, string>
}

export interface BannerSlot {
  era: string
  caption: string
  notebooklm_adapted: boolean
  /** Asset SHA of the uploaded image, or null for the placeholder. */
  image_asset_id: string | null
  /** Resolved URL for thumbnail display ('' when no image). */
  image_url: string
}

export interface HomepageSettings {
  subject_name: string
  subject_birth: string
  subject_place: string
  tagline: string
  dedication: string
  notebooklm_cta_title: string
  notebooklm_cta_subtitle: string
  notebooklm_url: string
  about_archive: string
  signoff: string
  about_notebooklm: string
  notebooklm_features: string[]
  banner_slots: BannerSlot[]
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
      json<{ ok: boolean; targets: TargetState[]; detail?: { warnings?: string[] } }>(r),
    ),
  unpublish: (slug: string, target: string) =>
    fetch(`/api/documents/${slug}/publish/${target}`, { method: 'DELETE' }).then((r) =>
      json<{ ok: boolean; targets: TargetState[] }>(r),
    ),
  deleteDocument: (slug: string) =>
    fetch(`/api/documents/${slug}`, { method: 'DELETE' }).then((r) =>
      json<{ ok: boolean; deleted: string }>(r),
    ),
  uploadFigureImage: (slug: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`/api/documents/${slug}/figures/upload-image`, {
      method: 'POST',
      body: form,
    }).then((r) => json<{ assetId: string }>(r))
  },
  uploadFigureSketch: (slug: string, blockId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`/api/documents/${slug}/figures/${blockId}/upload-sketch`, {
      method: 'POST',
      body: form,
    }).then((r) => json<{ ok: boolean; detail: { sketchAssetId: string } }>(r))
  },
  generateCaption: (slug: string, blockId: string) =>
    fetch(`/api/documents/${slug}/figures/${blockId}/generate-caption`, { method: 'POST' }).then(
      (r) => json<{ caption: string }>(r),
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
  polishLast: (slug: string) =>
    fetch(`/api/documents/${slug}/polish/last`).then((r) =>
      json<PolishLastRun | null>(r),
    ),
  polishResolveFlags: (slug: string) =>
    fetch(`/api/documents/${slug}/polish/resolve-flags`, { method: 'POST' }).then((r) =>
      json<PolishLastRun | null>(r),
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
  generateReport: (slug: string) =>
    fetch(`/api/documents/${slug}/report/generate`, { method: 'POST' }).then((r) =>
      json<{ ok: boolean; detail: Record<string, unknown>; report: ReportState }>(r),
    ),
  reportProgress: (slug: string) =>
    fetch(`/api/documents/${slug}/report/progress`, { cache: 'no-store' }).then((r) =>
      json<ReportProgress>(r),
    ),
  report: (slug: string) =>
    fetch(`/api/documents/${slug}/report`).then((r) =>
      json<ReportState & { body_md: string }>(r),
    ),
  pushReport: (slug: string) =>
    fetch(`/api/documents/${slug}/report/push`, { method: 'POST' }).then((r) =>
      json<{ ok: boolean; detail: Record<string, unknown>; report: ReportState }>(r),
    ),
  masterStatus: () => fetch('/api/reports/master').then((r) => json<MasterStatus>(r)),
  generateMaster: () =>
    fetch('/api/reports/master/generate', { method: 'POST' }).then((r) =>
      json<{ ok: boolean; master: MasterStatus; pushed: Record<string, unknown> }>(r),
    ),
  saveReportSettings: (reports: { model: string; rules: string }) =>
    fetch('/api/settings/reports', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reports),
    }).then((r) => json<{ ok: boolean }>(r)),
  settings: () =>
    fetch('/api/settings').then((r) =>
      json<{
        sketch: { model: string; default_prompt: string; face_gate: string }
        polish: { model: string; extra_rules: string }
        reports: { model: string; rules: string }
        narrative: { label: string }
        footer: { notice: string; license_label: string; license_url: string }
        homepage: HomepageSettings
        secrets: Record<string, boolean>
      }>(r),
    ),
  saveHomepageSettings: (body: HomepageSettings) =>
    fetch('/api/settings/homepage', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => json<{ ok: boolean; homepage: HomepageSettings }>(r)),
  uploadBannerImage: (slotIndex: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`/api/homepage/banner-image/${slotIndex}`, {
      method: 'POST',
      body: form,
    }).then((r) => json<{ image_url: string; image_asset_id: string }>(r))
  },
  saveNarrativeSettings: (body: { label: string }) =>
    fetch('/api/settings/narrative', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => json<{ ok: boolean }>(r)),
  saveFooterSettings: (body: { notice: string; license_label: string; license_url: string }) =>
    fetch('/api/settings/footer', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => json<{ ok: boolean }>(r)),
  saveSketchSettings: (sketch: { model: string; default_prompt: string; face_gate: string }) =>
    fetch('/api/settings/sketch', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sketch),
    }).then((r) => json<{ ok: boolean }>(r)),
  generateAllSketches: (slug: string, batchFaceGate: 'warn' | 'block' = 'warn') =>
    fetch(`/api/documents/${slug}/figures/generate-all-sketches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_face_gate: batchFaceGate }),
    }).then((r) => json<{ job_id: string; eligible: number }>(r)),
  sketchJobStatus: (slug: string, jobId: string) =>
    fetch(
      `/api/documents/${slug}/figures/generate-all-sketches/status?job_id=${encodeURIComponent(jobId)}`,
      { cache: 'no-store' },
    ).then((r) =>
      json<{
        status: 'running' | 'done' | 'failed'
        done: number
        total: number
        failed: number
        results: { block_id: string; ok: boolean; face_gate: string; error?: string }[]
      }>(r),
    ),
  ingest: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/ingest', { method: 'POST', body: form }).then((r) =>
      json<{ ok: boolean; slug: string; title: string; detected_date: string; figures: number }>(r),
    )
  },
  createDocument: (title = 'Untitled') =>
    fetch('/api/documents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }).then((r) => json<{ ok: boolean; slug: string; title: string }>(r)),
  groups: () => fetch('/api/groups').then((r) => json<GroupInfo[]>(r)),
  createGroup: (name: string, color: string) =>
    fetch('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, color }),
    }).then((r) => json<{ id: number; name: string; color: string; sort_order: number }>(r)),
  updateGroup: (id: number, patch: { name?: string; color?: string }) =>
    fetch(`/api/groups/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).then((r) => json<{ id: number; name: string; color: string; sort_order: number }>(r)),
  reorderGroups: (ids: number[]) =>
    fetch('/api/groups/order', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }).then((r) => json<{ ok: boolean }>(r)),
  deleteGroup: (id: number) =>
    fetch(`/api/groups/${id}`, { method: 'DELETE' }).then((r) =>
      json<{ ok: boolean; moved: number }>(r),
    ),
  setDocumentGroup: (slug: string, groupId: number | null) =>
    fetch(`/api/documents/${slug}/group`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: groupId }),
    }).then((r) => json<{ ok: boolean; group_id: number | null; group_position: number }>(r)),
  setPositions: (groupId: number | null, slugs: string[]) =>
    fetch('/api/documents/positions', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: groupId, slugs }),
    }).then((r) => json<{ ok: boolean }>(r)),
}
