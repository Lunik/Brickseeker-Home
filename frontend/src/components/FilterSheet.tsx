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
  sortOptions?: SortOption[]
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
 * The value is drawn as text and the `<select>` is a transparent overlay on the whole row. A
 * styled select cannot be right-aligned: its box is as wide as its widest option, and the browser
 * lays the chosen label out at the *left* of that box — so "Tous" floated in the middle of the row
 * while "Dans ma collection" reached the chevron. Text plus an invisible native picker gives the
 * iOS alignment and keeps the platform picker UI.
 */
function PickerRow({
  label,
  value,
  valueLabel,
  onChange,
  children,
}: {
  label: string
  value: string
  /** What the current value reads as — the row's own copy, since the select is invisible. */
  valueLabel: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return (
    <div className="relative flex min-h-12 items-center gap-3 border-b border-line px-4 py-3 last:border-0">
      <span className="shrink-0 text-[17px] text-ink">{label}</span>
      <span className="ml-auto min-w-0 truncate text-right text-[17px] text-ink-muted">{valueLabel}</span>
      <Icon name="chevron-right" className="h-4 w-4 shrink-0 text-ink-faint" />
      <select
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={label}
      >
        {children}
      </select>
    </div>
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
  sortOptions,
  showOwnedFilter = false,
  showAvailabilityFilter = true,
  unknownAvailabilityCount = 0,
}: FilterSheetProps) {
  const sorts = (sortOptions ?? ALL_SORT_OPTIONS).filter((option) => !excludedSorts.includes(option))

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
              <div className="relative flex flex-1 items-center gap-3">
                <span className="shrink-0 text-[17px] text-ink">Trier par</span>
                <span className="ml-auto min-w-0 truncate text-right text-[17px] text-ink-muted">
                  {SORT_LABEL[filter.sort]}
                </span>
                <select
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
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
              </div>
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
              valueLabel={filter.themeName ?? 'Tous'}
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
              valueLabel={filter.year === null ? 'Toutes' : String(filter.year)}
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
                valueLabel={filter.listName ?? 'Toutes'}
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
                valueLabel={
                  filter.ownedOnly === null
                    ? 'Tous'
                    : filter.ownedOnly
                      ? 'Dans ma collection'
                      : 'Pas dans ma collection'
                }
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
                valueLabel={filter.availability ? AVAILABILITY_LABEL[filter.availability] : 'Toutes'}
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
