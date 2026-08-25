/** forgeAttachment block: view, labels, upload flow, schema + slash item. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ForgeAttachmentView, type ForgeAttachmentProps } from '../forge/ForgeAttachmentView'
import { extLabel, formatBytes, publishedPath } from '../forge/attachments'
import { attachmentSlashItem, forgeSchema } from '../forge/schema'

const filled: ForgeAttachmentProps = {
  assetId: 'a'.repeat(64),
  name: 'Annex C — Order of battle',
  description: 'Sub-unit listing for the task force, March 1968.',
  filename: 'annex-c.pdf',
  mime: 'application/pdf',
  sizeBytes: 2517621,
  path: '',
}

const empty: ForgeAttachmentProps = {
  assetId: '',
  name: '',
  description: '',
  filename: '',
  mime: '',
  sizeBytes: 0,
  path: '',
}

const assetUrl = (sha: string) => (sha ? `/api/assets/${sha}` : '')

describe('label helpers', () => {
  it('derives the type label from the filename, then the mime', () => {
    expect(extLabel('annex-c.pdf', 'application/pdf')).toBe('PDF')
    expect(extLabel('noext', 'application/pdf')).toBe('PDF')
    expect(extLabel('', '')).toBe('FILE')
  })

  it('formats sizes the way the backend does', () => {
    expect(formatBytes(0)).toBe('')
    expect(formatBytes(900)).toBe('900 bytes')
    expect(formatBytes(2517621)).toBe('2.4 MB')
    expect(formatBytes(52428800)).toBe('50 MB')
  })
})

describe('publishedPath', () => {
  it('defaults to the site root, named from the attachment name', () => {
    expect(publishedPath('Annex A — Operation Order 1/66', 'scan final v2.PDF')).toBe(
      'annex-a-operation-order-1-66.pdf',
    )
  })

  it('honours an operator folder', () => {
    expect(
      publishedPath('Annex A — Operation Order 1/66', 'scan.pdf', 'rfs/vietnam/attachments'),
    ).toBe('rfs/vietnam/attachments/annex-a-operation-order-1-66.pdf')
    expect(publishedPath('Annex A', 'scan.pdf', '/rfs/vietnam/')).toBe(
      'rfs/vietnam/annex-a.pdf',
    )
  })

  it('accepts a full path and still forces the real extension', () => {
    expect(publishedPath('Annex A', 'scan.pdf', 'rfs/vietnam/oporder-1-66.pdf')).toBe(
      'rfs/vietnam/oporder-1-66.pdf',
    )
    expect(publishedPath('Annex A', 'scan.pdf', 'rfs/evil.html')).toBe('rfs/evil.pdf')
  })

  it('cannot escape the site root', () => {
    expect(publishedPath('Annex A', 'scan.pdf', '../../etc/passwd')).toBe(
      'etc/passwd/annex-a.pdf',
    )
  })
})

describe('ForgeAttachmentView', () => {
  it('shows the file-type tile, name, description and meta line', () => {
    render(<ForgeAttachmentView props={filled} assetUrl={assetUrl} />)
    const el = screen.getByTestId('forge-attachment')
    expect(el.querySelector('.forge-attachment-ext')?.textContent).toBe('PDF')
    expect(screen.getByLabelText('Attachment name')).toHaveValue('Annex C — Order of battle')
    expect(screen.getByLabelText('Attachment description')).toHaveValue(
      'Sub-unit listing for the task force, March 1968.',
    )
    const meta = el.querySelector('.forge-attachment-meta')?.textContent ?? ''
    expect(meta).toContain('PDF')
    expect(meta).toContain('2.4 MB')
    expect(meta).toContain('opens in a new tab')
  })

  it('links the preview at the stored asset, in a new tab', () => {
    render(<ForgeAttachmentView props={filled} assetUrl={assetUrl} />)
    const link = screen.getByText('Preview') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe(`/api/assets/${filled.assetId}`)
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
  })

  it('edits name and description through the callbacks', () => {
    const onNameChange = vi.fn()
    const onDescriptionChange = vi.fn()
    render(
      <ForgeAttachmentView
        props={filled}
        assetUrl={assetUrl}
        onNameChange={onNameChange}
        onDescriptionChange={onDescriptionChange}
      />,
    )
    fireEvent.change(screen.getByLabelText('Attachment name'), { target: { value: 'Annex D' } })
    fireEvent.change(screen.getByLabelText('Attachment description'), {
      target: { value: 'Signals instruction.' },
    })
    expect(onNameChange).toHaveBeenCalledWith('Annex D')
    expect(onDescriptionChange).toHaveBeenCalledWith('Signals instruction.')
  })

  it('offers a dropzone until a file is attached', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined)
    render(<ForgeAttachmentView props={empty} assetUrl={assetUrl} onUpload={onUpload} />)
    const zone = document.querySelector('.forge-upload-area') as HTMLElement
    expect(zone.textContent).toContain('Click or drop a PDF or document to attach')

    const file = new File(['%PDF-1.4'], 'annex-c.pdf', { type: 'application/pdf' })
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file))
  })

  it('surfaces an upload failure instead of silently dropping it', async () => {
    const onUpload = vi.fn().mockRejectedValue(new Error('415: not an allowed type'))
    render(<ForgeAttachmentView props={empty} assetUrl={assetUrl} onUpload={onUpload} />)
    const zone = document.querySelector('.forge-upload-area') as HTMLElement
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(['x'], 'payload.exe')] },
    })
    await waitFor(() =>
      expect(document.querySelector('.forge-gen-error')?.textContent).toContain(
        'not an allowed type',
      ),
    )
  })

  it('edits the publish path and previews the resulting URL', () => {
    const onPathChange = vi.fn()
    render(
      <ForgeAttachmentView props={filled} assetUrl={assetUrl} onPathChange={onPathChange} />,
    )
    const input = screen.getByLabelText('Attachment path')
    expect(input).toHaveValue('')
    fireEvent.change(input, { target: { value: 'rfs/vietnam/attachments' } })
    expect(onPathChange).toHaveBeenCalledWith('rfs/vietnam/attachments')
    // The preview shows where the file lands (base URL resolves at runtime).
    expect(document.querySelector('.forge-attachment-url')?.textContent).toContain(
      '/annex-c-order-of-battle.pdf',
    )
  })

  it('previews a pathed attachment at its folder', () => {
    render(
      <ForgeAttachmentView
        props={{ ...filled, path: 'rfs/vietnam/attachments' }}
        assetUrl={assetUrl}
      />,
    )
    expect(document.querySelector('.forge-attachment-url')?.textContent).toContain(
      '/rfs/vietnam/attachments/annex-c-order-of-battle.pdf',
    )
  })

  it('is read-only without callbacks (no replace button)', () => {
    render(<ForgeAttachmentView props={filled} assetUrl={assetUrl} />)
    expect(screen.queryByText('Replace file')).toBeNull()
  })
})

describe('forge schema — forgeAttachment', () => {
  it('registers forgeAttachment alongside the other Forge blocks', () => {
    expect(Object.keys(forgeSchema.blockSpecs)).toEqual(
      expect.arrayContaining(['forgeImage', 'forgeNarrative', 'forgeAttachment']),
    )
  })

  it('carries the display props the renderer needs, with no inline content', () => {
    const spec = forgeSchema.blockSpecs.forgeAttachment
    expect(spec.config.content).toBe('none')
    expect(Object.keys(spec.config.propSchema).sort()).toEqual([
      'assetId',
      'description',
      'filename',
      'mime',
      'name',
      'path',
      'sizeBytes',
    ])
  })

  it('inserts the block from the slash menu', () => {
    const editor = {}
    const item = attachmentSlashItem(editor)
    expect(item.title).toBe('Attachment')
    expect(item.group).toBe('Forge')
    expect(item.aliases).toContain('pdf')
  })
})
