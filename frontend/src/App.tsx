/**
 * The shell: auth gate, settings/theme provider, routes, and the persistent navigation.
 *
 * Set detail is a route (`/set/:setNum`) rather than local state, so it is linkable and the
 * browser's back button behaves — the web equivalent of the iOS sheet, which every screen could
 * present. The list a set was opened from is passed through router state so the detail view can
 * page through it, mirroring `SetDetailPagerView`.
 */

import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api, setUnauthorizedHandler } from './api/client'
import { SettingsProvider, useSettings } from './lib/settings-context'
import { LoadingBlock } from './components/ui'
import LoginGate from './pages/LoginGate'
import HomePage from './pages/HomePage'
import ScannerPage from './pages/ScannerPage'
import CollectionPage from './pages/CollectionPage'
import HistoryPage from './pages/HistoryPage'
import WishlistPage from './pages/WishlistPage'
import StatsPage from './pages/StatsPage'
import MinifigsPage from './pages/MinifigsPage'
import NewSetsPage from './pages/NewSetsPage'
import AlertsPage from './pages/AlertsPage'
import SettingsPage from './pages/SettingsPage'
import OnboardingPage from './pages/OnboardingPage'
import SetDetailPage from './pages/SetDetailPage'
import NotificationsBell from './components/NotificationsBell'
import Icon, { type IconName } from './components/Icon'

interface AuthStatus {
  authRequired: boolean
  authenticated: boolean
}

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: '/', label: 'Accueil', icon: 'home', end: true },
  { to: '/collection', label: 'Collection', icon: 'box' },
  { to: '/scan', label: 'Scanner', icon: 'camera' },
  { to: '/history', label: 'Historique', icon: 'clock' },
  { to: '/wishlist', label: 'Cadeaux', icon: 'gift' },
]

function Chrome() {
  const location = useLocation()
  const { preferences } = useSettings()

  // The walkthrough runs once, exactly like the iOS `hasSeenOnboarding` gate. Never redirect away
  // from the scanner: arriving there from a shortcut shouldn't be interrupted.
  const needsOnboarding =
    preferences && preferences.hasSeenOnboarding === false && location.pathname !== '/onboarding'
  if (needsOnboarding) return <Navigate to="/onboarding" replace />

  const isScanner = location.pathname === '/scan'

  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col">
      {!isScanner && (
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-surface/90 px-4 py-3 backdrop-blur">
          <NavLink to="/" className="text-lg font-extrabold tracking-tight text-ink">
            Brick<span className="text-brand">Seeker</span>
          </NavLink>
          <div className="flex items-center gap-1">
            <NotificationsBell />
            <NavLink to="/settings" className="btn-ghost px-2 py-1.5" aria-label="Réglages">
              <Icon name="settings" />
            </NavLink>
          </div>
        </header>
      )}

      <main className={`flex-1 ${isScanner ? '' : 'px-4 pb-28 pt-4'}`}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="/scan" element={<ScannerPage />} />
          <Route path="/collection" element={<CollectionPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/wishlist" element={<WishlistPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/minifigs" element={<MinifigsPage />} />
          <Route path="/new-sets" element={<NewSetsPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/set/:setNum" element={<SetDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      {!isScanner && (
        <nav className="fixed inset-x-0 bottom-0 z-30 mx-auto flex w-full max-w-3xl justify-around border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition-colors ${
                  isActive ? 'text-brand' : 'text-ink-faint hover:text-ink-muted'
                }`
              }
            >
              <Icon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  )
}

export default function App() {
  const [unauthorized, setUnauthorized] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['auth-status'],
    queryFn: () => api.get<AuthStatus>('/auth/status'),
    retry: false,
    staleTime: Infinity,
  })

  useEffect(() => {
    setUnauthorizedHandler(() => setUnauthorized(true))
    return () => setUnauthorizedHandler(null)
  }, [])

  if (isLoading) return <LoadingBlock />

  const needsLogin = (data?.authRequired && !data.authenticated) || unauthorized
  if (needsLogin) {
    return (
      <LoginGate
        onSuccess={async () => {
          setUnauthorized(false)
          await refetch()
        }}
      />
    )
  }

  return (
    <SettingsProvider>
      <Chrome />
    </SettingsProvider>
  )
}
