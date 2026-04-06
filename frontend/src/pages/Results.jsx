import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getBook, getBookResults, getPageDetail, submitReview, exportCsvUrl } from '../api'

function ConfidenceBadge({ level }) {
  return <span className={`badge badge-${level}`}>{level}</span>
}

function ReviewStatusBadge({ decision }) {
  if (!decision) return <span className="badge badge-pending">Pending</span>
  return <span className={`badge badge-${decision}`}>{decision.replace('_', ' ')}</span>
}

function DetailPanel({ detection, bookId, onReviewSaved, onClose }) {
  const [pageDetail, setPageDetail] = useState(null)
  const [imgError, setImgError] = useState(false)
  const [decision, setDecision] = useState(detection.review_decision || null)
  const [notes, setNotes] = useState(detection.reviewer_notes || '')
  const [grantor, setGrantor] = useState(detection.grantor_grantee || '')
  const [propertyInfo, setPropertyInfo] = useState(detection.property_info || '')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  useEffect(() => {
    // Reset form when detection changes
    setDecision(detection.review_decision || null)
    setNotes(detection.reviewer_notes || '')
    setGrantor(detection.grantor_grantee || '')
    setPropertyInfo(detection.property_info || '')
    setSaveSuccess(false)
    setSaveError(null)
    setPageDetail(null)
    setImgError(false)

    getPageDetail(bookId, detection.page_number)
      .then(setPageDetail)
      .catch(() => setPageDetail({ error: true }))
  }, [detection.detection_id, bookId, detection.page_number])

  async function handleSave() {
    if (!decision) {
      setSaveError('Please select a review decision first.')
      return
    }
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      await submitReview(detection.detection_id, {
        decision,
        notes,
        grantor_grantee: grantor,
        property_info: propertyInfo,
      })
      setSaveSuccess(true)
      onReviewSaved(detection.detection_id, { decision, notes, grantor_grantee: grantor, property_info: propertyInfo })
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const imageUrl = pageDetail?.image_path
    ? `/page-image?path=${encodeURIComponent(pageDetail.image_path)}`
    : null

  return (
    <div className="detail-panel">
      <div className="detail-panel-header">
        <div>
          <div className="bold">Book #{detection.book_number || ''}, Page {detection.page_number}</div>
          <ConfidenceBadge level={detection.confidence} />
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>✕ Close</button>
      </div>

      <div className="detail-panel-body">
        {/* Page image */}
        <div className="section-label">Page Image</div>
        <div className="page-image-wrap">
          {!pageDetail ? (
            <div className="page-image-placeholder">
              <div className="spinner spinner-sm" style={{ margin: '0 auto 8px' }} />
              Loading image…
            </div>
          ) : pageDetail.error || !imageUrl || imgError ? (
            <div className="page-image-placeholder">
              📄 Image not available
            </div>
          ) : (
            <img
              src={imageUrl}
              alt={`Page ${detection.page_number}`}
              onError={() => setImgError(true)}
            />
          )}
        </div>

        {/* Detected covenant text */}
        {detection.detected_text && (
          <>
            <div className="section-label">Detected Language</div>
            <div className="detected-text-box">
              "{detection.detected_text}"
            </div>
          </>
        )}

        {/* Target groups */}
        {detection.target_groups?.length > 0 && (
          <>
            <div className="section-label">Target Groups</div>
            <div className="tag-list mb-16">
              {detection.target_groups.map(g => <span key={g} className="tag">{g}</span>)}
            </div>
          </>
        )}

        {/* Full OCR text */}
        {pageDetail?.ocr_text && (
          <>
            <div className="section-label">Full OCR Text</div>
            <div className="ocr-text-box">{pageDetail.ocr_text}</div>
          </>
        )}

        <hr className="divider" />

        {/* Review decision */}
        <div className="section-label">Your Review Decision</div>
        <div className="review-buttons mb-16">
          <button
            className={`review-btn review-btn-confirm ${decision === 'confirmed' ? 'selected' : ''}`}
            onClick={() => setDecision('confirmed')}
            type="button"
          >
            ✓ Confirm<br/>Covenant
          </button>
          <button
            className={`review-btn review-btn-fp ${decision === 'false_positive' ? 'selected' : ''}`}
            onClick={() => setDecision('false_positive')}
            type="button"
          >
            ✗ False<br/>Positive
          </button>
          <button
            className={`review-btn review-btn-needs ${decision === 'needs_review' ? 'selected' : ''}`}
            onClick={() => setDecision('needs_review')}
            type="button"
          >
            ? Needs<br/>Review
          </button>
        </div>

        {/* Metadata fields */}
        <div className="form-group">
          <label>Grantor / Grantee</label>
          <input
            type="text"
            placeholder="e.g. Endicott Land Company"
            value={grantor}
            onChange={e => setGrantor(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label>Property Info</label>
          <input
            type="text"
            placeholder="Address or parcel identifier"
            value={propertyInfo}
            onChange={e => setPropertyInfo(e.target.value)}
          />
        </div>

        <div className="form-group">
          <label>Notes</label>
          <textarea
            placeholder="Any additional notes about this page…"
            value={notes}
            onChange={e => setNotes(e.target.value)}
            style={{ minHeight: 60 }}
          />
        </div>

        {saveError && (
          <div className="alert alert-error mb-16">⚠️ {saveError}</div>
        )}
        {saveSuccess && (
          <div className="alert alert-success mb-16">✅ Review saved.</div>
        )}

        <button
          className="btn btn-primary btn-full"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? <><span className="spinner spinner-sm" /> Saving…</> : '💾 Save Review'}
        </button>
      </div>
    </div>
  )
}

export default function Results() {
  const { bookId } = useParams()
  const [book, setBook] = useState(null)
  const [detections, setDetections] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedId, setSelectedId] = useState(null)

  useEffect(() => {
    Promise.all([getBook(bookId), getBookResults(bookId)])
      .then(([b, d]) => {
        setBook(b)
        setDetections(d)
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [bookId])

  function handleReviewSaved(detectionId, review) {
    setDetections(prev =>
      prev.map(d =>
        d.detection_id === detectionId
          ? {
              ...d,
              reviewed: true,
              review_decision: review.decision,
              reviewer_notes: review.notes,
              grantor_grantee: review.grantor_grantee,
              property_info: review.property_info,
            }
          : d
      )
    )
  }

  const selected = detections.find(d => d.detection_id === selectedId)

  const confirmed = detections.filter(d => d.review_decision === 'confirmed').length
  const pending = detections.filter(d => !d.reviewed).length
  const falsePos = detections.filter(d => d.review_decision === 'false_positive').length

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
        <div className="alert alert-error">⚠️ {error}</div>
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="flex gap-12 mb-24" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }}>
          <h1 className="page-title">Book #{book?.book_number} — Results</h1>
          <p className="page-sub">
            {detections.length === 0
              ? 'No pages flagged. This book appears to contain no racial covenants.'
              : `${detections.length} page${detections.length !== 1 ? 's' : ''} flagged for review.`}
          </p>
        </div>
        <div className="flex gap-8" style={{ flexShrink: 0 }}>
          <a
            href={exportCsvUrl(bookId, 'all_detections')}
            className="btn btn-ghost btn-sm"
            download
          >
            ⬇ Export CSV
          </a>
          <a
            href={exportCsvUrl(bookId, 'confirmed_only')}
            className="btn btn-outline-primary btn-sm"
            download
          >
            ⬇ Confirmed Only
          </a>
          <Link to="/history" className="btn btn-ghost btn-sm">
            ← History
          </Link>
        </div>
      </div>

      {/* Stats */}
      {detections.length > 0 && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#dc2626' }}>{detections.length}</div>
            <div className="stat-label">Total Flagged</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#15803d' }}>{confirmed}</div>
            <div className="stat-label">Confirmed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#1d4ed8' }}>{pending}</div>
            <div className="stat-label">Pending Review</div>
          </div>
          <div className="stat-card">
            <div className="stat-value" style={{ color: '#64748b' }}>{falsePos}</div>
            <div className="stat-label">False Positives</div>
          </div>
        </div>
      )}

      {detections.length === 0 ? (
        <div className="card">
          <div className="empty">
            <div className="empty-icon">✅</div>
            <div className="empty-title">No covenants detected</div>
            <div className="empty-text">
              The AI found no racial covenant language in Book #{book?.book_number}.
              <br />If you believe this is incorrect, try rescanning with a higher-quality PDF.
            </div>
          </div>
        </div>
      ) : (
        <div className={`results-layout ${selected ? 'with-panel' : ''}`}>
          {/* Detection table */}
          <div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Page</th>
                    <th>Confidence</th>
                    <th>Target Groups</th>
                    <th>Detected Language</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {detections.map(d => (
                    <tr
                      key={d.detection_id}
                      className={`clickable ${d.detection_id === selectedId ? 'selected' : ''}`}
                      onClick={() => setSelectedId(d.detection_id === selectedId ? null : d.detection_id)}
                    >
                      <td>
                        <span className="bold">{d.page_number}</span>
                      </td>
                      <td>
                        <ConfidenceBadge level={d.confidence} />
                      </td>
                      <td>
                        <div className="tag-list">
                          {(d.target_groups || []).map(g => (
                            <span key={g} className="tag">{g}</span>
                          ))}
                          {(!d.target_groups || d.target_groups.length === 0) && (
                            <span className="text-muted">—</span>
                          )}
                        </div>
                      </td>
                      <td>
                        {d.detected_text ? (
                          <span
                            title={d.detected_text}
                            className="truncate"
                            style={{ display: 'block', fontStyle: 'italic', color: '#374151', fontSize: 13 }}
                          >
                            "{d.detected_text.length > 80 ? d.detected_text.slice(0, 80) + '…' : d.detected_text}"
                          </span>
                        ) : (
                          <span className="text-muted">keyword match only</span>
                        )}
                      </td>
                      <td>
                        <ReviewStatusBadge decision={d.review_decision} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="small mt-16" style={{ color: '#64748b' }}>
              Click any row to open the review panel. Sort by clicking column headers.
            </p>
          </div>

          {/* Detail / review panel */}
          {selected && (
            <DetailPanel
              detection={{ ...selected, book_number: book?.book_number }}
              bookId={bookId}
              onReviewSaved={handleReviewSaved}
              onClose={() => setSelectedId(null)}
            />
          )}
        </div>
      )}
    </div>
  )
}
