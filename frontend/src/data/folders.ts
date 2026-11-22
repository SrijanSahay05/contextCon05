import type { Folder } from '../types/startup'

export interface FolderMeta {
  id: Folder
  label: string
  /** How a startup in this folder is described elsewhere, e.g. on its page. */
  status: string
  title: string
  subtitle: string
  empty: string
}

export const FOLDERS: FolderMeta[] = [
  {
    id: 'discover',
    status: 'Recommended',
    label: 'For you',
    title: 'Find what’s next.',
    subtitle: 'Tell us how you invest. We’ll scout the companies worth your time, and show why.',
    empty: 'Nothing new right now. Refine your thesis above to widen the search.',
  },
  {
    id: 'watching',
    status: 'Watching',
    label: 'Watching',
    title: 'Watching',
    subtitle: 'Companies you’re tracking. Each one is re-checked on a schedule set by its momentum.',
    empty: 'Watch a startup to track it here.',
  },
  {
    id: 'outreach',
    status: 'In outreach',
    label: 'In outreach',
    title: 'In outreach',
    subtitle: 'Conversations in progress, with their status and next step.',
    empty: 'Startups you reach out to appear here.',
  },
  {
    id: 'discarded',
    status: 'Discarded',
    label: 'Discarded',
    title: 'Discarded',
    subtitle: 'Passed for now. Restore any of them at any time.',
    empty: 'Nothing discarded.',
  },
]

export const folderMeta = (id: Folder) => FOLDERS.find((f) => f.id === id) ?? FOLDERS[0]
