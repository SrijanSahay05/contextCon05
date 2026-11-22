import { useState } from 'react'
import { Composer } from './components/Composer/Composer'
import { Cursor } from './components/Cursor/Cursor'
import { Sidebar } from './components/Sidebar/Sidebar'
import { StartupModal } from './components/StartupModal/StartupModal'
import { useHashRoute } from './hooks/useHashRoute'
import { useScoutSearch } from './hooks/useScoutSearch'
import { useStartups } from './hooks/useStartups'
import { FolderPage } from './pages/FolderPage/FolderPage'
import { StartupPage } from './pages/StartupPage/StartupPage'
import './App.css'

function App() {
  const store = useStartups()
  const { route, navigate } = useHashRoute()
  const scout = useScoutSearch(store.replaceDiscover)
  const [quickLook, setQuickLook] = useState<{ id: string; origin: DOMRect } | null>(null)

  const selected = quickLook ? store.byId(quickLook.id) : undefined

  const search = (thesis: string) => {
    if (route.page !== 'folder' || route.folder !== 'discover') navigate({ page: 'folder', folder: 'discover' })
    void scout.search(thesis)
  }

  return (
    <div className="app">
      <Cursor />
      <Sidebar active={route.page === 'folder' ? route.folder : null} counts={store.counts} />

      <main className="app__main">
        {route.page === 'folder' ? (
          <FolderPage
            folder={route.folder}
            items={store.inFolder(route.folder)}
            runId={scout.runId}
            busy={scout.busy && route.folder === 'discover'}
            intro={route.folder === 'discover' ? <Composer status={scout.status} onSubmit={search} /> : undefined}
            onMove={store.move}
            onSchedule={store.schedule}
            onOpen={(id, origin) => setQuickLook({ id, origin })}
          />
        ) : (
          <StartupPage
            item={store.byId(route.id)}
            onMove={store.move}
            onSchedule={store.schedule}
            onDetailLoaded={store.setDetail}
          />
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
          onDetailLoaded={store.setDetail}
        />
      )}
    </div>
  )
}

export default App
