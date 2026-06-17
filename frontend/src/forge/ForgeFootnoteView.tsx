/** Presentational core of the forgeFootnote block: marker + note text,
 * rendered as the house style's inline co-located aside. The note text may
 * carry minimal inline HTML from import (one corpus footnote has <em>);
 * it is edited as raw text here. */

import { AutoTextarea } from './AutoTextarea'

export interface ForgeFootnoteProps {
  marker: string
  text: string
}

export interface ForgeFootnoteViewProps {
  props: ForgeFootnoteProps
  onTextChange?: (text: string) => void
  onMarkerChange?: (marker: string) => void
  /** Remove this footnote (note + inline reference) and renumber the rest. */
  onRemove?: () => void
}

export function ForgeFootnoteView({
  props,
  onTextChange,
  onMarkerChange,
  onRemove,
}: ForgeFootnoteViewProps) {
  return (
    <aside className="forge-footnote" role="note" data-testid="forge-footnote">
      <input
        className="forge-footnote-marker"
        value={props.marker}
        aria-label="Footnote marker"
        onChange={(e) => onMarkerChange?.(e.target.value)}
        readOnly={!onMarkerChange}
      />
      <AutoTextarea
        className="forge-footnote-text"
        value={props.text}
        aria-label="Footnote text"
        placeholder="Footnote text…"
        onChange={(e) => onTextChange?.(e.target.value)}
        readOnly={!onTextChange}
      />
      {onRemove && (
        <button
          type="button"
          className="forge-footnote-remove"
          aria-label="Remove footnote"
          title="Remove footnote and its reference, then renumber"
          contentEditable={false}
          onClick={onRemove}
        >
          <i className="ti ti-trash" aria-hidden />
        </button>
      )}
    </aside>
  )
}
