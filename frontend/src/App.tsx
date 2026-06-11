import { useEffect, useState } from 'react'
import { Library } from './views/Library'
import { Editor } from './views/Editor'

function slugFromHash(): string | null {
  const m = window.location.hash.match(/^#\/doc\/(.+)$/)
  return m ? decodeURIComponent(m[1]) : null
}

export default function App() {
  const [slug, setSlug] = useState<string | null>(slugFromHash())

  useEffect(() => {
    const onHash = () => setSlug(slugFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  if (slug) {
    return (
      <Editor
        slug={slug}
        onBack={() => {
          window.location.hash = ''
        }}
      />
    )
  }
  return (
    <Library
      onOpen={(s) => {
        window.location.hash = `#/doc/${encodeURIComponent(s)}`
      }}
    />
  )
}
