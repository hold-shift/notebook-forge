import { describe, expect, it } from 'vitest'
import {
  buildRenumberMap,
  collectNoteMarkers,
  nextTempMarker,
  removeFootnote,
  renumberFootnotes,
} from '../forge/footnotes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Block = any

const ref = (n: string) => ({ type: 'text', text: n, styles: { fnRef: true } })
const txt = (t: string) => ({ type: 'text', text: t, styles: {} })

function para(id: string, ...runs: object[]): Block {
  return { id, type: 'paragraph', props: {}, content: runs, children: [] }
}
function note(id: string, marker: string, text = `note ${marker}`): Block {
  return { id, type: 'forgeFootnote', props: { marker, text }, content: undefined, children: [] }
}

/** A doc with three footnotes in order: 1, 2, 3. */
function tripleDoc(): Block[] {
  return [
    para('p1', txt('First'), ref('1'), txt('.')),
    note('n1', '1'),
    para('p2', txt('Second'), ref('2'), txt('.')),
    note('n2', '2'),
    para('p3', txt('Third'), ref('3'), txt('.')),
    note('n3', '3'),
  ]
}

describe('renumberFootnotes', () => {
  it('is a no-op on an already-sequential doc', () => {
    const { changed } = renumberFootnotes(tripleDoc())
    expect(changed).toBe(false)
  })

  it('closes the gap after a middle footnote is removed', () => {
    // Remove footnote 2 by hand, leaving refs/notes 1 and 3.
    const doc: Block[] = [
      para('p1', txt('First'), ref('1'), txt('.')),
      note('n1', '1'),
      para('p3', txt('Third'), ref('3'), txt('.')),
      note('n3', '3'),
    ]
    const { blocks, changed } = renumberFootnotes(doc)
    expect(changed).toBe(true)
    // 3 becomes 2 (both the inline ref and the note marker).
    expect(collectNoteMarkers(blocks)).toEqual(['1', '2'])
    const refRun = blocks[2].content.find((r: Block) => r.styles?.fnRef)
    expect(refRun.text).toBe('2')
  })

  it('orders by first reference, not by note position', () => {
    // References appear 3, 1, 2 in prose → notes resequence to that order.
    const doc: Block[] = [
      para('a', ref('3')),
      para('b', ref('1')),
      para('c', ref('2')),
      note('n3', '3'),
      note('n1', '1'),
      note('n2', '2'),
    ]
    const map = buildRenumberMap(doc)
    expect(map.get('3')).toBe('1')
    expect(map.get('1')).toBe('2')
    expect(map.get('2')).toBe('3')
  })

  it('leaves an orphan reference (no matching note) untouched', () => {
    const doc: Block[] = [
      para('p1', txt('x'), ref('1'), txt(' '), ref('9')),
      note('n1', '1'),
    ]
    const { blocks } = renumberFootnotes(doc)
    const markers = blocks[0].content.filter((r: Block) => r.styles?.fnRef).map((r: Block) => r.text)
    expect(markers).toEqual(['1', '9']) // 9 has no note → preserved
  })
})

describe('removeFootnote', () => {
  it('drops the note and its inline reference, then renumbers', () => {
    const blocks = removeFootnote(tripleDoc(), '2')
    // Note 2 is gone; 3 collapses to 2.
    expect(collectNoteMarkers(blocks)).toEqual(['1', '2'])
    // No paragraph still carries a fnRef '2' pointing at the deleted note's
    // old number — p2's ref was removed entirely.
    const allRefs = blocks
      .flatMap((b: Block) => b.content ?? [])
      .filter((r: Block) => r?.styles?.fnRef)
      .map((r: Block) => r.text)
    expect(allRefs.sort()).toEqual(['1', '2'])
    // The orphaned paragraph text survives.
    expect(blocks.some((b: Block) => b.type === 'paragraph')).toBe(true)
  })
})

describe('nextTempMarker', () => {
  it('returns one past the highest existing marker', () => {
    expect(nextTempMarker(tripleDoc())).toBe('4')
    expect(nextTempMarker([])).toBe('1')
  })
})
