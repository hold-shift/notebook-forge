import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Button } from '../../ui/Button'

describe('Button', () => {
  it('renders children', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByText('Click me')).toBeTruthy()
  })

  it('primary variant has ink background', () => {
    render(<Button variant="primary">Save</Button>)
    const btn = screen.getByText('Save')
    expect(btn.style.background).toContain('var(--color-text-primary)')
    expect(btn.style.color).toContain('var(--color-background-primary)')
  })

  it('secondary variant has transparent background', () => {
    render(<Button variant="secondary">Cancel</Button>)
    const btn = screen.getByText('Cancel')
    expect(btn.style.background).toBe('transparent')
  })

  it('danger variant has danger fg color', () => {
    render(<Button variant="danger">Delete</Button>)
    const btn = screen.getByText('Delete')
    expect(btn.style.color).toContain('var(--pill-danger-fg)')
  })

  it('ghost variant has no border and muted text', () => {
    render(<Button variant="ghost">Back</Button>)
    const btn = screen.getByText('Back')
    expect(btn.style.background).toBe('transparent')
    expect(btn.style.color).toContain('var(--color-text-secondary)')
  })

  it('sm size has smaller padding', () => {
    render(<Button size="sm">Small</Button>)
    const btn = screen.getByText('Small')
    expect(btn.style.padding).toBe('3px 10px')
    expect(btn.style.fontSize).toBe('12px')
  })

  it('disabled state works', () => {
    render(<Button disabled>Disabled</Button>)
    const btn = screen.getByText('Disabled') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.style.opacity).toBe('0.55')
    expect(btn.style.cursor).toBe('default')
  })
})
