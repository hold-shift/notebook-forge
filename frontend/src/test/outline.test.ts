/** Outline Navigator logic: tree building, level-skip lint, collapse state. */

import { describe, expect, it } from 'vitest'
import {
  buildOutline,
  collapseAll,
  expandAll,
  headingIds,
  parentIds,
  toggleCollapsed,
  type BlockLike,
} from '../forge/outline'

function h(id: string, level: number, text: string): BlockLike {
  return { id, type: 'heading', props: { level }, content: [{ type: 'text', text }] }
}

function p(id: string): BlockLike {
  return { id, type: 'paragraph', content: [{ type: 'text', text: 'prose' }] }
}

describe('buildOutline', () => {
  it('nests H3s under H2s and ignores non-headings', () => {
    const tree = buildOutline([
      h('a', 2, 'Chapter one'),
      p('x'),
      h('b', 3, 'Section one-a'),
      h('c', 3, 'Section one-b'),
      h('d', 2, 'Chapter two'),
      p('y'),
    ])
    expect(tree).toHaveLength(2)
    expect(tree[0].text).toBe('Chapter one')
    expect(tree[0].children.map((n) => n.text)).toEqual(['Section one-a', 'Section one-b'])
    expect(tree[1].text).toBe('Chapter two')
    expect(tree[1].children).toHaveLength(0)
  })

  it('handles three levels and returns to shallower levels correctly', () => {
    const tree = buildOutline([
      h('a', 1, 'Part'),
      h('b', 2, 'Chapter'),
      h('c', 3, 'Section'),
      h('d', 2, 'Chapter two'),
    ])
    expect(tree).toHaveLength(1)
    expect(tree[0].children.map((n) => n.text)).toEqual(['Chapter', 'Chapter two'])
    expect(tree[0].children[0].children[0].text).toBe('Section')
  })

  it('flags headings that skip a level', () => {
    const tree = buildOutline([
      h('a', 1, 'Part'),
      h('b', 3, 'Orphan section'), // H3 directly under H1
      h('c', 2, 'Chapter'),
    ])
    const orphan = tree[0].children[0]
    expect(orphan.text).toBe('Orphan section')
    expect(orphan.warn).toMatch(/Skips H2/)
    expect(tree[0].warn).toBeNull()
    expect(tree[0].children[1].warn).toBeNull()
  })

  it('uses the shallowest level as baseline (H2-rooted corpus norm)', () => {
    const tree = buildOutline([h('a', 2, 'Chapter'), h('b', 3, 'Section')])
    expect(tree[0].warn).toBeNull() // first H2 in an H2-rooted doc is fine
    expect(tree[0].children[0].warn).toBeNull()
  })

  it('flags an H3 before any H2 in an H2-rooted doc', () => {
    const tree = buildOutline([h('a', 3, 'Too deep too soon'), h('b', 2, 'Chapter')])
    expect(tree[0].warn).toMatch(/Skips H2/)
  })

  it('labels untitled headings and clamps levels', () => {
    const tree = buildOutline([
      { id: 'a', type: 'heading', props: { level: 9 }, content: [] },
    ])
    expect(tree[0].text).toBe('(untitled heading)')
    expect(tree[0].level).toBe(3)
  })
})

describe('collapse state', () => {
  const tree = buildOutline([
    h('a', 2, 'One'),
    h('b', 3, 'One-a'),
    h('c', 2, 'Two'),
    h('d', 3, 'Two-a'),
    h('e', 2, 'Three'), // leaf
  ])

  it('parentIds returns only nodes with children', () => {
    expect(parentIds(tree)).toEqual(['a', 'c'])
  })

  it('toggle adds and removes without mutating the input', () => {
    const s0 = new Set<string>()
    const s1 = toggleCollapsed(s0, 'a')
    expect(s1.has('a')).toBe(true)
    expect(s0.has('a')).toBe(false)
    const s2 = toggleCollapsed(s1, 'a')
    expect(s2.has('a')).toBe(false)
  })

  it('collapseAll collapses every parent; expandAll clears', () => {
    const all = collapseAll(tree)
    expect([...all].sort()).toEqual(['a', 'c'])
    expect(expandAll().size).toBe(0)
  })

  it('headingIds flattens the tree in document order', () => {
    expect(headingIds(tree)).toEqual(['a', 'b', 'c', 'd', 'e'])
  })
})
