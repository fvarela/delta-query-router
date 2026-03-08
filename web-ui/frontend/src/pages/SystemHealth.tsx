import { useEffect, useState } from 'react'
import StatusCard from '../components/StatusCard'
import type { HealthResponse } from '../types'
import './SystemHealth.css'

const SERVICE_LABELS: Record<string, string> = {
  web_ui: 'Web UI',
  routing_service: 'Routing Service',
  postgresql: 'PostgreSQL',
  duckdb_worker: 'DuckDB Worker',
  databricks: 'Databricks',
}

const SERVICE_ORDER = ['web_ui', 'routing_service', 'postgresql', 'duckdb_worker', 'databricks']

const POLL_INTERVAL = 15_000

export default function SystemHealth() {
  const [services, setServices] = useState<HealthResponse | null>(null)
  const [lastChecked, setLastChecked] = useState<Date | null>(null)

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch('/api/health/services')
        const data = await res.json()
        setServices(data)
        setLastChecked(new Date())
      } catch {
        // If fetch itself fails, leave previous state
      }
    }
    fetchHealth()
    const interval = setInterval(fetchHealth, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [])

  return (
    <div>
      <div className="health-header">
        <h1>System Health</h1>
        {lastChecked && (
          <span className="health-timestamp">
            Last checked: {lastChecked.toLocaleTimeString()}
          </span>
        )}
      </div>
      <div className="health-grid">
        {services
          ? SERVICE_ORDER.map((key) => (
              <StatusCard
                key={key}
                name={SERVICE_LABELS[key] ?? key}
                status={services[key]?.status ?? 'unknown'}
                detail={services[key]?.detail}
              />
            ))
          : <div className="health-loading">Loading...</div>
        }
      </div>
    </div>
  )
}
