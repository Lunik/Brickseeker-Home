import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload } from '../api/types'
import { CONDITION_LABEL } from '../lib/format'
import { EmptyState, ErrorLabel, Sheet, Spinner } from './ui'

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
  const queryClient = useQueryClient()
  const [newName, setNewName] = useState('')

  const { data } = useQuery({
    queryKey: ['collection'],
    queryFn: () => api.get<CollectionPayload>('/collection'),
    enabled: open,
  })

  // Rebrickable lists are created from here too: with no list at all the sheet was a dead end that
  // sent the user to rebrickable.com mid-task.
  const createList = useMutation({
    mutationFn: (name: string) => api.post<{ id: number }>('/collection/lists', { name }),
    onSuccess: async (created) => {
      setNewName('')
      await queryClient.invalidateQueries({ queryKey: ['collection'] })
      onPick(created.id)
    },
  })

  const lists = data?.lists ?? []

  return (
    <Sheet open={open} title={title} onClose={onClose}>
      {lists.length === 0 ? (
        <EmptyState
          title="Aucune liste Rebrickable"
          message="Créez-en une ci-dessous, ou synchronisez votre collection."
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

      <form
        className="mt-4 space-y-2 border-t border-line pt-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (newName.trim()) createList.mutate(newName.trim())
        }}
      >
        <label className="block space-y-1.5">
          <span className="section-title">Nouvelle liste</span>
          <input
            className="input"
            placeholder="Nom de la liste"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
          />
        </label>
        <button
          type="submit"
          className="btn-secondary w-full"
          disabled={!newName.trim() || createList.isPending}
        >
          {createList.isPending ? <Spinner className="h-4 w-4" /> : 'Créer et utiliser'}
        </button>
        {createList.isError && <ErrorLabel message={(createList.error as Error).message} />}
      </form>
    </Sheet>
  )
}
