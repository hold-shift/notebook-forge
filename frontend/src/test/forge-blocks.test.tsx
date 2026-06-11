/** M5 gate: component tests for the two custom blocks. */

import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ForgeImageView, type ForgeImageProps } from '../forge/ForgeImageView'
import { ForgeFootnoteView } from '../forge/ForgeFootnoteView'
import { forgeSchema } from '../forge/schema'

const imageProps: ForgeImageProps = {
  assetId: 'sha-original',
  sketchAssetId: 'sha-sketch',
  caption: 'Pvt. Robert. F. Skitch.',
  altText: 'A young man in uniform',
  approval: 'approved',
  displayWidth: 'portrait',
}

const assetUrl = (sha: string) => `/api/assets/${sha}`

describe('forgeImage block', () => {
  it('renders original and sketch side by side', () => {
    render(<ForgeImageView props={imageProps} assetUrl={assetUrl} />)
    const imgs = screen.getAllByRole('img')
    expect(imgs).toHaveLength(2)
    expect(imgs[0]).toHaveAttribute('src', '/api/assets/sha-original')
    expect(imgs[0]).toHaveAttribute('alt', 'A young man in uniform')
    expect(imgs[1]).toHaveAttribute('src', '/api/assets/sha-sketch')
    expect(screen.getByText('Sketch (NotebookLM-safe)')).toBeInTheDocument()
    expect(screen.getByTestId('forge-image')).toHaveClass('portrait')
  })

  it('shows a placeholder when the sketch is missing', () => {
    render(
      <ForgeImageView props={{ ...imageProps, sketchAssetId: '' }} assetUrl={assetUrl} />,
    )
    expect(screen.getAllByRole('img')).toHaveLength(1)
    expect(screen.getByTestId('sketch-missing')).toBeInTheDocument()
  })

  it('edits the caption and toggles approval', () => {
    const onCaption = vi.fn()
    const onApproval = vi.fn()
    render(
      <ForgeImageView
        props={{ ...imageProps, approval: 'pending' }}
        assetUrl={assetUrl}
        onCaptionChange={onCaption}
        onApprovalToggle={onApproval}
      />,
    )
    fireEvent.change(screen.getByDisplayValue('Pvt. Robert. F. Skitch.'), {
      target: { value: 'New caption' },
    })
    expect(onCaption).toHaveBeenCalledWith('New caption')
    fireEvent.click(screen.getByText('○ pending'))
    expect(onApproval).toHaveBeenCalled()
  })
})

describe('forgeFootnote block', () => {
  it('renders marker and text as a co-located aside', () => {
    render(<ForgeFootnoteView props={{ marker: '2', text: 'A note about the mess.' }} />)
    const aside = screen.getByTestId('forge-footnote')
    expect(aside).toHaveAttribute('role', 'note')
    expect(screen.getByLabelText('Footnote marker')).toHaveValue('2')
    expect(screen.getByLabelText('Footnote text')).toHaveValue('A note about the mess.')
  })

  it('propagates edits', () => {
    const onText = vi.fn()
    render(
      <ForgeFootnoteView props={{ marker: '1', text: 'old' }} onTextChange={onText} />,
    )
    fireEvent.change(screen.getByLabelText('Footnote text'), { target: { value: 'new text' } })
    expect(onText).toHaveBeenCalledWith('new text')
  })
})

describe('forge schema', () => {
  it('registers both custom blocks and the fnRef style alongside defaults', () => {
    expect(Object.keys(forgeSchema.blockSpecs)).toEqual(
      expect.arrayContaining(['paragraph', 'heading', 'quote', 'table', 'forgeImage', 'forgeFootnote']),
    )
    expect(Object.keys(forgeSchema.styleSpecs)).toContain('fnRef')
    const props = forgeSchema.blockSpecs.forgeImage.config.propSchema
    expect(Object.keys(props)).toEqual(
      expect.arrayContaining([
        'assetId',
        'sketchAssetId',
        'caption',
        'altText',
        'approval',
        'peopleCount',
        'displayWidth',
      ]),
    )
  })
})

describe('forgeImage sketch generation', () => {
  it('shows Generate when no sketch, Regenerate when present, and calls back', async () => {
    const onGenerate = vi.fn().mockResolvedValue(undefined)
    const { rerender } = render(
      <ForgeImageView
        props={{ ...imageProps, sketchAssetId: '' }}
        assetUrl={assetUrl}
        onGenerateSketch={onGenerate}
      />,
    )
    const btn = screen.getByText('✏ Generate sketch')
    fireEvent.click(btn)
    expect(onGenerate).toHaveBeenCalledOnce()
    rerender(
      <ForgeImageView props={imageProps} assetUrl={assetUrl} onGenerateSketch={onGenerate} />,
    )
    expect(await screen.findByText('↻ Regenerate')).toBeInTheDocument()
  })

  it('hides the button without a callback (read-only render)', () => {
    render(<ForgeImageView props={imageProps} assetUrl={assetUrl} />)
    expect(screen.queryByText(/Generate|Regenerate/)).not.toBeInTheDocument()
  })
})
