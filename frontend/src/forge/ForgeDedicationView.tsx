/** Presentational core of the forgeDedication block: a centered italic
 * dedication line, styled to match the published .dedication class. */

export interface ForgeDedicationViewProps {
  text: string
  onChange?: (text: string) => void
}

export function ForgeDedicationView({ text, onChange }: ForgeDedicationViewProps) {
  return (
    <div className="forge-dedication-wrap" data-testid="forge-dedication">
      <input
        className="forge-dedication-input"
        value={text}
        placeholder="Dedication…"
        aria-label="Dedication text"
        onChange={(e) => onChange?.(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
        }}
        readOnly={!onChange}
      />
    </div>
  )
}
