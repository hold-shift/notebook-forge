/** M5 gate: forgeNarrative block component + schema smoke tests. */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ForgeNarrativeView } from '../forge/ForgeNarrativeView'
import { forgeSchema } from '../forge/schema'

describe('ForgeNarrativeView', () => {
  it('renders data-testid="forge-narrative" with class forge-narrative', () => {
    render(<ForgeNarrativeView contentRef={null} />)
    const el = screen.getByTestId('forge-narrative')
    expect(el).toHaveClass('forge-narrative')
  })

  it('contains an inner .forge-narrative-text element', () => {
    render(<ForgeNarrativeView contentRef={null} />)
    const inner = document.querySelector('.forge-narrative-text')
    expect(inner).not.toBeNull()
    expect(inner?.tagName.toLowerCase()).toBe('p')
  })
})

describe('forge schema — forgeNarrative', () => {
  it('registers forgeNarrative in blockSpecs alongside existing blocks', () => {
    expect(Object.keys(forgeSchema.blockSpecs)).toEqual(
      expect.arrayContaining([
        'paragraph', 'heading', 'forgeImage', 'forgeFootnote',
        'forgeDedication', 'forgeDocGroup', 'forgeNarrative',
      ]),
    )
  })

  it('forgeNarrative has inline content and no props', () => {
    const spec = forgeSchema.blockSpecs.forgeNarrative
    expect(spec.config.content).toBe('inline')
    expect(Object.keys(spec.config.propSchema)).toHaveLength(0)
  })
})
