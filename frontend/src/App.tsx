import { useRef, useState } from 'react'
import { Composer } from './components/Composer/Composer'
import { Cursor } from './components/Cursor/Cursor'
import { Sidebar } from './components/Sidebar/Sidebar'
import { StartupModal } from './components/StartupModal/StartupModal'
import { useHashRoute } from './hooks/useHashRoute'
import { useStartups } from './hooks/useStartups'
import { FolderPage } from './pages/FolderPage/FolderPage'
import { StartupPage } from './pages/StartupPage/StartupPage'
import type { SearchStatus } from './types/startup'
import './App.css'

// Long enough to see the scouting animation; the real search will set its own pace.
const SEARCH_DELAY_MS = 3200

function App() {
  const store = useStartups()
  const { route, navigate } = useHashRoute()
  const [quickLook, setQuickLook] = useState<{ id: string; origin: DOMRect } | null>(null)
  const [status, setStatus] = useState<SearchStatus | null>(null)
  const [runId, setRunId] = useState(0)
  const timer = useRef<number | undefined>(undefined)

  // Stand-in for a real search: pretend to scout, then re-run the list.
  const search = (thesis: string) => {
    if (route.page !== 'folder' || route.folder !== 'discover') navigate({ page: 'folder', folder: 'discover' })
    setStatus({ state: 'busy', thesis })
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      setStatus({ state: 'done', thesis })
      setRunId((n) => n + 1)
    }, SEARCH_DELAY_MS)
  }

  const busy = status?.state === 'busy'
  const selected = quickLook ? store.byId(quickLook.id) : undefined

  return (
    <div className="app">
      <Cursor />
      <Sidebar active={route.page === 'folder' ? route.folder : null} counts={store.counts} />

      <main className="app__main">
        {route.page === 'folder' ? (
          <FolderPage
            folder={route.folder}
            items={store.inFolder(route.folder)}
            runId={runId}
            busy={busy && route.folder === 'discover'}
            intro={route.folder === 'discover' ? <Composer status={status} onSubmit={search} /> : undefined}
            onMove={store.move}
            onSchedule={store.schedule}
            onOpen={(id, origin) => setQuickLook({ id, origin })}
          />
        ) : (
          <StartupPage item={store.byId(route.id)} onMove={store.move} onSchedule={store.schedule} />
        )}
      </main>

      {selected && quickLook && (
        <StartupModal
          item={selected}
          origin={quickLook.origin}
          onClose={() => setQuickLook(null)}
          onOpenPage={() => navigate({ page: 'startup', id: selected.id })}
          onMove={(to) => store.move(selected.id, to)}
          onSchedule={() => store.schedule(selected.id)}
        />
      )}
    </div>
  )
}

export default App
