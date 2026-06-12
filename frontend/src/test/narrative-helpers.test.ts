/** M5 gate: narrative helper purity tests (mirrors backend D3). */

import { describe, expect, it } from 'vitest'
import { stripItalic, addItalic } from '../forge/narrative'

const textRun = (text: string, styles: Record<string, unknown> = {}) => ({
  type: 'text',
  text,
  styles,
})

const linkRun = (text: string, styles: Record<string, unknown> = {}) => ({
  type: 'link',
  href: 'https://example.com',
  content: [textRun(text, styles)],
})

describe('stripItalic', () => {
  it('removes italic from a plain text run', () => {
    const runs = [textRun('Hello', { italic: true })]
    const result = stripItalic(runs)
    expect(result[0].styles.italic).toBeUndefined()
  })

  it('leaves other styles untouched', () => {
    const runs = [textRun('Bold italic', { bold: true, italic: true })]
    const result = stripItalic(runs)
    expect(result[0].styles.bold).toBe(true)
    expect(result[0].styles.italic).toBeUndefined()
  })

  it('strips italic recursively from link inner content', () => {
    const runs = [linkRun('link text', { italic: true })]
    const result = stripItalic(runs)
    expect(result[0].content[0].styles.italic).toBeUndefined()
  })

  it('leaves non-italic runs unchanged', () => {
    const runs = [textRun('plain', {})]
    const result = stripItalic(runs)
    expect(result[0].styles.italic).toBeUndefined()
    expect(result[0].text).toBe('plain')
  })
})

describe('addItalic', () => {
  it('adds italic to a plain text run', () => {
    const runs = [textRun('Hello', {})]
    const result = addItalic(runs)
    expect(result[0].styles.italic).toBe(true)
  })

  it('skips fnRef-styled runs', () => {
    const runs = [textRun('2', { fnRef: true })]
    const result = addItalic(runs)
    expect(result[0].styles.italic).toBeUndefined()
    expect(result[0].styles.fnRef).toBe(true)
  })

  it('adds italic recursively to link inner content', () => {
    const runs = [linkRun('link', {})]
    const result = addItalic(runs)
    expect(result[0].content[0].styles.italic).toBe(true)
  })
})

describe('addItalic(stripItalic(x)) round-trip', () => {
  it('restores italic on a fully italic paragraph', () => {
    const runs = [
      textRun('Looking back on those years', { italic: true }),
      textRun(' and more', { italic: true }),
    ]
    const stripped = stripItalic(runs)
    expect(stripped.every((r) => !r.styles?.italic)).toBe(true)
    const restored = addItalic(stripped)
    expect(restored.every((r) => r.styles?.italic === true)).toBe(true)
  })

  it('preserves fnRef runs through round-trip (not made italic)', () => {
    const runs = [textRun('note text', { italic: true }), textRun('1', { fnRef: true })]
    const result = addItalic(stripItalic(runs))
    expect(result[0].styles.italic).toBe(true)
    expect(result[1].styles.italic).toBeUndefined()
    expect(result[1].styles.fnRef).toBe(true)
  })
})
