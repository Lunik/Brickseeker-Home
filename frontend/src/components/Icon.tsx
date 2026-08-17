/**
 * The interface icon set.
 *
 * Self-hosted inline SVG rather than an icon CDN or an emoji font: emoji render differently on
 * every platform (and as coloured pictures rather than UI chrome), while a CDN would be a network
 * dependency a self-hosted app has no business having.
 *
 * All icons are 24×24, drawn on a single stroke geometry so they sit consistently next to text and
 * inherit `currentColor`. To swap in a licensed set (Flaticon and the like), replace the `PATHS`
 * entries with those files' path data — nothing else in the app needs to change.
 */

export type IconName =
  | 'home'
  | 'box'
  | 'camera'
  | 'clock'
  | 'gift'
  | 'bell'
  | 'bell-off'
  | 'settings'
  | 'warning'
  | 'hash'
  | 'chart'
  | 'user'
  | 'sparkles'
  | 'image'
  | 'keyboard'
  | 'heart'
  | 'search'
  | 'filter'
  | 'map'
  | 'upload'
  | 'link'
  | 'close'
  | 'flashlight'
  | 'eye'
  | 'eye-off'
  | 'chevron-left'
  | 'chevron-right'
  | 'check'
  | 'refresh'
  | 'plus'
  | 'minus'
  | 'brick'
  | 'download'
  | 'tag'
  | 'inbox'
  | 'viewfinder'
  | 'checklist'
  | 'layers'
  | 'folder'
  | 'trash'
  | 'ellipsis'
  | 'minifig'

