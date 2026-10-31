import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { InteractivePriceRefresh } from '../api/types'
import Icon from './Icon'
import { Spinner } from './ui'

interface BlockedPayload {
  total: number
  sources: { source: string; sourceName: string; setCount: number }[]
}

// The button remounts on every navigation (each page owns its header), so the running operation
// and the popup live outside the component — otherwise changing page would lose the popup.
interface UiState {
  operationId: string | null
  message: string | null
}
const UI_KEY = ['blocked-prices-ui']
let popup: Window | null = null
let shownChallenge: string | null = null

const isDone = (status?: InteractivePriceRefresh['status']) =>
  status === 'completed' || status === 'failed' || status === 'cancelled'

/**
 * App-wide entry point to the retailer CAPTCHA popup: one validation per blocked retailer, then the
 * server replays every set that retailer had refused. Hidden while nothing is blocked.
 */
export default function BlockedPricesButton() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const ui = useQuery<UiState>({
    queryKey: UI_KEY,
    // Never refetched: a global `invalidateQueries()` must not wipe the running operation or the
    // result message, so the fetcher hands back what the cache already holds.
    queryFn: () => queryClient.getQueryData<UiState>(UI_KEY) ?? { operationId: null, message: null },
    staleTime: Infinity,
    gcTime: Infinity,
  })
  const { operationId, message } = ui.data ?? { operationId: null, message: null }
  const setUi = (next: Partial<UiState>) =>
    queryClient.setQueryData<UiState>(UI_KEY, { operationId, message, ...next })

  const blocked = useQuery({
    queryKey: ['blocked-prices'],
    queryFn: () => api.get<BlockedPayload>('/prices/blocked'),
    refetchInterval: 4_000,
  })

  const operation = useQuery({
    queryKey: ['blocked-prices-operation', operationId],
    queryFn: () => api.get<InteractivePriceRefresh>(`/prices/interactive/${encodeURIComponent(operationId ?? '')}`),
    enabled: Boolean(operationId),
    retry: false,
    refetchInterval: (query) => (isDone(query.state.data?.status) ? false : 800),
  })

  const start = useMutation({
    mutationFn: () => api.post<InteractivePriceRefresh>('/prices/interactive/start-blocked'),
    onSuccess: (op) => {
      setUi({ operationId: op.operationId, message: null })
    },
    onError: (caught) =>
      setUi({ message: caught instanceof Error ? caught.message : 'Validation impossible' }),
  })

  const data = operation.data
  useEffect(() => {
    if (!data || !operationId) return
    if (isDone(data.status)) {
      popup?.close()
      popup = null
      shownChallenge = null
      setUi({
        operationId: null,
        message:
          data.error
          ?? data.warning
          ?? `${data.replayDone} set${data.replayDone > 1 ? 's' : ''} relancé${data.replayDone > 1 ? 's' : ''}.`,
      })
      void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== UI_KEY[0] })
      return
    }
    if (popup?.closed) {
      // Closing the popup abandons the validation, as on a set page.
      popup = null
      shownChallenge = null
      void api.post(`/prices/interactive/${encodeURIComponent(operationId)}/cancel`)
      return
    }
    const challenge = data.challenge
    if (!challenge || shownChallenge === challenge.challengeId) return
    shownChallenge = challenge.challengeId
    const url = `/captcha/${encodeURIComponent(challenge.challengeId)}?returnTo=${encodeURIComponent('/')}`
    const opened = window.open(url, 'brickseeker-price-captcha', 'popup,width=1100,height=820,resizable=yes,scrollbars=no')
    if (opened) popup = opened
    else navigate(url)
  }, [data, operationId, navigate, queryClient])

  const total = blocked.data?.total ?? 0
  const running = Boolean(operationId) || start.isPending
  if (total === 0 && !running && !message) return null

  const names = blocked.data?.sources.map((entry) => entry.sourceName).join(', ')
  const progress = data && data.replayTotal > 0 ? ` (${data.replayDone}/${data.replayTotal})` : ''
  const label = running
    ? `Validation CAPTCHA en cours${progress}`
    : `CAPTCHA requis : ${names} — ${total} set${total > 1 ? 's' : ''} en attente`

  return (
    <div className="relative">
      <button
        type="button"
        className="nav-circle relative text-[rgb(var(--warning))]"
        onClick={() => (message && total === 0 ? setUi({ message: null }) : start.mutate())}
        disabled={running}
        aria-label={label}
        title={label}
      >
        {running ? <Spinner className="h-5 w-5" /> : <Icon name="warning" className="h-6 w-6" />}
        {total > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-bold text-white">
            {total > 99 ? '99+' : total}
          </span>
        )}
      </button>
      {(message || running) && (
        <button
          type="button"
          onClick={() => setUi({ message: null })}
          className="absolute right-0 top-full z-10 mt-2 w-64 rounded-xl border border-line bg-surface p-3 text-left text-[13px] text-ink shadow-lg"
        >
          {running ? label : message}
        </button>
      )}
    </div>
  )
}
