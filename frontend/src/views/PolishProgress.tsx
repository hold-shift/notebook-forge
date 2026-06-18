import { useEffect, useState } from 'react'
import { api } from '../api'

interface ProgressState {
  running: boolean
  done: number
  total: number
  failed: number
}

export function PolishProgress({
  slug,
  poll = api.polishProgress,
  heading = 'Polishing with Gemini…',
  prepLabel = 'Snapshotting and chunking…',
  unit = 'chunk',
}: {
  slug: string
  /** Progress fetcher; defaults to polish. The report pass injects
   * api.reportProgress so this same UI drives both runs. */
  poll?: (slug: string) => Promise<ProgressState>
  heading?: string
  prepLabel?: string
  unit?: string
}) {
  const [progress, setProgress] = useState<ProgressState>({
    running: true,
    done: 0,
    total: 0,
    failed: 0,
  })

  useEffect(() => {
    const id = setInterval(() => {
      poll(slug).then(
        (p) => setProgress(p),
        () => { /* transient — keep polling */ },
      )
    }, 1200)
    return () => clearInterval(id)
  }, [slug, poll])

  const pct =
    progress.total > 0 ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 0

  return (
    <div className="modal-backdrop">
      <div className="modal-box polish-progress-modal">
        <div className="modal-header">
          <h3>{heading}</h3>
        </div>
        <div className="polish-progress-body">
          {progress.total === 0 ? (
            <p className="muted">{prepLabel}</p>
          ) : (
            <>
              <div className="polish-progbar">
                <div className="polish-progbar-fill" style={{ width: `${pct}%` }} />
              </div>
              <p className="muted">
                Processing {unit} {progress.done} of {progress.total}
                {progress.failed > 0 && ` · ${progress.failed} failed`}
                {` (${pct}%)`}
              </p>
            </>
          )}
          <p className="muted polish-progress-note">
            Runs in parallel — a long document takes a few minutes.
          </p>
        </div>
      </div>
    </div>
  )
}