/** Path data only — the shared stroke attributes live on the `<svg>` below. */
const PATHS: Record<IconName, string> = {
  home: 'M3 10.5 12 3l9 7.5M5.5 9.5V20h13V9.5M9.5 20v-6h5v6',
  box: 'M3 7.5 12 3l9 4.5v9L12 21l-9-4.5v-9ZM3 7.5 12 12m0 0 9-4.5M12 12v9',
  camera: 'M3 8.5A1.5 1.5 0 0 1 4.5 7h2.2l1.3-2h7l1.3 2h2.2A1.5 1.5 0 0 1 20 8.5v9A1.5 1.5 0 0 1 18.5 19h-13A1.5 1.5 0 0 1 4 17.5v-9ZM12 16a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3.5 2',
  gift: 'M3.5 11h17v9.5h-17V11ZM2.5 7.5h19V11h-19V7.5ZM12 7.5V20.5M12 7.5S10.5 3.5 8 3.5a2 2 0 0 0 0 4h4Zm0 0s1.5-4 4-4a2 2 0 0 1 0 4h-4Z',
  bell: 'M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6ZM10.3 20a2 2 0 0 0 3.4 0',
  'bell-off': 'M18 9a6 6 0 0 0-8.5-5.5M6.2 6.2A6 6 0 0 0 6 9c0 5-2 6-2 6h12M10.3 20a2 2 0 0 0 3.4 0M3 3l18 18',
  settings:
    'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7.4-2.3.1-1.2-.1-1.2 2-1.5-2-3.4-2.3.9a7.6 7.6 0 0 0-2-1.2L14.7 3H9.3l-.4 2.6c-.7.3-1.4.7-2 1.2l-2.3-.9-2 3.4 2 1.5-.1 1.2.1 1.2-2 1.5 2 3.4 2.3-.9c.6.5 1.3.9 2 1.2l.4 2.6h5.4l.4-2.6c.7-.3 1.4-.7 2-1.2l2.3.9 2-3.4-2-1.5Z',
  warning: 'M12 3.5 21.5 20H2.5L12 3.5ZM12 10v4.5M12 17.2v.3',
  hash: 'M4.5 9h15M4.5 15h15M10 3.5 8 20.5M16 3.5l-2 17',
  chart: 'M3.5 20.5h17M7 17V10M12 17V4.5M17 17v-9',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4.5 20.5a7.5 7.5 0 0 1 15 0',
  sparkles:
    'm12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3ZM18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z',
  image: 'M3.5 5.5h17v13h-17v-13ZM3.5 16l4.5-4.5 3.5 3.5 3-3 6 6M15.5 9.5v.01',
  keyboard:
    'M2.5 6.5h19v11h-19v-11ZM6 10v.01M9.5 10v.01M13 10v.01M16.5 10v.01M6 13.5v.01M9.5 13.5h5M18 13.5v.01',
  heart: 'M12 20s-7.5-4.7-7.5-9.4A4.1 4.1 0 0 1 12 8a4.1 4.1 0 0 1 7.5 2.6C19.5 15.3 12 20 12 20Z',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM16 16l4.5 4.5',
  filter: 'M3.5 5.5h17l-6.5 8v6l-4 2v-8l-6.5-8Z',
  map: 'M9 4.5 3.5 6.5v13L9 17.5m0-13 6 2.5m-6-2.5v13m6-10.5 5.5-2v13l-5.5 2m0-13v13m0 0-6-2.5',
  upload: 'M12 16V4.5M8 8.5 12 4.5l4 4M4.5 15.5v3a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-3',
  link: 'M10 13.5a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1.5 1.5M14 10.5a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1.5-1.5',
  close: 'M5.5 5.5 18.5 18.5M18.5 5.5 5.5 18.5',
  flashlight: 'M8 3.5h8v3.5l-2 3v10.5h-4V10l-2-3V3.5ZM8 7h8',
  eye: 'M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Zm9.5 2.8a2.8 2.8 0 1 0 0-5.6 2.8 2.8 0 0 0 0 5.6Z',
  'eye-off':
    'M9.9 5.8A8.6 8.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16 16 0 0 1-3 3.7M6.4 7.9A16 16 0 0 0 2.5 12S6 18.5 12 18.5c1 0 1.9-.2 2.7-.5M3 3l18 18M10 10a2.8 2.8 0 0 0 3.9 3.9',
  'chevron-left': 'M14.5 5.5 8 12l6.5 6.5',
  'chevron-right': 'M9.5 5.5 16 12l-6.5 6.5',
  check: 'M5 12.5 10 17.5 19.5 7',
  refresh: 'M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5',
  plus: 'M12 5.5v13M5.5 12h13',
  minus: 'M5.5 12h13',
  brick: 'M3.5 9.5h17v10h-17v-10ZM7 9.5V7a1.5 1.5 0 0 1 3 0v2.5M14 9.5V7a1.5 1.5 0 0 1 3 0v2.5',
  download: 'M12 4.5V16M8 12l4 4 4-4M4.5 19.5h15',
  tag: 'M11 3.5H20.5V13L11.5 22 2 12.5 11 3.5ZM16.5 8v.01',
  // The scan reticle, matching the iOS `viewfinder` symbol on the "scans effectués" tile.
  viewfinder: 'M3.5 8.5V5A1.5 1.5 0 0 1 5 3.5h3.5M15.5 3.5H19A1.5 1.5 0 0 1 20.5 5v3.5M20.5 15.5V19a1.5 1.5 0 0 1-1.5 1.5h-3.5M8.5 20.5H5A1.5 1.5 0 0 1 3.5 19v-3.5',
  // The multi-select affordance: two rows, the first ticked.
  checklist: 'M12 7h8M12 17h8M4 7l2 2 3.5-3.5M4 17l2 2 3.5-3.5',
  // Mode lot — stacked sheets, matching the iOS `square.stack` symbol.
  layers: 'm12 3 9 4.5-9 4.5-9-4.5L12 3ZM3 12l9 4.5L21 12M3 16.5 12 21l9-4.5',
  // The three symbols the iOS bulk-action menus use: `folder`, `trash`, `ellipsis.circle`.
  folder: 'M3.5 6.5A1.5 1.5 0 0 1 5 5h4l2 2.5h8a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18V6.5Z',
  trash: 'M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4L18 7M10 11v6M14 11v6',
  ellipsis: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM8 12v.01M12 12v.01M16 12v.01',
  // The stand-in for a minifig with no artwork — Rebrickable has plenty. A recognisable figure
  // beats the generic person glyph, which read as "user account" in a grid of minifigures.
  minifig:
    'M10.2 2.5h3.6v1.4M8.9 3.9h6.2v4.2H8.9zM7.2 8.1h9.6v6H7.2zM4.6 9.2h2.6v4.6M16.8 9.2h2.6v4.6M9.4 14.1v7.4h2.1v-7.4M12.5 14.1v7.4h2.1v-7.4',
  inbox:
    'M3.5 13.5h4l1.5 3h6l1.5-3h4M3.5 13.5 6 5h12l2.5 8.5v5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5v-5Z',
}

export interface IconProps {
  name: IconName
  /** Tailwind size classes; defaults to 20px square, which lines up with body text. */
  className?: string
  /** Filled icons (a "wishlisted" heart, an armed bell) read as *state*, not as an action. */
  filled?: boolean
  /** Set when the icon is the only content of a control and carries its meaning. */
  label?: string
}

export default function Icon({ name, className = 'h-5 w-5', filled = false, label }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
