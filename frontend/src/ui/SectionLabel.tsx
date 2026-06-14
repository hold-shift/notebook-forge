import type { ReactNode } from 'react'

interface SectionLabelProps {
  children: ReactNode
  style?: React.CSSProperties
}

export function SectionLabel({ children, style }: SectionLabelProps) {
  return (
    <span
      style={{
        color: 'var(--color-text-secondary)',
        fontSize: 11,
        fontWeight: 500,
        letterSpacing: '0.04em',
        ...style,
      }}
    >
      {children}
    </span>
  )
}
