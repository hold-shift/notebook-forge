import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { InfoTip } from '../../ui/InfoTip'

describe('InfoTip', () => {
  it('hides its content until opened', () => {
    render(<InfoTip>Explains the feature.</InfoTip>)
    expect(screen.queryByText('Explains the feature.')).toBeNull()
  })

  it('reveals content on click and toggles it off again', () => {
    render(<InfoTip>Explains the feature.</InfoTip>)
    const trigger = screen.getByRole('button', { name: 'More information' })
    fireEvent.click(trigger)
    expect(screen.getByText('Explains the feature.')).toBeTruthy()
    fireEvent.click(trigger)
    expect(screen.queryByText('Explains the feature.')).toBeNull()
  })

  it('reveals content on hover and hides on leave', () => {
    const { container } = render(<InfoTip>Hover help.</InfoTip>)
    const wrapper = container.querySelector('.infotip') as HTMLElement
    fireEvent.mouseEnter(wrapper)
    expect(screen.getByText('Hover help.')).toBeTruthy()
    fireEvent.mouseLeave(wrapper)
    expect(screen.queryByText('Hover help.')).toBeNull()
  })

  it('uses a custom aria-label when provided', () => {
    render(<InfoTip label="About slugs">…</InfoTip>)
    expect(screen.getByRole('button', { name: 'About slugs' })).toBeTruthy()
  })
})
