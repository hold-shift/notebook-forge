/** Integration guard: the canonical block JSON produced by the importer
 * must be loadable by BlockNote as initialContent without throwing, and
 * survive a document read-back with custom props intact. Fixture: the real
 * imported Junior memoir (94 blocks, 9 forgeImages, footnote markers). */

import { describe, expect, it } from 'vitest'
import { BlockNoteEditor, type PartialBlock } from '@blocknote/core'
import { forgeSchema } from '../forge/schema'
import juniorBlocks from './fixtures/junior.blocks.json'

describe('imported blocks load into BlockNote', () => {
  it('creates an editor from the real Junior block tree', () => {
    const editor = BlockNoteEditor.create({
      schema: forgeSchema,
      initialContent: juniorBlocks as PartialBlock<typeof forgeSchema.blockSchema>[],
    })
    const doc = editor.document
    expect(doc.length).toBe(juniorBlocks.length)

    const images = doc.filter((b) => b.type === 'forgeImage')
    expect(images).toHaveLength(9)
    for (const img of images) {
      expect(img.props.assetId).toMatch(/^[0-9a-f]{64}$/)
      expect(img.props.sketchAssetId).toMatch(/^[0-9a-f]{64}$/)
    }

    const headings = doc.filter((b) => b.type === 'heading')
    expect(headings.length).toBeGreaterThan(30)

    // block ids survive load so saves don't rewrite identity
    expect(doc[0].id).toBe((juniorBlocks as { id: string }[])[0].id)
  })
})
