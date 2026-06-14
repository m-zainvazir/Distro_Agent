import type {
  StartDiscoveryRequest,
  StartDiscoveryResponse,
  StatusResponse,
  ReportResponse,
} from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public override message: string,
    public status_code: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(
      typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`,
      res.status,
    )
  }

  return res.json() as Promise<T>
}

export async function startDiscovery(
  req: StartDiscoveryRequest,
): Promise<StartDiscoveryResponse> {
  return request<StartDiscoveryResponse>('/api/v1/discovery/start', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function pollStatus(taskId: string): Promise<StatusResponse> {
  return request<StatusResponse>(`/api/v1/discovery/${taskId}/status`)
}

export async function fetchReport(taskId: string): Promise<ReportResponse> {
  return request<ReportResponse>(`/api/v1/discovery/${taskId}/report`)
}
