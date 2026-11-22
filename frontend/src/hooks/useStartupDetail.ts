import { useCallback, useEffect, useState } from 'react'
import { fetchStartupDetail } from '../lib/api'
import type { Item, StartupDetail } from '../types/startup'

/**
 * Loads the detail for a live startup the first time it's opened, then keeps
 * it on the item so reopening is instant. Sample startups carry their detail.
 */
export function useStartupDetail(item: Item | undefined, onLoaded: (id: string, detail: StartupDetail) => void) {
  // The failure is keyed by startup, so opening another one starts clean.
  const [failure, setFailure] = useState<{ id: string; message: string } | null>(null)
  const [attempt, setAttempt] = useState(0)

  const id = item?.id
  const crustdataId = item?.crustdataId
  const failed = !!failure && failure.id === id
  const needsFetch = !!item && !item.detail && item.source === 'crustdata' && crustdataId != null

  useEffect(() => {
    if (!needsFetch || failed || !id || crustdataId == null) return
    let cancelled = false
    fetchStartupDetail(crustdataId)
      .then((detail) => !cancelled && onLoaded(id, detail))
      .catch(
        (e: unknown) =>
          !cancelled && setFailure({ id, message: e instanceof Error ? e.message : 'Could not load details' }),
      )
    return () => {
      cancelled = true
    }
  }, [needsFetch, failed, id, crustdataId, onLoaded, attempt])

  const retry = useCallback(() => {
    setFailure(null)
    setAttempt((n) => n + 1)
  }, [])

  return { detail: item?.detail, loading: needsFetch && !failed, error: failed ? failure.message : null, retry }
}
