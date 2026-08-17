import { useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BulkAction } from '../components/SetListScreen'

interface BulkResult {
  succeeded: string[]
  failed: { setNum: string; error: string }[]
}

/** The endpoint answers 200 with a per-set breakdown; a partial failure must not read as success. */
function reportFailures(result: BulkResult): void {
  if (result.failed?.length) {
    throw new Error(
      `${result.failed.length} set(s) n'ont pas pu être traités. Vérifiez votre connexion.`,
    )
  }
}

/**
 * The bulk actions shared by every list screen.
 *
 * They live here rather than being re-declared per screen because Historique, Liste cadeaux and
 * Nouveaux sets offer the *same* actions on the iOS side — and because "add to collection" needs a
 * list picker, whose deferred-resolution dance is exactly the kind of thing that drifts when it is
 * written three times.
 */
export function useSetActions() {
  const queryClient = useQueryClient()
  // The picker resolves a promise the bulk action is awaiting, so `run` can stay a plain async
  // function from `SetListScreen`'s point of view.
  const [pendingPick, setPendingPick] = useState<((listId: number | null) => void) | null>(null)

  const askForList = useCallback(
    () =>
      new Promise<number | null>((resolve) => {
        setPendingPick(() => (listId: number | null) => {
          setPendingPick(null)
          resolve(listId)
        })
      }),
    [],
  )

  const refreshPrices: BulkAction = {
    key: 'prices',
    label: 'Actualiser les prix',
    run: async (setNums) => {
      // The updater refuses when a run is already in flight; reporting that as success left the
      // user believing a refresh had been queued when nothing had.
      const { status } = await api.post<{ status: string }>('/prices/batch/start', { setNums })
      await queryClient.invalidateQueries({ queryKey: ['priceBatch'] })
      if (status === 'busy') {
        throw new Error('Une actualisation des prix est déjà en cours — réessayez ensuite.')
      }
    },
  }

  const addToCollection: BulkAction = {
    key: 'add-collection',
    label: 'Ajouter à la collection',
    run: async (setNums) => {
      const listId = await askForList()
      if (listId === null) return
      const result = await api.post<BulkResult>('/collection/bulk', { setNums, action: 'move', listId })
      await queryClient.invalidateQueries()
      reportFailures(result)
    },
  }

  const addToWishlist: BulkAction = {
    key: 'add-wishlist',
    label: 'Ajouter à ma liste de cadeaux',
    run: async (setNums) => {
      // One call per set: Brickset resolves each set number separately and is throttled, so there
      // is no batch endpoint to be had.
      await Promise.all(setNums.map((setNum) => api.post(`/wishlist/${encodeURIComponent(setNum)}`)))
      await queryClient.invalidateQueries()
    },
  }

  return {
    refreshPrices,
    addToCollection,
    addToWishlist,
    /** Wire into `<ListPickerSheet open={listPicker.open} …>`. */
    listPicker: {
      open: pendingPick !== null,
      pick: (listId: number) => pendingPick?.(listId),
      cancel: () => pendingPick?.(null),
    },
  }
}
