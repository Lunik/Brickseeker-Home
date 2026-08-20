import type { ReactNode } from 'react'

import type { SetRow as SetRowData } from '../api/types'
import { useLongPress } from '../hooks/useLongPress'
import { baseSetNum, formatEUR } from '../lib/format'
import Icon from './Icon'
import { SetThumbnail } from './ui'

/**
 * One row of a browse list.
 *
 * The selection indicator is **trailing**, not leading: it has to sit where the thumb already is
 * and must not push the artwork sideways when selection mode turns on.
 */
export function RowSelectionIndicator({ selected }: { selected: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 ${
        selected ? 'border-brand bg-brand text-white' : 'border-line text-transparent'
      }`}
    >
      <Icon name="check" className="h-3.5 w-3.5" />
    </span>
  )
}

export interface SetRowProps {
  row: SetRowData
  subtitle?: string | null
  selecting?: boolean
  selected?: boolean
  onClick?: () => void
  /** Right-click on desktop, long-press on touch — both open the same quick-action sheet. */
  onQuickAction?: (row: SetRowData) => void
  trailing?: ReactNode
}

export default function SetRow({
  row,
  subtitle,
  selecting = false,
  selected = false,
  onClick,
  onQuickAction,
  trailing,
}: SetRowProps) {
  const longPress = useLongPress(row, onQuickAction ?? (() => undefined), Boolean(onQuickAction))

  return (
    <button
      type="button"
      onClick={() => {
        if (!longPress.consumeIfFired()) onClick?.()
      }}
      onContextMenu={longPress.onContextMenu}
      onPointerDown={longPress.onPointerDown}
      onPointerMove={longPress.onPointerMove}
      onPointerUp={longPress.onPointerUp}
      onPointerCancel={longPress.onPointerCancel}
      className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-sunken"
      aria-pressed={selecting ? selected : undefined}
    >
      <SetThumbnail url={row.setImgUrl} alt={row.name} />

      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="text-[20px] font-semibold text-ink">{baseSetNum(row.setNum)}</span>
          {row.quantity > 1 && (
            // VoiceOver read a bare "×2" as "multiplication 2" on iOS, hence the explicit label.
            <span className="text-[13px] font-bold text-ink-muted" aria-label={`${row.quantity} exemplaires`}>
              ×{row.quantity}
            </span>
          )}
          {row.isInWishlist && (
            <Icon name="heart" filled className="h-3.5 w-3.5 text-pink-500" label="Dans votre liste cadeaux" />
          )}
          {row.hasPriceAlert && (
            <Icon name="bell" filled className="h-3.5 w-3.5 text-[rgb(var(--warning))]" label="Alerte de prix active" />
          )}
        </span>
        <span className="block truncate text-[17px] text-ink-muted">{row.name}</span>
        {subtitle && <span className="block truncate text-[13px] text-ink-faint">{subtitle}</span>}
      </span>

      <span className="flex shrink-0 items-center gap-3">
        {row.resolvedPrice !== null && (
          <span className="text-right">
            <span className="block text-[17px] font-semibold text-ink">{formatEUR(row.resolvedPrice)}</span>
            {row.priceLabel && <span className="block text-[11px] text-ink-faint">{row.priceLabel}</span>}
          </span>
        )}
        {trailing}
        {selecting && <RowSelectionIndicator selected={selected} />}
      </span>
    </button>
  )
}
