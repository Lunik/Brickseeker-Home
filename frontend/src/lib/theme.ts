/**
 * Brand colour + appearance, ported from the iOS `AppTheme`.
 *
 * Both live server-side in app settings so the choice follows the user across devices — which is
 * the point of a self-hosted app. Applied by rewriting CSS custom properties rather than swapping
 * class names, so every `bg-brand` in the app follows without knowing which colour is active.
 */

export type BrandColor = 'red' | 'yellow' | 'blue'
export type AppearanceMode = 'system' | 'light' | 'dark'

interface BrandTokens {
  label: string
  /** `R G B`, the space-separated form Tailwind's `<alpha-value>` syntax needs. */
  rgb: string
  softLight: string
  softDark: string
  hex: string
}

export const BRAND_COLORS: Record<BrandColor, BrandTokens> = {
  red: { label: 'Rouge', rgb: '227 0 11', softLight: '253 232 233', softDark: '60 20 22', hex: '#E3000B' },
  yellow: { label: 'Jaune', rgb: '247 181 0', softLight: '254 243 214', softDark: '61 47 8', hex: '#F7B500' },
  blue: { label: 'Bleu', rgb: '0 109 183', softLight: '224 239 250', softDark: '12 38 58', hex: '#006DB7' },
}

export const APPEARANCE_LABELS: Record<AppearanceMode, string> = {
  system: 'Système',
  light: 'Clair',
  dark: 'Sombre',
}

const prefersDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches

export function applyBrandColor(color: BrandColor): void {
  const tokens = BRAND_COLORS[color] ?? BRAND_COLORS.red
  const root = document.documentElement
  root.style.setProperty('--brand', tokens.rgb)
  root.style.setProperty('--brand-soft', root.classList.contains('dark') ? tokens.softDark : tokens.softLight)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', tokens.hex)
}

export function applyAppearance(mode: AppearanceMode, color: BrandColor): void {
  const dark = mode === 'dark' || (mode === 'system' && prefersDark())
  document.documentElement.classList.toggle('dark', dark)
  // Re-applied after the class flips: `--brand-soft` differs per scheme.
  applyBrandColor(color)
}

/** Keeps `system` honest when the OS setting changes while the app is open. */
export function watchSystemAppearance(getMode: () => AppearanceMode, getColor: () => BrandColor): () => void {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const listener = () => {
    if (getMode() === 'system') applyAppearance('system', getColor())
  }
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}
