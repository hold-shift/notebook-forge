/** Footnote add / remove / renumber for the editor.
 *
 * A footnote is two linked pieces, matched by their literal number:
 *   - an inline REFERENCE: a text run carrying `styles.fnRef` whose text is
 *     the marker number (the superscript in prose), and
 *   - a NOTE: a `forgeFootnote` block with `props.marker` + `props.text`,
 *     co-located after the referencing paragraph.
 *
 * Renumbering mirrors the backend (ingest_vendor/renumber.py): footnotes are
 * sequenced 1..N by the order their inline reference first appears in the
 * document. Refs with no matching note (and notes with no ref) are left
 * untouched so nothing is silently destroyed.
 *
 * Typed loosely as any to avoid fighting BlockNote's editor generics. */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Run = any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Block = any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Editor = any

function isFnRef(run: Run): boolean {
  return run?.type === 'text' && !!run.styles?.fnRef
}

/** Visit every fnRef text run in document order (recursing links + children). */
function eachRefRun(blocks: Block[], fn: (run: Run) => void): void {
  const walkContent = (content: Run[] | undefined): void => {
    for (const run of content ?? []) {
      if (isFnRef(run)) fn(run)
      else if (run?.type === 'link') walkContent(run.content)
    }
  }
  const walkBlocks = (bs: Block[]): void => {
    for (const b of bs) {
      walkContent(b.content)
      if (b.children?.length) walkBlocks(b.children)
    }
  }
  walkBlocks(blocks)
}

/** Every forgeFootnote block, depth-first. */
function eachNote(blocks: Block[], fn: (b: Block) => void): void {
  for (const b of blocks) {
    if (b.type === 'forgeFootnote') fn(b)
    if (b.children?.length) eachNote(b.children, fn)
  }
}

export function collectNoteMarkers(blocks: Block[]): string[] {
  const out: string[] = []
  eachNote(blocks, (b) => out.push(String(b.props?.marker ?? '').trim()))
  return out
}

/** Order-of-first-reference map old-marker → new-number ("1".."N"), built
 * only from references that have a matching note (mirrors the backend). */
export function buildRenumberMap(blocks: Block[]): Map<string, string> {
  const notes = new Set(collectNoteMarkers(blocks))
  const firstSeen: string[] = []
  eachRefRun(blocks, (run) => {
    const m = String(run.text ?? '').trim()
    if (notes.has(m) && !firstSeen.includes(m)) firstSeen.push(m)
  })
  const map = new Map<string, string>()
  firstSeen.forEach((old, i) => map.set(old, String(i + 1)))
  return map
}

function applyMap(blocks: Block[], map: Map<string, string>): Block[] {
  const mapContent = (content: Run[] | undefined): Run[] | undefined => {
    if (!content) return content
    return content.map((run) => {
      if (isFnRef(run)) {
        const nw = map.get(String(run.text ?? '').trim())
        return nw ? { ...run, text: nw } : run
      }
      if (run?.type === 'link') return { ...run, content: mapContent(run.content) }
      return run
    })
  }
  const mapBlock = (b: Block): Block => {
    let nb = b
    if (b.type === 'forgeFootnote') {
      const nw = map.get(String(b.props?.marker ?? '').trim())
      if (nw) nb = { ...nb, props: { ...nb.props, marker: nw } }
    }
    const content = mapContent(nb.content)
    const children = nb.children?.length ? nb.children.map(mapBlock) : nb.children
    return { ...nb, content, children }
  }
  return blocks.map(mapBlock)
}

/** Re-sequence footnotes 1..N by order of first reference. Returns the same
 * array reference (and changed=false) when no number actually moves. */
export function renumberFootnotes(blocks: Block[]): { blocks: Block[]; changed: boolean } {
  const map = buildRenumberMap(blocks)
  let changed = false
  map.forEach((nw, old) => {
    if (nw !== old) changed = true
  })
  if (!changed) return { blocks, changed: false }
  return { blocks: applyMap(blocks, map), changed: true }
}

/** A temporary marker guaranteed not to collide with any existing one
 * (max numeric marker + 1). Renumbering then assigns its real position. */
export function nextTempMarker(blocks: Block[]): string {
  let max = 0
  const consider = (s: string): void => {
    const n = parseInt(s, 10)
    if (!Number.isNaN(n) && n > max) max = n
  }
  collectNoteMarkers(blocks).forEach(consider)
  eachRefRun(blocks, (r) => consider(String(r.text ?? '').trim()))
  return String(max + 1)
}

/** Drop a footnote: remove its note block(s) AND every inline reference
 * carrying its marker, then renumber the survivors. Pure — returns new blocks. */
export function removeFootnote(blocks: Block[], marker: string): Block[] {
  const target = String(marker ?? '').trim()
  const stripContent = (content: Run[] | undefined): Run[] | undefined => {
    if (!content) return content
    return content
      .filter((run) => !(isFnRef(run) && String(run.text ?? '').trim() === target))
      .map((run) =>
        run?.type === 'link' ? { ...run, content: stripContent(run.content) } : run,
      )
  }
  const filterBlocks = (bs: Block[]): Block[] =>
    bs
      .filter(
        (b) => !(b.type === 'forgeFootnote' && String(b.props?.marker ?? '').trim() === target),
      )
      .map((b) => ({
        ...b,
        content: stripContent(b.content),
        children: b.children?.length ? filterBlocks(b.children) : b.children,
      }))
  return renumberFootnotes(filterBlocks(blocks)).blocks
}

// ---- editor-bound operations (live BlockNote editor) ----

/** Insert a footnote reference at the cursor + a co-located note block right
 * after the current block, then renumber the whole document. */
export function addFootnoteAtCursor(editor: Editor): void {
  const cur = editor.getTextCursorPosition?.()?.block
  if (!cur) return
  const temp = nextTempMarker(editor.document)
  editor.insertInlineContent([{ type: 'text', text: temp, styles: { fnRef: true } }])
  editor.insertBlocks([{ type: 'forgeFootnote', props: { marker: temp, text: '' } }], cur, 'after')
  const { blocks, changed } = renumberFootnotes(editor.document)
  if (changed) editor.replaceBlocks(editor.document, blocks)
}

/** Remove the footnote with this marker (note + reference) and renumber. */
export function removeFootnoteFromEditor(editor: Editor, marker: string): void {
  editor.replaceBlocks(editor.document, removeFootnote(editor.document, marker))
}
