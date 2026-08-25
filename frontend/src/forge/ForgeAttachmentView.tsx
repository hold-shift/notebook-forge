/** Presentational core of the forgeAttachment block: a hosted file (PDF or
 * other document) with an editable name and description. The in-editor twin
 * of a.attachment on the published page — file-type tile on the left, name,
 * description and type/size meta on the right. Kept editor-free so it can be
 * unit-tested directly. */

import { useRef, useState } from 'react'
import { AutoTextarea } from './AutoTextarea'
import { extLabel, formatBytes, publishedPath, useSiteBaseUrl } from './attachments'

export interface ForgeAttachmentProps {
  assetId: string
  name: string
  description: string
  filename: string
  mime: string
  sizeBytes: number
  /** Publish location relative to the SITE root. Empty = the site root. */
  path: string
}

export interface ForgeAttachmentViewProps {
  props: ForgeAttachmentProps
  /** Preview URL for the stored asset (dev server serves it from the store). */
  assetUrl: (sha: string) => string
  onNameChange?: (name: string) => void
  onDescriptionChange?: (description: string) => void
  onPathChange?: (path: string) => void
  /** Upload (or replace) the attached file. Resolves when the block is updated. */
  onUpload?: (file: File) => Promise<void>
}

export function ForgeAttachmentView({
  props,
  assetUrl,
  onNameChange,
  onDescriptionChange,
  onPathChange,
  onUpload,
}: ForgeAttachmentViewProps) {
  const { assetId, name, description, filename, mime, sizeBytes, path } = props
  const baseUrl = useSiteBaseUrl()
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (file: File) => {
    if (!onUpload) return
    setUploading(true)
    setUploadError('')
    try {
      await onUpload(file)
    } catch (e) {
      setUploadError(String(e))
    } finally {
      setUploading(false)
    }
  }

  const picker = onUpload ? (
    <input
      ref={fileInputRef}
      type="file"
      accept=".pdf,.docx,.xlsx,.pptx,.txt,.csv,.jpg,.jpeg,.png,.zip"
      style={{ display: 'none' }}
      onChange={(e) => {
        const file = e.target.files?.[0]
        if (file) void handleUpload(file)
        e.target.value = ''
      }}
    />
  ) : null

  if (!assetId && onUpload) {
    return (
      <div className="forge-attachment forge-attachment-upload-wrap" data-testid="forge-attachment">
        <div
          className={`forge-upload-area${dragging ? ' dragging' : ''}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files[0]
            if (file) void handleUpload(file)
          }}
        >
          {picker}
          {uploading ? (
            <span>Uploading…</span>
          ) : (
            <>
              <span className="forge-upload-icon">📎</span>
              <span>Click or drop a PDF or document to attach</span>
            </>
          )}
        </div>
        {uploadError && <p className="forge-gen-error">{uploadError}</p>}
      </div>
    )
  }

  const kind = extLabel(filename, mime)
  const size = formatBytes(sizeBytes)

  return (
    <div className="forge-attachment" data-testid="forge-attachment">
      <div className="forge-attachment-card">
        <div className="forge-attachment-tile" aria-hidden="true">
          <svg viewBox="0 0 26 32">
            <path d="M4 1h11l7 7v23H4z" />
            <path d="M15 1v7h7" />
          </svg>
          <span className="forge-attachment-ext">{kind}</span>
        </div>
        <div className="forge-attachment-body">
          <AutoTextarea
            className="forge-attachment-name"
            value={name}
            aria-label="Attachment name"
            placeholder="Attachment name…"
            onChange={(e) => onNameChange?.(e.target.value)}
            readOnly={!onNameChange}
          />
          <AutoTextarea
            className="forge-attachment-desc"
            value={description}
            aria-label="Attachment description"
            placeholder="Description…"
            onChange={(e) => onDescriptionChange?.(e.target.value)}
            readOnly={!onDescriptionChange}
          />
          <div className="forge-attachment-meta">
            <span>
              {kind}
              {size ? ` · ${size}` : ''}
              {' · opens in a new tab'}
            </span>
            {assetId && (
              <a
                className="forge-attachment-preview"
                href={assetUrl(assetId)}
                target="_blank"
                rel="noopener noreferrer"
              >
                Preview
              </a>
            )}
            {onUpload && (
              <button
                type="button"
                className="forge-attachment-replace"
                onClick={() => fileInputRef.current?.click()}
              >
                {uploading ? 'Uploading…' : 'Replace file'}
              </button>
            )}
          </div>
          <div className="forge-attachment-path">
            <label htmlFor={`att-path-${assetId}`}>Path</label>
            <input
              id={`att-path-${assetId}`}
              value={path}
              placeholder="site root — e.g. rfs/vietnam/attachments"
              aria-label="Attachment path"
              onChange={(e) => onPathChange?.(e.target.value)}
              readOnly={!onPathChange}
            />
          </div>
          <p className="forge-attachment-url" title="Where this file will be published">
            {baseUrl}/{publishedPath(name, filename, path)}
          </p>
          {filename && <p className="forge-attachment-filename">Uploaded as {filename}</p>}
        </div>
        {picker}
      </div>
      {uploadError && <p className="forge-gen-error">{uploadError}</p>}
    </div>
  )
}
