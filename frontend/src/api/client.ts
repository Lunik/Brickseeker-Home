/**
 * The single fetch wrapper. Everything talks to the API through this — never bare `fetch` — so
 * error shape, credentials and the 401 → login redirect are handled in exactly one place.
 */

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

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: payload,
    signal,
    credentials: 'same-origin',
  })

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
 * Rewrites a remote image URL through the caching proxy. Set images are re-downloaded on every
 * render otherwise, and the browser can't reach an origin the container can.
 */
export function imageUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  return `/api/images?url=${encodeURIComponent(url)}`
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
