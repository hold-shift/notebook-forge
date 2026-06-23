import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/**
 * A small "ⓘ" affordance that reveals a short explanation of a feature on
 * hover, focus, or click. Self-contained (no icon font / CSS file needed) and
 * safe to nest inside clickable rows — the trigger is a role="button" span (not
 * a real <button>, so it never nests illegally) and stops click propagation.
 *
 * The popover is portalled to <body> with fixed positioning so it is never
 * clipped by a scrolling/overflow ancestor (e.g. the editor side rail). `align`
 * controls which edge anchors to the icon: "right" opens leftward (for triggers
 * near the right edge of the screen).
 */
export function InfoTip({
  children,
  label = 'More information',
  align = 'left',
}: {
  children: ReactNode
  label?: string
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number } | null>(null)
  const ref = useRef<HTMLSpanElement>(null)
  const popRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open || !ref.current) {
      setPos(null)
      return
    }
    const r = ref.current.getBoundingClientRect()
    setPos(
      align === 'right'
        ? { top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) }
        : { top: r.bottom + 6, left: r.left },
    )
  }, [open, align])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node
      if (ref.current?.contains(t) || popRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = (e: { preventDefault: () => void; stopPropagation: () => void }) => {
    e.preventDefault()
    e.stopPropagation()
    setOpen((o) => !o)
  }

  const popoverStyle: CSSProperties = {
    position: 'fixed',
    top: pos?.top,
    ...(pos?.right !== undefined ? { right: pos.right } : { left: pos?.left }),
    zIndex: 200,
    width: 'max-content',
    maxWidth: 280,
    background: 'var(--color-background-primary)',
    border: '0.5px solid var(--color-border-tertiary)',
    borderRadius: 'var(--border-radius-lg)',
    boxShadow: '0 4px 16px rgba(0,0,0,.12)',
    padding: '9px 12px',
    fontSize: 12,
    fontWeight: 400,
    fontStyle: 'normal',
    lineHeight: 1.45,
    color: 'var(--color-text-secondary)',
    textAlign: 'left',
    whiteSpace: 'normal',
    cursor: 'default',
  }

  return (
    <span
      ref={ref}
      className="infotip"
      style={{ position: 'relative', display: 'inline-flex', verticalAlign: 'middle' }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span
        role="button"
        tabIndex={0}
        aria-label={label}
        aria-expanded={open}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') toggle(e)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 14,
          height: 14,
          borderRadius: '50%',
          border: '1px solid var(--color-text-tertiary)',
          color: 'var(--color-text-tertiary)',
          fontSize: 9,
          fontWeight: 700,
          fontStyle: 'italic',
          fontFamily: 'Georgia, "Times New Roman", serif',
          lineHeight: 1,
          cursor: 'pointer',
          userSelect: 'none',
          flexShrink: 0,
        }}
      >
        i
      </span>
      {open &&
        pos &&
        createPortal(
          <span ref={popRef} role="tooltip" style={popoverStyle}>
            {children}
          </span>,
          document.body,
        )}
    </span>
  )
}
