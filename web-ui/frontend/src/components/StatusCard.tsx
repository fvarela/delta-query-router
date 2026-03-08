import type { StatusValue } from '../types'
import './StatusCard.css'

interface StatusCardProps {
  name: string
  status: StatusValue
  detail?: string
}

const statusConfig: Record<StatusValue, { label: string; className: string }> = {
  connected: { label: 'Connected', className: 'status-connected' },
  error: { label: 'Error', className: 'status-error' },
  unknown: { label: 'Unknown', className: 'status-unknown' },
  not_configured: { label: 'Not Configured', className: 'status-not-configured' },
}

export default function StatusCard({ name, status, detail }: StatusCardProps) {
  const { label, className } = statusConfig[status]

  return (
    <div className={`status-card ${className}`}>
      <h3 className="status-card-name">{name}</h3>
      <div className="status-card-indicator">{label}</div>
      {detail && <div className="status-card-detail">{detail}</div>}
    </div>
  )
}
