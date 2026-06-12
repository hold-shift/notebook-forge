import type { FlaggedBlock, PolishReport } from '../api'

interface PolishReviewProps {
  report: PolishReport
  onApply: (blockId: string, content: unknown[]) => void
  onSkip: (blockId: string) => void
  onDone: () => void
  remaining: Set<string>
}

export function PolishReview({ report, onApply, onSkip, onDone, remaining }: PolishReviewProps) {
  const pending = report.flagged.filter((f) => remaining.has(f.block_id))
  const acted = report.flagged.length - pending.length

  return (
    <div className="polish-review">
      <div className="polish-review-head">
        <h3>Polish review</h3>
        <p className="muted">
          {report.blocks_polished} block{report.blocks_polished !== 1 ? 's' : ''} auto-applied
          &nbsp;·&nbsp;
          {report.flagged.length} to review
          {report.blocks_unchanged > 0 && ` · ${report.blocks_unchanged} unchanged`}
          <br />
          <span className="polish-model">{report.model}</span>
        </p>
        {report.failed_chunks.length > 0 && (
          <p className="error" style={{ fontSize: '0.8em' }}>
            <i className="ti ti-alert-triangle" aria-hidden /> {report.failed_chunks.length} chunk(s) failed
          </p>
        )}
      </div>

      {pending.length === 0 ? (
        <p className="muted" style={{ padding: '8px 0' }}>
          All {acted} block{acted !== 1 ? 's' : ''} reviewed.
        </p>
      ) : (
        <div className="polish-cards">
          {pending.map((f) => (
            <FlaggedCard key={f.block_id} block={f} onApply={onApply} onSkip={onSkip} />
          ))}
        </div>
      )}

      <button type="button" className="btn-primary" style={{ marginTop: 8 }} onClick={onDone}>
        Done — reload editor
      </button>
    </div>
  )
}

function FlaggedCard({
  block,
  onApply,
  onSkip,
}: {
  block: FlaggedBlock
  onApply: (blockId: string, content: unknown[]) => void
  onSkip: (blockId: string) => void
}) {
  return (
    <div className="polish-card">
      <div className="polish-diff">
        <div className="polish-diff-label">Original</div>
        <div className="polish-orig">{block.original}</div>
        <div className="polish-diff-label">Polished</div>
        <div className="polish-new">{block.polished}</div>
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
      </div>
    </div>
  )
}
