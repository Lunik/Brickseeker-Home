import type { FilterState, SortOption, StoreAvailability } from '../api/types'
import { ALL_AVAILABILITIES, ALL_SORT_OPTIONS, SORT_DEFAULT_ASCENDING } from '../hooks/useFilterState'
import { AVAILABILITY_LABEL, SORT_LABEL } from '../lib/format'
import Icon from './Icon'
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
  /** Sorts that make no sense on this screen — e.g. "date de scan" on a catalogue browser. */
  excludedSorts?: SortOption[]
  showOwnedFilter?: boolean
  showAvailabilityFilter?: boolean
  /** How many rows have never had their lego.com availability checked. This is why "Inconnue" is
   *  a selectable value rather than a hidden bucket — it points at the refresh that fills it in. */
  unknownAvailabilityCount?: number
}

/**
 * A row in a grouped card: label on the left, current value on the right — the shape of an iOS
 * `Form` picker row, rather than a label stacked above a full-width control.
 *
 * The select carries its own value text (so no second copy can drift out of sync) and is
 * right-aligned with a chevron beside it.
 */
function PickerRow({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return (
    <label className="flex min-h-12 items-center gap-3 border-b border-line px-4 py-3 last:border-0">
      <span className="shrink-0 text-[17px] text-ink">{label}</span>
      <select
        className="ml-auto min-w-0 max-w-[55%] cursor-pointer appearance-none truncate bg-transparent text-right text-[17px] text-ink-muted focus:outline-none"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={label}
      >
        {children}
      </select>
      <Icon name="chevron-right" className="pointer-events-none h-4 w-4 shrink-0 text-ink-faint" />
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
        <div className="flex items-center justify-between gap-2">
          <button type="button" className="btn-ghost" onClick={reset}>
            Réinitialiser
          </button>
          <button type="button" className="btn-primary" onClick={onClose}>
            Voir les résultats
          </button>
        </div>
      }
    >
      <div className="space-y-5">
        {/* Sort comes first, as it does on iOS, and the direction is an arrow inside the same row
            rather than two large buttons competing with it. */}
        <section className="space-y-2">
          <h3 className="section-title px-1">Tri</h3>
          <div className="list-card">
            <div className="flex min-h-12 items-center gap-2 px-4 py-2">
              <label className="relative flex flex-1 items-center gap-3">
                <span className="flex-1 text-[17px] text-ink">Trier par</span>
                <select
                  className="cursor-pointer appearance-none bg-transparent pr-1 text-right text-[17px] text-ink-muted focus:outline-none"
                  value={filter.sort}
                  onChange={(event) => {
                    const sort = event.target.value as SortOption
                    // Switching sort resets the direction to the one that option reads naturally
                    // in, so "Nom" doesn't inherit a descending choice made for "Année".
                    setFilter({ sort, ascending: SORT_DEFAULT_ASCENDING[sort] })
                  }}
                  aria-label="Trier par"
                >
                  {sorts.map((option) => (
                    <option key={option} value={option}>
                      {SORT_LABEL[option]}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-ink-muted active:opacity-60"
                onClick={() => setFilter({ ascending: !filter.ascending })}
                aria-label="Ordre de tri"
                aria-pressed={filter.ascending}
              >
                <span className="text-[17px]">{filter.ascending ? '↑' : '↓'}</span>
              </button>
            </div>
          </div>
        </section>

        <section className="space-y-2">
          <div className="list-card">
            <PickerRow
              label="Thème"
              value={filter.themeName ?? ''}
              onChange={(value) => setFilter({ themeName: value || null })}
            >
              <option value="">Tous</option>
              {themes.map((theme) => (
                <option key={theme} value={theme}>
                  {theme}
                </option>
              ))}
            </PickerRow>

            <PickerRow
              label="Année"
              value={filter.year === null ? '' : String(filter.year)}
              onChange={(value) => setFilter({ year: value ? Number(value) : null })}
            >
              <option value="">Toutes</option>
              {years.map((year) => (
                <option key={year} value={String(year)}>
                  {year}
                </option>
              ))}
            </PickerRow>

            {lists.length > 0 && (
              <PickerRow
                label="Liste"
                value={filter.listName ?? ''}
                onChange={(value) => setFilter({ listName: value || null })}
              >
                <option value="">Toutes</option>
                {lists.map((list) => (
                  <option key={list} value={list}>
                    {list}
                  </option>
                ))}
              </PickerRow>
            )}

            {showOwnedFilter && (
              <PickerRow
                label="Possession"
                value={filter.ownedOnly === null ? '' : String(filter.ownedOnly)}
                onChange={(value) =>
                  setFilter({ ownedOnly: value === '' ? null : value === 'true' })
                }
              >
                <option value="">Tous</option>
                <option value="true">Dans ma collection</option>
                <option value="false">Pas dans ma collection</option>
              </PickerRow>
            )}

            {showAvailabilityFilter && (
              <PickerRow
                label="Disponibilité lego.com"
                value={filter.availability ?? ''}
                onChange={(value) =>
                  setFilter({ availability: (value || null) as StoreAvailability | null })
                }
              >
                <option value="">Toutes</option>
                {ALL_AVAILABILITIES.map((availability) => (
                  <option key={availability} value={availability}>
                    {AVAILABILITY_LABEL[availability]}
                  </option>
                ))}
              </PickerRow>
            )}
          </div>

          {showAvailabilityFilter && unknownAvailabilityCount > 0 && (
            <p className="section-footer">
              {unknownAvailabilityCount} set
              {unknownAvailabilityCount > 1 ? 's' : ''}{' '}
              {unknownAvailabilityCount > 1 ? "n'ont" : "n'a"} pas encore d'information de
              disponibilité lego.com. Elle est relevée en même temps que le prix lego.com :
              actualisez les prix pour la compléter.
            </p>
          )}
        </section>
      </div>
    </Sheet>
  )
}
