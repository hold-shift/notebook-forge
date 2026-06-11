/** Presentational core of the forgeImage block: original photo and its
 * NotebookLM-safe sketch side by side, caption + approval state below.
 * Kept editor-free so it can be unit-tested directly. */

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
}

export function ForgeImageView({
  props,
  assetUrl,
  onCaptionChange,
  onApprovalToggle,
}: ForgeImageViewProps) {
  const { assetId, sketchAssetId, caption, altText, approval, displayWidth } = props
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
        <button
          type="button"
          className={`forge-approval ${approval}`}
          onClick={onApprovalToggle}
          title="Toggle sketch approval"
        >
          {approval === 'approved' ? '✓ approved' : '○ pending'}
        </button>
      </figcaption>
    </figure>
  )
}
