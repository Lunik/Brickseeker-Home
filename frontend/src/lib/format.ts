/**
 * Display formatting. French locale everywhere, deliberately — the app's UI text is French
 * regardless of the browser's own locale, so its numbers and dates shouldn't silently follow it.
 */

const eur = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })
const eurCompact = new Intl.NumberFormat('fr-FR', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})
const integer = new Intl.NumberFormat('fr-FR')
const dateShort = new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
const dateTime = new Intl.DateTimeFormat('fr-FR', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export const formatEUR = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : eur.format(value)

export const formatEURCompact = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : eurCompact.format(value)

export const formatNumber = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : integer.format(value)

export const formatPercent = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(digits)} %`

export const formatDate = (iso: string | null | undefined): string =>
  iso ? dateShort.format(new Date(iso)) : '—'

export const formatDateTime = (iso: string | null | undefined): string =>
  iso ? dateTime.format(new Date(iso)) : '—'

/** "il y a 3 jours" — used for price ages, where the exact timestamp is noise. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  const rtf = new Intl.RelativeTimeFormat('fr-FR', { numeric: 'auto' })
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 31536000],
    ['month', 2592000],
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(-Math.round(seconds / size), unit)
  }
  return "à l'instant"
}

/** Rebrickable's variant suffix is noise outside the disambiguator: "71045-3" → "71045". */
export const baseSetNum = (setNum: string): string =>
  setNum.startsWith('fig-') ? setNum : (setNum.split('-')[0] ?? setNum)

export const isMinifig = (setNum: string): boolean => setNum.startsWith('fig-')

export const CONDITION_LABEL: Record<string, string> = { newSet: 'Neuf', used: 'Occasion' }

export const AVAILABILITY_LABEL: Record<string, string> = {
  available: 'En vente',
  outOfStock: 'Rupture de stock',
  retired: 'Retiré de la vente',
  unknown: 'Inconnue',
}

export const SOURCE_LABEL: Record<string, string> = {
  bricklink: 'BrickLink',
  bricklinkNew: 'BrickLink (neuf)',
  bricklinkUsed: 'BrickLink (occasion)',
  amazon: 'Amazon (neuf)',
  cdiscount: 'Cdiscount (neuf)',
  cultura: 'Cultura (neuf)',
  smythToys: 'Smyths Toys (neuf)',
  kingJouet: 'King Jouet (neuf)',
  laGrandeRecre: 'La Grande Récré (neuf)',
  joueclub: 'JouéClub (neuf)',
  legoStore: 'lego.com (officiel)',
}

export function formatPriceSources(sources: string[]): string {
  const labels = sources.map((source) => SOURCE_LABEL[source] ?? source)
  if (labels.length <= 3) return labels.join(', ')
  return `${labels.slice(0, 3).join(', ')} et ${labels.length - 3} autre(s)`
}

export const NON_SET_LABEL: Record<string, string> = {
  merchandise: 'Produit dérivé',
  book: 'Livre',
  exclusive: 'Exclusivité LEGO',
  catalogArtifact: 'Entrée de catalogue',
}

export const SORT_LABEL: Record<string, string> = {
  dateScanned: 'Date de scan',
  deal: 'Promo',
  year: 'Année',
  name: 'Nom',
  partCount: 'Nombre de pièces',
  price: 'Prix',
  dateAdded: "Date d'ajout",
}
