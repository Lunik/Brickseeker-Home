/**
 * The shell: auth gate, settings/theme provider, routes.
 *
 * There is deliberately **no tab bar**. The iOS app navigates entirely from Home's tile grid and
 * its floating scan cluster, with every other screen pushed on top carrying a back button — so a
 * persistent tab bar here would be a structure the original doesn't have.
 *
 * Set detail is a route rather than local state, so it is linkable and the browser's back button
 * behaves. The list a set was opened from rides along in router state, which is what lets the
 * detail screen page through it the way `SetDetailPagerView` does.
 */

import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
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

interface AuthStatus {
  authRequired: boolean
  authenticated: boolean
}

function Chrome() {
  const location = useLocation()
  const { preferences } = useSettings()

  // The walkthrough runs once, on the same `hasSeenOnboarding` flag the iOS app uses.
  const needsOnboarding =
    preferences && preferences.hasSeenOnboarding === false && location.pathname !== '/onboarding'
  if (needsOnboarding) return <Navigate to="/onboarding" replace />

  // The scanner is full-bleed: no page padding, no chrome of its own.
  const isScanner = location.pathname === '/scan'

  return (
    <div className="mx-auto min-h-full w-full max-w-2xl">
      <main className={isScanner ? '' : 'px-4 pb-16 pt-2'}>
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
