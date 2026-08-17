import { useCallback, useEffect, useRef, useState } from 'react'

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
      const width = Math.round(video.videoWidth * crop.widthRatio)
      const height = Math.round(video.videoHeight * crop.heightRatio)
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

  return {
    videoRef,
    isActive,
    error,
    hasTorch,
    torchOn,
    toggleTorch,
    captureFrame,
    restart: () => setAttempt((value) => value + 1),
  }
}
