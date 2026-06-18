/** Presentational core of the forgeImage block: original photo and its
 * NotebookLM-safe sketch side by side, caption + approval state below.
 * Kept editor-free so it can be unit-tested directly. */

import { useRef, useState } from 'react'
import { InfoTip } from '../ui'
import { AutoTextarea } from './AutoTextarea'

export type SafeMode = 'sketch' | 'original' | 'omit'

export interface ForgeImageProps {
  assetId: string
  sketchAssetId: string
  caption: string
  altText: string
  approval: 'pending' | 'approved'
  displayWidth: 'full' | 'portrait'
  peopleCount?: number
  safeMode?: SafeMode
  faceGate?: 'ok' | 'flagged' | 'n/a'
}

export interface ForgeImageViewProps {
  props: ForgeImageProps
  assetUrl: (sha: string) => string
  /** Stable block id — sets id="figure-{blockId}" for sidebar nav stepper. */
  blockId?: string
  onCaptionChange?: (caption: string) => void
  onApprovalToggle?: () => void
  /** Generate (or regenerate) the sketch via Gemini. An optional prompt
   * overrides the default for this figure only. Resolves when done. */
  onGenerateSketch?: (prompt?: string) => Promise<void>
  /** What the NotebookLM-safe edition embeds for this figure. */
  onSafeModeChange?: (mode: SafeMode) => void
  /** Upload a photo file — called when the block has no assetId yet. */
  onImageUpload?: (file: File) => Promise<void>
  /** Upload a hand-made sketch — escape hatch when the model refuses. */
  onSketchUpload?: (file: File) => Promise<void>
}

export function ForgeImageView({
  props,
  assetUrl,
  blockId,
  onCaptionChange,
  onApprovalToggle,
  onGenerateSketch,
  onSafeModeChange,
  onImageUpload,
  onSketchUpload,
}: ForgeImageViewProps) {
  const { assetId, sketchAssetId, caption, altText, approval, displayWidth, faceGate } = props
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState('')
  const [showPrompt, setShowPrompt] = useState(false)
  const [promptOverride, setPromptOverride] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [sketchUploading, setSketchUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const sketchInputRef = useRef<HTMLInputElement>(null)

  const handleSketchUpload = async (file: File) => {
    if (!onSketchUpload) return
    setSketchUploading(true)
    setGenError('')
    try {
      await onSketchUpload(file)
    } catch (e) {
      setGenError(String(e))
    } finally {
      setSketchUploading(false)
    }
  }

  const handleUpload = async (file: File) => {
    if (!onImageUpload) return
    setUploading(true)
    setUploadError('')
    try {
      await onImageUpload(file)
    } catch (e) {
      setUploadError(String(e))
    } finally {
      setUploading(false)
    }
  }

  const generate = onGenerateSketch
    ? () => {
        setGenerating(true)
        setGenError('')
        onGenerateSketch(promptOverride.trim() || undefined)
          .catch((e: unknown) => setGenError(String(e)))
          .finally(() => setGenerating(false))
      }
    : undefined

  if (!assetId && onImageUpload) {
    return (
      <figure className="forge-image forge-image-upload-wrap" data-testid="forge-image">
        <div
          className={`forge-upload-area${dragging ? ' dragging' : ''}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files[0]
            if (file) void handleUpload(file)
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void handleUpload(file)
            }}
          />
          {uploading ? (
            <span>Uploading…</span>
          ) : (
            <>
              <span className="forge-upload-icon">🖼️</span>
              <span>Click or drop a photo to add a figure</span>
            </>
          )}
        </div>
        {uploadError && <p className="forge-gen-error">{uploadError}</p>}
      </figure>
    )
  }

  return (
    <figure
      id={blockId ? `figure-${blockId}` : undefined}
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
          <div
            className={`forge-image-cell forge-image-missing${onSketchUpload ? ' uploadable' : ''}`}
            data-testid="sketch-missing"
            onClick={onSketchUpload ? () => sketchInputRef.current?.click() : undefined}
            title={onSketchUpload ? 'Click to upload your own sketch' : undefined}
          >
            <span>{sketchUploading ? 'Uploading…' : 'No sketch yet'}</span>
            {onSketchUpload && !sketchUploading && (
              <span className="forge-image-sublabel">Click to upload one</span>
            )}
          </div>
        )}
      </div>
      {onSketchUpload && (
        <input
          ref={sketchInputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void handleSketchUpload(file)
            e.target.value = ''
          }}
        />
      )}
      <figcaption>
        <AutoTextarea
          className="forge-caption-input"
          value={caption}
          placeholder="Caption…"
          onChange={(e) => onCaptionChange?.(e.target.value)}
          readOnly={!onCaptionChange}
        />
        <div className="forge-caption-controls">
          {generate && (
            <>
              <button
                type="button"
                className="forge-generate"
                onClick={generate}
                disabled={generating}
                title="Generate a NotebookLM-safe sketch via Gemini"
              >
                {generating ? 'Generating…' : sketchAssetId ? '↻ Regenerate' : '✏ Generate sketch'}
              </button>
              <button
                type="button"
                className={`forge-generate ${showPrompt ? 'active' : ''}`}
                onClick={() => setShowPrompt(!showPrompt)}
                title="Override the silhouette prompt for this figure only"
              >
                ✎ prompt
              </button>
            </>
          )}
          {onSketchUpload && (
            <button
              type="button"
              className="forge-generate"
              onClick={() => sketchInputRef.current?.click()}
              disabled={sketchUploading}
              title="Upload your own sketch (use when the model won't generate one)"
            >
              {sketchUploading ? 'Uploading…' : '⬆ Upload sketch'}
            </button>
          )}
          {onSafeModeChange && (
            <select
              className="forge-safemode"
              value={props.safeMode ?? 'sketch'}
              title="What the NotebookLM-safe edition embeds for this figure"
              onChange={(e) => onSafeModeChange(e.target.value as SafeMode)}
            >
              <option value="sketch">Safe: sketch</option>
              <option value="original">Safe: original</option>
              <option value="omit">Safe: omit</option>
            </select>
          )}
          {faceGate === 'flagged' && (
            <span className="forge-face-flag" title="Face detected by gate — review before approving">
              ⚠ face flag
            </span>
          )}
          <button
            type="button"
            className={`forge-approval ${approval}`}
            onClick={onApprovalToggle}
            title="Toggle sketch approval"
          >
            {approval === 'approved' ? '✓ approved' : '○ pending'}
          </button>
          <InfoTip label="About the figure tools" align="right">
            These tools prepare this figure for the NotebookLM-safe edition. Generate/Regenerate
            makes a faceless sketch; “✎ prompt” overrides the silhouette prompt for this figure
            only; “Upload sketch” lets you supply your own. “Safe: sketch / original / omit”
            chooses what the safe edition embeds — the public site always uses the original.
            A “face flag” means a face was still detected; review before approving. Toggle
            approval to mark the sketch final — approved figures are skipped by batch generation.
          </InfoTip>
        </div>
      </figcaption>
      {showPrompt && (
        <textarea
          className="forge-prompt-override"
          rows={4}
          placeholder="Per-figure prompt override — leave blank to use the default silhouette prompt (Settings → Sketch generation). Applies to the next Generate/Regenerate."
          value={promptOverride}
          onChange={(e) => setPromptOverride(e.target.value)}
        />
      )}
      {genError && <p className="forge-gen-error">{genError}</p>}
    </figure>
  )
}
