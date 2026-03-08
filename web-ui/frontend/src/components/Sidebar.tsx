import { NavLink } from 'react-router-dom'
import './Sidebar.css'

const navItems = [
  { to: '/', label: 'System Health' },
  { to: '/query-console', label: 'Query Console' },
  { to: '/live-logs', label: 'Live Query Logs' },
  { to: '/observability', label: 'Observability' },
  { to: '/router-config', label: 'Router Config' },
  { to: '/operations', label: 'Operations' },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">Delta Router</div>
      <nav className="sidebar-nav">
        {navItems.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `sidebar-link${isActive ? ' active' : ''}`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
