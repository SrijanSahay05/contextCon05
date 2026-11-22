import type { SearchResponse, StartupDetail } from '../types/startup'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, { headers: { 'content-type': 'application/json' }, ...init })
  } catch {
    throw new ApiError('Can’t reach the Scout server. Is the backend running?', 0)
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // Not JSON (e.g. a proxy error page); keep the generic message.
    }
    throw new ApiError(message, res.status)
  }
  return (await res.json()) as T
}

export const searchStartups = (thesis: string) =>
  request<SearchResponse>('/scout/search', { method: 'POST', body: JSON.stringify({ thesis }) })

export const fetchStartupDetail = (crustdataId: number) =>
  request<StartupDetail & { creditsUsed: number }>(`/scout/startups/${crustdataId}`)
