import { describe, expect, it } from 'vitest'
import { imageSketchUpdates } from '../forge/sketchSync'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Block = any

const img = (id: string, props: Record<string, unknown> = {}): Block => ({
  id,
  type: 'forgeImage',
  props: { assetId: `asset-${id}`, sketchAssetId: '', faceGate: 'n/a', approval: 'pending', ...props },
  children: [],
})
const para = (id: string): Block => ({ id, type: 'paragraph', props: {}, content: [], children: [] })

describe('imageSketchUpdates', () => {
  it('produces an update when the server has a new sketch the editor lacks', () => {
    const editor = [img('a'), para('p'), img('b')]
    const server = [img('a', { sketchAssetId: 'sk-a', faceGate: 'ok' }), para('p'), img('b')]
    const updates = imageSketchUpdates(editor, server)
    expect(updates).toHaveLength(1)
    expect(updates[0].id).toBe('a')
    expect(updates[0].props.sketchAssetId).toBe('sk-a')
    expect(updates[0].props.faceGate).toBe('ok')
    // unrelated props are preserved
    expect(updates[0].props.assetId).toBe('asset-a')
  })

  it('returns nothing when editor and server sketch props already match', () => {
    const editor = [img('a', { sketchAssetId: 'sk-a' })]
    const server = [img('a', { sketchAssetId: 'sk-a' })]
    expect(imageSketchUpdates(editor, server)).toEqual([])
  })

  it('updates every changed figure in a batch', () => {
    const editor = [img('a'), img('b'), img('c')]
    const server = [
      img('a', { sketchAssetId: 'sk-a' }),
      img('b', { faceGate: 'flagged' }),
      img('c'), // unchanged
    ]
    const updates = imageSketchUpdates(editor, server)
    expect(updates.map((u) => u.id).sort()).toEqual(['a', 'b'])
  })

  it('ignores non-image blocks and editor figures missing from the server', () => {
    const editor = [para('p'), img('gone')]
    const server = [para('p')] // 'gone' not present server-side
    expect(imageSketchUpdates(editor, server)).toEqual([])
  })

  it('does NOT touch prose edits — only forgeImage sketch props change', () => {
    const editor = [img('a'), para('p')]
    const server = [img('a', { sketchAssetId: 'sk-a' }), para('p')]
    const updates = imageSketchUpdates(editor, server)
    expect(updates.every((u) => u.id !== 'p')).toBe(true)
  })
})
