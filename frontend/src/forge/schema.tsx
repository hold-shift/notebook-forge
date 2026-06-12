/** BlockNote schema: defaults + the two Forge custom blocks + the fnRef
 * inline style (footnote reference markers in prose). No @blocknote/xl-*
 * packages — core/react/mantine only (licence guardrail). */

import { BlockNoteSchema, defaultBlockSpecs, defaultStyleSpecs, filterSuggestionItems, insertOrUpdateBlockForSlashMenu } from '@blocknote/core'
import { createReactBlockSpec, createReactStyleSpec, getDefaultReactSlashMenuItems } from '@blocknote/react'
import { api } from '../api'
import { ForgeImageView, type ForgeImageProps } from './ForgeImageView'
import { ForgeFootnoteView, type ForgeFootnoteProps } from './ForgeFootnoteView'
import { ForgeDedicationView } from './ForgeDedicationView'
import { ForgeDocGroupView, type ForgeDocGroupProps } from './ForgeDocGroupView'

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

export const forgeDedicationSpec = createReactBlockSpec(
  { type: 'forgeDedication', propSchema: { text: { default: '' } }, content: 'none' },
  {
    render: ({ block, editor }) => (
      <ForgeDedicationView
        text={block.props.text}
        onChange={(text) => editor.updateBlock(block, { props: { ...block.props, text } })}
      />
    ),
  },
)

export const forgeDocGroupSpec = createReactBlockSpec(
  {
    type: 'forgeDocGroup',
    propSchema: {
      groupId: { default: '' },
      sort: { default: 'manual', values: ['manual', 'date_range', 'title_az', 'last_updated'] },
      showBlurbs: { default: true },
      showWordCounts: { default: true },
      layout: { default: 'list', values: ['list', 'compact_grid'] },
    },
    content: 'none',
  },
  {
    render: ({ block, editor }) => (
      <ForgeDocGroupView
        props={block.props as ForgeDocGroupProps}
        onChange={(patch) => editor.updateBlock(block, { props: { ...block.props, ...patch } })}
      />
    ),
  },
)

export const forgeSchema = BlockNoteSchema.create({
  blockSpecs: {
    ...defaultBlockSpecs,
    forgeImage: forgeImageSpec(),
    forgeFootnote: forgeFootnoteSpec(),
    forgeDedication: forgeDedicationSpec(),
    forgeDocGroup: forgeDocGroupSpec(),
  },
  styleSpecs: {
    ...defaultStyleSpecs,
    fnRef: fnRefStyleSpec,
  },
})

/** Slash menu item for inserting a forgeDocGroup block (homepage only). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function docGroupSlashItem(editor: any) {
  return {
    title: 'Document group',
    aliases: ['group'],
    group: 'Forge',
    subtext: 'Curated list of library documents',
    icon: <i className="ti ti-folders" />,
    onItemClick: () => insertOrUpdateBlockForSlashMenu(editor, { type: 'forgeDocGroup' }),
  }
}

/** Slash menu item for inserting a forgeDedication block (homepage only). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function dedicationSlashItem(editor: any) {
  return {
    title: 'Dedication',
    aliases: ['dedication'],
    group: 'Forge',
    subtext: 'Italic dedication line',
    icon: <i className="ti ti-heart" />,
    onItemClick: () => insertOrUpdateBlockForSlashMenu(editor, { type: 'forgeDedication' }),
  }
}

export { filterSuggestionItems, getDefaultReactSlashMenuItems }
