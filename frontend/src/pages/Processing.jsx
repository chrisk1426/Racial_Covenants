import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getScanStatus } from '../api'

const STAGE_LABELS = {
  queued: { label: 'Preparing…', cls: 'stage-queued', icon: '⏳' },
  scraping: { label: 'Downloading pages from county site…', cls: 'stage-queued', icon: '🌐' },
  ocr: { label: 'Extracting text from pages…', cls: 'stage-ocr', icon: '🔍' },
  filtering: { label: 'Screening for covenant language…', cls: 'stage-filtering', icon: '🔎' },
  classifying: { label: 'AI analyzing flagged pages…', cls: 'stage-classifying', icon: '🤖' },
  complete: { label: 'Complete!', cls: 'stage-complete', icon: '✅' },
  error: { label: 'Error', cls: 'stage-error', icon: '❌' },
}

export default function Processing() {
  const { jobId } = useParams()
  const navigate = useNavigate()

  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  useEffect(() => {
    async function poll() {
      try {
        const data = await getScanStatus(jobId)
        setStatus(data)

        if (data.status === 'complete') {
          clearInterval(intervalRef.current)
          // Short delay so user sees the completion state
          setTimeout(() => navigate(`/results/${data.book_id}`), 1500)
        } else if (data.status === 'error') {
          clearInterval(intervalRef.current)
        }
      } catch (err) {
        setError(err.message)
        clearInterval(intervalRef.current)
      }
    }

    poll() // immediate first poll
    intervalRef.current = setInterval(poll, 2000)
    return () => clearInterval(intervalRef.current)
  }, [jobId, navigate])

  if (error) {
    return (
      <div style={{ maxWidth: 560, margin: '0 auto' }}>
        <div className="alert alert-error">
          <span>❌</span>
          <div>
            <div className="bold">Scan failed</div>
            <div>{error}</div>
          </div>
        </div>
      </div>
    )
  }

  if (!status) {
    return (
      <div className="flex-center" style={{ paddingTop: 80 }}>
        <div className="spinner" />
      </div>
    )
  }

  const stage = STAGE_LABELS[status.status] || STAGE_LABELS.queued
  const pct = status.total_pages
    ? Math.round((status.pages_processed / status.total_pages) * 100)
    : 0
  const isComplete = status.status === 'complete'
  const isError = status.status === 'error'

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div className="mb-24">
        <h1 className="page-title">Scanning Book #{status.book_id}</h1>
        <p className="page-sub">
          Please keep this tab open. This may take several minutes for large books.
        </p>
      </div>

      <div className="card">
        {/* Stage indicator */}
        <div className={`status-stage ${stage.cls}`}>
          <span>{stage.icon}</span>
          <span>{stage.label}</span>
        </div>

        {/* Progress bar */}
        <div className="progress-wrap">
          <div
            className={`progress-bar ${isComplete ? 'complete' : isError ? 'error' : ''}`}
            style={{ width: isComplete ? '100%' : `${Math.max(pct, 2)}%` }}
          />
        </div>

        {/* Counts */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, color: '#374151', marginBottom: 8 }}>
          <span>
            {status.total_pages
              ? `${status.pages_processed.toLocaleString()} of ${status.total_pages.toLocaleString()} pages`
              : `${status.pages_processed.toLocaleString()} pages processed`}
          </span>
          <span style={{ fontWeight: 700 }}>{pct}%</span>
        </div>

        {/* Flagged count */}
        {status.pages_flagged > 0 && (
          <div className="alert alert-info" style={{ marginTop: 16, marginBottom: 0 }}>
            🚩 <strong>{status.pages_flagged}</strong> potential covenant{status.pages_flagged !== 1 ? 's' : ''} found so far
          </div>
        )}

        {/* Error message */}
        {isError && status.error_message && (
          <div className="alert alert-error" style={{ marginTop: 16, marginBottom: 0 }}>
            {status.error_message}
          </div>
        )}

        {/* Complete */}
        {isComplete && (
          <div className="alert alert-success" style={{ marginTop: 16, marginBottom: 0 }}>
            ✅ Scan complete — redirecting to results…
          </div>
        )}
      </div>

      {/* Stage legend */}
      <div className="card card-sm mt-24">
        <p className="small bold mb-8" style={{ color: '#64748b' }}>Processing stages</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            ['🔍', 'Text Extraction (OCR)', 'Each page image is converted to searchable text.'],
            ['🔎', 'Keyword Screening', 'Pages with no relevant terms are skipped quickly.'],
            ['🤖', 'AI Classification', 'Claude reads candidate pages and flags covenants.'],
          ].map(([icon, title, desc]) => (
            <div key={title} style={{ display: 'flex', gap: 10, fontSize: 13, color: '#374151' }}>
              <span>{icon}</span>
              <div>
                <span className="bold">{title}:</span> {desc}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
