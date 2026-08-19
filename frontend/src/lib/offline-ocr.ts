/**
 * All OCR, always — the camera loop and the photo-import picker both run every recognition through
 * this module. There is deliberately no server-side OCR path (there used to be one, `POST
 * /scan/ocr` + pytesseract): keeping both meant every change to the accepted-number logic had to
 * be ported and re-verified twice, and the backend one still required a reachable server for the
 * single most connectivity-sensitive moment in the app — identifying the thing in front of the
 * camera. One path, always on-device, is both simpler and works with zero backend reachable.
 *
 * The set-number *extraction* (`set-number-extractor.ts`) is what used to be a straight port of
 * `backend/app/services/ocr.py`'s regex layer before that file was deleted; it still defines the
 * shape a recognition result must have (lines of text) for that extractor to run over it.
 *
 * The worker/core/language files are self-hosted under `public/tesseract/` (see
 * `scripts/fetch-tesseract-assets.mjs`) rather than left at tesseract.js's CDN defaults — a CDN
 * fetch on first use would defeat "scanning works immediately, backend or no backend", since that
 * fetch is exactly the thing with no path to succeed the moment it's needed. They're also in the
 * service worker's precache list (`vite.config.ts`), so they're on-device before they're ever
 * needed, not fetched from cold on the first scan.
 */

import * as Tesseract from 'tesseract.js'

const LANGS = 'eng+fra'

let workerPromise: Promise<Tesseract.Worker> | null = null

async function getWorker(): Promise<Tesseract.Worker> {
  workerPromise ??= Tesseract.createWorker(LANGS, Tesseract.OEM.LSTM_ONLY, {
    workerPath: '/tesseract/worker.min.js',
    corePath: '/tesseract/tesseract-core-simd-lstm.wasm.js',
    langPath: '/tesseract/lang-data',
  }).then(async (worker) => {
    await worker.setParameters({ tessedit_pageseg_mode: Tesseract.PSM.SPARSE_TEXT })
    return worker
  })
  return workerPromise
}

/**
 * Starts the worker before it's actually needed. OCR is on the critical path for every scan now
 * (not a fallback reached only after a failed network attempt), so `ScannerPage` calls this on
 * mount rather than paying the worker's cold-start — loading the WASM core and both language
 * packs — inside the first capture tick, which would otherwise sit there looking unresponsive.
 * Safe to call repeatedly: `getWorker` itself is what dedupes concurrent/redundant starts.
 */
export async function warmUp(): Promise<void> {
  await getWorker()
}

/**
 * Terminates the warm worker, freeing its WASM memory. Call on scanner unmount/tab-hidden,
 * mirroring `useCamera.ts`'s own stop-on-hidden discipline — a later `recognize` call
 * transparently spins a fresh worker back up.
 */
export async function terminateOfflineOcr(): Promise<void> {
  const pending = workerPromise
  workerPromise = null
  const worker = await pending?.catch(() => null)
  await worker?.terminate()
}

/**
 * OCR one frame locally. Returns recognised lines, or an empty list on any failure — a scanner
 * that throws on a blurry frame would break the live capture loop, exactly like the server path.
 */
export async function recognize(image: Blob): Promise<string[]> {
  try {
    const worker = await getWorker()
    const {
      data: { text },
    } = await worker.recognize(image)
    return text
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
  } catch {
    return []
  }
}
