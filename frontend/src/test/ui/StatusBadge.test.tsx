import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from '../../ui/StatusBadge'

describe('StatusBadge', () => {
  it('live variant shows pine dot and Live label', () => {
    render(<StatusBadge variant="live" />)
    const badge = screen.getByText('Live').parentElement!
    const dot = badge.querySelector('[data-badge-dot]') as HTMLElement
    expect(dot.style.background).toContain('var(--color-pine)')
  })

  it('changes variant shows tan dot', () => {
    render(<StatusBadge variant="changes" />)
    const badge = screen.getByText('Changes').parentElement!
    const dot = badge.querySelector('[data-badge-dot]') as HTMLElement
    expect(dot.style.background).toContain('var(--color-tan)')
  })

  it('unpublished variant shows tertiary dot', () => {
    render(<StatusBadge variant="unpublished" />)
    const dot = screen.getByText('Unpublished').parentElement!.querySelector('[data-badge-dot]') as HTMLElement
    expect(dot.style.background).toContain('var(--color-text-tertiary)')
  })

  it('polished variant shows pine dot', () => {
    render(<StatusBadge variant="polished" />)
    const dot = screen.getByText('Polished').parentElement!.querySelector('[data-badge-dot]') as HTMLElement
    expect(dot.style.background).toContain('var(--color-pine)')
  })

  it('flagged variant shows amber dot', () => {
    render(<StatusBadge variant="flagged" />)
    const dot = screen.getByText('Flagged').parentElement!.querySelector('[data-badge-dot]') as HTMLElement
    expect(dot.style.background).toContain('var(--color-amber)')
  })

  it('never-run variant shows tertiary dot', () => {
    render(<StatusBadge variant="never-run" />)
    const dot = screen.getByText('Not polished').parentElement!.querySelector('[data-badge-dot]') as HTMLElement
    expect(dot.style.background).toContain('var(--color-text-tertiary)')
  })

  it('stale variant shows tan dot', () => {
    render(<StatusBadge variant="stale" />)
    const dot = screen.getByText('Stale').parentElement!.querySelector('[data-badge-dot]') as HTMLElement
    expect(dot.style.background).toContain('var(--color-tan)')
  })

  it('label override works', () => {
    render(<StatusBadge variant="live" label="Custom label" />)
    expect(screen.getByText('Custom label')).toBeTruthy()
  })

  it('renders with data-badge-variant attribute', () => {
    render(<StatusBadge variant="changes" />)
    const el = document.querySelector('[data-badge-variant="changes"]')
    expect(el).toBeTruthy()
  })
})
