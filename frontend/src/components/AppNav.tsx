import { NavLink, useLocation } from 'react-router-dom'

import Icon, { type IconName } from './Icon'

interface Destination {
  to: string
  label: string
  icon: IconName
  /** Paths that belong to this destination, so the tab stays lit on its sub-screens. */
  also?: string[]
}

/** The five destinations of the bottom bar on a phone, and the top of the sidebar on a desktop. */
export const TABS: Destination[] = [
  { to: '/', label: 'Accueil', icon: 'home', also: ['/history'] },
  { to: '/collection', label: 'Collection', icon: 'box', also: ['/minifigs', '/new-sets'] },
  { to: '/wishlist', label: 'Cadeaux', icon: 'gift' },
  { to: '/stats', label: 'Stats', icon: 'chart' },
  { to: '/settings', label: 'Réglages', icon: 'settings', also: ['/alerts'] },
]

/** Reached from a tab or a tile — listed in the sidebar only, where there is room. */
const MORE: Destination[] = [
  { to: '/history', label: 'Historique', icon: 'clock' },
  { to: '/minifigs', label: 'Minifigs', icon: 'user' },
  { to: '/new-sets', label: 'Nouveaux sets', icon: 'sparkles' },
  { to: '/alerts', label: 'Alertes de prix', icon: 'bell' },
]

/** Screens that are the root of a tab: no back button, the bar is the way out. */
export const ROOT_PATHS = new Set(['/', '/collection', '/wishlist', '/stats', '/settings'])

const isActive = (pathname: string, d: Destination) =>
  d.to === '/' ? pathname === '/' : [d.to, ...(d.also ?? [])].some((p) => pathname.startsWith(p))

/** Phone: a bottom bar. Hidden on a set's page, which is a modal-like pager with its own header. */
export function TabBar() {
  const { pathname } = useLocation()
  if (pathname.startsWith('/set/')) return null
  return (
    <nav
      aria-label="Navigation principale"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line/60 bg-surface-raised pb-[env(safe-area-inset-bottom)] lg:hidden"
    >
      <ul className="mx-auto flex max-w-2xl">
        {TABS.map((tab) => {
          const active = isActive(pathname, tab)
          return (
            <li key={tab.to} className="flex-1">
              <NavLink
                to={tab.to}
                aria-current={active ? 'page' : undefined}
                className={`relative flex h-16 flex-col items-center justify-center gap-1 text-[12px] font-medium transition-colors ${
                  active ? 'text-brand' : 'text-ink-faint'
                }`}
              >
                {/* Line art stays line art: filling these glyphs turns them into solid blobs. */}
                {active && <span className="absolute inset-x-6 top-0 h-0.5 rounded-full bg-brand" />}
                <Icon name={tab.icon} className="h-6 w-6" />
                {tab.label}
              </NavLink>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

/** Desktop: a fixed sidebar carrying every destination. */
export function Sidebar() {
  const { pathname } = useLocation()
  const link = (d: Destination) => {
    // One entry lit at a time: a sub-screen lights its own sidebar row, not its parent tab as well.
    const onMore = MORE.some((m) => pathname.startsWith(m.to))
    const active = MORE.includes(d)
      ? pathname.startsWith(d.to)
      : !onMore && isActive(pathname, d)
    return (
      <li key={d.to}>
        <NavLink
          to={d.to}
          aria-current={active ? 'page' : undefined}
          className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition-colors ${
            active ? 'bg-brand/10 text-brand' : 'text-ink-muted hover:bg-surface-sunken'
          }`}
        >
          <Icon name={d.icon} className="h-5 w-5" />
          {d.label}
        </NavLink>
      </li>
    )
  }
  return (
    <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col gap-6 border-r border-line/60 bg-surface-raised px-4 py-6 lg:flex">
      <p className="px-3 text-[22px] font-extrabold tracking-tight text-ink">
        Brick<span className="text-brand">Seeker</span>
      </p>
      <nav aria-label="Navigation principale" className="space-y-6">
        <ul className="space-y-1">{TABS.map(link)}</ul>
        <div className="space-y-2">
          <p className="section-title px-3">Explorer</p>
          <ul className="space-y-1">{MORE.map(link)}</ul>
        </div>
      </nav>
    </aside>
  )
}
