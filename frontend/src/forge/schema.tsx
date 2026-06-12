/** BlockNote schema: defaults + the two Forge custom blocks + the fnRef
 * inline style (footnote reference markers in prose). No @blocknote/xl-*
 * packages — core/react/mantine only (licence guardrail). */

import { BlockNoteSchema, defaultBlockSpecs, defaultStyleSpecs } from '@blocknote/core'
import { createReactBlockSpec, createReactStyleSpec } from '@blocknote/react'
import { api } from '../api'
import { ForgeImageView, type ForgeImageProps } from './ForgeImageView'
import { ForgeFootnoteView, type ForgeFootnoteProps } from './ForgeFootnoteView'

export const forgeImageSpec = createReactBlockSpec(
  {
    type: 'forgeImage',
    propSchema: {
      assetId: { default: '' },
      sketchAssetId: { default: '' },
      caption: { default: '' },
      altText: { default: '' },
      approval: { default: 'pending', values: ['pending', 'approved'] },
      peopleCount: { default: 0 },
      displayWidth: { default: 'full', values: ['full', 'portrait'] },
      // What the NotebookLM-safe edition embeds for this figure:
      // the sketch (default), the original photo (maps/diagrams), or
      // nothing at all (the figure number is still consumed so anchors
      // stay aligned with the HTML edition).
      safeMode: { default: 'sketch', values: ['sketch', 'original', 'omit'] },
    },
    content: 'none',
  },
  {
    render: ({ block, editor }) => (
      <ForgeImageView
        props={block.props as ForgeImageProps}
        assetUrl={api.assetUrl}
        onCaptionChange={(caption) =>
          editor.updateBlock(block, { props: { ...block.props, caption } })
        }
        onApprovalToggle={() =>
          editor.updateBlock(block, {
            props: {
              ...block.props,
              approval: block.props.approval === 'approved' ? 'pending' : 'approved',
            },
          })
        }
        onSafeModeChange={(safeMode) =>
          editor.updateBlock(block, { props: { ...block.props, safeMode } })
        }
        onGenerateSketch={async (prompt?: string) => {
          const slug = currentDocSlug()
          if (!slug) throw new Error('no document open')
          // A REgenerate (sketch already exists) must roll fresh — bypass
          // the cache; a first Generate takes the free cache hit if any.
          const force = Boolean(block.props.sketchAssetId)
          const resp = await api.generateSketch(slug, block.id, prompt, force)
          editor.updateBlock(block, {
            props: {
              ...block.props,
              sketchAssetId: resp.detail.sketchAssetId,
              approval: 'pending',
            },
          })
        }}
        onImageUpload={async (file: File) => {
          const slug = currentDocSlug()
          if (!slug) throw new Error('no document open')
          const resp = await api.uploadFigureImage(slug, file)
          editor.updateBlock(block, { props: { ...block.props, assetId: resp.assetId } })
        }}
      />
    ),
  },
)

/** The editor is only mounted at #/doc/{slug}; block renders read the slug
 * from the hash rather than threading it through the BlockNote schema. */
function currentDocSlug(): string | null {
  const m = window.location.hash.match(/^#\/doc\/(.+)$/)
  return m ? decodeURIComponent(m[1]) : null
}

export const forgeFootnoteSpec = createReactBlockSpec(
  {
    type: 'forgeFootnote',
    propSchema: {
      marker: { default: '' },
      text: { default: '' },
    },
    content: 'none',
  },
  {
    render: ({ block, editor }) => (
      <ForgeFootnoteView
        props={block.props as ForgeFootnoteProps}
        onTextChange={(text) => editor.updateBlock(block, { props: { ...block.props, text } })}
        onMarkerChange={(marker) =>
          editor.updateBlock(block, { props: { ...block.props, marker } })
        }
      />
    ),
  },
)

export const fnRefStyleSpec = createReactStyleSpec(
  { type: 'fnRef', propSchema: 'boolean' },
  {
    render: ({ contentRef }) => <sup className="fn-ref" ref={contentRef} />,
  },
)

export const forgeSchema = BlockNoteSchema.create({
  blockSpecs: {
    ...defaultBlockSpecs,
    forgeImage: forgeImageSpec(),
    forgeFootnote: forgeFootnoteSpec(),
  },
  styleSpecs: {
    ...defaultStyleSpecs,
    fnRef: fnRefStyleSpec,
  },
})
