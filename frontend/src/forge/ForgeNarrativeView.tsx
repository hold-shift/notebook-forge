/** Presentational wrapper for the forgeNarrative block in the editor.
 * Full editor-body width, warm tinted panel — the in-editor twin of
 * div.narrative on the published page. No label in the editor (D10). */

export function ForgeNarrativeView({ contentRef }: { contentRef: React.Ref<HTMLElement> }) {
  return (
    <div className="forge-narrative" data-testid="forge-narrative">
      <p className="forge-narrative-text" ref={contentRef as React.Ref<HTMLParagraphElement>} />
    </div>
  )
}
