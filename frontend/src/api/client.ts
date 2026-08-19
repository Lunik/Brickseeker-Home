/**
 * The single fetch wrapper. Everything talks to the API through this — never bare `fetch` — so
 * error shape, credentials and the 401 → login redirect are handled in exactly one place.
 */

import { reportRequestOutcome } from '../lib/backend-reachability'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Set by App once it knows auth is on, so a session expiring mid-session lands on the gate. */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join(', ')
  } catch {
    /* a non-JSON body (a proxy error page) is not worth surfacing verbatim */
  }
  return `Erreur ${response.status}`
}

interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
  /** Set for multipart uploads — the browser must pick its own boundary header. */
  raw?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, raw = false } = options

  const headers: Record<string, string> = {}
  let payload: BodyInit | undefined
  if (body !== undefined) {
    if (raw) {
      payload = body as BodyInit
    } else {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body)
    }
  }

  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: payload,
      signal,
      credentials: 'same-origin',
    })
  } catch (caught) {
    // An aborted fetch (React Query cancelling a superseded request, or unmounting mid-fetch) is
    // routine, not a connectivity signal — only a genuine failure (DNS, connection refused, no
    // path to the LAN server) should flip the banner.
    if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
      reportRequestOutcome(false)
    }
    throw caught
  }
  reportRequestOutcome(true)

  if (response.status === 401) {
    onUnauthorized?.()
    throw new ApiError(await parseError(response), 401)
  }
  if (!response.ok) {
    throw new ApiError(await parseError(response), response.status)
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string, body?: unknown) => request<T>(path, { method: 'DELETE', body }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form, raw: true }),
}

/**
 * A catalogue image URL, used as-is: the browser fetches artwork straight from Rebrickable's (or
 * Brickset's / BrickLink's) CDN.
 *
 * This used to go through a `/api/images` proxy that cached to disk. Loading direct is strictly
 * better for caching — the CDN sends `max-age=31536000`, where the proxy re-stated a week — and it
 * costs the container no storage, no bandwidth and no request handling. The browser's own HTTP
 * cache then serves the artwork on later visits, and offline too, since a year-fresh entry needs
 * no revalidation.
 *
 * Kept as a function rather than inlining the field: it is the one place that decides where
 * artwork comes from, and every `<img>` in the app already routes through it.
 */
export function imageUrl(url: string | null | undefined): string | undefined {
  return url || undefined
}

/** Builds a query string, dropping empty values so `?year=&theme=City` never happens. */
export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}
