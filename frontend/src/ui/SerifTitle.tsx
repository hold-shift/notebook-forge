import type { ReactNode, ElementType } from 'react'

interface SerifTitleProps {
  children: ReactNode
  as?: ElementType
  style?: React.CSSProperties
  className?: string
}

export function SerifTitle({ children, as: Tag = 'h2', style, className }: SerifTitleProps) {
  return (
    <Tag
      className={className}
      style={{
        fontFamily: 'var(--font-serif)',
        fontWeight: 400,
        fontSize: 14,
        margin: 0,
        ...style,
      }}
    >
      {children}
    </Tag>
  )
}
