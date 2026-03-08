export type StatusValue = 'connected' | 'error' | 'unknown' | 'not_configured'

export interface ServiceStatus {
  status: StatusValue
  detail?: string
}

export type HealthResponse = Record<string, ServiceStatus>
