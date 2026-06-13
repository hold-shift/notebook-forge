/** Mirror of backend narrative.strip_italic / add_italic (decision D3).
 * Operates on the plain BlockNote inline content JSON shape.
 * Typed loosely as any[] to avoid fighting BlockNote generics. */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Run = any

export function stripItalic(content: Run[]): Run[] {
  return content.map((run: Run) => {
    if (run.type === 'text') {
      const { italic: _italic, ...styles } = run.styles ?? {}
      return { ...run, styles }
    }
    if (run.type === 'link') {
      return { ...run, content: stripItalic(run.content ?? []) }
    }
    return run
  })
}

export function addItalic(content: Run[]): Run[] {
  return content.map((run: Run) => {
    if (run.type === 'text') {
      if (run.styles?.fnRef) return run
      return { ...run, styles: { ...(run.styles ?? {}), italic: true } }
    }
    if (run.type === 'link') {
      return { ...run, content: addItalic(run.content ?? []) }
    }
    return run
  })
}
