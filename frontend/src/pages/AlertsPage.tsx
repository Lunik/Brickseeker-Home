import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { PriceAlert } from '../api/types'
import { CONDITION_LABEL, formatEUR, formatRelative } from '../lib/format'
import Icon from '../components/Icon'
import { EmptyState, ErrorLabel, LoadingBlock, SetThumbnail } from '../components/ui'

export default function AlertsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['alerts'],
    queryFn: () => api.get<{ alerts: PriceAlert[] }>('/alerts'),
  })

  const toggle = useMutation({
    mutationFn: (payload: { id: number; isEnabled: boolean }) =>
      api.patch(`/alerts/${payload.id}`, { isEnabled: payload.isEnabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/alerts/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  })

  if (isLoading) return <LoadingBlock />
  if (error) return <ErrorLabel message={(error as Error).message} />

  const alerts = data?.alerts ?? []

  return (
    <div className="space-y-4">
      <h1 className="text-[34px] font-bold leading-tight text-ink">Alertes de prix</h1>

      {alerts.length === 0 ? (
        <EmptyState
          icon={<Icon name="bell" className="h-9 w-9" />}
          title="Aucune alerte"
          message="Ouvre la fiche d'un set et crée une alerte pour être prévenu quand son prix descend."
          action={
            <button type="button" className="btn-primary" onClick={() => navigate('/collection')}>
              Parcourir ma collection
            </button>
          }
        />
      ) : (
        <ul className="space-y-2">
          {alerts.map((alert) => {
            const threshold = alert.effectiveThresholdEur
            const observed = alert.lastObservedPriceEur
            const gap = threshold !== null && observed !== null ? observed - threshold : null

            return (
              <li key={alert.id} className="card flex items-start gap-3">
                <SetThumbnail url={alert.setImgUrl} alt={alert.setName} size="sm" />
                <div className="min-w-0 flex-1 space-y-1">
                  <button
                    type="button"
                    className="block text-left"
                    onClick={() => navigate(`/set/${encodeURIComponent(alert.setNum)}`)}
                  >
                    <span className="block font-semibold text-ink">{alert.setNum}</span>
                    <span className="block truncate text-sm text-ink-muted">{alert.setName}</span>
                  </button>
                  <p className="text-xs text-ink-faint">
                    {CONDITION_LABEL[alert.condition]} · seuil {formatEUR(threshold)}
                    {alert.discountPercent !== null && alert.referencePriceEur !== null && (
                      <>
                        {' '}
                        (−{alert.discountPercent} % de {formatEUR(alert.referencePriceEur)}
                        {alert.referenceSourceName ? `, ${alert.referenceSourceName}` : ''})
                      </>
                    )}
                  </p>
                  <p className="text-xs">
                    {observed !== null ? (
                      <>
                        Dernier prix vu : <strong className="text-ink">{formatEUR(observed)}</strong>
                        {gap !== null && (
                          <span className={gap <= 0 ? 'text-[rgb(var(--positive))]' : 'text-ink-faint'}>
                            {gap <= 0 ? ' — sous le seuil' : ` — ${formatEUR(gap)} au-dessus`}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-ink-faint">Aucun prix relevé pour l'instant</span>
                    )}
                  </p>
                  {alert.lastNotifiedAt && (
                    <p className="text-xs text-ink-faint">
                      Dernière notification {formatRelative(alert.lastNotifiedAt)}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <label className="flex items-center gap-1.5 text-xs text-ink-muted">
                    <input
                      type="checkbox"
                      checked={alert.isEnabled}
                      onChange={(event) => toggle.mutate({ id: alert.id, isEnabled: event.target.checked })}
                    />
                    Active
                  </label>
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1 text-xs text-[rgb(var(--negative))]"
                    onClick={() => remove.mutate(alert.id)}
                  >
                    Supprimer
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <p className="text-xs text-ink-faint">
        Le rafraîchissement en arrière-plan ne peut interroger que BrickLink : une alerte
        « occasion » est entièrement surveillée, une alerte « neuf » l'est jusqu'à BrickLink neuf.
        Les autres sources (lego.com, Amazon, Cdiscount) sont relevées quand tu ouvres la fiche du
        set ou lances une mise à jour des prix.
      </p>
    </div>
  )
}
