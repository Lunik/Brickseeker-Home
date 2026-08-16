import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { SetRow } from '../api/types'
import SetListScreen, { type BulkAction } from '../components/SetListScreen'
import Icon from '../components/Icon'
import { EmptyState, ErrorLabel, Sheet, Spinner } from '../components/ui'

interface WishlistPayload {
  sets: SetRow[]
  isLinked: boolean
  lastSyncedAt: string | null
}

interface ImportProgress {
  total: number
  processed: number
  added: number
  alreadyWanted: number
  notFound: number
  failed: number
  isRunning: boolean
  error: string | null
  errors: string[]
}

export default function WishlistPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showImport, setShowImport] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['wishlist'],
    queryFn: () => api.get<WishlistPayload>('/wishlist'),
  })

  const sync = useMutation({
    mutationFn: () => api.post('/wishlist/sync'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['wishlist'] }),
  })

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.upload<{ started: boolean; total: number }>('/wishlist/import', form)
    },
  })

  // Polled only while the import runs — each set costs a throttled Brickset lookup plus an add,
  // so a 150-set list genuinely takes minutes.
  const progress = useQuery({
    queryKey: ['wishlist-import'],
    queryFn: () => api.get<ImportProgress>('/wishlist/import/status'),
    enabled: showImport,
    refetchInterval: (query) => (query.state.data?.isRunning ? 1500 : false),
  })

  const actions: BulkAction[] = [
    {
      key: 'prices',
      label: 'Rafraîchir les prix',
      run: async (setNums) => {
        await api.post('/prices/batch/start', { setNums })
      },
    },
    {
      key: 'remove',
      label: 'Retirer de la liste',
      destructive: true,
      confirm: (count) => `${count} set(s) seront retirés de ta liste cadeaux Brickset.`,
      run: async (setNums) => {
        await Promise.all(setNums.map((setNum) => api.delete(`/wishlist/${encodeURIComponent(setNum)}`)))
        await queryClient.invalidateQueries({ queryKey: ['wishlist'] })
      },
    },
  ]

  return (
    <>
      <SetListScreen
        title="Liste cadeaux"
        screenId="wishlist"
        rows={data?.sets ?? []}
        isLoading={isLoading}
        error={error ? (error as Error).message : null}
        subtitleFor={(row) => [row.themeName, row.year || null].filter(Boolean).join(' · ')}
        bulkActions={actions}
        onOpenSet={(row, visible) =>
          navigate(`/set/${encodeURIComponent(row.setNum)}`, {
            state: { siblings: visible.map((item) => item.setNum) },
          })
        }
        onRefresh={() => sync.mutate()}
        isRefreshing={sync.isPending}
        header={
          data?.isLinked ? (
            <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setShowImport(true)}>
              <Icon name="upload" className="mr-1 inline h-4 w-4 align-text-bottom" />
              Importer depuis un CSV Rebrickable
            </button>
          ) : undefined
        }
        emptyState={
          !data?.isLinked ? (
            <EmptyState
              icon={<Icon name="link" className="h-9 w-9" />}
              title="Compte Brickset non lié"
              message="La liste cadeaux est stockée sur Brickset — un compte séparé de Rebrickable. Lie-le dans les Réglages."
              action={
                <button type="button" className="btn-primary" onClick={() => navigate('/settings')}>
                  Ouvrir les Réglages
                </button>
              }
            />
          ) : (
            <EmptyState
              icon={<Icon name="gift" className="h-9 w-9" />}
              title="Liste cadeaux vide"
              message="Marque des sets comme « voulus » depuis leur fiche, ou importe une liste Rebrickable."
              action={
                <button type="button" className="btn-primary" onClick={() => setShowImport(true)}>
                  Importer un CSV
                </button>
              }
            />
          )
        }
      />

      <Sheet open={showImport} title="Importer une liste" onClose={() => setShowImport(false)}>
        <div className="space-y-4">
          <p className="text-sm text-ink-muted">
            Exporte une liste personnalisée depuis Rebrickable au format CSV, puis dépose-la ici.
            Chaque set est ajouté à ta liste « wanted » Brickset, un par un — compte environ une
            seconde par set.
          </p>

          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            className="input"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) upload.mutate(file)
            }}
          />

          {upload.isError && <ErrorLabel message={(upload.error as Error).message} />}

          {progress.data && (progress.data.isRunning || progress.data.processed > 0) && (
            <div className="space-y-2 rounded-xl bg-surface-sunken p-3 text-sm">
              <div className="flex items-center gap-2">
                {progress.data.isRunning && <Spinner className="h-4 w-4" />}
                <span>
                  {progress.data.processed} / {progress.data.total} traité(s)
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full bg-brand transition-all"
                  style={{
                    width: `${progress.data.total ? (progress.data.processed / progress.data.total) * 100 : 0}%`,
                  }}
                />
              </div>
              {/* Per-set outcomes, not a single pass/fail: a set Brickset doesn't catalogue is an
                  expected result, not an error. */}
              <ul className="text-xs text-ink-muted">
                <li>Ajoutés : {progress.data.added}</li>
                <li>Déjà voulus : {progress.data.alreadyWanted}</li>
                <li>Introuvables sur Brickset : {progress.data.notFound}</li>
                <li>Échecs : {progress.data.failed}</li>
              </ul>
              {progress.data.error && <ErrorLabel message={progress.data.error} />}
            </div>
          )}
        </div>
      </Sheet>
    </>
  )
}
