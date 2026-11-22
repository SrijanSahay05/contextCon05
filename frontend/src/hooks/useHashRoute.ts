import { useCallback, useEffect, useState } from 'react'
import type { Folder } from '../types/startup'

export type Route = { page: 'folder'; folder: Folder } | { page: 'startup'; id: string }

const FOLDERS: Folder[] = ['discover', 'watching', 'outreach', 'discarded']

export function parseHash(hash: string): Route {
  const [, kind, value] = hash.replace(/^#/, '').split('/')
  if (kind === 'startup' && value) return { page: 'startup', id: decodeURIComponent(value) }
  if (FOLDERS.includes(kind as Folder)) return { page: 'folder', folder: kind as Folder }
  return { page: 'folder', folder: 'discover' }
}

export const hrefFor = (route: Route) =>
  route.page === 'startup' ? `#/startup/${encodeURIComponent(route.id)}` : `#/${route.folder}`

/** Tiny hash router: enough for a few pages without a dependency. */
export function useHashRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash))
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const navigate = useCallback((to: Route) => {
    window.location.hash = hrefFor(to)
  }, [])

  return { route, navigate }
}
