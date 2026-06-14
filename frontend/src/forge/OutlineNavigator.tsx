/** Outline Navigator sidebar — heading tree, expand/collapse, lint flags.
 * Doubles as a live preview of the published ToC structure. */

import { useState } from 'react'
import {
  collapseAll,
  expandAll,
  toggleCollapsed,
  type OutlineNode,
} from './outline'
import { SectionLabel } from '../ui'

function Row({
  node,
  depth,
  activeId,
  collapsed,
  onToggle,
  onSelect,
}: {
  node: OutlineNode
  depth: number
  activeId: string | null
  collapsed: Set<string>
  onToggle: (id: string) => void
  onSelect: (id: string) => void
}) {
  const hasKids = node.children.length > 0
  const isCollapsed = collapsed.has(node.id)
  return (
    <>
      <div
        className={`nf-row ${activeId === node.id ? 'nf-active' : ''}`}
        style={{ paddingLeft: 6 + depth * 14 }}
        onClick={() => onSelect(node.id)}
        title={node.text}
      >
        <span
          className={`nf-caret ${hasKids ? (isCollapsed ? '' : 'nf-open') : 'nf-leaf'}`}
          onClick={(e) => {
            e.stopPropagation()
            if (hasKids) onToggle(node.id)
          }}
        >
          ▶
        </span>
        <span className="nf-label">{node.text}</span>
        {node.warn && <i className="ti ti-alert-triangle nf-warn" title={node.warn} aria-hidden />}
        <span className="nf-chip">H{node.level}</span>
      </div>
      {hasKids &&
        !isCollapsed &&
        node.children.map((c) => (
          <Row
            key={c.id}
            node={c}
            depth={depth + 1}
            activeId={activeId}
            collapsed={collapsed}
            onToggle={onToggle}
            onSelect={onSelect}
          />
        ))}
    </>
  )
}

export function OutlineNavigator({
  nodes,
  activeId,
  onSelect,
}: {
  nodes: OutlineNode[]
  activeId: string | null
  onSelect: (id: string) => void
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  return (
    <div className="nf-side" data-testid="outline-navigator">
      <div className="nf-side-head">
        <SectionLabel>Outline</SectionLabel>
        <button
          type="button"
          className="nf-ibtn"
          title="Expand all"
          onClick={() => setCollapsed(expandAll())}
        >
          <i className="ti ti-arrows-move-vertical" aria-hidden />
        </button>
        <button
          type="button"
          className="nf-ibtn"
          title="Collapse all"
          onClick={() => setCollapsed(collapseAll(nodes))}
        >
          <i className="ti ti-arrows-diff" aria-hidden style={{ transform: 'rotate(90deg)', display: 'inline-block' }} />
        </button>
      </div>
      <div className="nf-tree">
        {nodes.length === 0 && <p className="muted" style={{ padding: '4px 8px' }}>No headings yet.</p>}
        {nodes.map((n) => (
          <Row
            key={n.id}
            node={n}
            depth={0}
            activeId={activeId}
            collapsed={collapsed}
            onToggle={(id) => setCollapsed((c) => toggleCollapsed(c, id))}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  )
}
