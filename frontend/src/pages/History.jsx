import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listBooks, getStats } from '../api'

function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{status}</span>
}

function formatDate(isoStr) {
  if (!isoStr) return '—'
  const d = new Date(isoStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function History() {
  const [books, setBooks] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([listBooks(), getStats()])
      .then(([b, s]) => {
        setBooks(b)
        setStats(s)
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex-center" style={{ paddingTop: 80 }}>
        <div className="spinner" />
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ maxWidth: 600, margin: '0 auto' }}>
        <div className="alert alert-error">
          ⚠️ Could not load history: {error}
          <br />
          <span className="small">Make sure the backend is running at localhost:8000.</span>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex gap-12 mb-24" style={{ alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <h1 className="page-title">Scan History</h1>
          <p className="page-sub">All deed books processed so far.</p>
        </div>
        <Link to="/" className="btn btn-primary btn-sm" style={{ flexShrink: 0 }}>
          + New Scan
        </Link>
      </div>

      {/* Dashboard stats */}
      {stats && (
        <div className="stats-grid mb-24">
          <div className="stat-card">
            <div className="stat-value">{stats.books_scanned}</div>
            <div className="stat-label">Books Scanned</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{(stats.total_pages_processed || 0).toLocaleString()}</div>
            <div className="stat-label">Pages Processed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#dc2626' }}>{stats.total_detections}</div>
            <div className="stat-label">Total Flagged</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#15803d' }}>{stats.confirmed_covenants}</div>
            <div className="stat-label">Confirmed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#1d4ed8' }}>{stats.pending_review}</div>
            <div className="stat-label">Pending Review</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#64748b' }}>{stats.false_positives}</div>
            <div className="stat-label">False Positives</div>
          </div>
        </div>
      )}

      {/* Books table */}
      {books.length === 0 ? (
        <div className="card">
          <div className="empty">
            <div className="empty-icon">📚</div>
            <div className="empty-title">No scans yet</div>
            <div className="empty-text">
              <Link to="/" className="btn btn-primary btn-sm" style={{ marginTop: 12, display: 'inline-flex' }}>
                Start your first scan
              </Link>
            </div>
          </div>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Book #</th>
                <th>Scan Date</th>
                <th>Total Pages</th>
                <th>Status</th>
                <th>Filename</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {books.map(b => (
                <tr key={b.id}>
                  <td><span className="bold">#{b.book_number}</span></td>
                  <td>{formatDate(b.created_at)}</td>
                  <td>{b.total_pages != null ? b.total_pages.toLocaleString() : <span className="text-muted">—</span>}</td>
                  <td><StatusBadge status={b.status} /></td>
                  <td>
                    <span className="text-muted small">
                      {b.upload_filename || '—'}
                    </span>
                  </td>
                  <td>
                    {b.status === 'complete' ? (
                      <Link
                        to={`/results/${b.id}`}
                        className="btn btn-outline-primary btn-sm"
                      >
                        View Results →
                      </Link>
                    ) : b.status === 'processing' ? (
                      <span className="text-muted small">In progress…</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
