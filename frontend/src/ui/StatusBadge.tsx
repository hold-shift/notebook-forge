import type { ReactNode } from 'react'

export type BadgeVariant = 'live' | 'changes' | 'unpublished' | 'polished' | 'flagged' | 'never-run' | 'stale'

interface BadgeConfig {
  bg: string
  fg: string
  border: string
  dot: string
  label: string
}

const CONFIGS: Record<BadgeVariant, BadgeConfig> = {
  live: {
    bg: 'var(--badge-live-bg)',
    fg: 'var(--badge-live-fg)',
    border: 'var(--badge-live-border)',
    dot: 'var(--color-pine)',
    label: 'Live',
  },
  changes: {
    bg: 'var(--badge-changes-bg)',
    fg: 'var(--badge-changes-fg)',
    border: 'var(--badge-changes-border)',
    dot: 'var(--color-tan)',
    label: 'Changes',
  },
  unpublished: {
    bg: 'var(--badge-unpublished-bg)',
    fg: 'var(--badge-unpublished-fg)',
    border: 'var(--badge-unpublished-border)',
    dot: 'var(--color-text-tertiary)',
    label: 'Unpublished',
  },
  polished: {
    bg: 'var(--badge-polished-bg)',
    fg: 'var(--badge-polished-fg)',
    border: 'var(--badge-polished-border)',
    dot: 'var(--color-pine)',
    label: 'Polished',
  },
  flagged: {
    bg: 'var(--badge-flagged-bg)',
    fg: 'var(--badge-flagged-fg)',
    border: 'var(--badge-flagged-border)',
    dot: 'var(--color-amber)',
    label: 'Flagged',
  },
  'never-run': {
    bg: 'var(--badge-never-bg)',
    fg: 'var(--badge-never-fg)',
    border: 'var(--badge-never-border)',
    dot: 'var(--color-text-tertiary)',
    label: 'Not polished',
  },
  stale: {
    bg: 'var(--badge-changes-bg)',
    fg: 'var(--badge-changes-fg)',
    border: 'var(--badge-changes-border)',
    dot: 'var(--color-tan)',
    label: 'Stale',
  },
}

interface StatusBadgeProps {
  variant: BadgeVariant
  label?: ReactNode
}

export function StatusBadge({ variant, label }: StatusBadgeProps) {
  const cfg = CONFIGS[variant]
  return (
    <span
      data-badge-variant={variant}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        borderRadius: 999,
        padding: '3px 10px',
        fontSize: 11,
        background: cfg.bg,
        color: cfg.fg,
        border: `0.5px solid ${cfg.border}`,
        whiteSpace: 'nowrap',
      }}
    >
      <span
        data-badge-dot
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: cfg.dot,
          flexShrink: 0,
        }}
      />
      {label ?? cfg.label}
    </span>
  )
}
