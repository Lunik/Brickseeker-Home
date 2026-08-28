import { useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'

import type { PriceSourceKey, SetDetail } from '../api/types'
import { imageUrl } from '../api/client'
import { baseSetNum, formatEUR, SOURCE_LABEL } from '../lib/format'
import Icon from './Icon'
import { Sheet } from './ui'

/** Sources shown in link mode (excludes BrickLink-only minifig sources). */
const LINK_SOURCES: Array<{ key: PriceSourceKey; label: string }> = [
  { key: 'amazon', label: 'Amazon' },
  { key: 'cdiscount', label: 'Cdiscount' },
  { key: 'bricklinkNew', label: 'BrickLink (neuf)' },
  { key: 'bricklinkUsed', label: 'BrickLink (occasion)' },
]

/** The three retailer rows shown on the image card (first three non-lego sources). */
const IMAGE_SOURCES: PriceSourceKey[] = ['amazon', 'cdiscount', 'bricklinkNew']

const CARD_WIDTH = 480
const CARD_HEIGHT = 640

interface Props {
  open: boolean
  onClose: () => void
  detail: SetDetail
}

export default function ShareSetSheet({ open, onClose, detail }: Props) {
  const [mode, setMode] = useState<'link' | 'image'>('image')
  const [selectedLinkSource, setSelectedLinkSource] = useState<'lego' | PriceSourceKey>('lego')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [imageReady, setImageReady] = useState(false)

  const bySource = new Map(detail.quotes.map((q) => [q.source, q]))

  // Build the lego.com URL from storeUrl or set number
  const legoUrl = detail.storeUrl ?? `https://www.lego.com/fr-fr/search?q=${baseSetNum(detail.set.setNum)}`

  // Resolve the shareable URL for the current selection
  function resolvedLinkUrl(): string {
    if (selectedLinkSource === 'lego') return legoUrl
    const quote = bySource.get(selectedLinkSource as PriceSourceKey)
    return quote?.sourceUrl ?? legoUrl
  }

  // Draw the image card whenever the sheet opens in image mode
  useEffect(() => {
    if (!open || mode !== 'image') return
    setImageReady(false)
    drawCard(canvasRef.current, detail, legoUrl).then(() => setImageReady(true))
  }, [open, mode, detail, legoUrl])

  function handleCopyLink() {
    navigator.clipboard.writeText(resolvedLinkUrl())
  }

  function handleOpenLink() {
    window.open(resolvedLinkUrl(), '_blank', 'noreferrer')
  }

  function handleDownloadImage() {
    const canvas = canvasRef.current
    if (!canvas) return
    const a = document.createElement('a')
    a.href = canvas.toDataURL('image/png')
    a.download = `lego-${baseSetNum(detail.set.setNum)}.png`
    a.click()
  }

  async function handleShareImage() {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.toBlob(async (blob) => {
      if (!blob) return
      const file = new File([blob], `lego-${baseSetNum(detail.set.setNum)}.png`, { type: 'image/png' })
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: detail.set.name })
      } else {
        handleDownloadImage()
      }
    }, 'image/png')
  }

  return (
    <Sheet open={open} title="Partager ce set" onClose={onClose}>
      <div className="space-y-4">
        {/* Mode selector */}
        <div className="flex rounded-xl bg-surface-raised p-1">
          {(['image', 'link'] as const).map((m) => (
            <button
              key={m}
              type="button"
              className={`flex-1 rounded-lg py-2 text-sm font-medium transition-colors ${
                mode === m ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted'
              }`}
              onClick={() => setMode(m)}
            >
              {m === 'image' ? '🖼 Image' : '🔗 Lien'}
            </button>
          ))}
        </div>

        {mode === 'link' && (
          <div className="space-y-3">
            {/* lego.com option */}
            <button
              type="button"
              className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left ${
                selectedLinkSource === 'lego'
                  ? 'border-brand bg-brand/10'
                  : 'border-line bg-surface-raised'
              }`}
              onClick={() => setSelectedLinkSource('lego')}
            >
              <span className="flex-1 text-sm font-medium text-ink">lego.com (officiel)</span>
              {detail.storePriceEur !== null && (
                <span className="text-sm font-bold text-ink">{formatEUR(detail.storePriceEur)}</span>
              )}
              {selectedLinkSource === 'lego' && (
                <Icon name="check" className="h-4 w-4 shrink-0 text-brand" />
              )}
            </button>

            {/* Retailer options — only those with a sourceUrl */}
            {LINK_SOURCES.filter((s) => !detail.isMinifig || s.key.startsWith('bricklink')).map(
              ({ key, label }) => {
                const quote = bySource.get(key)
                if (!quote?.sourceUrl) return null
                return (
                  <button
                    key={key}
                    type="button"
                    className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left ${
                      selectedLinkSource === key
                        ? 'border-brand bg-brand/10'
                        : 'border-line bg-surface-raised'
                    }`}
                    onClick={() => setSelectedLinkSource(key)}
                  >
                    <span className="flex-1 text-sm font-medium text-ink">{label}</span>
                    <span className="text-sm font-bold text-ink">{formatEUR(quote.amount)}</span>
                    {selectedLinkSource === key && (
                      <Icon name="check" className="h-4 w-4 shrink-0 text-brand" />
                    )}
                  </button>
                )
              },
            )}

            <div className="flex gap-2 pt-1">
              <button type="button" className="btn-secondary flex-1" onClick={handleCopyLink}>
                <Icon name="copy" className="h-4 w-4" />
                Copier
              </button>
              <button type="button" className="btn-primary flex-1" onClick={handleOpenLink}>
                <Icon name="link" className="h-4 w-4" />
                Ouvrir
              </button>
            </div>
          </div>
        )}

        {mode === 'image' && (
          <div className="space-y-3">
            {/* Preview canvas — scaled down to fit the sheet width */}
            <div className="flex justify-center">
              <canvas
                ref={canvasRef}
                width={CARD_WIDTH}
                height={CARD_HEIGHT}
                className="w-full max-w-xs rounded-2xl shadow-lg"
                style={{ aspectRatio: `${CARD_WIDTH}/${CARD_HEIGHT}` }}
              />
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                className="btn-secondary flex-1"
                disabled={!imageReady}
                onClick={handleDownloadImage}
              >
                <Icon name="download" className="h-4 w-4" />
                Télécharger
              </button>
              <button
                type="button"
                className="btn-primary flex-1"
                disabled={!imageReady}
                onClick={handleShareImage}
              >
                <Icon name="share" className="h-4 w-4" />
                Partager
              </button>
            </div>
          </div>
        )}
      </div>
    </Sheet>
  )
}

