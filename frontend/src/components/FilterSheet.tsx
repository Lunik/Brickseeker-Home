import type { FilterState, SortOption, StoreAvailability } from '../api/types'
import { ALL_AVAILABILITIES, ALL_SORT_OPTIONS } from '../hooks/useFilterState'
import { AVAILABILITY_LABEL, SORT_LABEL } from '../lib/format'
import { Sheet } from './ui'

interface FilterSheetProps {
  open: boolean
  onClose: () => void
  filter: FilterState
  setFilter: (patch: Partial<FilterState>) => void
  reset: () => void
  themes: string[]
  years: number[]
  lists?: string[]
  /** Sorts that make no sense on this screen — e.g. "date de scan" on a catalogue browser, whose
   *  entries were never scanned. */
  excludedSorts?: SortOption[]
  showOwnedFilter?: boolean
  showAvailabilityFilter?: boolean
  /** How many rows have never had their lego.com availability checked. This is the whole reason
   *  "Inconnue" is a selectable value rather than a hidden bucket — it points at the refresh that
   *  would fill it in. */
  unknownAvailabilityCount?: number
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="section-title">{label}</span>
      {children}
    </label>
  )
}

export default function FilterSheet({
  open,
  onClose,
  filter,
  setFilter,
  reset,
  themes,
  years,
  lists = [],
  excludedSorts = [],
  showOwnedFilter = false,
  showAvailabilityFilter = true,
  unknownAvailabilityCount = 0,
}: FilterSheetProps) {
  const sorts = ALL_SORT_OPTIONS.filter((option) => !excludedSorts.includes(option))

  return (
    <Sheet
      open={open}
      title="Filtres et tri"
      onClose={onClose}
      footer={
        <div className="flex justify-between gap-2">
          <button type="button" className="btn-ghost" onClick={reset}>
            Réinitialiser
          </button>
          <button type="button" className="btn-primary" onClick={onClose}>
            Voir les résultats
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <Field label="Thème">
          <select
            className="input"
            value={filter.themeName ?? ''}
            onChange={(event) => setFilter({ themeName: event.target.value || null })}
          >
            <option value="">Tous les thèmes</option>
            {themes.map((theme) => (
              <option key={theme} value={theme}>
                {theme}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Année">
          <select
            className="input"
            value={filter.year ?? ''}
            onChange={(event) => setFilter({ year: event.target.value ? Number(event.target.value) : null })}
          >
            <option value="">Toutes les années</option>
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </Field>

        {lists.length > 0 && (
          <Field label="Liste">
            <select
              className="input"
              value={filter.listName ?? ''}
              onChange={(event) => setFilter({ listName: event.target.value || null })}
            >
              <option value="">Toutes les listes</option>
              {lists.map((list) => (
                <option key={list} value={list}>
                  {list}
                </option>
              ))}
            </select>
          </Field>
        )}

        {showOwnedFilter && (
          <Field label="Possession">
            <select
              className="input"
              value={filter.ownedOnly === null ? '' : String(filter.ownedOnly)}
              onChange={(event) =>
                setFilter({ ownedOnly: event.target.value === '' ? null : event.target.value === 'true' })
              }
            >
              <option value="">Tous</option>
              <option value="true">Dans ma collection</option>
              <option value="false">Pas dans ma collection</option>
            </select>
          </Field>
        )}

        {showAvailabilityFilter && (
          <Field label="Disponibilité lego.com">
            <select
              className="input"
              value={filter.availability ?? ''}
              onChange={(event) =>
                setFilter({ availability: (event.target.value || null) as StoreAvailability | null })
              }
            >
              <option value="">Toutes</option>
              {ALL_AVAILABILITIES.map((availability) => (
                <option key={availability} value={availability}>
                  {AVAILABILITY_LABEL[availability]}
                </option>
              ))}
            </select>
            {unknownAvailabilityCount > 0 && (
              <span className="mt-1 block text-xs text-ink-faint">
                {unknownAvailabilityCount} set(s) n'ont jamais été vérifiés sur lego.com — lance une
                mise à jour des prix pour renseigner leur disponibilité.
              </span>
            )}
          </Field>
        )}

        <Field label="Trier par">
          <select
            className="input"
            value={filter.sort}
            onChange={(event) => setFilter({ sort: event.target.value as SortOption })}
          >
            {sorts.map((option) => (
              <option key={option} value={option}>
                {SORT_LABEL[option]}
              </option>
            ))}
          </select>
        </Field>

        <div className="flex gap-2">
          <button
            type="button"
            className={filter.ascending ? 'btn-primary flex-1' : 'btn-secondary flex-1'}
            onClick={() => setFilter({ ascending: true })}
          >
            Croissant
          </button>
          <button
            type="button"
            className={!filter.ascending ? 'btn-primary flex-1' : 'btn-secondary flex-1'}
            onClick={() => setFilter({ ascending: false })}
          >
            Décroissant
          </button>
        </div>
      </div>
    </Sheet>
  )
}
