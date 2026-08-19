import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from '../api/client'
import type { LegoSet, ResolveResult } from '../api/types'
import { useCamera } from '../hooks/useCamera'
import { useBackendReachable } from '../lib/backend-reachability'
import { batchSession, useBatchSession } from '../lib/batch-session'
import {
  playCandidateDetected,
  playResolutionFailed,
  playResolutionSucceeded,
  prepareFeedback,
} from '../lib/feedback'
import { offlineCatalogStore } from '../lib/offline-catalog-store'
import * as offlineOcr from '../lib/offline-ocr'
import { offlineScanQueue } from '../lib/offline-scan-queue'
import { extractSetNumbers } from '../lib/set-number-extractor'
import { useSettings } from '../lib/settings-context'
import Icon from '../components/Icon'
import { SetThumbnail } from '../components/ui'
import { EmptyState, Sheet, Spinner } from '../components/ui'

/** One OCR round per 800 ms. Faster is wasted work processing frames the eye hasn't settled on. */
const CAPTURE_INTERVAL_MS = 800
/** A candidate must persist before it's worth resolving; the pulse fires immediately regardless. */
const DEBOUNCE_MS = 1200
/**
 * How long the same set number stays locked out after being resolved. Without it, keeping one box
 * in frame re-resolves it every ~2 s and each round-trip writes another ScanEvent — Historique
 * fills with duplicates of a single scan. Mirrors the iOS lock.
 */
const REPEAT_LOCK_MS = 30_000
/** A candidate must appear in this many frames before it is worth a lookup. */
const MIN_SIGHTINGS = 2
/** How long a candidate keeps accumulating credit after it was last seen. */
const CANDIDATE_TTL_MS = 6_000

