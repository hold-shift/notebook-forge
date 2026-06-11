import { useCallback, useEffect, useRef, useState } from 'react'
import { BlockNoteView } from '@blocknote/mantine'
import { useCreateBlockNote } from '@blocknote/react'
import type { PartialBlock } from '@blocknote/core'
import '@blocknote/core/fonts/inter.css'
import '@blocknote/mantine/style.css'
import { api, type DocDetail, type TargetState } from '../api'
import { forgeSchema } from '../forge/schema'

const AUTOSAVE_MS = 1200

function PendingPanel({
  targets,
  onPush,
  pushing,
}: {
  targets: TargetState[]
  onPush: (target: string) => void
  pushing: string | null
}) {
  return (
    <div className="pending-panel">
      <h3>Targets</h3>
      {targets.map((t) => (
        <div key={t.target} className="pending-row">
          <span className={`dot ${t.dirty ? 'dirty' : 'clean'}`} />
          <span className="pending-name">{t.target}</span>
          <span className="pending-state">
            {t.dirty ? 'pending changes' : t.status === 'PUBLISHED' ? 'clean' : t.status}
            {t.published_at ? ` · published ${t.published_at.slice(0, 10)}` : ''}
          </span>
          <button
            type="button"
            disabled={!t.dirty || pushing === t.target}
            onClick={() => onPush(t.target)}
          >
            {pushing === t.target ? 'Pushing…' : 'Push'}
          </button>
        </div>
      ))}
    </div>
  )
}

function EditorInner({ doc, onBack }: { doc: DocDetail; onBack: () => void }) {
  const [targets, setTargets] = useState<TargetState[]>(doc.targets)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [pushing, setPushing] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(null)

  const editor = useCreateBlockNote({
    schema: forgeSchema,
    initialContent: doc.blocks as PartialBlock<typeof forgeSchema.blockSchema>[],
  })

  const save = useCallback(() => {
    setSaveState('saving')
    api.saveBlocks(doc.slug, editor.document).then(
      (resp) => {
        setTargets(resp.targets)
        setSaveState('saved')
      },
      () => setSaveState('error'),
    )
  }, [doc.slug, editor])

  const onChange = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(save, AUTOSAVE_MS)
  }, [save])

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  const onPush = useCallback(
    (target: string) => {
      setPushing(target)
      api.publish(doc.slug, target).then(
        (resp) => {
          setTargets(resp.targets)
          setPushing(null)
        },
        (e) => {
          setPushing(null)
          alert(`Publish failed: ${e}`)
        },
      )
    },
    [doc.slug],
  )

  return (
    <div className="editor-screen">
      <header className="editor-header">
        <button type="button" onClick={onBack}>
          ← Library
        </button>
        <div className="editor-titles">
          <h2>{doc.title}</h2>
          <span className="muted">{String(doc.meta.year_display ?? '')}</span>
        </div>
        <span className={`save-state ${saveState}`}>
          {saveState === 'saving'
            ? 'Saving…'
            : saveState === 'saved'
              ? 'Saved'
              : saveState === 'error'
                ? 'Save failed'
                : ''}
        </span>
      </header>
      <div className="editor-body">
        <div className="editor-canvas">
          <BlockNoteView editor={editor} onChange={onChange} theme="light" />
        </div>
        <PendingPanel targets={targets} onPush={onPush} pushing={pushing} />
      </div>
    </div>
  )
}

export function Editor({ slug, onBack }: { slug: string; onBack: () => void }) {
  const [doc, setDoc] = useState<DocDetail | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setDoc(null)
    api.getDocument(slug).then(setDoc, (e) => setError(String(e)))
  }, [slug])

  if (error) return <p className="error">{error}</p>
  if (!doc) return <p className="muted">Loading {slug}…</p>
  return <EditorInner doc={doc} onBack={onBack} />
}
