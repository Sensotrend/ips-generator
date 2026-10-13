import type {
  ApiErrorBody,
  Approval,
  Draft,
  Job,
  ReviewAction,
  ReviewerRole,
  Source,
} from './types'

/** Typed API error (the backend never puts document content in error messages). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>[]

  constructor(status: number, code: string, message: string, details: Record<string, unknown>[]) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  // cache: 'no-store' — responses can contain PHI and must not land in the HTTP cache.
  const response = await fetch(path, {
    ...init,
    cache: 'no-store',
    headers: { Accept: 'application/json', ...init.headers },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new ApiError(
      response.status,
      body?.error.code ?? 'http_error',
      body?.error.message ?? `Request failed (${response.status})`,
      body?.error.details ?? [],
    )
  }
  return (await response.json()) as T
}

function json(method: string, body: unknown): RequestInit {
  return { method, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } }
}

export const api = {
  uploadJob(file: File): Promise<Job> {
    const form = new FormData()
    form.append('file', file)
    return request<Job>('/api/jobs', { method: 'POST', body: form })
  },
  listJobs: () => request<Job[]>('/api/jobs'),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  getDraft: (id: string) => request<Draft>(`/api/jobs/${id}/draft`),
  updateDraft: (id: string, version: number, actions: ReviewAction[]) =>
    request<Draft>(`/api/jobs/${id}/draft`, json('PUT', { version, actions })),
  approve: (id: string, version: number, role: ReviewerRole) =>
    request<Approval>(`/api/jobs/${id}/approve`, json('POST', { version, role })),
  /** Asks the API (which asks the credential issuer) for a wallet credential-offer URL. */
  walletOffer: (id: string) =>
    request<{ url: string }>(`/api/jobs/${id}/wallet-offer`, { method: 'POST' }),
  getSource: (id: string) => request<Source>(`/api/jobs/${id}/source`),
  async getBinary(url: string): Promise<ArrayBuffer> {
    const response = await fetch(url, { cache: 'no-store' })
    if (!response.ok) throw new ApiError(response.status, 'http_error', 'Download failed', [])
    return response.arrayBuffer()
  },
  eventsUrl: (id: string) => `/api/jobs/${id}/events`,
  ipsUrl: (id: string) => `/api/jobs/${id}/ips`,
}

/** Download the approved IPS JSON via an in-memory Blob (nothing is persisted). */
export async function downloadIps(id: string): Promise<void> {
  const response = await fetch(api.ipsUrl(id), { cache: 'no-store' })
  if (!response.ok) throw new ApiError(response.status, 'http_error', 'Download failed', [])
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `ips-${id}.json`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
