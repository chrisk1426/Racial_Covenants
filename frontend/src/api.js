/**
 * API client — thin wrappers around fetch() for each backend endpoint.
 * All routes are relative so the Vite proxy (dev) or same-origin (prod) handles them.
 */

async function request(url, options = {}) {
  const res = await fetch(url, options)
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch (_) {}
    throw new Error(detail)
  }
  return res.json()
}

// ── Scan ──────────────────────────────────────────────────────────────────────

export async function uploadScan(bookNumber, sourceUrl, file, skipAi = false) {
  const form = new FormData()
  form.append('book_number', bookNumber)
  if (sourceUrl) form.append('source_url', sourceUrl)
  form.append('skip_ai', String(skipAi))
  form.append('file', file)
  return request('/scan/upload', { method: 'POST', body: form })
}

export async function getScanStatus(jobId) {
  return request(`/scan/status/${jobId}`)
}

export async function startScrapeScan(bookNumber, lastPage, sourceUrl, skipAi = false) {
  return request('/scan/scrape', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      book_number: bookNumber,
      last_page: lastPage,
      source_url: sourceUrl || null,
      skip_ai: skipAi,
    }),
  })
}

export function exportCsvUrl(bookId, mode = 'all_detections') {
  return `/scan/export/${bookId}?mode=${mode}`
}

// ── Books ─────────────────────────────────────────────────────────────────────

export async function listBooks() {
  return request('/books/')
}

export async function getBook(bookId) {
  return request(`/books/${bookId}`)
}

export async function getBookResults(bookId) {
  return request(`/books/${bookId}/results`)
}

export async function getPageDetail(bookId, pageNumber) {
  return request(`/books/${bookId}/pages/${pageNumber}`)
}

// ── Detections / Reviews ──────────────────────────────────────────────────────

export async function submitReview(detectionId, { decision, notes, grantor_grantee, property_info }) {
  return request(`/detections/${detectionId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, notes, grantor_grantee, property_info }),
  })
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export async function getStats() {
  return request('/stats')
}
