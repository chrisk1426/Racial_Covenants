import { Routes, Route, Link, useLocation } from 'react-router-dom'
import Upload from './pages/Upload'
import Processing from './pages/Processing'
import Results from './pages/Results'
import History from './pages/History'

export default function App() {
  const location = useLocation()
  const isProcessing = location.pathname.startsWith('/processing')

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="logo">
            <span className="logo-icon">📜</span>
            <span className="logo-text">Covenant Detector</span>
          </Link>
          {!isProcessing && (
            <nav className="nav">
              <Link to="/" className={location.pathname === '/' ? 'nav-link active' : 'nav-link'}>
                New Scan
              </Link>
              <Link to="/history" className={location.pathname === '/history' ? 'nav-link active' : 'nav-link'}>
                History
              </Link>
            </nav>
          )}
        </div>
      </header>

      <main className="main">
        <Routes>
          <Route path="/" element={<Upload />} />
          <Route path="/processing/:jobId" element={<Processing />} />
          <Route path="/results/:bookId" element={<Results />} />
          <Route path="/history" element={<History />} />
        </Routes>
      </main>

      <footer className="footer">
        <p>Broome County Racial Covenant Detection Tool &mdash; Broome County Clerk's Office Records</p>
      </footer>
    </div>
  )
}
