/**
 * The shared primitives every screen is built from. Kept in one file on purpose: they are small,
 * they are used everywhere, and a folder of one-component files would make the design language
 * harder to see than it makes it easier to find.
 */

import type { ReactNode } from 'react'

import { imageUrl } from '../api/client'
import Icon from './Icon'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>
}

export function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-90"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  )
}

export function LoadingBlock({ label = 'Chargement…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-ink-muted" role="status">
      <Spinner />
      <span className="text-sm">{label}</span>
    </div>
  )
}

/**
 * The `ContentUnavailableView` equivalent. An empty state with an action beats one without —
 * "aucun set" with nothing to tap is a dead end.
 */
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
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      {icon && <div className="text-4xl text-ink-faint">{icon}</div>}
      <p className="text-base font-semibold text-ink">{title}</p>
      {message && <p className="max-w-sm text-sm text-ink-muted">{message}</p>}
      {action}
    </div>
  )
}

/**
 * An inline failure. Deliberately not styled like the neutral status lines beside it — a failed
 * sync that reads as just another status update is a failed sync nobody notices.
 */
export function ErrorLabel({ message, className = '' }: { message: string; className?: string }) {
  return (
    <p className={`flex items-center gap-1.5 text-sm font-medium text-[rgb(var(--negative))] ${className}`}>
      <Icon name="warning" className="h-4 w-4 shrink-0" />
      <span>{message}</span>
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
    positive: 'bg-[rgb(var(--positive))]/12 text-[rgb(var(--positive))]',
    negative: 'bg-[rgb(var(--negative))]/12 text-[rgb(var(--negative))]',
    warning: 'bg-[rgb(var(--warning))]/15 text-[rgb(var(--warning))]',
    brand: 'bg-brand/12 text-brand',
  }
  return <span className={`chip ${tones[tone]}`}>{children}</span>
}

/**
 * Set/minifig artwork. Always goes through the caching proxy, and always reserves its box so a
 * long list doesn't reflow line by line as images land.
 */
export function SetThumbnail({
  url,
  alt,
  size = 'md',
}: {
  url: string | null | undefined
  alt: string
  size?: 'sm' | 'md' | 'lg'
}) {
  const dimensions = { sm: 'h-12 w-12', md: 'h-16 w-16', lg: 'h-24 w-24' }[size]
  const src = imageUrl(url)
  return (
    <div
      className={`${dimensions} shrink-0 overflow-hidden rounded-lg bg-surface-sunken flex items-center justify-center`}
    >
      {src ? (
        <img src={src} alt={alt} loading="lazy" className="h-full w-full object-contain" />
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
      className="fixed inset-x-0 bottom-24 z-50 mx-auto w-fit max-w-[90vw] rounded-full bg-ink px-4 py-2.5
                 text-sm font-medium text-surface shadow-lg"
      onClick={onDismiss}
    >
      {message}
    </div>
  )
}

export function Sheet({
  open,
  title,
  onClose,
  children,
  footer,
  wide = false,
}: {
  open: boolean
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Fermer"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />
      <div
        className={`relative flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl bg-surface
                    shadow-2xl sm:rounded-2xl ${wide ? 'sm:max-w-4xl' : 'sm:max-w-lg'}`}
      >
        <header className="flex items-center justify-between gap-4 border-b border-line px-4 py-3">
          <h2 className="truncate text-base font-semibold text-ink">{title}</h2>
          <button type="button" className="btn-ghost px-2 py-1" onClick={onClose}>
            Fermer
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && <footer className="border-t border-line px-4 py-3">{footer}</footer>}
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
  return (
    <Sheet
      open={open}
      title={title}
      onClose={onCancel}
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onCancel}>
            Annuler
          </button>
          <button
            type="button"
            className={destructive ? 'btn-danger' : 'btn-primary'}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      }
    >
      {message && <p className="text-sm text-ink-muted">{message}</p>}
    </Sheet>
  )
}

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
    <div className="card flex h-full flex-col gap-2 text-left">
      <div className="flex items-center justify-between">
        <span className="text-xl text-brand" aria-hidden="true">
          {icon}
        </span>
        {isLink && <Icon name="chevron-right" className="h-4 w-4 text-ink-faint" />}
      </div>
      {value !== undefined && <p className="text-2xl font-bold leading-tight text-ink">{value}</p>}
      <p className="text-sm text-ink-muted">{title}</p>
      {caption && <p className="text-xs text-ink-faint">{caption}</p>}
    </div>
  )
}
