import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload } from '../api/types'
import { CONDITION_LABEL } from '../lib/format'
import { EmptyState, Sheet } from './ui'

/**
 * "Into which list?" — Rebrickable has no default-list concept the app can rely on, so every
 * add-to-collection path has to ask. Shared by the set detail sheet and by the bulk actions on
 * Historique / Liste cadeaux / Nouveaux sets.
 */
export default function ListPickerSheet({
  open,
  onClose,
  onPick,
  title = 'Ajouter à la collection',
}: {
  open: boolean
  onClose: () => void
  onPick: (listId: number) => void
  title?: string
}) {
  const { data } = useQuery({
    queryKey: ['collection'],
    queryFn: () => api.get<CollectionPayload>('/collection'),
    enabled: open,
  })

  const lists = data?.lists ?? []

  return (
    <Sheet open={open} title={title} onClose={onClose}>
      {lists.length === 0 ? (
        <EmptyState
          title="Aucune liste Rebrickable"
          message="Synchronisez votre collection, ou créez une liste sur rebrickable.com."
        />
      ) : (
        <div className="space-y-2">
          {lists.map((list) => (
            <button
              key={list.id}
              type="button"
              className="btn-secondary w-full justify-between"
              onClick={() => onPick(list.id)}
            >
              <span>{list.name}</span>
              <span className="text-[13px] text-ink-faint">{CONDITION_LABEL[list.condition]}</span>
            </button>
          ))}
        </div>
      )}
    </Sheet>
  )
}
