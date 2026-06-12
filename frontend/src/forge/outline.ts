/** Outline Navigator logic — pure functions, no React.
 *
 * Builds the heading tree the sidebar renders from the editor's block
 * array. The published ToC derives from this same heading structure, so
 * the lint here mirrors how build_heading_tree will treat the document:
 * a heading that skips a level (e.g. H3 with no H2 above it) gets promoted
 * oddly in the generated ToC, and is flagged.
 */

interface InlineRun {
  type?: string
  text?: string
  content?: InlineRun[]
}

export interface BlockLike {
  id: string
  type: string
  props?: Record<string, unknown>
  content?: InlineRun[] | unknown
}

export interface OutlineNode {
  id: string
  text: string
  level: number
  warn: string | null
  children: OutlineNode[]
}

function inlineText(content: unknown): string {
  if (!Array.isArray(content)) return ''
  let out = ''
  for (const run of content as InlineRun[]) {
    if (run.type === 'text') out += run.text ?? ''
    else if (run.type === 'link') out += inlineText(run.content)
  }
  return out
}

/** Single pass over the block array → nested heading tree with lint. */
export function buildOutline(blocks: BlockLike[]): OutlineNode[] {
  const headings = blocks
    .filter((b) => b.type === 'heading')
    .map((b) => ({
      id: b.id,
      text: inlineText(b.content).trim() || '(untitled heading)',
      level: Math.min(3, Math.max(1, Number(b.props?.level ?? 2))),
    }))
  if (headings.length === 0) return []

  // Baseline = the shallowest level used; a document whose chapters are H2
  // (the corpus norm) shouldn't warn on every chapter.
  const baseline = Math.min(...headings.map((h) => h.level))

  const roots: OutlineNode[] = []
  const stack: OutlineNode[] = []
  let prevLevel = baseline - 1
  for (const h of headings) {
    const skipped = h.level > prevLevel + 1
    const node: OutlineNode = {
      id: h.id,
      text: h.text,
      level: h.level,
      warn: skipped
        ? `Skips H${h.level - 1} — will indent oddly in the generated ToC`
        : null,
      children: [],
    }
    while (stack.length > 0 && stack[stack.length - 1].level >= h.level) {
      stack.pop()
    }
    if (stack.length === 0) roots.push(node)
    else stack[stack.length - 1].children.push(node)
    stack.push(node)
    prevLevel = h.level
  }
  return roots
}

export function headingIds(nodes: OutlineNode[]): string[] {
  const out: string[] = []
  const walk = (ns: OutlineNode[]) => {
    for (const n of ns) {
      out.push(n.id)
      walk(n.children)
    }
  }
  walk(nodes)
  return out
}

/** ----- collapse-state helpers (a Set of collapsed parent ids) ----- */

export function parentIds(nodes: OutlineNode[]): string[] {
  const out: string[] = []
  const walk = (ns: OutlineNode[]) => {
    for (const n of ns) {
      if (n.children.length > 0) {
        out.push(n.id)
        walk(n.children)
      }
    }
  }
  walk(nodes)
  return out
}

export function toggleCollapsed(collapsed: Set<string>, id: string): Set<string> {
  const next = new Set(collapsed)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

export function expandAll(): Set<string> {
  return new Set()
}

export function collapseAll(nodes: OutlineNode[]): Set<string> {
  return new Set(parentIds(nodes))
}
