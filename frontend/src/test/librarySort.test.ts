import { describe, expect, it } from 'vitest'
import type { DocSummary, GroupInfo } from '../api'
import {
  bucketDocs,
  effectiveSort,
  needsAttention,
  sortDocs,
  startYear,
} from '../lib/librarySort'

function doc(overrides: Partial<DocSummary> = {}): DocSummary {
  return {
    slug: 'test',
    title: 'Test',
    year_display: '',
    standfirst: '',
    updated_at: null,
    source_type: 'HTML',
    figures: 0,
    sketched: 0,
    pending_review: 0,
    group_id: null,
    group_position: 0,
    date_confirmed: true,
    targets: [],
    report: { exists: false, status: 'never-run', stale: false, needs_push: false },
    ...overrides,
  }
}

function group(overrides: Partial<GroupInfo> = {}): GroupInfo {
  return {
    id: 1,
    name: 'Group',
    color: '#9c5a3c',
    sort_order: 0,
    members: [],
    ...overrides,
  }
}

describe('startYear', () => {
  it('extracts leading integer', () => expect(startYear('1930-alpha')).toBe(1930))
  it('returns 9999 for non-numeric', () => expect(startYear('test-doc')).toBe(9999))
  it('handles homepage slug', () => expect(startYear('homepage')).toBe(9999))
})

describe('needsAttention', () => {
  it('true when pending_review > 0', () => {
    expect(needsAttention(doc({ pending_review: 1 }))).toBe(true)
  })
  it('true when date_confirmed false', () => {
    expect(needsAttention(doc({ date_confirmed: false }))).toBe(true)
  })
  it('true when dirty target', () => {
    expect(needsAttention(doc({ targets: [{ target: 't', kind: 'k', status: 'PUBLISHED', dirty: true, published_at: null, snapshot_id: null, url: null }] }))).toBe(true)
  })
  it('false when all good', () => {
    expect(needsAttention(doc())).toBe(false)
  })
})

describe('sortDocs', () => {
  const d1 = doc({ slug: '1930-alpha', title: 'Zebra', group_position: 1, updated_at: '2020-01-01T00:00:00' })
  const d2 = doc({ slug: '1940-beta', title: 'Apple', group_position: 0, updated_at: '2024-01-01T00:00:00' })

  it('manual: by group_position then slug', () => {
    const r = sortDocs([d1, d2], 'manual')
    expect(r[0].slug).toBe('1940-beta')
  })
  it('date_range: by startYear then slug', () => {
    const r = sortDocs([d2, d1], 'date_range')
    expect(r[0].slug).toBe('1930-alpha')
  })
  it('title_az', () => {
    const r = sortDocs([d1, d2], 'title_az')
    expect(r[0].title).toBe('Apple')
  })
  it('last_updated: newest first', () => {
    const r = sortDocs([d1, d2], 'last_updated')
    expect(r[0].slug).toBe('1940-beta')
  })
  it('attention: attention docs first', () => {
    const da = doc({ slug: '1930-alpha', pending_review: 1 })
    const db = doc({ slug: '1940-beta' })
    const r = sortDocs([db, da], 'attention')
    expect(r[0].slug).toBe('1930-alpha')
  })
})

describe('effectiveSort', () => {
  it('manual + group = manual', () => expect(effectiveSort('group', 'manual')).toBe('manual'))
  it('manual + none = date_range', () => expect(effectiveSort('none', 'manual')).toBe('date_range'))
  it('date_range + none = date_range', () => expect(effectiveSort('none', 'date_range')).toBe('date_range'))
})

describe('bucketDocs', () => {
  const g1 = group({ id: 1, name: 'G1', sort_order: 0 })
  const g2 = group({ id: 2, name: 'G2', sort_order: 1 })
  const d1 = doc({ slug: 'd1', group_id: 1 })
  const d2 = doc({ slug: 'd2', group_id: 2 })
  const d3 = doc({ slug: 'd3', group_id: null })

  it('group: one bucket per group + ungrouped last', () => {
    const b = bucketDocs([d1, d2, d3], 'group', [g1, g2])
    expect(b.length).toBe(3)
    expect(b[0].label).toBe('G1')
    expect(b[1].label).toBe('G2')
    expect(b[2].label).toBe('Ungrouped')
    expect(b[2].groupId).toBeNull()
  })
  it('group: empty groups still present', () => {
    const b = bucketDocs([d3], 'group', [g1, g2])
    expect(b.find((x) => x.label === 'G1')?.docs).toHaveLength(0)
  })
  it('none: single bucket', () => {
    const b = bucketDocs([d1, d2], 'none', [])
    expect(b.length).toBe(1)
  })
  it('status: omits empty buckets', () => {
    const clean = doc({ slug: 'c', targets: [{ target: 't', kind: 'k', status: 'PUBLISHED', dirty: false, published_at: null, snapshot_id: null, url: null }] })
    const b = bucketDocs([clean], 'status', [])
    expect(b.every((x) => x.docs.length > 0)).toBe(true)
    expect(b.find((x) => x.label === 'Never published')).toBeUndefined()
  })
  it('format: sorted A-Z, no empty buckets', () => {
    const pdf = doc({ slug: 'a', source_type: 'PDF' })
    const docx = doc({ slug: 'b', source_type: 'DOCX' })
    const b = bucketDocs([pdf, docx], 'format', [])
    expect(b[0].label).toBe('DOCX')
    expect(b[1].label).toBe('PDF')
  })
})
