/** Presentational core of the forgeImage block: original photo and its
 * NotebookLM-safe sketch side by side, caption + approval state below.
 * Kept editor-free so it can be unit-tested directly. */

import { useState } from 'react'

export interface ForgeImageProps {
  assetId: string
  sketchAssetId: string
  caption: string
  altText: string
  approval: 'pending' | 'approved'
  displayWidth: 'full' | 'portrait'
  peopleCount?: number
}

export interface ForgeImageViewProps {
  props: ForgeImageProps
  assetUrl: (sha: string) => string
  onCaptionChange?: (caption: string) => void
  onApprovalToggle?: () => void
  /** Generate (or regenerate) the sketch via Gemini. Resolves when done. */
  onGenerateSketch?: () => Promise<void>
}

export function ForgeImageView({
  props,
  assetUrl,
  onCaptionChange,
  onApprovalToggle,
  onGenerateSketch,
}: ForgeImageViewProps) {
  const { assetId, sketchAssetId, caption, altText, approval, displayWidth } = props
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState('')

  const generate = onGenerateSketch
    ? () => {
        setGenerating(true)
        setGenError('')
        onGenerateSketch()
          .catch((e: unknown) => setGenError(String(e)))
          .finally(() => setGenerating(false))
      }
    : undefined

  return (
    <figure
      className={`forge-image ${displayWidth === 'portrait' ? 'portrait' : 'full'}`}
      data-testid="forge-image"
    >
      <div className="forge-image-pair">
        <div className="forge-image-cell">
          <img src={assetUrl(assetId)} alt={altText} />
          <span className="forge-image-label">Original</span>
        </div>
        {sketchAssetId ? (
          <div className="forge-image-cell">
            <img src={assetUrl(sketchAssetId)} alt={`Sketch: ${altText}`} />
            <span className="forge-image-label">Sketch (NotebookLM-safe)</span>
          </div>
        ) : (
          <div className="forge-image-cell forge-image-missing" data-testid="sketch-missing">
            <span>No sketch yet</span>
          </div>
        )}
      </div>
      <figcaption>
        <input
          className="forge-caption-input"
          value={caption}
          placeholder="Caption…"
          onChange={(e) => onCaptionChange?.(e.target.value)}
          readOnly={!onCaptionChange}
        />
        {generate && (
          <button
            type="button"
            className="forge-generate"
            onClick={generate}
            disabled={generating}
            title="Generate a NotebookLM-safe sketch via Gemini"
          >
            {generating ? 'Generating…' : sketchAssetId ? '↻ Regenerate' : '✏ Generate sketch'}
          </button>
        )}
        <button
          type="button"
          className={`forge-approval ${approval}`}
          onClick={onApprovalToggle}
          title="Toggle sketch approval"
        >
          {approval === 'approved' ? '✓ approved' : '○ pending'}
        </button>
      </figcaption>
      {genError && <p className="forge-gen-error">{genError}</p>}
    </figure>
  )
}
