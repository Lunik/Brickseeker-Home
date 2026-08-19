import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * The rear camera, as a hook.
 *
 * The stream is stopped on unmount *and* whenever the tab is hidden. A camera left running is a
 * battery drain and a privacy problem, and the iOS app treats stopping the capture session as a
 * hard requirement whenever anything covers the scanner.
 */
export interface CameraHandle {
  videoRef: React.RefObject<HTMLVideoElement>
  isActive: boolean
  error: string | null
  hasTorch: boolean
  torchOn: boolean
  toggleTorch: () => Promise<void>
  /** A JPEG of the reticle region, or null if no frame is available yet. */
  captureFrame: (crop?: { widthRatio: number; heightRatio: number }) => Promise<Blob | null>
  restart: () => void
}

export function useCamera(enabled: boolean): CameraHandle {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [isActive, setIsActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasTorch, setHasTorch] = useState(false)
  const [torchOn, setTorchOn] = useState(false)
  const [attempt, setAttempt] = useState(0)

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    setIsActive(false)
    setTorchOn(false)
  }, [])

  useEffect(() => {
    if (!enabled) {
      stop()
      return
    }

    let cancelled = false

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError(
          "Ce navigateur ne donne pas accès à la caméra. Utilisez la saisie manuelle ou l'import de photo.",
        )
        return
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 } },
          audio: false,
        })
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => undefined)
        }
        const capabilities = stream.getVideoTracks()[0]?.getCapabilities?.() as
          | { torch?: boolean }
          | undefined
        setHasTorch(Boolean(capabilities?.torch))
        setIsActive(true)
        setError(null)
      } catch (caught) {
        if (cancelled) return
        const name = (caught as DOMException)?.name
        setError(
          name === 'NotAllowedError'
            ? "Accès à la caméra refusé. Autorisez-le dans votre navigateur, ou utilisez la saisie manuelle."
            : name === 'NotFoundError'
              ? "Aucune caméra détectée sur cet appareil."
              : // getUserMedia is https-only outside localhost, and that is by far the most common
                // stumbling block for a self-hosted app reached by LAN IP.
                "Caméra indisponible. Sur une adresse non-HTTPS, les navigateurs bloquent l'accès à la caméra.",
        )
      }
    }

    void start()
    return () => {
      cancelled = true
      stop()
    }
  }, [enabled, stop, attempt])

  useEffect(() => {
    function onVisibility() {
      if (document.hidden) stop()
      else if (enabled) setAttempt((value) => value + 1)
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [enabled, stop])

  const toggleTorch = useCallback(async () => {
    const track = streamRef.current?.getVideoTracks()[0]
    if (!track) return
    const next = !torchOn
    try {
      // `torch` ships in Chromium but isn't in the DOM typings yet.
      await track.applyConstraints({ advanced: [{ torch: next }] } as unknown as MediaTrackConstraints)
      setTorchOn(next)
    } catch {
      setHasTorch(false)
    }
  }, [torchOn])

  const captureFrame = useCallback(
    async (crop = { widthRatio: 0.8, heightRatio: 0.35 }): Promise<Blob | null> => {
      const video = videoRef.current
      if (!video || video.readyState < 2 || !video.videoWidth) return null

      const canvas = (canvasRef.current ??= document.createElement('canvas'))
      // Only the reticle region is sent: OCR on the full frame picks up every other number on the
      // packaging, and the upload is ~4× larger for no gain.
      //
      // The ratios are of what is *on screen*, not of the raw frame, because the element is
      // `object-cover`: the source is scaled up and centre-cropped to fill it, so the visible
      // picture is a sub-rectangle of the frame. Taking the same ratios off the raw frame instead
      // is not the reticle at all — on a 390×844 element showing a 1920×1080 stream the reticle
      // covers 399 source px across while that crop sent 1536, i.e. 3.85× too wide, over a
      // thousand of them never on screen. Everything the user had deliberately framed out came
      // along, and the number they aimed at shrank to a fraction of the image OCR then read.
      const elementWidth = video.clientWidth || video.videoWidth
      const elementHeight = video.clientHeight || video.videoHeight
      // How `object-cover` sizes the source against the element; the crop it applies is centred,
      // and so is the reticle, so only the size has to be mapped back.
      const cover = Math.max(elementWidth / video.videoWidth, elementHeight / video.videoHeight)
      const visibleWidth = elementWidth / cover
      const visibleHeight = elementHeight / cover

      const width = Math.round(visibleWidth * crop.widthRatio)
      const height = Math.round(visibleHeight * crop.heightRatio)
      canvas.width = width
      canvas.height = height

      const context = canvas.getContext('2d')
      if (!context) return null
      context.drawImage(
        video,
        Math.round((video.videoWidth - width) / 2),
        Math.round((video.videoHeight - height) / 2),
        width,
        height,
        0,
        0,
        width,
        height,
      )
      return new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.85))
    },
    [],
  )

  const restart = useCallback(() => setAttempt((value) => value + 1), [])

  // A fresh object every render defeats any effect that depends on this handle wholesale — exactly
  // the `resolvingRef`-vs-effect-deps trap described above, but for the handle itself: the capture
  // loop in ScannerPage depends on `camera`, so an unmemoized return tore that interval down and
  // rebuilt it on every `setResolving`/`setCandidate` inside a resolve, restarting its 800 ms
  // cadence each time.
  return useMemo(
    () => ({ videoRef, isActive, error, hasTorch, torchOn, toggleTorch, captureFrame, restart }),
    [isActive, error, hasTorch, torchOn, toggleTorch, captureFrame, restart],
  )
}
