import { useState, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { uploadScan, startScrapeScan } from '../api'

export default function Upload() {
  const navigate = useNavigate()
  const fileInputRef = useRef(null)

  // Tab: 'upload' or 'scrape'
  const [tab, setTab] = useState('upload')

  // Shared
  const [bookNumber, setBookNumber] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Upload-only
  const [file, setFile] = useState(null)
  const [dragover, setDragover] = useState(false)

  // Scrape-only
  const [lastPage, setLastPage] = useState('')

  function handleDrop(e) {
    e.preventDefault()
    setDragover(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped && dropped.type === 'application/pdf') setFile(dropped)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)

    if (!bookNumber.trim()) {
      setError('Please enter a book number.')
      return
    }

    if (tab === 'upload') {
      if (!file) {
        setError('Please select a PDF file to upload.')
        return
      }
      setLoading(true)
      try {
        const { job_id } = await uploadScan(bookNumber.trim(), sourceUrl.trim() || null, file)
        navigate(`/processing/${job_id}`)
      } catch (err) {
        setError(err.message || 'Upload failed. Is the backend running?')
        setLoading(false)
      }
    } else {
      const pages = parseInt(lastPage, 10)
      if (!lastPage || isNaN(pages) || pages < 1) {
        setError('Please enter the number of pages in this book.')
        return
      }
      setLoading(true)
      try {
        const { job_id } = await startScrapeScan(bookNumber.trim(), pages, sourceUrl.trim() || null)
        navigate(`/processing/${job_id}`)
      } catch (err) {
        setError(err.message || 'Could not start scrape. Is the backend running?')
        setLoading(false)
      }
    }
  }

  return (
    <div style={{ maxWidth: 600, margin: '0 auto' }}>
      <div className="mb-24">
        <h1 className="page-title">Scan a Deed Book</h1>
        <p className="page-sub">
          Upload a PDF you already have, or let the tool download the pages
          directly from the Broome County records site.
        </p>
      </div>

      {/* Tab switcher */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 24, borderBottom: '2px solid #e5e7eb' }}>
        {[
          { key: 'upload', label: '📄 Upload PDF' },
          { key: 'scrape', label: '🌐 Download from County Site' },
        ].map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => { setTab(key); setError(null) }}
            style={{
              padding: '10px 20px',
              background: 'none',
              border: 'none',
              borderBottom: tab === key ? '2px solid #2563eb' : '2px solid transparent',
              marginBottom: -2,
              fontWeight: tab === key ? 700 : 400,
              color: tab === key ? '#2563eb' : '#6b7280',
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="card">
        {error && (
          <div className="alert alert-error mb-16">
            <span>⚠️</span> {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Book number — shared */}
          <div className="form-group">
            <label htmlFor="book-number">Book Number *</label>
            <input
              id="book-number"
              type="text"
              placeholder="e.g. 290"
              value={bookNumber}
              onChange={e => setBookNumber(e.target.value)}
              disabled={loading}
            />
            <p className="hint">The deed book number as shown on the county website.</p>
          </div>

          {/* Source URL — shared */}
          <div className="form-group">
            <label htmlFor="source-url">Source URL (optional)</label>
            <input
              id="source-url"
              type="url"
              placeholder="https://searchiqs.com/nybro/..."
              value={sourceUrl}
              onChange={e => setSourceUrl(e.target.value)}
              disabled={loading}
            />
            <p className="hint">Link to this book on the Broome County records site, for reference.</p>
          </div>

          {/* Upload tab: PDF file picker */}
          {tab === 'upload' && (
            <div className="form-group">
              <label>PDF File *</label>
              <div
                className={`upload-zone ${dragover ? 'dragover' : ''} ${file ? 'has-file' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setDragover(true) }}
                onDragLeave={() => setDragover(false)}
                onDrop={handleDrop}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={e => setFile(e.target.files[0] || null)}
                  disabled={loading}
                />
                {file ? (
                  <>
                    <div className="upload-icon">✅</div>
                    <div className="upload-filename">{file.name}</div>
                    <div className="upload-hint" style={{ marginTop: 4 }}>
                      {(file.size / 1024 / 1024).toFixed(1)} MB — click to change
                    </div>
                  </>
                ) : (
                  <>
                    <div className="upload-icon">📄</div>
                    <div className="upload-label">Click to select PDF, or drag & drop</div>
                    <div className="upload-hint">PDF files only</div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Scrape tab: page count field */}
          {tab === 'scrape' && (
            <div className="form-group">
              <label htmlFor="last-page">Number of Pages *</label>
              <input
                id="last-page"
                type="number"
                min="1"
                placeholder="e.g. 1000"
                value={lastPage}
                onChange={e => setLastPage(e.target.value)}
                disabled={loading}
              />
              <p className="hint">
                How many pages are in this book? Typical Broome County deed books are 500–1,500 pages.
                Check the county site if unsure.
              </p>
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-lg btn-full"
            disabled={loading}
          >
            {loading ? (
              <><span className="spinner spinner-sm" /> {tab === 'scrape' ? 'Starting download…' : 'Uploading…'}</>
            ) : (
              tab === 'scrape' ? '🌐 Download & Scan' : '▶ Start Scan'
            )}
          </button>
        </form>
      </div>

      <div className="mt-24" style={{ textAlign: 'center' }}>
        <Link to="/history" className="btn btn-ghost btn-sm">
          📋 View past scans
        </Link>
      </div>

      {/* Tips card */}
      {tab === 'upload' && (
        <div className="card card-sm mt-24" style={{ background: '#fffbeb', borderColor: '#fde68a' }}>
          <p className="small bold mb-4">💡 Tips for best results</p>
          <ul style={{ paddingLeft: 18, fontSize: 13, color: '#78350f', lineHeight: 1.8 }}>
            <li>Scan quality matters — higher DPI scans give better OCR results.</li>
            <li>Each 1,000-page book takes roughly 5–15 minutes to process.</li>
            <li>The tool flags aggressively — expect some false positives to review.</li>
            <li>Known covenant books: #290 (pg. 9), #180 (pg. 438).</li>
          </ul>
        </div>
      )}

      {tab === 'scrape' && (
        <div className="card card-sm mt-24" style={{ background: '#eff6ff', borderColor: '#bfdbfe' }}>
          <p className="small bold mb-4">💡 How this works</p>
          <ul style={{ paddingLeft: 18, fontSize: 13, color: '#1e40af', lineHeight: 1.8 }}>
            <li>The tool opens the Broome County records site and saves each page image automatically.</li>
            <li>No account or payment needed — viewing pages on the site is free.</li>
            <li>Downloading takes 1–2 hours for a full book (3–6 seconds per page).</li>
            <li>Covenant detection runs automatically once downloading is complete.</li>
            <li>Known covenant books: #290 (pg. 9), #180 (pg. 438).</li>
          </ul>
        </div>
      )}
    </div>
  )
}
