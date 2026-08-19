// One-time fetch of self-hosted tesseract.js runtime assets — worker script, WASM core, and
// English/French trained data — into public/tesseract/, so offline OCR needs no CDN reachable at
// the moment it's actually needed (which is exactly when a CDN fetch is guaranteed to fail).
// Run manually (`npm run fetch-tesseract-assets`) and commit the output — same reproducibility
// pattern as `generate-icons.mjs`.
//
// `tesseract-core-simd-lstm.wasm.js` is the self-contained variant (WASM binary embedded as
// base64, confirmed by its size — larger than the raw .wasm — and by grepping it for any fetch of
// a sibling .wasm file, of which there is none): copying this one file is enough, no separate
// .wasm to keep alongside it.

import { copyFile, mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(root, '../public/tesseract')
const langDir = resolve(outDir, 'lang-data')

// The CDN tesseract.js itself defaults `langPath` to — same trained-data version the library was
// built against. Kept in mirrored form here rather than fetched from tesseract.js's own default at
// runtime, since relying on that default would silently reintroduce the CDN dependency this script
// exists to remove.
const TESSDATA_BASE = 'https://tessdata.projectnaptha.com/4.0.0'
// Matches the backend's `settings.ocr_languages` (`backend/app/config.py`) exactly, so offline
// recognition reads the same languages the server-side path does.
const LANGS = ['eng', 'fra']

async function download(url, destPath) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${url} → HTTP ${response.status}`)
  const buffer = Buffer.from(await response.arrayBuffer())
  await writeFile(destPath, buffer)
  console.log(`  ${destPath} (${(buffer.length / 1024).toFixed(0)} KB)`)
}

await mkdir(langDir, { recursive: true })

console.log('Copying tesseract.js runtime files…')
await copyFile(
  resolve(root, '../node_modules/tesseract.js/dist/worker.min.js'),
  resolve(outDir, 'worker.min.js'),
)
await copyFile(
  resolve(root, '../node_modules/tesseract.js-core/tesseract-core-simd-lstm.wasm.js'),
  resolve(outDir, 'tesseract-core-simd-lstm.wasm.js'),
)

console.log('Downloading trained language data…')
for (const lang of LANGS) {
  await download(`${TESSDATA_BASE}/${lang}.traineddata.gz`, resolve(langDir, `${lang}.traineddata.gz`))
}
console.log('Done.')