/** Renders the share card onto the provided canvas. Returns after all async work is done. */
async function drawCard(canvas: HTMLCanvasElement | null, detail: SetDetail, legoUrl: string): Promise<void> {
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const W = CARD_WIDTH
  const H = CARD_HEIGHT
  const bySource = new Map(detail.quotes.map((q) => [q.source, q]))

  // ─── Background ────────────────────────────────────────────────────────────
  // Gradient from deep navy to slightly lighter — matches the app's dark surface palette
  const bg = ctx.createLinearGradient(0, 0, 0, H)
  bg.addColorStop(0, '#1a1f2e')
  bg.addColorStop(1, '#111827')
  ctx.fillStyle = bg
  roundRect(ctx, 0, 0, W, H, 24)
  ctx.fill()

  // ─── Set image ─────────────────────────────────────────────────────────────
  const imgSrc = imageUrl(detail.set.setImgUrl)
  if (imgSrc) {
    try {
      const img = await loadImage(imgSrc)
      const imgW = 260
      const imgH = 200
      const imgX = (W - imgW) / 2
      ctx.save()
      roundRect(ctx, imgX - 4, 28 - 4, imgW + 8, imgH + 8, 16)
      ctx.clip()
      ctx.fillStyle = 'rgba(255,255,255,0.04)'
      ctx.fillRect(imgX - 4, 28 - 4, imgW + 8, imgH + 8)
      ctx.drawImage(img, imgX, 28, imgW, imgH)
      ctx.restore()
    } catch {
      // Image failed to load — draw placeholder brick icon
      ctx.fillStyle = 'rgba(255,255,255,0.08)'
      roundRect(ctx, W / 2 - 48, 50, 96, 96, 12)
      ctx.fill()
    }
  }

  // ─── Set number ────────────────────────────────────────────────────────────
  ctx.fillStyle = '#f97316' // brand orange
  ctx.font = 'bold 22px system-ui, -apple-system, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(baseSetNum(detail.set.setNum), W / 2, 254)

  // ─── Set name ──────────────────────────────────────────────────────────────
  ctx.fillStyle = '#f1f5f9'
  ctx.font = 'bold 20px system-ui, -apple-system, sans-serif'
  wrapText(ctx, detail.set.name, W / 2, 282, W - 48, 26)

  // ─── Meta line (year · parts) ───────────────────────────────────────────────
  ctx.fillStyle = '#94a3b8'
  ctx.font = '14px system-ui, -apple-system, sans-serif'
  const meta = [
    detail.set.year ? String(detail.set.year) : null,
    detail.set.numParts ? `${detail.set.numParts.toLocaleString('fr')} pièces` : null,
  ]
    .filter(Boolean)
    .join(' · ')
  ctx.fillText(meta, W / 2, 318)

  // ─── Divider ───────────────────────────────────────────────────────────────
  ctx.strokeStyle = 'rgba(255,255,255,0.1)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(24, 334)
  ctx.lineTo(W - 24, 334)
  ctx.stroke()

  // ─── lego.com price row ────────────────────────────────────────────────────
  const priceRowHeight = 44
  let rowY = 348

  drawPriceRow(ctx, 'lego.com (officiel)', detail.storePriceEur, null, rowY, W)
  rowY += priceRowHeight

  // ─── Three retailer rows ───────────────────────────────────────────────────
  for (const sourceKey of IMAGE_SOURCES) {
    if (detail.isMinifig && !sourceKey.startsWith('bricklink')) continue
    const quote = bySource.get(sourceKey)
    const pct = quote && detail.storePriceEur
      ? Math.round(((quote.amount - detail.storePriceEur) / detail.storePriceEur) * 100)
      : null
    drawPriceRow(ctx, SOURCE_LABEL[sourceKey], quote?.amount ?? null, pct, rowY, W)
    rowY += priceRowHeight
  }

  // ─── QR code ───────────────────────────────────────────────────────────────
  const qrSize = 100
  const qrX = (W - qrSize) / 2
  const qrY = H - qrSize - 36

  try {
    const qrDataUrl = await QRCode.toDataURL(legoUrl, {
      width: qrSize * 2,
      margin: 1,
      color: { dark: '#1a1f2e', light: '#ffffff' },
    })
    const qrImg = await loadImage(qrDataUrl)
    // White pill behind QR
    ctx.fillStyle = '#ffffff'
    roundRect(ctx, qrX - 8, qrY - 8, qrSize + 16, qrSize + 16, 14)
    ctx.fill()
    ctx.drawImage(qrImg, qrX, qrY, qrSize, qrSize)
  } catch {
    // QR generation failed — skip silently
  }

  // ─── Footer label ──────────────────────────────────────────────────────────
  ctx.fillStyle = '#475569'
  ctx.font = '11px system-ui, -apple-system, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText('BrickSeeker', W / 2, H - 14)
}

