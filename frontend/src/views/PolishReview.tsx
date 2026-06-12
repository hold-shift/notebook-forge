import { useEffect } from 'react'
import type { DiffSegment, FlaggedBlock, PolishReport } from '../api'

interface PolishReviewProps {
  report: PolishReport
  remaining: Set<string>
  onApply: (blockId: string, content: unknown[]) => void
  onSkip: (blockId: string) => void
  onDone: () => void
  onClose: () => void
  onApplyAll: () => void
  onSkipAll: () => void
  onJumpToBlock: (blockId: string) => void
}

export function PolishReview({
  report,
  remaining,
  onApply,
  onSkip,
  onDone,
  onClose,
  onApplyAll,
  onSkipAll,
  onJumpToBlock,
}: PolishReviewProps) {
  const pending = report.flagged.filter((f) => remaining.has(f.block_id))
  const acted = report.flagged.length - pending.length

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box polish-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="polish-modal-title">
            <h3>Polish review</h3>
            <span className="muted" style={{ fontSize: '11px', marginLeft: 8 }}>
              {report.blocks_polished} auto-applied
              {' · '}
              {report.flagged.length} to review
              {report.blocks_unchanged > 0 && ` · ${report.blocks_unchanged} unchanged`}
              {' · '}
              <span className="polish-model">{report.model}</span>
            </span>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <i className="ti ti-x" aria-hidden />
          </button>
        </div>

        {report.failed_chunks.length > 0 && (
          <details className="polish-failed-chunks">
            <summary>
              <i className="ti ti-alert-triangle" aria-hidden />{' '}
              {report.failed_chunks.length} chunk{report.failed_chunks.length !== 1 ? 's' : ''} failed
            </summary>
            <ul>
              {report.failed_chunks.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </details>
        )}

        <div className="polish-cards">
          {pending.length === 0 ? (
            <p className="muted" style={{ padding: '16px' }}>
              All {acted} block{acted !== 1 ? 's' : ''} reviewed.
            </p>
          ) : (
            pending.map((f) => (
              <FlaggedCard
                key={f.block_id}
                block={f}
                onApply={onApply}
                onSkip={onSkip}
                onJumpToBlock={onJumpToBlock}
              />
            ))
          )}
        </div>

        <div className="polish-modal-footer">
          <div className="polish-modal-footer-left">
            {pending.length > 0 && (
              <>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={onApplyAll}
                >
                  Apply all ({pending.length})
                </button>
                <button type="button" onClick={onSkipAll}>
                  Skip all
                </button>
              </>
            )}
          </div>
          <button type="button" className="btn-primary" onClick={onDone}>
            Done — reload editor
          </button>
        </div>
      </div>
    </div>
  )
}

function DiffText({
  segments,
  side,
  fallback,
}: {
  segments: DiffSegment[] | undefined
  side: 'original' | 'polished'
  fallback: string
}) {
  if (!segments || segments.length === 0) return <>{fallback}</>
  return (
    <>
      {segments.map((seg, i) => {
        const text = side === 'original' ? seg.a : seg.b
        if (!text) return null
        if (
          (side === 'original' && (seg.op === 'delete' || seg.op === 'replace')) ||
          (side === 'polished' && (seg.op === 'insert' || seg.op === 'replace'))
        ) {
          return (
            <mark key={i} className={side === 'original' ? 'diff-del' : 'diff-ins'}>
              {text}
            </mark>
          )
        }
        return <span key={i}>{text}</span>
      })}
    </>
  )
}

function FlaggedCard({
  block,
  onApply,
  onSkip,
  onJumpToBlock,
}: {
  block: FlaggedBlock
  onApply: (blockId: string, content: unknown[]) => void
  onSkip: (blockId: string) => void
  onJumpToBlock: (blockId: string) => void
}) {
  return (
    <div className="polish-card">
      <div className="polish-diff">
        <div className="polish-diff-label">Original</div>
        <div className="polish-orig">
          <DiffText segments={block.diff} side="original" fallback={block.original} />
        </div>
        <div className="polish-diff-label">Polished</div>
        <div className="polish-new">
          <DiffText segments={block.diff} side="polished" fallback={block.polished} />
        </div>
      </div>
      <div className="polish-summary">{block.summary}</div>
      <div className="polish-actions">
        <button
          type="button"
          className="btn-primary"
          onClick={() => onApply(block.block_id, block.polished_content)}
        >
          Apply
        </button>
        <button type="button" onClick={() => onSkip(block.block_id)}>
          Skip
        </button>
        <button
          type="button"
          className="polish-jump-btn"
          title="Scroll to block in editor"
          onClick={() => onJumpToBlock(block.block_id)}
        >
          <i className="ti ti-crosshair" aria-hidden />
        </button>
      </div>
    </div>
  )
}
