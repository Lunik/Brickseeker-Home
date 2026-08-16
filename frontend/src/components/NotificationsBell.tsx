import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { AppNotification } from '../api/types'
import { formatRelative } from '../lib/format'
import Icon from './Icon'
import { EmptyState, Sheet } from './ui'

interface NotificationsPayload {
  notifications: AppNotification[]
  unreadCount: number
}

/**
 * The in-app notification centre.
 *
 * Polling rather than push: this is what makes the feature work for someone who never granted
 * browser notification permission, which is most people. Web Push, when enabled, delivers the
 * same payloads on top.
 */
export default function NotificationsBell() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<NotificationsPayload>('/notifications'),
    refetchInterval: 60_000,
  })

  const markRead = useMutation({
    mutationFn: () => api.post('/notifications/read', {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  })

  const unread = data?.unreadCount ?? 0

  return (
    <>
      <button
        type="button"
        className="nav-circle relative"
        onClick={() => {
          setOpen(true)
          if (unread > 0) markRead.mutate()
        }}
        aria-label={unread > 0 ? `Notifications (${unread} non lues)` : 'Notifications'}
      >
        <Icon name="bell" filled={unread > 0} className="h-6 w-6" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-bold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      <Sheet open={open} title="Notifications" onClose={() => setOpen(false)}>
        {!data?.notifications.length ? (
          <EmptyState icon={<Icon name="bell-off" className="h-9 w-9" />} title="Aucune notification" message="Les baisses de prix que tu surveilles apparaîtront ici." />
        ) : (
          <ul className="divide-y divide-line">
            {data.notifications.map((notification) => (
              <li key={notification.id}>
                <button
                  type="button"
                  className="w-full py-3 text-left"
                  disabled={!notification.setNum}
                  onClick={() => {
                    if (!notification.setNum) return
                    setOpen(false)
                    navigate(`/set/${encodeURIComponent(notification.setNum)}`)
                  }}
                >
                  <p className="text-sm font-semibold text-ink">{notification.title}</p>
                  <p className="text-sm text-ink-muted">{notification.body}</p>
                  <p className="text-xs text-ink-faint">{formatRelative(notification.createdAt)}</p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Sheet>
    </>
  )
}
