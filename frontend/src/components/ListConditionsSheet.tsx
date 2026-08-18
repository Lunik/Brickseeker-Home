import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { CollectionPayload, ListCondition } from '../api/types'
import { CONDITION_LABEL } from '../lib/format'
import Icon from './Icon'
import { Sheet } from './ui'

/**
 * "Neuf ou occasion ?" per Rebrickable list — the iOS `ListConditionsView`.
 *
 * The condition has no Rebrickable equivalent: it is purely ours, and it decides which price chain
 * values a list's sets (retail for neuf, BrickLink occasion for used). It therefore has to be
 * reachable from both places that show a total resting on it — Ma collection and Statistiques —
 * which is why it lives here rather than inline in either screen. It reads the collection from the
 * same query key both pages already hold, so opening it costs no extra fetch.
 */
export default function ListConditionsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ['collection'],
    queryFn: () => api.get<CollectionPayload>('/collection'),
    enabled: open,
  })

  const setCondition = useMutation({
    mutationFn: (payload: { listId: number; condition: ListCondition }) =>
      api.patch(`/collection/lists/${payload.listId}`, { condition: payload.condition }),
    // The estimated value is derived from these, so the stats have to be recomputed too.
    onSuccess: () => queryClient.invalidateQueries(),
  })

  const lists = data?.lists ?? []

  return (
    <Sheet open={open} title="Conditions des listes" onClose={onClose}>
      <p className="mb-3 text-[15px] text-ink-muted">
        La condition d'une liste décide de la source de prix utilisée pour valoriser les sets
        qu'elle contient : « Neuf » pour les sets encore scellés (lego.com en priorité), «&nbsp;Occasion&nbsp;»
        pour les sets ouverts (BrickLink occasion).
      </p>
      {lists.length === 0 ? (
        <p className="text-[15px] text-ink-muted">
          Aucune liste Rebrickable. Synchronisez votre collection depuis l'accueil pour les voir ici.
        </p>
      ) : (
        <ul className="list-card">
          {lists.map((list) => (
            <li
              key={list.id}
              className="relative flex min-h-12 items-center gap-3 border-b border-line px-4 py-3 last:border-0"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[17px] text-ink">{list.name}</span>
                <span className="block text-[13px] text-ink-faint">{list.numSets} set(s)</span>
              </span>
              <span className="shrink-0 text-[17px] text-ink-muted">{CONDITION_LABEL[list.condition]}</span>
              <Icon name="chevron-right" className="h-4 w-4 shrink-0 text-ink-faint" />
              {/* Same invisible-native-picker trick as the filter rows: a styled select cannot be
                  right-aligned, and the row has to read as an iOS picker row. */}
              <select
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                value={list.condition}
                aria-label={`Condition de la liste ${list.name}`}
                onChange={(event) =>
                  setCondition.mutate({
                    listId: list.id,
                    condition: event.target.value as ListCondition,
                  })
                }
              >
                <option value="newSet">{CONDITION_LABEL.newSet}</option>
                <option value="used">{CONDITION_LABEL.used}</option>
              </select>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  )
}