export default function ScannerPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { preferences } = useSettings()

  const [candidate, setCandidate] = useState<string | null>(null)
  const [resolving, setResolving] = useState(false)
  const [ambiguous, setAmbiguous] = useState<LegoSet[] | null>(null)
  // What a fully offline resolution found: there is no live detail page to navigate to (no backend
  // to answer GET /sets/:setNum, no cache for a set never seen on this device before), so this
  // confirmation sheet is the offline equivalent of `navigate()` on the online path below — without
  // it, a successful offline scan showed only a toast and read as if nothing had happened.
  const [offlineFound, setOfflineFound] = useState<LegoSet | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [manual, setManual] = useState('')
  const [showManual, setShowManual] = useState(false)
  // Mode lot: scans accumulate into a session instead of opening each set's sheet, so a shelf can
  // be swept in one pass and reviewed afterwards. The session itself lives outside this component
  // (see `lib/batch-session`) — it has to outlive the camera, since looking at any set in it
  // navigates away from here.
  const [batchMode, setBatchMode] = useState(false)
  const batchItems = useBatchSession()
  const backendReachable = useBackendReachable()

  // Any sheet covering the camera stops it — the iOS scanner treats this as a hard rule, and
  // it is also what keeps a background resolve from yanking the user off a form they are typing.
  const isCovered = showManual || ambiguous !== null || offlineFound !== null
  const camera = useCamera(!isCovered)

  /**
   * Every set number seen recently, with how many frames saw it and when it first appeared.
   *
   * Keyed on the whole candidate list rather than `setNums[0]`: OCR returns a different *first*
   * candidate from frame to frame (a parts count, an age rating, the real number), so requiring
   * two consecutive identical firsts meant the debounce never elapsed and a detected set was
   * never resolved. Counting every candidate makes the real number win by persistence.
   */
  const sightingsRef = useRef<Map<string, { count: number; firstSeen: number; lastSeen: number }>>(new Map())
  const resolvedAtRef = useRef<Map<string, number>>(new Map())
  const inFlightRef = useRef(false)
  // Read inside the interval without making it a dependency: putting it in the deps tore the
  // timer down and rebuilt it on every resolve, restarting the cadence each time.
  const resolvingRef = useRef(false)
  /** The last candidate that got a beep, so one detection is one cue and not one per frame. */
  const pulsedRef = useRef<string | null>(null)

  const captureLocation = Boolean(preferences?.scan_location_enabled)

  // Opening the scanner is a user gesture, which is what lets the audio context start at all —
  // one created later, inside the capture loop, is born suspended and stays silent.
  useEffect(() => {
    prepareFeedback()
  }, [])

  // Every scan runs through the OCR worker now, not just a fallback reached after a failed network
  // attempt — so it's started here rather than left to spin up cold inside the first capture tick,
  // which would otherwise sit there looking unresponsive while the WASM core and both language
  // packs load. Torn down on unmount/tab-hidden, mirroring `useCamera.ts`'s own stop-on-hidden
  // discipline; a later `recognize` call transparently spins a fresh worker back up.
  useEffect(() => {
    void offlineOcr.warmUp()
    function onVisibility() {
      if (document.hidden) void offlineOcr.terminateOfflineOcr()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      void offlineOcr.terminateOfflineOcr()
    }
  }, [])

  const resolve = useCallback(
    async (setNum: string, source: string) => {
      // Only the camera path gives feedback: a phone that buzzes while you type a number by hand
      // is noise, and the user is looking at the screen anyway. Same rule as iOS.
      const withFeedback = source === 'camera'
      resolvingRef.current = true
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

        // No backend to ask at all — resolve against the on-device catalogue snapshot instead. A
        // hit is queued for the sync engine (`lib/offline-scan-sync.ts`) to replay through the
        // real `/scan/lookup` once reachable; outside batch mode, `offlineFound` below stands in
        // for the `navigate()` the online path gets, since there's no live detail page to open —
        // no backend to answer GET /sets/:setNum, no cache for a set never seen on this device.
        async function resolveOffline(): Promise<void> {
          const found = await offlineCatalogStore.lookupSet(setNum)
          if (found) {
            if (withFeedback) playResolutionSucceeded()
            await offlineScanQueue.enqueue({
              setNum: found.setNum,
              source,
              scannedAt: new Date().toISOString(),
              priceSeenEur: null,
              latitude: coords.latitude ?? null,
              longitude: coords.longitude ?? null,
              resolvedSet: found,
            })
            if (batchMode) {
              // Mirrors the online batch-mode path exactly: stay on the camera, don't interrupt
              // the sweep.
              batchSession.add(found)
              setMessage(`${found.setNum} ajouté à la session (hors connexion)`)
              return
            }
            setOfflineFound(found)
            return
          }
          if (withFeedback) playResolutionFailed()
          setMessage(
            (await offlineCatalogStore.isEmpty('sets'))
              ? 'Catalogue hors-ligne non synchronisé sur cet appareil (Réglages).'
              : `Aucun set trouvé pour « ${setNum} » dans le catalogue hors-ligne.`,
          )
        }

        if (!backendReachable) {
          await resolveOffline()
          return
        }

        // Fired now either way, but only *awaited* below when there's no faster signal to act on
        // — `/scan/lookup` still does real work beyond identification (records the ScanEvent,
        // reverse-geocodes a camera scan, caches the canonical row) that nothing here needs to
        // wait on just to confirm the scan landed.
        const lookupPromise = api.post<ResolveResult>('/scan/lookup', { setNum, source, ...coords })

        // The on-device catalogue snapshot is the same Rebrickable data the live call would
        // consult anyway, so a hit here is trustworthy enough to act on before the network round
        // trip finishes — which is what made a successful scan feel like it hadn't registered.
        // Left running underneath, `lookupPromise`'s eventual ScanEvent is what History actually
        // shows; a set detail page opened from here reads its own data independently on mount, so
        // it doesn't matter that this is a beat ahead of what the server has confirmed yet.
        const quickMatch = await offlineCatalogStore.lookupSet(setNum)
        if (quickMatch) {
          if (withFeedback) playResolutionSucceeded()
          void lookupPromise
            .then((result) => {
              if (result.set) return queryClient.invalidateQueries({ queryKey: ['history'] })
            })
            .catch(() => {
              // Nothing left to report a late failure to — the user has already moved on, and a
              // detail page opened below reads its own data on its own query, not this response.
            })
          if (batchMode) {
            batchSession.add(quickMatch)
            setMessage(`${quickMatch.setNum} ajouté à la session`)
            return
          }
          // `scanEventId: null`, not `lookupPromise`'s eventual one: waiting on it here would
          // undo the whole point of this branch. The narrow cost is that "Prix vu en magasin",
          // if saved in the roughly one second before the ScanEvent above actually lands, creates
          // a second History row instead of patching this scan's — accepted rather than threading
          // a result that only arrives after the component reading it may already be mounted.
          navigate(`/set/${encodeURIComponent(quickMatch.setNum)}`, {
            state: { fromScan: true, offline: false, scanEventId: null },
          })
          return
        }

        let result: ResolveResult
        try {
          result = await lookupPromise
        } catch (caught) {
          // A real HTTP error response (`ApiError`) is a server-side problem, not a connectivity
          // one — surface it normally via the outer catch. Anything else is a genuine network
          // failure: the pre-flight `backendReachable` check above was simply stale (nothing had
          // failed yet to flip it), so fall back exactly as if it had been caught upfront.
          if (caught instanceof ApiError) throw caught
          await resolveOffline()
          return
        }
        if (result.set) {
          if (withFeedback) playResolutionSucceeded()
          await queryClient.invalidateQueries({ queryKey: ['history'] })
          if (batchMode) {
            // Stay on the camera: the whole point of the session is not to interrupt the sweep.
            const found = result.set
            batchSession.add(found)
            setMessage(`${found.setNum} ajouté à la session`)
            return
          }
          navigate(`/set/${encodeURIComponent(result.set.setNum)}`, {
            state: { fromScan: true, offline: result.status === 'offline', scanEventId: result.scanEventId },
          })
          return
        }
        if (result.status === 'ambiguous' && result.candidates.length) {
          // Something *was* recognised — the user still has to pick, but the scan worked.
          if (withFeedback) playResolutionSucceeded()
          setAmbiguous(result.candidates)
          return
        }
        if (withFeedback) playResolutionFailed()
        setMessage(`Aucun set trouvé pour « ${setNum} ».`)
      } catch (caught) {
        if (withFeedback) playResolutionFailed()
        setMessage(caught instanceof Error ? caught.message : 'Recherche impossible')
      } finally {
        resolvingRef.current = false
        setResolving(false)
        setCandidate(null)
        pulsedRef.current = null
      }
    },
    [backendReachable, batchMode, captureLocation, navigate, queryClient],
  )

  useEffect(() => {
    if (isCovered || !camera.isActive) return

    const timer = window.setInterval(async () => {
      if (inFlightRef.current || resolvingRef.current) return
      inFlightRef.current = true
      try {
        const blob = await camera.captureFrame()
        if (!blob) return

        // Always on-device — see `lib/offline-ocr.ts`. No network round trip in the capture loop
        // at all, reachable backend or not.
        const candidates = await offlineOcr.recognize(blob)
        const setNums = extractSetNumbers(candidates)
        const now = Date.now()

        // Forget anything not seen for a while, so a number glimpsed on a neighbouring box
        // doesn't keep accumulating credit while the camera looks elsewhere.
        for (const [key, seen] of sightingsRef.current) {
          if (now - seen.lastSeen > CANDIDATE_TTL_MS) sightingsRef.current.delete(key)
        }

        for (const setNum of setNums) {
          const seen = sightingsRef.current.get(setNum)
          if (seen) {
            seen.count += 1
            seen.lastSeen = now
          } else {
            sightingsRef.current.set(setNum, { count: 1, firstSeen: now, lastSeen: now })
          }
        }
        if (!setNums.length) return

        // The strongest current candidate drives the pulse, so the user sees a detection landing
        // before any network call starts.
        const ranked = [...sightingsRef.current.entries()]
          .filter(([setNum]) => {
            const resolvedAt = resolvedAtRef.current.get(setNum)
            return !resolvedAt || now - resolvedAt >= REPEAT_LOCK_MS
          })
          .sort((a, b) => b[1].count - a[1].count || a[1].firstSeen - b[1].firstSeen)

        const best = ranked[0]
        if (!best) return
        setCandidate(best[0])
        // Fires the moment a number is picked out of the frame, before any network call — the
        // point is to tell a user holding the phone at arm's length that the shot landed.
        if (pulsedRef.current !== best[0]) {
          pulsedRef.current = best[0]
          playCandidateDetected()
        }

        const [setNum, seen] = best
        if (seen.count >= MIN_SIGHTINGS && now - seen.firstSeen >= DEBOUNCE_MS) {
          resolvedAtRef.current.set(setNum, now)
          sightingsRef.current.delete(setNum)
          await resolve(setNum, 'camera')
        }
      } catch {
        /* a blurry or challenged frame is normal; the next tick tries again */
      } finally {
        inFlightRef.current = false
      }
    }, CAPTURE_INTERVAL_MS)

    return () => window.clearInterval(timer)
  }, [camera, isCovered, resolve])

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

      {/* Same status-bar overlap as the rest of the app, except this screen is full-bleed and has
          no `<main>` padding to inherit — the close/mode/torch row has to clear the inset itself. */}
      <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4 pt-[calc(1rem_+_env(safe-area-inset-top))]">
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

        {/* Stays visible once the session has items even after mode lot is switched off: turning
            the toggle off doesn't discard the session, and hiding this would strand it. */}
        {(batchMode || batchItems.length > 0) && (
          <div className="space-y-1">
            <p className="text-sm text-white/80">
              {batchItems.length === 0
                ? 'Mode lot actif — scannez un set pour commencer'
                : 'Les prochains scans seront ajoutés à la session, sans ouvrir la fiche du set.'}
            </p>
            {batchItems.length > 0 && (
              <button
                type="button"
                className="btn-primary"
                onClick={() => navigate('/scan/session')}
              >
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
        onClose={() => setAmbiguous(null)}
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
        open={offlineFound !== null}
        title="Trouvé hors-ligne"
        onClose={() => setOfflineFound(null)}
      >
        {offlineFound && (
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <SetThumbnail url={offlineFound.setImgUrl} alt={offlineFound.name} />
              <span className="min-w-0 flex-1">
                <span className="block font-semibold text-ink">{offlineFound.setNum}</span>
                <span className="block truncate text-sm text-ink-muted">{offlineFound.name}</span>
                <span className="block text-xs text-ink-faint">
                  {offlineFound.year} · {offlineFound.numParts} pièces
                </span>
              </span>
            </div>
            <p className="text-sm text-ink-muted">
              Identifié via le catalogue hors-ligne. Sera enregistré dans l'Historique, avec son
              prix, dès le retour de la connexion.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-primary flex-1"
                onClick={() => setOfflineFound(null)}
              >
                Fermer
              </button>
              <button
                type="button"
                className="btn-secondary flex-1"
                onClick={() => navigate('/history')}
              >
                Voir l'historique
              </button>
            </div>
          </div>
        )}
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
