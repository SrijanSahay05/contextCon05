import type { Folder, Item } from '../../types/startup'
import { Calendar, Restore, Send, Star, Tray } from '../Icons/Icons'
import './StartupActions.css'

interface Props {
  item: Item
  onMove: (to: Folder) => void
  onSchedule: () => void
  size?: 'md' | 'lg'
}

/** The actions available for a startup, depending on which folder it's in. */
export function StartupActions({ item, onMove, onSchedule, size = 'md' }: Props) {
  const lg = size === 'lg' ? ' btn--lg' : ''

  if (item.folder === 'discarded') {
    return (
      <div className="startup-actions">
        <button
          type="button"
          className={`btn btn--tinted${lg}`}
          onClick={() => onMove(item.previousFolder ?? 'discover')}
        >
          <Restore /> Restore
        </button>
      </div>
    )
  }

  const booked = item.outreach?.status === 'Meeting booked'

  return (
    <div className="startup-actions">
      {item.folder === 'discover' && (
        <button type="button" className={`btn btn--tinted${lg}`} onClick={() => onMove('watching')}>
          <Star /> Watch
        </button>
      )}
      {item.folder === 'outreach' ? (
        <button type="button" className={`btn btn--primary${lg}`} disabled={booked} onClick={onSchedule}>
          <Calendar /> {booked ? 'Scheduled' : 'Schedule meet'}
        </button>
      ) : (
        <button type="button" className={`btn btn--primary${lg}`} onClick={() => onMove('outreach')}>
          <Send /> Reach out
        </button>
      )}
      <button
        type="button"
        className={`btn btn--icon btn--danger${lg}`}
        aria-label={`Discard ${item.name}`}
        title="Discard"
        onClick={() => onMove('discarded')}
      >
        <Tray size={16} />
      </button>
    </div>
  )
}
