/**
 * The shared primitives, matched to the iOS app.
 *
 * The pieces that carry the app's look — the grouped card, the navigation bar with its pill
 * buttons, the stat tile, the white-backed thumbnail — live here so a screen never re-invents
 * one slightly differently.
 */

import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { imageUrl } from '../api/client'
import minifigPlaceholder from '../assets/minifig-placeholder.png'
import Icon from './Icon'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>
}

/**
 * A grouped section: grey label, card, explanatory footer. The single most recognisable piece of
 * the iOS settings/detail layout.
 */
export function Section({
  title,
  footer,
  children,
  className = '',
}: {
  title?: string
  footer?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`space-y-2 ${className}`}>
      {title && <h2 className="section-title px-1">{title}</h2>}
      <div className="list-card">{children}</div>
      {footer && <p className="section-footer">{footer}</p>}
    </section>
  )
}

/** One row inside a `Section`, with the divider inset past the leading content. */
export function Row({
  children,
  className = '',
  onClick,
  inset = true,
}: {
  children: ReactNode
  className?: string
  onClick?: () => void
  inset?: boolean
}) {
  const content = (
    <div
      className={`flex min-h-12 items-center gap-3 px-4 py-3 ${
        inset ? 'border-b border-line last:border-0' : ''
      } ${className}`}
    >
      {children}
    </div>
  )
  if (!onClick) return content
  return (
    <button type="button" onClick={onClick} className="block w-full text-left active:bg-surface-sunken">
      {content}
    </button>
  )
}

/**
 * The navigation bar: a circular back button, a centred title, and pill actions on the right.
 * Home is the only screen without one — it carries a large title in its scrolling content instead.
 */
export function NavBar({
  title,
  onBack,
  backLabel = 'Retour',
  actions,
}: {
  title: string
  onBack?: () => void
  backLabel?: string
  actions?: ReactNode
}) {
  const navigate = useNavigate()
  return (
    <div className="sticky top-0 z-30 -mx-4 mb-3 flex items-center gap-2 bg-surface/90 px-4 py-2 backdrop-blur">
      <button
        type="button"
        className="nav-circle shrink-0"
        onClick={onBack ?? (() => navigate(-1))}
        aria-label={backLabel}
      >
        <Icon name="chevron-left" />
      </button>
      <h1 className="min-w-0 flex-1 truncate text-center text-[17px] font-semibold text-ink">{title}</h1>
      <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
    </div>
  )
}

export function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

export function LoadingBlock({ label = 'Chargement…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-ink-muted" role="status">
      <Spinner />
      <span className="text-[15px]">{label}</span>
    </div>
  )
}

/** The `ContentUnavailableView` equivalent — an empty state with an action, never a dead end. */
export function EmptyState({
  icon,
  title,
  message,
  action,
}: {
  icon?: ReactNode
  title: string
  message?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      {icon && <div className="mb-1 text-ink-faint">{icon}</div>}
      <p className="text-[20px] font-bold text-ink">{title}</p>
      {message && <p className="max-w-sm text-[15px] text-ink-muted">{message}</p>}
      {action && <div className="pt-3">{action}</div>}
    </div>
  )
}

/** Deliberately not styled like the neutral status lines beside it. */
export function ErrorLabel({ message, className = '' }: { message: string; className?: string }) {
  return (
    <p className={`flex items-center gap-1.5 text-[15px] font-medium text-[rgb(var(--negative))] ${className}`}>
      <Icon name="warning" className="h-4 w-4 shrink-0" />
      <span>{message}</span>
    </p>
  )
}

/** The green "in your collection" line the detail screen leads with. */
export function StatusLine({
  tone = 'positive',
  children,
}: {
  tone?: 'positive' | 'neutral' | 'warning'
  children: ReactNode
}) {
  const colors = {
    positive: 'text-[rgb(var(--positive))]',
    neutral: 'text-ink-muted',
    warning: 'text-[rgb(var(--warning))]',
  }
  return (
    <p className={`flex items-center justify-center gap-2 text-[17px] font-medium ${colors[tone]}`}>
      {tone === 'positive' && (
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[rgb(var(--positive))] text-white">
          <Icon name="check" className="h-3.5 w-3.5" />
        </span>
      )}
      {children}
    </p>
  )
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'positive' | 'negative' | 'warning' | 'brand'
}) {
  const tones = {
    neutral: 'bg-surface-sunken text-ink-muted',
    positive: 'bg-[rgb(var(--positive))]/15 text-[rgb(var(--positive))]',
    negative: 'bg-[rgb(var(--negative))]/15 text-[rgb(var(--negative))]',
    warning: 'bg-[rgb(var(--warning))]/15 text-[rgb(var(--warning))]',
    brand: 'bg-brand/15 text-brand',
  }
  return <span className={`chip ${tones[tone]}`}>{children}</span>
}

/**
 * The iOS switch. Use this for every on/off preference — a bare checkbox reads as a form control
 * from another app entirely next to the rest of these primitives.
 *
 * Drop it inside the `<label>` that carries the wording, as the iOS rows do:
 *
 *     <label className="flex items-center justify-between gap-3">
 *       <span className="text-sm text-ink">Rafraîchissement en arrière-plan</span>
 *       <Toggle checked={…} onChange={…} />
 *     </label>
 *
 * `label` is only needed when the switch stands on its own, with no wording wrapping it.
 */