function drawPriceRow(
  ctx: CanvasRenderingContext2D,
  label: string,
  amount: number | null,
  pct: number | null,
  y: number,
  W: number,
) {
  const PAD = 28
  ctx.textAlign = 'left'
  ctx.fillStyle = '#cbd5e1'
  ctx.font = '14px system-ui, -apple-system, sans-serif'
  ctx.fillText(label, PAD, y + 16)

  ctx.textAlign = 'right'
  if (amount !== null) {
    ctx.fillStyle = '#f1f5f9'
    ctx.font = 'bold 15px system-ui, -apple-system, sans-serif'
    ctx.fillText(formatEUR(amount), W - PAD, y + 16)

    if (pct !== null && pct !== 0) {
      const positive = pct < 0
      ctx.fillStyle = positive ? '#4ade80' : '#f87171'
      ctx.font = '12px system-ui, -apple-system, sans-serif'
      ctx.textAlign = 'right'
      ctx.fillText(`${pct > 0 ? '+' : ''}${pct} %`, W - PAD, y + 32)
    }
  } else {
    ctx.fillStyle = '#475569'
    ctx.font = '14px system-ui, -apple-system, sans-serif'
    ctx.fillText('Indisponible', W - PAD, y + 16)
  }
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

/** Draws a rounded rectangle path (does not fill or stroke). */
function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

/** Naive single-line ellipsis wrap — draws at most two lines then clips with "…". */
function wrapText(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
) {
  const words = text.split(' ')
  let line = ''
  let lineCount = 0
  for (const word of words) {
    const test = line ? `${line} ${word}` : word
    if (ctx.measureText(test).width > maxWidth && line) {
      if (lineCount === 1) {
        // Second line overflow — truncate with ellipsis
        let truncated = line
        while (ctx.measureText(`${truncated}…`).width > maxWidth && truncated.length > 0) {
          truncated = truncated.slice(0, -1)
        }
        ctx.fillText(`${truncated}…`, cx, y + lineCount * lineHeight)
        return
      }
      ctx.fillText(line, cx, y + lineCount * lineHeight)
      lineCount++
      line = word
    } else {
      line = test
    }
  }
  ctx.fillText(line, cx, y + lineCount * lineHeight)
}
