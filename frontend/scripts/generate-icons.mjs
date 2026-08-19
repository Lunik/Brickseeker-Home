// Rasterizes the two PWA icon sources into the PNGs `public/icons/` and the manifest reference.
// Run manually (`npm run icons`) and commit the output — this is not part of the build, since
// re-rastering four PNGs on every CI run for an asset that changes maybe once a year is wasted
// work, and `sharp` is a devDependency with a native binding.

import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import sharp from 'sharp'

const root = dirname(fileURLToPath(import.meta.url))
const source = resolve(root, '../src/assets/pwa-icon-source.svg')
const maskableSource = resolve(root, '../src/assets/pwa-icon-maskable-source.svg')
const outDir = resolve(root, '../public/icons')

await mkdir(outDir, { recursive: true })

async function render(svgPath, size, filename) {
  await sharp(svgPath, { density: (size / 64) * 96 })
    .resize(size, size)
    .png()
    .toFile(resolve(outDir, filename))
  console.log(`  ${filename} (${size}x${size})`)
}

console.log('Generating PWA icons…')
await render(source, 192, 'icon-192.png')
await render(source, 512, 'icon-512.png')
await render(source, 180, 'apple-touch-icon.png')
await render(maskableSource, 512, 'icon-maskable-512.png')
console.log('Done.')
