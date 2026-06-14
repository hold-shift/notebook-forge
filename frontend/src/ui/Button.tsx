import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
export type ButtonSize = 'sm' | 'md'

const BASE: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  borderRadius: 'var(--border-radius-md)',
  cursor: 'pointer',
  fontWeight: 500,
  fontFamily: 'inherit',
  transition: 'background 0.12s, border-color 0.12s, opacity 0.12s',
  whiteSpace: 'nowrap',
}

const VARIANT_STYLES: Record<ButtonVariant, React.CSSProperties> = {
  primary: {
    background: 'var(--color-text-primary)',
    color: 'var(--color-background-primary)',
    border: 'none',
  },
  secondary: {
    background: 'transparent',
    color: 'var(--color-text-primary)',
    border: '0.5px solid var(--color-border-tertiary)',
  },
  danger: {
    background: 'var(--color-background-primary)',
    color: 'var(--pill-danger-fg)',
    border: '0.5px solid var(--color-border-error, #e8b4b4)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--color-text-secondary)',
    border: 'none',
  },
}

const SIZE_STYLES: Record<ButtonSize, React.CSSProperties> = {
  sm: { padding: '3px 10px', fontSize: 12 },
  md: { padding: '5px 12px', fontSize: 13 },
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  children: ReactNode
}

export function Button({ variant = 'secondary', size = 'md', style, children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      style={{
        ...BASE,
        ...VARIANT_STYLES[variant],
        ...SIZE_STYLES[size],
        ...(rest.disabled ? { opacity: 0.55, cursor: 'default' } : {}),
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  )
}
