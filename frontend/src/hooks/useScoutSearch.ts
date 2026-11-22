import { useCallback, useRef, useState } from 'react'
import { searchStartups } from '../lib/api'
import type { SearchStatus, StartupSummary } from '../types/startup'

/**
 * Runs a thesis search against the backend and hands the results to the
 * store. Only the latest search wins if several are in flight.
 */
export function useScoutSearch(onResults: (startups: StartupSummary[]) => void) {
  const [status, setStatus] = useState<SearchStatus | null>(null)
  const [runId, setRunId] = useState(0)
  const latest = useRef(0)

  const search = useCallback(
    async (thesis: string) => {
      const ticket = ++latest.current
      setStatus({ state: 'busy', thesis })
      try {
        const res = await searchStartups(thesis)
        if (ticket !== latest.current) return
        onResults(res.startups.map((s) => ({ ...s, source: 'crustdata' as const })))
        setStatus({ state: 'done', thesis, plan: res.plan, count: res.startups.length, credits: res.creditsUsed })
        setRunId((n) => n + 1)
      } catch (e) {
        if (ticket !== latest.current) return
        setStatus({ state: 'error', thesis, message: e instanceof Error ? e.message : 'Search failed' })
      }
    },
    [onResults],
  )

  return { status, runId, busy: status?.state === 'busy', search }
}
