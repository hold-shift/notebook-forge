import type { DocSummary, GroupInfo } from '../api'

export type GroupBy = 'group' | 'none' | 'status' | 'format'
export type SortMode = 'manual' | 'date_range' | 'title_az' | 'last_updated' | 'attention'

export interface Bucket {
  key: string
  label: string
  color?: string
  groupId?: number | null
  docs: DocSummary[]
}

export function startYear(slug: string): number {
  const m = slug.match(/^(\d+)/)
  return m ? parseInt(m[1], 10) : 9999
}

export function needsAttention(d: DocSummary): boolean {
  return (
    d.pending_review > 0 ||
    d.date_confirmed === false ||
    d.targets.some((t) => t.dirty)
  )
}

export function sortDocs(docs: DocSummary[], sort: SortMode): DocSummary[] {
  const copy = [...docs]
  switch (sort) {
    case 'manual':
      copy.sort((a, b) => a.group_position - b.group_position || a.slug.localeCompare(b.slug))
      break
    case 'date_range':
      copy.sort((a, b) => startYear(a.slug) - startYear(b.slug) || a.slug.localeCompare(b.slug))
      break
    case 'title_az':
      copy.sort((a, b) => a.title.toLocaleLowerCase().localeCompare(b.title.toLocaleLowerCase()))
      break
    case 'last_updated':
      copy.sort((a, b) => {
        if (!a.updated_at) return 1
        if (!b.updated_at) return -1
        return b.updated_at.localeCompare(a.updated_at)
      })
      break
    case 'attention':
      copy.sort((a, b) => {
        const aa = needsAttention(a)
        const ba = needsAttention(b)
        if (aa !== ba) return aa ? -1 : 1
        if (aa && ba) return b.pending_review - a.pending_review || a.title.toLocaleLowerCase().localeCompare(b.title.toLocaleLowerCase())
        return startYear(a.slug) - startYear(b.slug) || a.slug.localeCompare(b.slug)
      })
      break
  }
  return copy
}

export function effectiveSort(groupBy: GroupBy, sort: SortMode): SortMode {
  return sort === 'manual' && groupBy !== 'group' ? 'date_range' : sort
}

export function bucketDocs(docs: DocSummary[], groupBy: GroupBy, groups: GroupInfo[]): Bucket[] {
  if (groupBy === 'none') {
    return [{ key: 'all', label: '', docs }]
  }
  if (groupBy === 'group') {
    const buckets: Bucket[] = groups.map((g) => ({
      key: `group-${g.id}`,
      label: g.name,
      color: g.color,
      groupId: g.id,
      docs: docs.filter((d) => d.group_id === g.id),
    }))
    buckets.push({
      key: 'ungrouped',
      label: 'Ungrouped',
      groupId: null,
      docs: docs.filter((d) => d.group_id == null),
    })
    return buckets
  }
  if (groupBy === 'status') {
    const dirty = docs.filter((d) => d.targets.some((t) => t.dirty))
    const neverPublished = docs.filter(
      (d) => !d.targets.some((t) => t.dirty) && !d.targets.some((t) => t.status === 'PUBLISHED'),
    )
    const clean = docs.filter(
      (d) => !d.targets.some((t) => t.dirty) && d.targets.some((t) => t.status === 'PUBLISHED'),
    )
    return [
      dirty.length ? { key: 'dirty', label: 'Changes to push', docs: dirty } : null,
      neverPublished.length ? { key: 'never', label: 'Never published', docs: neverPublished } : null,
      clean.length ? { key: 'clean', label: 'Published · clean', docs: clean } : null,
    ].filter(Boolean) as Bucket[]
  }
  // format
  const byFormat = new Map<string, DocSummary[]>()
  for (const d of docs) {
    const k = d.source_type || 'HTML'
    if (!byFormat.has(k)) byFormat.set(k, [])
    byFormat.get(k)!.push(d)
  }
  return [...byFormat.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, ds]) => ({ key: `format-${k}`, label: k, docs: ds }))
}
