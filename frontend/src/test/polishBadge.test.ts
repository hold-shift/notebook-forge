import { describe, expect, it } from 'vitest'
import { computePolishBadge } from '../views/Editor'
import type { PolishLastRun } from '../api'

function makeRun(overrides: Partial<PolishLastRun> = {}): PolishLastRun {
  return {
    at: '2026-06-14T10:00:00',
    model: 'gemini-2.5-flash',
    blocks_changed: 2,
    blocks_unchanged: 5,
    flagged_ids: [],
    chunks: 1,
    failed_chunks: 0,
    ...overrides,
  }
}

describe('computePolishBadge', () => {
  it('returns never-run when polishLast is null', () => {
    expect(computePolishBadge(null, null)).toBe('never-run')
    expect(computePolishBadge(null, '2026-06-14T09:00:00')).toBe('never-run')
  })

  it('returns loading when polishLast is loading', () => {
    expect(computePolishBadge('loading', null)).toBe('loading')
  })

  it('returns polished when at > updated_at and no flags', () => {
    const run = makeRun({ at: '2026-06-14T11:00:00' })
    expect(computePolishBadge(run, '2026-06-14T10:00:00')).toBe('polished')
  })

  it('returns polished when updated_at is null and no flags', () => {
    const run = makeRun({ at: '2026-06-14T10:00:00' })
    expect(computePolishBadge(run, null)).toBe('polished')
  })

  it('returns stale when at <= updated_at', () => {
    const run = makeRun({ at: '2026-06-14T09:00:00' })
    expect(computePolishBadge(run, '2026-06-14T10:00:00')).toBe('stale')
  })

  it('returns stale when at == updated_at', () => {
    const run = makeRun({ at: '2026-06-14T10:00:00' })
    expect(computePolishBadge(run, '2026-06-14T10:00:00')).toBe('stale')
  })

  it('returns flagged when flagged_ids is non-empty (regardless of at/updated_at)', () => {
    const run = makeRun({ at: '2026-06-14T11:00:00', flagged_ids: ['block-1', 'block-2'] })
    // Even if run is newer than updated_at, flagged wins
    expect(computePolishBadge(run, '2026-06-14T09:00:00')).toBe('flagged')
  })

  it('returns flagged when flagged_ids non-empty even if stale', () => {
    const run = makeRun({ at: '2026-06-14T08:00:00', flagged_ids: ['block-1'] })
    expect(computePolishBadge(run, '2026-06-14T10:00:00')).toBe('flagged')
  })
})
