import { useCallback, useMemo, useReducer } from 'react'
import { SAMPLE_STARTUPS } from '../data/startups'
import type { Folder, Item, StartupDetail, StartupSummary } from '../types/startup'

type Action =
  | { type: 'move'; id: string; to: Folder }
  | { type: 'schedule'; id: string }
  | { type: 'replaceDiscover'; startups: StartupSummary[] }
  | { type: 'setDetail'; id: string; detail: StartupDetail }

function updateItem(items: Item[], id: string, fn: (item: Item) => Item) {
  return items.map((item) => (item.id === id ? fn(item) : item))
}

function reducer(items: Item[], action: Action): Item[] {
  switch (action.type) {
    case 'move':
      return updateItem(items, action.id, (item) => ({
        ...item,
        folder: action.to,
        previousFolder: action.to === 'discarded' ? item.folder : undefined,
        outreach:
          action.to === 'outreach' && !item.outreach
            ? { status: 'Drafting intro', nextStep: 'Awaiting your approval' }
            : item.outreach,
      }))
    case 'schedule':
      return updateItem(items, action.id, (item) => ({
        ...item,
        outreach: { status: 'Meeting booked', nextStep: 'Thu, 11:00 AM' },
      }))
    case 'setDetail':
      return updateItem(items, action.id, (item) => ({ ...item, detail: action.detail }))
    case 'replaceDiscover': {
      // A new search replaces "For you", but never touches startups the
      // investor already filed elsewhere (watching, outreach, discarded).
      const kept = items.filter((i) => i.folder !== 'discover')
      const filed = new Set(kept.map((i) => i.id))
      const fresh: Item[] = action.startups.filter((s) => !filed.has(s.id)).map((s) => ({ ...s, folder: 'discover' }))
      return [...fresh, ...kept]
    }
  }
}

/** Client-side store. Searches and details come from the backend; folders live here for now. */
export function useStartups() {
  const [items, dispatch] = useReducer(reducer, SAMPLE_STARTUPS)

  const counts = useMemo(() => {
    const c: Record<Folder, number> = { discover: 0, watching: 0, outreach: 0, discarded: 0 }
    for (const i of items) c[i.folder]++
    return c
  }, [items])

  const inFolder = useCallback(
    (folder: Folder) => items.filter((i) => i.folder === folder).sort((a, b) => b.score - a.score),
    [items],
  )

  const byId = useCallback((id: string) => items.find((i) => i.id === id), [items])
  const move = useCallback((id: string, to: Folder) => dispatch({ type: 'move', id, to }), [])
  const schedule = useCallback((id: string) => dispatch({ type: 'schedule', id }), [])
  const replaceDiscover = useCallback(
    (startups: StartupSummary[]) => dispatch({ type: 'replaceDiscover', startups }),
    [],
  )
  const setDetail = useCallback((id: string, detail: StartupDetail) => dispatch({ type: 'setDetail', id, detail }), [])

  return { items, counts, inFolder, byId, move, schedule, replaceDiscover, setDetail }
}

export type StartupStore = ReturnType<typeof useStartups>
