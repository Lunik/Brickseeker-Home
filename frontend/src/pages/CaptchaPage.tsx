import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useLocation, useParams } from 'react-router-dom'

import { api } from '../api/client'
import type { CaptchaSessionStatus, InteractivePriceRefresh } from '../api/types'
import { ErrorLabel, Spinner } from '../components/ui'

const FRAME_INTERVAL_MS = 500
const POINTER_MOVE_INTERVAL_MS = 30

export default function CaptchaPage() {
  const { challengeId = 'waiting' } = useParams()
  const location = useLocation()
  const waiting = challengeId === 'waiting'
  const search = new URLSearchParams(location.search)
  const waitingOperationId = search.get('operationId')
  const returnTo = search.get('returnTo') || '/'
  const [frameVersion, setFrameVersion] = useState(0)
  const [interactionError, setInteractionError] = useState<string | null>(null)
  const [waitingError, setWaitingError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [operationState, setOperationState] = useState<InteractivePriceRefresh | null>(null)
  const [knownOperationId, setKnownOperationId] = useState<string | null>(waitingOperationId)
  const pointerDown = useRef(false)
  const lastPointerMove = useRef(0)
  const frameTimer = useRef<number | null>(null)

  const challenge = useQuery({
    queryKey: ['captcha-session', challengeId],
    queryFn: () => api.get<CaptchaSessionStatus>(`/prices/captcha/${encodeURIComponent(challengeId)}`),
    enabled: !waiting,
    retry: 2,
    refetchInterval: submitted ? 1000 : false,
  })

  useEffect(() => {
    if (challenge.data?.operationId) setKnownOperationId(challenge.data.operationId)
  }, [challenge.data?.operationId])

  const operationId = knownOperationId ?? waitingOperationId

  useEffect(() => {
    return () => {
      if (frameTimer.current !== null) window.clearTimeout(frameTimer.current)
    }
  }, [])

  function scheduleNextFrame(delay = FRAME_INTERVAL_MS) {
    if (submitted) return
    if (frameTimer.current !== null) window.clearTimeout(frameTimer.current)
    frameTimer.current = window.setTimeout(() => {
      frameTimer.current = null
      setFrameVersion((value) => value + 1)
    }, delay)
  }

  useEffect(() => {
    if (!operationId) return
    let active = true
    async function poll() {
      try {
        const state = await api.get<InteractivePriceRefresh>(
          `/prices/interactive/${encodeURIComponent(operationId ?? '')}`,
        )
        if (!active) return
        setOperationState(state)
        const nextChallenge = state.challenge?.challengeId
        if (nextChallenge && nextChallenge !== challengeId) {
          window.location.replace(
            `/captcha/${encodeURIComponent(nextChallenge)}?returnTo=${encodeURIComponent(returnTo)}`,
          )
          return
        }
        if (state.status === 'completed' || state.status === 'cancelled') {
          if (window.opener) window.close()
          else window.location.replace(returnTo)
        } else if (state.status === 'failed') {
          setWaitingError(state.error ?? 'Actualisation interactive impossible.')
        }
      } catch (caught) {
        if (active) {
          setWaitingError(caught instanceof Error ? caught.message : 'Actualisation introuvable')
        }
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 800)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [challengeId, operationId, returnTo])

  const continueChallenge = useMutation({
    mutationFn: () => api.post(`/prices/captcha/${encodeURIComponent(challengeId)}/continue`),
    onSuccess: () => setSubmitted(true),
  })

  const skipChallenge = useMutation({
    mutationFn: () => api.post(`/prices/captcha/${encodeURIComponent(challengeId)}/skip`),
    onSuccess: () => setSubmitted(true),
  })

  function remoteCoordinates(event: PointerEvent<HTMLDivElement>) {
    const image = event.currentTarget.querySelector('img')
    const rect = event.currentTarget.getBoundingClientRect()
    const width = image?.naturalWidth || 1280
    const height = image?.naturalHeight || 800
    return {
      x: ((event.clientX - rect.left) / rect.width) * width,
      y: ((event.clientY - rect.top) / rect.height) * height,
    }
  }

  function sendPointer(event: PointerEvent<HTMLDivElement>, eventType: 'move' | 'down' | 'up') {
    const now = performance.now()
    if (eventType === 'move' && now - lastPointerMove.current < POINTER_MOVE_INTERVAL_MS) return
    if (eventType === 'move') lastPointerMove.current = now
    const coordinates = remoteCoordinates(event)
    void api
      .post(`/prices/captcha/${encodeURIComponent(challengeId)}/pointer`, {
        eventType,
        ...coordinates,
        button: event.button === 1 ? 'middle' : event.button === 2 ? 'right' : 'left',
      })
      .catch((error: Error) => setInteractionError(error.message))
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    pointerDown.current = true
    event.currentTarget.focus()
    event.currentTarget.setPointerCapture(event.pointerId)
    sendPointer(event, 'down')
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!pointerDown.current) return
    sendPointer(event, 'move')
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (!pointerDown.current) return
    pointerDown.current = false
    sendPointer(event, 'up')
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  function onWheel(event: WheelEvent<HTMLDivElement>) {
    event.preventDefault()
    void api
      .post(`/prices/captcha/${encodeURIComponent(challengeId)}/wheel`, {
        deltaX: event.deltaX,
        deltaY: event.deltaY,
      })
      .catch((error: Error) => setInteractionError(error.message))
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return
    const printable = event.key.length === 1 && event.key !== ' '
    const key = event.key === ' ' ? 'Space' : event.key
    event.preventDefault()
    void api
      .post(`/prices/captcha/${encodeURIComponent(challengeId)}/key`, {
        key: printable ? null : key,
        text: printable ? event.key : null,
      })
      .catch((error: Error) => setInteractionError(error.message))
  }

  if (waiting) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface px-6 text-center">
        <div className="space-y-3">
          <Spinner className="mx-auto h-7 w-7" />
          <h1 className="text-xl font-bold text-ink">Recherche des prix</h1>
          <p className="text-sm text-ink-muted">
            Cette fenêtre se fermera automatiquement si aucun CAPTCHA n'est demandé.
          </p>
          {waitingError && <ErrorLabel message={waitingError} />}
        </div>
      </div>
    )
  }

  if (operationState?.status === 'failed') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface px-6">
        <div className="space-y-4">
          <ErrorLabel message={operationState.error ?? 'Actualisation interactive impossible.'} />
          <button type="button" className="btn-secondary w-full" onClick={() => window.location.replace(returnTo)}>
            Retour à la fiche
          </button>
        </div>
      </div>
    )
  }

  const terminal = operationState?.status === 'completed' || operationState?.status === 'cancelled'
  if (submitted || terminal) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface px-6 text-center">
        <div className="space-y-3">
          {!terminal && <Spinner className="mx-auto h-7 w-7" />}
          <h1 className="text-xl font-bold text-ink">
            {terminal ? 'Actualisation terminée' : 'Validation en cours…'}
          </h1>
          <p className="text-sm text-ink-muted">
            BrickSeeker vérifie la session et reprend uniquement la source concernée.
          </p>
        </div>
      </div>
    )
  }

  if (challenge.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface px-6">
        <ErrorLabel message="Cette session CAPTCHA est terminée ou a expiré." />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <header className="sticky top-0 z-10 border-b border-line bg-surface px-4 py-3">
        <h1 className="font-bold text-ink">
          CAPTCHA {challenge.data ? `· ${challenge.data.sourceName}` : ''}
        </h1>
        <p className="text-xs text-ink-muted">
          Interagissez avec la page distante puis confirmez. Les cookies restent chiffrés sur le serveur.
        </p>
      </header>

      <div className="flex flex-1 items-center justify-center overflow-hidden bg-black p-2">
        {challenge.isLoading ? (
          <Spinner className="h-7 w-7 text-white" />
        ) : (
          <div
            className="relative w-full max-w-[1280px] cursor-default overflow-hidden outline-none"
            style={{ aspectRatio: '16 / 10', touchAction: 'none' }}
            tabIndex={0}
            role="application"
            aria-label="Page distante du CAPTCHA"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onWheel={onWheel}
            onKeyDown={onKeyDown}
            onContextMenu={(event) => event.preventDefault()}
          >
            <img
              src={`/api/prices/captcha/${encodeURIComponent(challengeId)}/frame?v=${frameVersion}`}
              alt={`Page ${challenge.data?.sourceName ?? 'retailer'} à valider`}
              className="h-full w-full select-none object-contain"
              draggable={false}
              onLoad={() => scheduleNextFrame()}
              onError={() => scheduleNextFrame(1000)}
            />
          </div>
        )}
      </div>

      <footer className="sticky bottom-0 grid gap-2 border-t border-line bg-surface p-3 sm:grid-cols-2">
        {(interactionError || continueChallenge.isError || skipChallenge.isError) && (
          <ErrorLabel
            message={
              interactionError
              ?? ((continueChallenge.error ?? skipChallenge.error) as Error).message
            }
            className="sm:col-span-2"
          />
        )}
        <button
          type="button"
          className="btn-primary w-full"
          onClick={() => continueChallenge.mutate()}
          disabled={continueChallenge.isPending || skipChallenge.isPending}
        >
          J'ai terminé
        </button>
        <button
          type="button"
          className="btn-secondary w-full"
          onClick={() => skipChallenge.mutate()}
          disabled={continueChallenge.isPending || skipChallenge.isPending}
        >
          Ignorer cette source
        </button>
      </footer>
    </div>
  )
}
