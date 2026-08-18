/**
 * App-wide settings: preferences, credential presence, catalogue state.
 *
 * One fetch at startup feeds the theme, the "compte non lié" copy on Accueil, and Réglages itself.
 * The theme is applied as a side effect of the same query, so a preference change is reflected
 * everywhere without prop-drilling a theme object through the tree.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { Preferences, SettingsPayload } from '../api/types'
import { applyAppearance, watchSystemAppearance, type AppearanceMode, type BrandColor } from './theme'

interface SettingsContextValue {
  settings: SettingsPayload | undefined
  isLoading: boolean
  preferences: Preferences | undefined
  updatePreferences: (values: Partial<Preferences>) => Promise<void>
  refresh: () => Promise<void>
  brandColor: BrandColor
  appearance: AppearanceMode
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

export function SettingsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<SettingsPayload>('/settings'),
    staleTime: 60_000,
  })

  const brandColor = (data?.preferences['appTheme.brandColor'] ?? 'red') as BrandColor
  const appearance = (data?.preferences['appTheme.appearanceMode'] ?? 'system') as AppearanceMode

  useEffect(() => {
    applyAppearance(appearance, brandColor)
  }, [appearance, brandColor])

  useEffect(
    () => watchSystemAppearance(() => appearance, () => brandColor),
    [appearance, brandColor],
  )

  const mutation = useMutation({
    mutationFn: (values: Partial<Preferences>) => api.patch<Preferences>('/settings/preferences', values),
    onSuccess: (preferences) => {
      queryClient.setQueryData<SettingsPayload>(['settings'], (previous) =>
        previous ? { ...previous, preferences } : previous,
      )
    },
  })

  const updatePreferences = useCallback(
    async (values: Partial<Preferences>) => {
      await mutation.mutateAsync(values)
    },
    [mutation],
  )

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ['settings'] })
  }, [queryClient])

  const value = useMemo<SettingsContextValue>(
    () => ({
      settings: data,
      isLoading,
      preferences: data?.preferences,
      updatePreferences,
      refresh,
      brandColor,
      appearance,
    }),
    [data, isLoading, updatePreferences, refresh, brandColor, appearance],
  )

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function useSettings(): SettingsContextValue {
  const context = useContext(SettingsContext)
  if (!context) throw new Error('useSettings doit être utilisé dans un SettingsProvider')
  return context
}
