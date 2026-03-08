import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import SystemHealth from './pages/SystemHealth'
import QueryConsole from './pages/QueryConsole'
import LiveQueryLogs from './pages/LiveQueryLogs'
import ObservabilityDashboard from './pages/ObservabilityDashboard'
import RouterConfiguration from './pages/RouterConfiguration'
import Operations from './pages/Operations'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<SystemHealth />} />
            <Route path="/query-console" element={<QueryConsole />} />
            <Route path="/live-logs" element={<LiveQueryLogs />} />
            <Route path="/observability" element={<ObservabilityDashboard />} />
            <Route path="/router-config" element={<RouterConfiguration />} />
            <Route path="/operations" element={<Operations />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
