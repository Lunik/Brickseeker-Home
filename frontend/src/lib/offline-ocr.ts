/**
 * Client-side OCR, reached only when the backend is unreachable — `/scan/ocr` stays the preferred
 * path whenever it answers, since the server-side pass is faster and this is purely the fallback
 * that makes offline scanning possible at all.
 *
 * Mirrors `backend/app/services/ocr.py`'s `recognize_text`: same PSM (11, "sparse text" — a set
 * number is a short isolated string on busy packaging artwork, not a paragraph), same languages
 * (`eng+fra`, matching `settings.ocr_languages`), same shape of return value (recognised lines),
 * so `set-number-extractor.ts` runs identically over either source.
 *
 * The worker/core/language files are self-hosted under `public/tesseract/` (see
 * `scripts/fetch-tesseract-assets.mjs`) rather than left at tesseract.js's CDN defaults — a CDN
 * fetch on first use would defeat "offline scanning works immediately", since that fetch is
 * exactly the thing with no path to succeed at the moment it's needed. They're also in the service
 * worker's precache list (`vite.config.ts`), so they're on-device before they're ever needed.
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
