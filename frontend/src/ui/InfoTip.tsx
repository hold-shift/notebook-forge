import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

/**
 * A small "ⓘ" affordance that reveals a short explanation of a feature on
 * hover, focus, or click. Self-contained (no icon font / CSS file needed) and
 * safe to nest inside clickable rows — the trigger is a role="button" span (not
 * a real <button>, so it never nests illegally) and stops click propagation.
 *
 * `align` controls which edge of the popover anchors to the icon: use "right"
 * for triggers near the right edge of the screen so the popover opens leftward
 * and doesn't clip.
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
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
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
    position: 'absolute',
    top: 'calc(100% + 6px)',
    ...(align === 'right' ? { right: 0 } : { left: 0 }),
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
      {open && (
        <span role="tooltip" style={popoverStyle}>
          {children}
        </span>
      )}
    </span>
  )
}