export function Toggle({
  checked,
  onChange,
  disabled = false,
  label,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  label?: string
}) {
  return (
    <span className="toggle">
      <input
        type="checkbox"
        role="switch"
        className="toggle-input"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.target.checked)}
      />
      {/* Purely decorative: the input above is the control a screen reader sees. */}
      <span className="toggle-track" aria-hidden="true">
        <span className="toggle-knob" />
      </span>
    </span>
  )
}

/**
 * The stand-in for a minifig with no usable artwork — the same idea as the iOS `MinifigPlaceholder`
 * asset. Bundled (Vite hashes it into the build) rather than fetched, so the fallback can't itself
 * fail to load, and trimmed to a transparent-background 2.3 KB PNG from the 1 MB original — safe to
 * drop on any surface, light or dark, unlike `SetThumbnail`'s fixed white tile below.
 */
export function MinifigPlaceholder({ className = '' }: { className?: string }) {
  return (
    <img
      src={minifigPlaceholder}
      alt=""
      aria-hidden="true"
      className={`h-full w-full object-contain ${className}`}
    />
  )
}

/**
 * Set and minifig artwork. The tile is **white** in both themes: Rebrickable's renders are cut out
 * on white, and on a dark tile they gain a visible grey box.
 */
export function SetThumbnail({
  url,
  alt,
  size = 'md',
  isMinifig = false,
}: {
  url: string | null | undefined
  alt: string
  size?: 'sm' | 'md' | 'lg'
  /** Missing artwork falls back to the minifig silhouette instead of the generic brick icon. */
  isMinifig?: boolean
}) {
  // Rebrickable serves plenty of URLs that 404, and a failed <img> falls back to the browser's own
  // torn-page glyph — which looks like the app is broken rather than the artwork missing. `onError`
  // is the only signal a load failure gives.
  const [failed, setFailed] = useState(false)
  const dimensions = { sm: 'h-12 w-12', md: 'h-[60px] w-[60px]', lg: 'h-24 w-24' }[size]
  const src = imageUrl(url)
  return (
    <div className={`${dimensions} shrink-0 overflow-hidden rounded-xl bg-white flex items-center justify-center`}>
      {src && !failed ? (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          // The browser now reaches the CDN itself, so it would otherwise hand that CDN the URL of
          // this instance — typically a private LAN address — with every thumbnail.
          referrerPolicy="no-referrer"
          className="h-full w-full object-contain p-0.5"
          onError={() => setFailed(true)}
        />
      ) : isMinifig ? (
        <MinifigPlaceholder className="p-1" />
      ) : (
        <Icon name="brick" className="h-6 w-6 text-ink-faint" />
      )}
    </div>
  )
}

export function Toast({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-28 z-50 mx-auto w-fit max-w-[90vw] rounded-full bg-surface-raised px-4 py-2.5
                 text-[15px] font-medium text-ink shadow-lg"
      onClick={onDismiss}
    >
      {message}
    </div>
  )
}

/** A modal sheet: "Fermer" on the left, an optional confirming action on the right. */
export function Sheet({
  open,
  title,
  onClose,
  children,
  footer,
  action,
  wide = false,
}: {
  open: boolean
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  action?: ReactNode
  wide?: boolean
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <button type="button" aria-label="Fermer" className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        className={`relative flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-3xl bg-surface
                    shadow-2xl sm:rounded-3xl ${wide ? 'sm:max-w-4xl' : 'sm:max-w-lg'}`}
      >
        <header className="flex items-center gap-2 px-4 pb-1 pt-3">
          <button type="button" className="nav-pill" onClick={onClose}>
            Fermer
          </button>
          <span className="min-w-0 flex-1 truncate text-center text-[17px] font-semibold text-ink">{title}</span>
          <div className="flex min-w-[76px] justify-end">{action}</div>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && <footer className="px-4 pb-6 pt-2">{footer}</footer>}
      </div>
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirmer',
  destructive = false,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message?: string
  confirmLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-8" role="alertdialog" aria-modal="true">
      <button type="button" aria-label="Annuler" className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative w-full max-w-[280px] overflow-hidden rounded-2xl bg-surface-raised text-center">
        <div className="space-y-1 px-4 py-4">
          <p className="text-[17px] font-semibold text-ink">{title}</p>
          {message && <p className="text-[13px] text-ink-muted">{message}</p>}
        </div>
        <div className="grid grid-cols-2 border-t border-line">
          <button
            type="button"
            className="border-r border-line py-3 text-[17px] text-brand active:bg-surface-sunken"
            onClick={onCancel}
          >
            Annuler
          </button>
          <button
            type="button"
            className={`py-3 text-[17px] font-semibold active:bg-surface-sunken ${
              destructive ? 'text-[rgb(var(--negative))]' : 'text-brand'
            }`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * The Home tile. The value is the headline and the caption sits pinned at the bottom, so tiles in
 * one row stay the same height whether their value is a number or a word.
 */
export function StatCard({
  title,
  value,
  icon,
  caption,
  isLink = false,
}: {
  title: string
  value?: string
  icon?: ReactNode
  caption?: string
  isLink?: boolean
}) {
  return (
    <div className="flex h-full min-h-[150px] flex-col rounded-2xl bg-surface-raised p-4 text-left">
      <div className="flex items-start justify-between">
        <span className="text-brand">{icon}</span>
        {isLink && <Icon name="chevron-right" className="h-4 w-4 text-ink-faint" />}
      </div>
      <p className="mt-2 text-[22px] font-bold leading-tight text-ink">{value ?? title}</p>
      <div className="flex-1" />
      <p className="text-[15px] text-ink-muted">{value === undefined ? (caption ?? '') : title}</p>
    </div>
  )
}
