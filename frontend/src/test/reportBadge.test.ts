import { describe, expect, it } from 'vitest'
import { computeReportBadge } from '../views/Editor'
import type { ReportState } from '../api'

function makeReport(overrides: Partial<ReportState> = {}): ReportState {
  return {
    exists: true,
    status: 'generated',
    stale: false,
    model: 'gemini-3.5-flash',
    source_name: '1934-1945_junior',
    ...overrides,
  }
}

describe('computeReportBadge', () => {
  it('returns loading when report is loading', () => {
    expect(computeReportBadge('loading')).toBe('loading')
  })

  it('returns never-run when null or not yet generated', () => {
    expect(computeReportBadge(null)).toEqual({ variant: 'never-run', label: 'Not generated' })
    expect(computeReportBadge(makeReport({ exists: false }))).toEqual({
      variant: 'never-run',
      label: 'Not generated',
    })
  })

  it('returns generated when fresh and successful', () => {
    expect(computeReportBadge(makeReport())).toEqual({ variant: 'polished', label: 'Generated' })
  })

  it('returns stale when the document has diverged', () => {
    expect(computeReportBadge(makeReport({ stale: true }))).toEqual({
      variant: 'stale',
      label: 'Stale',
    })
  })

  it('returns failed when generation failed (regardless of staleness)', () => {
    expect(computeReportBadge(makeReport({ status: 'failed' }))).toEqual({
      variant: 'flagged',
      label: 'Failed',
    })
    expect(computeReportBadge(makeReport({ status: 'failed', stale: true }))).toEqual({
      variant: 'flagged',
      label: 'Failed',
    })
  })
})
