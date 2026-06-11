import { useEffect, useState } from 'react'
import { Library } from './views/Library'
import { Editor } from './views/Editor'
import { Settings } from './views/Settings'

type Route = { view: 'library' } | { view: 'settings' } | { view: 'doc'; slug: string }

function routeFromHash(): Route {
  const hash = window.location.hash
  if (hash === '#/settings') return { view: 'settings' }
  const m = hash.match(/^#\/doc\/(.+)$/)
  if (m) return { view: 'doc', slug: decodeURIComponent(m[1]) }
  return { view: 'library' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash())

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const toLibrary = () => {
    window.location.hash = ''
  }

  if (route.view === 'doc') return <Editor slug={route.slug} onBack={toLibrary} />
  if (route.view === 'settings') return <Settings onBack={toLibrary} />
  return (
    <Library
      onOpen={(s) => {
        window.location.hash = `#/doc/${encodeURIComponent(s)}`
      }}
      onSettings={() => {
        window.location.hash = '#/settings'
      }}
    />
  )
}
