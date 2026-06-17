import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EditorErrorBoundary } from '../views/Editor'

function Boom(): never {
  throw new Error('menu blew up')
}

describe('EditorErrorBoundary', () => {
  it('contains a child crash instead of letting it blank the app', () => {
    // React logs the caught error; silence it for a clean test run.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <EditorErrorBoundary>
        <Boom />
      </EditorErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/menu blew up/)).toBeInTheDocument()
    spy.mockRestore()
  })

  it('renders children normally when nothing throws', () => {
    render(
      <EditorErrorBoundary>
        <p>all good</p>
      </EditorErrorBoundary>,
    )
    expect(screen.getByText('all good')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('recovers when the error is dismissed', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    function Maybe({ crash }: { crash: boolean }) {
      if (crash) throw new Error('boom')
      return <p>recovered</p>
    }
    const { rerender } = render(
      <EditorErrorBoundary>
        <Maybe crash />
      </EditorErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    rerender(
      <EditorErrorBoundary>
        <Maybe crash={false} />
      </EditorErrorBoundary>,
    )
    fireEvent.click(screen.getByText('Dismiss'))
    expect(screen.getByText('recovered')).toBeInTheDocument()
    spy.mockRestore()
  })
})
