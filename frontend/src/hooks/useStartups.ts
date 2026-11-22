import { useCallback, useMemo, useReducer } from 'react'
import { SAMPLE_STARTUPS } from '../data/startups'
import type { Folder, Item } from '../types/startup'

type Action = { type: 'move'; id: string; to: Folder } | { type: 'schedule'; id: string }

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
  }
}

/** Client-side store for the prototype. */
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

  return { items, counts, inFolder, byId, move, schedule }
}

export type StartupStore = ReturnType<typeof useStartups>
