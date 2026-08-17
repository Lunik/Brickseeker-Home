import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { LegoSet, ResolveResult } from '../api/types'
import { useCamera } from '../hooks/useCamera'
import { useSettings } from '../lib/settings-context'
import Icon from '../components/Icon'
import { SetThumbnail } from '../components/ui'
import { EmptyState, Sheet, Spinner } from '../components/ui'

/** One OCR round per 800 ms. Faster is wasted work — and here it also costs a round-trip. */
const CAPTURE_INTERVAL_MS = 800
/** A candidate must persist before it's worth resolving; the pulse fires immediately regardless. */
const DEBOUNCE_MS = 1200

export default function ScannerPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { preferences } = useSettings()

  const [paused, setPaused] = useState(false)
  const camera = useCamera(!paused)
  const [candidate, setCandidate] = useState<string | null>(null)
  const [resolving, setResolving] = useState(false)
  const [ambiguous, setAmbiguous] = useState<LegoSet[] | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [manual, setManual] = useState('')
  const [showManual, setShowManual] = useState(false)
  // Mode lot: scans accumulate into a session instead of opening each set's sheet, so a shelf can
  // be swept in one pass and reviewed afterwards.
  const [batchMode, setBatchMode] = useState(false)
  const [batchItems, setBatchItems] = useState<LegoSet[]>([])
  const [showBatch, setShowBatch] = useState(false)

  const lastCandidateRef = useRef<{ setNum: string; at: number } | null>(null)
  const inFlightRef = useRef(false)

  const captureLocation = Boolean(preferences?.scan_location_enabled)

  const resolve = useCallback(
    async (setNum: string, source: string) => {
      setResolving(true)
      setMessage(null)
      try {
        let coords: { latitude?: number; longitude?: number } = {}
        if (source === 'camera' && captureLocation && navigator.geolocation) {
          coords = await new Promise((resolve) => {
            navigator.geolocation.getCurrentPosition(
              (position) =>
                resolve({
                  latitude: position.coords.latitude,
                  longitude: position.coords.longitude,
                }),
              // A refused or slow fix must never block the lookup: the position is a bonus.
              () => resolve({}),
              { timeout: 4000, maximumAge: 60_000 },
            )
          })
        }

        const result = await api.post<ResolveResult>('/scan/lookup', { setNum, source, ...coords })
        if (result.set) {
          await queryClient.invalidateQueries({ queryKey: ['history'] })
          if (batchMode) {
            // Stay on the camera: the whole point of the session is not to interrupt the sweep.
            const found = result.set
            setBatchItems((current) =>
              current.some((item) => item.setNum === found.setNum) ? current : [...current, found],
            )
            setMessage(`${found.setNum} ajouté à la session`)
            return
          }
          navigate(`/set/${encodeURIComponent(result.set.setNum)}`, {
            state: { fromScan: true, offline: result.status === 'offline' },
          })
          return
        }
        if (result.status === 'ambiguous' && result.candidates.length) {
          setPaused(true)
          setAmbiguous(result.candidates)
          return
        }
        setMessage(`Aucun set trouvé pour « ${setNum} ».`)
      } catch (caught) {
        setMessage(caught instanceof Error ? caught.message : 'Recherche impossible')
      } finally {
        setResolving(false)
        setCandidate(null)
      }
    },
    [batchMode, captureLocation, navigate, queryClient],
  )

  useEffect(() => {
    if (paused || !camera.isActive) return

    const timer = window.setInterval(async () => {
      if (inFlightRef.current || resolving) return
      inFlightRef.current = true
      try {
        const blob = await camera.captureFrame()
        if (!blob) return
        const form = new FormData()
        form.append('file', blob, 'frame.jpg')
        const { setNums } = await api.upload<{ setNums: string[] }>('/scan/ocr', form)
        const found = setNums[0]
        if (!found) return

        // The pulse fires the moment a candidate is seen, before the lookup — the user needs to
        // know something happened before the network call starts.
        setCandidate(found)
        const previous = lastCandidateRef.current
        const now = Date.now()
        if (previous?.setNum === found && now - previous.at >= DEBOUNCE_MS) {
          lastCandidateRef.current = null
          await resolve(found, 'camera')
        } else if (previous?.setNum !== found) {
          lastCandidateRef.current = { setNum: found, at: now }
        }
      } catch {
        /* a blurry or challenged frame is normal; the next tick tries again */
      } finally {
        inFlightRef.current = false
      }
    }, CAPTURE_INTERVAL_MS)

    return () => window.clearInterval(timer)
  }, [camera, paused, resolve, resolving])

  return (
    <div className="relative min-h-[100dvh] bg-black">
      <video
        ref={camera.videoRef}
        playsInline
        muted
        autoPlay
        className="h-[100dvh] w-full object-cover"
      />

      {/* Reticle: matches the crop `captureFrame` actually sends, so what you frame is what is read. */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div
          className={`h-[35dvh] w-[80vw] rounded-2xl border-4 transition-colors ${
            candidate ? 'animate-pulse border-green-400' : 'border-white/70'
          }`}
        />
      </div>

      <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
        <button
          type="button"
          className="rounded-full bg-black/60 px-3 py-2 text-white"
          onClick={() => navigate('/')}
          aria-label="Fermer le scanner"
        >
          <Icon name="close" />
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={`rounded-full px-3 py-2 ${batchMode ? 'bg-brand text-white' : 'bg-black/60 text-white'}`}
            onClick={() => setBatchMode((current) => !current)}
            aria-pressed={batchMode}
            aria-label="Mode lot"
          >
            <Icon name="layers" />
          </button>
          {camera.hasTorch && (
          <button
            type="button"
            className="rounded-full bg-black/60 px-3 py-2 text-white"
            onClick={() => void camera.toggleTorch()}
            aria-label={camera.torchOn ? 'Éteindre la lampe' : 'Allumer la lampe'}
          >
            <Icon name="flashlight" filled={camera.torchOn} />
          </button>
          )}
        </div>
      </div>

      <div className="absolute inset-x-0 bottom-0 space-y-3 bg-gradient-to-t from-black/80 to-transparent p-4 pb-8 text-center">
        {resolving ? (
          <p className="flex items-center justify-center gap-2 text-sm text-white">
            <Spinner className="h-4 w-4" /> Recherche de {candidate}…
          </p>
        ) : candidate ? (
          <p className="text-sm font-semibold text-green-300">Numéro détecté : {candidate}</p>
        ) : (
          <p className="text-sm text-white/80">Visez le numéro imprimé sur la boîte</p>
        )}
        {message && <p className="text-sm font-semibold text-amber-300">{message}</p>}

        {batchMode && (
          <div className="space-y-1">
            <p className="text-sm text-white/80">
              {batchItems.length === 0
                ? 'Mode lot actif — scannez un set pour commencer'
                : 'Les prochains scans seront ajoutés à la session, sans ouvrir la fiche du set.'}
            </p>
            {batchItems.length > 0 && (
              <button type="button" className="btn-primary" onClick={() => setShowBatch(true)}>
                Voir la session ({batchItems.length})
              </button>
            )}
          </div>
        )}

        {/* Always available, camera or not: a scanner with no way out is a dead end. */}
        <div className="flex justify-center gap-2">
          <button type="button" className="btn-secondary" onClick={() => setShowManual(true)}>
            Saisie manuelle
          </button>
          <button type="button" className="btn-secondary" onClick={() => navigate('/settings')}>
            Paramètres
          </button>
        </div>
      </div>

      {camera.error && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface p-6">
          <EmptyState
            icon={<Icon name="camera" className="h-9 w-9" />}
            title="Caméra indisponible"
            message={camera.error}
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <button type="button" className="btn-primary" onClick={() => setShowManual(true)}>
                  Saisir un numéro
                </button>
                <button type="button" className="btn-secondary" onClick={camera.restart}>
                  Réessayer
                </button>
                <button type="button" className="btn-ghost" onClick={() => navigate('/')}>
                  Retour
                </button>
              </div>
            }
          />
        </div>
      )}

      <Sheet
        open={ambiguous !== null}
        title="Plusieurs sets correspondent"
        onClose={() => {
          setAmbiguous(null)
          setPaused(false)
        }}
      >
        <ul className="divide-y divide-line">
          {(ambiguous ?? []).map((set) => (
            <li key={set.setNum}>
              <button
                type="button"
                className="flex w-full items-center gap-3 py-3 text-left"
                onClick={() => {
                  setAmbiguous(null)
                  navigate(`/set/${encodeURIComponent(set.setNum)}`)
                }}
              >
                <SetThumbnail url={set.setImgUrl} alt={set.name} />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-ink">{set.setNum}</span>
                  <span className="block truncate text-sm text-ink-muted">{set.name}</span>
                  <span className="block text-xs text-ink-faint">
                    {set.year} · {set.numParts} pièces
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Sheet>

      <Sheet
        open={showBatch}
        title={`Session de scan (${batchItems.length})`}
        onClose={() => setShowBatch(false)}
        footer={
          <button
            type="button"
            className="btn-secondary w-full"
            onClick={() => {
              setBatchItems([])
              setShowBatch(false)
            }}
          >
            Vider la session
          </button>
        }
      >
        <ul className="list-card">
          {batchItems.map((item) => (
            <li key={item.setNum} className="border-b border-line last:border-0">
              <button
                type="button"
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
                onClick={() => navigate(`/set/${encodeURIComponent(item.setNum)}`)}
              >
                <SetThumbnail url={item.setImgUrl} alt={item.name} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-ink">{item.setNum}</span>
                  <span className="block truncate text-[15px] text-ink-muted">{item.name}</span>
                </span>
                <Icon name="chevron-right" className="h-4 w-4 text-ink-faint" />
              </button>
            </li>
          ))}
        </ul>
      </Sheet>

      <Sheet open={showManual} title="Saisie manuelle" onClose={() => setShowManual(false)}>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (!manual.trim()) return
            setShowManual(false)
            void resolve(manual.trim(), 'manualEntry')
          }}
        >
          <input
            className="input"
            autoFocus
            inputMode="numeric"
            placeholder="10307"
            value={manual}
            onChange={(event) => setManual(event.target.value)}
          />
          <button type="submit" className="btn-primary w-full">
            Rechercher
          </button>
        </form>
      </Sheet>
    </div>
  )
}
