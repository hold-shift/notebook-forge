/** After a batch sketch job persists sketches server-side, the editor's
 * in-memory blocks are stale. This computes the minimal set of forgeImage
 * prop updates to pull the server's sketch state back into the editor —
 * only the sketch-related props, so unsaved prose edits are preserved.
 *
 * Typed loosely as any to avoid fighting BlockNote's editor generics. */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Block = any

const SKETCH_PROPS = ['sketchAssetId', 'faceGate', 'approval'] as const

export interface SketchUpdate {
  id: string
  props: Record<string, unknown>
}

/** Updates needed to bring `editorBlocks` forgeImage sketch props in line with
 * `serverBlocks`. Returns one entry per changed block (empty if all in sync). */
export function imageSketchUpdates(editorBlocks: Block[], serverBlocks: Block[]): SketchUpdate[] {
  const serverProps = new Map<string, Record<string, unknown>>(
    serverBlocks
      .filter((b) => b.type === 'forgeImage')
      .map((b) => [b.id as string, (b.props ?? {}) as Record<string, unknown>]),
  )
  const updates: SketchUpdate[] = []
  for (const b of editorBlocks) {
    if (b.type !== 'forgeImage') continue
    const sp = serverProps.get(b.id)
    if (!sp) continue
    const cur = (b.props ?? {}) as Record<string, unknown>
    if (SKETCH_PROPS.some((k) => sp[k] !== cur[k])) {
      updates.push({
        id: b.id,
        props: {
          ...cur,
          sketchAssetId: sp.sketchAssetId,
          faceGate: sp.faceGate,
          approval: sp.approval,
        },
      })
    }
  }
  return updates
}
