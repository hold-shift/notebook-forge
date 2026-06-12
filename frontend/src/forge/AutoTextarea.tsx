import { useLayoutEffect, useRef } from 'react'

interface AutoTextareaProps {
  className?: string
  value: string
  placeholder?: string
  readOnly?: boolean
  'aria-label'?: string
  onChange?: (e: React.ChangeEvent<HTMLTextAreaElement>) => void
}

/** Single-line-feeling textarea that grows to fit its content automatically. */
export function AutoTextarea({ value, onChange, ...rest }: AutoTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = '0'
    el.style.height = el.scrollHeight + 'px'
  }, [value])
  return (
    <textarea
      ref={ref}
      rows={1}
      value={value}
      onChange={onChange}
      {...rest}
    />
  )
}
