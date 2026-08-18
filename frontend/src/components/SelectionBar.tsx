import { useState } from 'react'

import Icon, { type IconName } from './Icon'
import { Sheet, Spinner } from './ui'

export interface SelectionAction {
  key: string
  label: string
  /** The symbol iOS puts on the same entry, so the two menus read alike. */
  icon?: IconName
  destructive?: boolean
  /** Shown in a confirmation dialog before running. Omit for actions that need no confirmation. */
  confirm?: (count: number) => string
  run: (setNums: string[]) => Promise<void>
}

interface SelectionBarProps {
  count: number
  total: number
  allSelected: boolean
  busy: boolean
  actions: SelectionAction[]
  onToggleAll: () => void
  onDone: () => void
  onRun: (action: SelectionAction) => void
}

/**
 * The multi-select toolbar, shared by every list screen and by the scan session.
 *
 * Shaped after the iOS bottom bar rather than the row of buttons this used to be:
 * `Tout sélectionner … Actions (N) Terminé`. Four flat rectangles competing for width gave a
 * destructive action the same weight as a price refresh and pushed the labels onto three lines;
 * behind one "Actions" control they become a list where an icon and a colour can say which is
 * which. The count lives on that control, as it does on iOS.
 *
 * The bar stays put when nothing is selected — only "Actions" goes disabled — so the controls
 * don't move under the user's thumb as they tick rows.
 */
export default function SelectionBar({
  count,
  total,
  allSelected,
  busy,
  actions,
  onToggleAll,
  onDone,
  onRun,
}: SelectionBarProps) {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <>
      <div
        className="fixed inset-x-0 bottom-0 z-30 mx-auto w-full max-w-2xl border-t border-line bg-surface/95
                   px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur"
      >
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="btn-ghost px-0 text-[15px]"
            onClick={onToggleAll}
            disabled={total === 0}
          >
            {allSelected ? 'Tout désélectionner' : 'Tout sélectionner'}
          </button>
          <span className="flex-1" />
          <button
            type="button"
            className="btn-secondary gap-1.5 px-3 py-1.5 text-[15px]"
            disabled={busy || count === 0}
            onClick={() => setMenuOpen(true)}
          >
            {busy ? (
              <Spinner className="h-4 w-4" />
            ) : (
              <>
                <Icon name="ellipsis" className="h-4 w-4" />
                Actions ({count})
              </>
            )}
          </button>
          <button
            type="button"
            className="btn-ghost px-1 text-[15px] font-semibold"
            onClick={onDone}
            // Leaving mid-action would orphan a running network loop.
            disabled={busy}
          >
            Terminé
          </button>
        </div>
      </div>

      <ActionSheet
        open={menuOpen}
        title={`${count} set${count > 1 ? 's' : ''} sélectionné${count > 1 ? 's' : ''}`}
        actions={actions}
        busy={busy}
        onClose={() => setMenuOpen(false)}
        onPick={(action) => {
          setMenuOpen(false)
          onRun(action)
        }}
      />
    </>
  )
}

/**
 * The action list itself — also used for a single row's context menu, so one row and a selection
 * of forty offer the same actions in the same order and shape.
 */
export function ActionSheet({
  open,
  title,
  actions,
  busy,
  onClose,
  onPick,
}: {
  open: boolean
  title: string
  actions: SelectionAction[]
  busy: boolean
  onClose: () => void
  onPick: (action: SelectionAction) => void
}) {
  return (
    <Sheet open={open} title={title} onClose={onClose}>
      <ul className="list-card">
        {actions.map((action) => (
          <li key={action.key} className="border-b border-line last:border-0">
            <button
              type="button"
              className="flex w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-sunken disabled:opacity-40"
              disabled={busy}
              onClick={() => onPick(action)}
            >
              {action.icon && (
                <Icon
                  name={action.icon}
                  className={`h-5 w-5 ${action.destructive ? 'text-[rgb(var(--negative))]' : 'text-brand'}`}
                />
              )}
              <span
                className={`flex-1 text-[17px] ${
                  action.destructive ? 'text-[rgb(var(--negative))]' : 'text-ink'
                }`}
              >
                {action.label}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  )
}
