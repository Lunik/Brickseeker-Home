// Rasterizes `src/assets/pwa-icon-source.png` into the icon set the manifest and index.html point
// at. Run manually (`npm run icons`) and commit the output — this is not part of the build, since
// re-rendering six PNGs on every CI run for an asset that changes maybe once a year is wasted work,
// and `sharp` is a devDependency with a native binding.
//
// The source is a 2000×2000 RGBA illustration whose rounded-square shape is baked in, with fully
// transparent corners. That single file cannot serve every target as-is:
//
//   * "any" icons keep the transparency, so the shape the artwork was drawn with is the shape shown.
//   * apple-touch-icon is flattened onto the artwork's own navy: iOS composites transparency against
//     black and applies its own rounded mask, so transparent corners come out as black fringing
//     just outside the mask.
//   * the maskable icon is the artwork inset on a full-bleed navy field. A maskable icon is cropped
//     by the OS to whatever shape it likes — circle, squircle, teardrop — and only the middle 80%
//     is guaranteed to survive, so full-bleed artwork would lose its edges.

import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import sharp from 'sharp'

const root = dirname(fileURLToPath(import.meta.url))
const source = resolve(root, '../src/assets/pwa-icon-source.png')
const outDir = resolve(root, '../public/icons')

/** Sampled from the artwork's own background, so the flattened edges are invisible against it. */
const BACKGROUND = { r: 10, g: 36, b: 63, alpha: 1 }
/** Share of the maskable canvas the artwork occupies — the rest is the bleed the OS may crop. */
const MASKABLE_SCALE = 0.78

await mkdir(outDir, { recursive: true })

async function transparent(size, filename) {
  await sharp(source).resize(size, size, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toFile(resolve(outDir, filename))
  console.log(`  ${filename} (${size}×${size}, transparent)`)
}

async function flattened(size, filename) {
  await sharp(source).resize(size, size, { fit: 'contain', background: BACKGROUND })
    .flatten({ background: BACKGROUND })
    .png()
    .toFile(resolve(outDir, filename))
  console.log(`  ${filename} (${size}×${size}, flattened)`)
}

async function maskable(size, filename) {
  const inner = Math.round(size * MASKABLE_SCALE)
  const art = await sharp(source).resize(inner, inner, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer()
  await sharp({ create: { width: size, height: size, channels: 4, background: BACKGROUND } })
    .composite([{ input: art, gravity: 'centre' }])
    .png()
    .toFile(resolve(outDir, filename))
  console.log(`  ${filename} (${size}×${size}, ${Math.round(MASKABLE_SCALE * 100)}% inset on navy)`)
}

console.log('Generating icons from pwa-icon-source.png…')
await transparent(192, 'icon-192.png')
await transparent(512, 'icon-512.png')
await flattened(180, 'apple-touch-icon.png')
await maskable(512, 'icon-maskable-512.png')
// Browser-tab sizes. The artwork is a detailed scene rather than a glyph, so it reads as a small
// dark tile here — legible as "this tab", not as a picture.
await flattened(32, 'favicon-32.png')
await flattened(16, 'favicon-16.png')
console.log('Done.')
