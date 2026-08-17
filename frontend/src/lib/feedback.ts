/**
 * Sound and vibration for the camera scanning flow — the web port of `ScanFeedback.swift`.
 *
 * In-store scanning is the design target: the phone is at arm's length pointed at a shelf, so the
 * user is not watching the screen when a number lands. Sound and vibration are what actually tell
 * them, which is why they always fire together here rather than being two independent settings.
 *
 * Only the camera path calls these. A manual entry or a tap in Historique resolves the same way but
 * with the user's eyes on the screen, and a phone that buzzes when you type is just noise — the iOS
 * app draws the same line with its `playsFeedbackSounds` flag.
 *
 * Everything degrades silently: no Web Audio (or a context the browser refuses to start without a
 * gesture) and no Vibration API are both normal — Safari has never shipped `navigator.vibrate`.
 * A missing buzz must never cost the user their scan.
 */

let context: AudioContext | null = null
let unavailable = false

function audioContext(): AudioContext | null {
  if (unavailable) return null
  if (!context) {
    const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) {
      unavailable = true
      return null
    }
    try {
      context = new Ctor()
    } catch {
      unavailable = true
      return null
    }
  }
  // Autoplay policies suspend a context created outside a gesture; resuming is a no-op otherwise.
  if (context.state === 'suspended') void context.resume().catch(() => undefined)
  return context
}

/**
 * Warms the audio context up, the counterpart of `UIImpactFeedbackGenerator.prepare()`.
 *
 * Call it from a user gesture (opening the scanner is one): a context first created inside the
 * capture loop starts suspended and swallows the first few beeps.
 */
export function prepareFeedback(): void {
  audioContext()
}

/** One tone. `when` offsets it from now, so a two-note cue is one call per note. */
function tone(frequency: number, duration: number, when = 0, gain = 0.09): void {
  const ctx = audioContext()
  if (!ctx) return
  try {
    const start = ctx.currentTime + when
    const oscillator = ctx.createOscillator()
    const envelope = ctx.createGain()
    oscillator.type = 'sine'
    oscillator.frequency.setValueAtTime(frequency, start)
    // A square-edged tone clicks on cheap phone speakers; the ramps are what make it a "tock".
    envelope.gain.setValueAtTime(0.0001, start)
    envelope.gain.exponentialRampToValueAtTime(gain, start + 0.008)
    envelope.gain.exponentialRampToValueAtTime(0.0001, start + duration)
    oscillator.connect(envelope).connect(ctx.destination)
    oscillator.start(start)
    oscillator.stop(start + duration + 0.02)
  } catch {
    /* an exhausted or closed context is not worth failing a scan over */
  }
}

function vibrate(pattern: number | number[]): void {
  try {
    navigator.vibrate?.(pattern)
  } catch {
    /* some browsers throw when the page is not visible */
  }
}

/** A number has been picked out of the frame — the moment the reticle turns green. */
export function playCandidateDetected(): void {
  tone(1180, 0.05)
  vibrate(12)
}

/** The lookup found a set: two ascending notes, the "resolved" cue. */
export function playResolutionSucceeded(): void {
  tone(880, 0.07)
  tone(1320, 0.1, 0.08)
  vibrate([16, 60, 28])
}

/** Nothing matched, or the lookup failed. Low and flat — never mistakable for a success. */
export function playResolutionFailed(): void {
  tone(320, 0.16, 0, 0.07)
  vibrate([40, 70, 40])
}
