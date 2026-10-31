import { useCallback, useEffect, useState } from 'react'

const money = (value, currency) => value == null ? 'Not extracted' : `${currency ? `${currency} ` : ''}${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const editableFields = ['invoice_number', 'invoice_date', 'supplier_name', 'customer_name', 'subtotal', 'tax', 'total', 'currency']
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'
const DEMO_USER = { email: 'public-demo@local.invalid', role: 'admin', demo: true }
// Keep upload limits aligned with backend upload settings.
const MAX_UPLOAD_FILES_PER_BATCH = 10
const MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
const MAX_UPLOAD_BATCH_BYTES = 90 * 1024 * 1024

function errorMessage(body, fallback) {
  if (typeof body?.detail === 'string') return body.detail
  if (body?.detail != null) return JSON.stringify(body.detail)
  return fallback
}

function cookieValue(name) {
  const prefix = `${name}=`
  const entry = document.cookie.split('; ').find(value => value.startsWith(prefix))
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : ''
}

async function api(path, options = {}) {
  const requestHeaders = new Headers(options.headers || {})
  const method = (options.method || 'GET').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = cookieValue('docintel_csrf')
    if (csrf) requestHeaders.set('X-CSRF-Token', csrf)
  }
  const response = await fetch(path, { ...options, credentials: 'same-origin', headers: requestHeaders })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(errorMessage(body, `Request failed (${response.status})`))
  return body
}

const toEditableLineItem = item => ({
  description: item?.description ?? '',
  quantity: item?.quantity == null ? '' : String(item.quantity),
  unit_price: item?.unit_price == null ? '' : String(item.unit_price),
  amount: item?.amount == null ? '' : String(item.amount),
})

const toLineItemPayload = items => items.map(item => ({
  description: item.description.trim() || null,
  quantity: item.quantity === '' ? null : Number(item.quantity),
  unit_price: item.unit_price === '' ? null : Number(item.unit_price),
  amount: item.amount === '' ? null : Number(item.amount),
})).filter(item => item.description || item.quantity != null || item.unit_price != null || item.amount != null)
const getHistoryChanges = event => {
  const before = event.details?.before
  const after = event.details?.after

  if (
    !before ||
    !after ||
    typeof before !== 'object' ||
    typeof after !== 'object' ||
    Array.isArray(before) ||
    Array.isArray(after)
  ) {
    return []
  }

  const fields = [...new Set([
    ...Object.keys(before),
    ...Object.keys(after),
  ])]

  return fields
    .filter(field =>
      JSON.stringify(before[field] ?? null) !==
      JSON.stringify(after[field] ?? null)
    )
    .map(field => ({
      field,
      before: before[field],
      after: after[field],
    }))
}

const formatHistoryValue = value => {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}
export default function App() {
  const [authChecking, setAuthChecking] = useState(!DEMO_MODE)
  const [setupRequired, setSetupRequired] = useState(false)
  const [bootstrapTokenRequired, setBootstrapTokenRequired] = useState(false)
  const [authUser, setAuthUser] = useState(DEMO_MODE ? DEMO_USER : null)
  const [authBusy, setAuthBusy] = useState(false)
  const [authForm, setAuthForm] = useState({ email: '', password: '', tenant_name: 'My workspace', bootstrap_token: '' })
  const [documents, setDocuments] = useState([])
  const [stats, setStats] = useState({ total: 0, completed: 0, queued: 0, failed: 0 })
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [queueStatus, setQueueStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [query, setQuery] = useState('')
  const [searchMode, setSearchMode] = useState('keyword')
  const [searchModeUsed, setSearchModeUsed] = useState('keyword')
  const [stateFilter, setStateFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const [invoiceFilter, setInvoiceFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [compareIds, setCompareIds] = useState([])
  const [comparison, setComparison] = useState(null)
  const [comparisonDocuments, setComparisonDocuments] = useState([])
  const [comparisonDocumentsLoading, setComparisonDocumentsLoading] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [edits, setEdits] = useState({})
  const [lineItemEdits, setLineItemEdits] = useState([])
  const [saving, setSaving] = useState(false)
  const [deleteBusyId, setDeleteBusyId] = useState(null)

  useEffect(() => {
    let active = true
    if (DEMO_MODE) {
      setAuthUser(DEMO_USER)
      setAuthChecking(false)
      return () => { active = false }
    }
    const initializeAuth = async () => {
      try {
        const setup = await api('/api/auth/setup-status')
        if (!active) return
        setSetupRequired(Boolean(setup.setup_required))
        setBootstrapTokenRequired(Boolean(setup.bootstrap_token_required))
        if (!setup.setup_required) {
          try {
            const current = await api('/api/auth/me')
            if (active) setAuthUser(current.user)
          } catch {
            if (active) setAuthUser(null)
          }
        }
      } catch (error) {
        if (active) setError(`Unable to initialize authentication: ${error.message}`)
      } finally {
        if (active) setAuthChecking(false)
      }
    }
    initializeAuth()
    return () => { active = false }
  }, [])

  const submitAuth = async event => {
    event.preventDefault()
    setAuthBusy(true); setError('')
    try {
      const endpoint = setupRequired ? '/api/auth/setup' : '/api/auth/login'
      const result = await api(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authForm),
      })
      setAuthUser(result.user)
      setSetupRequired(false)
      setMessage(setupRequired ? 'Administrator account created.' : 'Signed in successfully.')
    } catch (error) {
      setError(error.message)
    } finally {
      setAuthBusy(false)
    }
  }

  const logout = async () => {
    try {
      await api('/api/auth/logout', { method: 'POST' })
      setAuthUser(null); setDocuments([]); setSelected(null); setDetail(null); setQueueStatus(null); setHistory([])
    } catch (error) { setError(`Sign out failed: ${error.message}`) }
  }

  const loadStats = useCallback(async () => {
    if (!authUser) return
    try {
      const params = new URLSearchParams()
      const filters = { state: stateFilter, file_type: typeFilter, supplier: supplierFilter, invoice_number: invoiceFilter, date_from: dateFrom, date_to: dateTo }
      Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value) })
      const result = await api(`/api/documents/stats?${params.toString()}`)
      setStats(result)
    } catch { /* Keep the last known counts if the stats request temporarily fails. */ }
  }, [authUser, stateFilter, typeFilter, supplierFilter, invoiceFilter, dateFrom, dateTo])

  const loadDocuments = useCallback(async () => {
    if (!authUser) return
    try {
      const params = new URLSearchParams({ q: query, mode: searchMode, limit: '51', offset: String(offset) })
      const filters = { state: stateFilter, file_type: typeFilter, supplier: supplierFilter, invoice_number: invoiceFilter, date_from: dateFrom, date_to: dateTo }
      Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value) })
      const result = await api(`/api/search?${params.toString()}`)
      const rows = result.results || []
      setHasNext(rows.length > 50)
      setDocuments(rows.slice(0, 50))
      setSearchModeUsed(result.mode_used || searchMode)
      setError('')
    } catch (e) { setError(e.message) }
  }, [authUser, query, searchMode, stateFilter, typeFilter, supplierFilter, invoiceFilter, dateFrom, dateTo, offset])
    const loadComparisonDocuments = useCallback(async () => {
    if (!authUser) {
      setComparisonDocuments([])
      return
    }

    setComparisonDocumentsLoading(true)

    try {
      const allDocuments = []
      const pageSize = 200

      for (let offset = 0; ; offset += pageSize) {
        const params = new URLSearchParams({
          state: 'completed',
          limit: String(pageSize),
          offset: String(offset),
        })

        const page = await api(`/api/documents?${params.toString()}`)
        allDocuments.push(...page)

        if (page.length < pageSize) break
      }



setComparisonDocuments(allDocuments)
    } catch (e) {
      setError(`Unable to load comparison documents: ${e.message}`)
    } finally {
      setComparisonDocumentsLoading(false)
    }
  }, [authUser])

  useEffect(() => { if (authUser) loadDocuments() }, [authUser, loadDocuments])
  useEffect(() => { if (authUser) loadStats() }, [authUser, loadStats])
  useEffect(() => {
  if (authUser) {
    loadComparisonDocuments()
  } else {
    setComparisonDocuments([])
  }
}, [authUser, loadComparisonDocuments])
  useEffect(() => {
    const activeDocuments = documents.filter(doc => ['pending', 'processing'].includes(doc.status))
    if (!authUser || activeDocuments.length === 0) return
    let polling = false
    const timer = window.setInterval(async () => {
      if (document.hidden || polling) return
      polling = true
      try {
        const statuses = await Promise.all(activeDocuments.map(doc => api(`/api/documents/${doc.id}/status`)))
        const byId = new Map(statuses.map(item => [item.document_id, item.document_status]))

        const statusChanged = activeDocuments.some(
          doc => byId.has(doc.id) && byId.get(doc.id) !== doc.status
        )

        setDocuments(current =>
          current.map(doc =>
            byId.has(doc.id) ? { ...doc, status: byId.get(doc.id) } : doc
          )
        )

        await loadStats()

        if (statusChanged) {
          await loadComparisonDocuments()
        }
      } catch { /* Keep current document rows visible during transient polling errors. */ }
      finally { polling = false }
    }, 5000)
    return () => window.clearInterval(timer)
  }, [authUser, documents, loadStats, loadComparisonDocuments])
  useEffect(() => { setOffset(0) }, [query, searchMode, stateFilter, typeFilter, supplierFilter, invoiceFilter, dateFrom, dateTo])

  useEffect(() => {
    setEdits(detail?.extracted_data || {})
    setLineItemEdits((detail?.extracted_data?.line_items || []).map(toEditableLineItem))
  }, [detail])

  const refreshSelected = useCallback(async id => {
    const [result, statusResult, historyResult] = await Promise.allSettled([
      api(`/api/documents/${id}/result`),
      api(`/api/documents/${id}/status`),
      api(`/api/documents/${id}/history`),
    ])
    if (result.status === 'fulfilled') {
      const latest = result.value
      setDetail(current => {
        if (!current || current.id !== latest.id || current.status !== latest.status || current.updated_at !== latest.updated_at) return latest
        return current
      })
    }
    if (statusResult.status === 'fulfilled') setQueueStatus(statusResult.value)
    if (historyResult.status === 'fulfilled') setHistory(historyResult.value || [])
  }, [])

  useEffect(() => {
    if (!authUser || !selected || !detail || !['pending', 'processing'].includes(detail.status)) return
    let polling = false
    const timer = window.setInterval(async () => {
      if (document.hidden || polling) return
      polling = true
      try {
        const latestStatus = await api(`/api/documents/${selected}/status`)
        setQueueStatus(latestStatus)
        if (latestStatus.document_status !== detail.status) await refreshSelected(selected)
      } catch { /* Keep the last known status visible on transient errors. */ }
      finally { polling = false }
    }, 2500)
    return () => window.clearInterval(timer)
  }, [authUser, selected, detail?.status, refreshSelected])

  const openDocument = async id => {
    setSelected(id)
    setDetail(null)
    setQueueStatus(null)
    setHistory([])
    setError('')
    try { await refreshSelected(id) } catch (e) { setError(e.message) }
  }

    const upload = async event => {
    event.preventDefault()
    if (!files.length) return

    setBusy(true)
    setError('')
    setMessage('')

    try {
      const selectedFiles = [...files]
      const batches = []
      const failed = []
      const rejected = []

      let currentBatch = []
      let currentBatchBytes = 0
      let acceptedCount = 0

      // Validate individual files and create safe upload batches.
      for (const file of selectedFiles) {
        if (file.size > MAX_UPLOAD_FILE_BYTES) {
          failed.push(
            `${file.name}: exceeds the 50 MB per-file limit.`
          )
          continue
        }

        const exceedsFileCount =
          currentBatch.length >= MAX_UPLOAD_FILES_PER_BATCH

        const exceedsBatchSize =
          currentBatchBytes + file.size > MAX_UPLOAD_BATCH_BYTES

        if (currentBatch.length > 0 && (exceedsFileCount || exceedsBatchSize)) {
          batches.push(currentBatch)
          currentBatch = []
          currentBatchBytes = 0
        }

        currentBatch.push(file)
        currentBatchBytes += file.size
      }

      if (currentBatch.length > 0) {
        batches.push(currentBatch)
      }

      // Upload batches sequentially. Never automatically retry a failed batch.
      for (let index = 0; index < batches.length; index++) {
        const batch = batches[index]

        setMessage(
          `Uploading batch ${index + 1} of ${batches.length}...`
        )

        try {
          const form = new FormData()
          batch.forEach(file => form.append('files', file))

          const body = await api('/api/documents/upload', {
            method: 'POST',
            body: form,
          })

          acceptedCount += body.accepted?.length || 0
          rejected.push(...(body.rejected || []))
        } catch (uploadError) {
          failed.push(
            `${batch.map(file => file.name).join(', ')}: ${uploadError.message}`
          )
        }
      }

      const issues = [
        ...rejected.map(item => `${item.filename}: ${item.reason}`),
        ...failed,
      ]

      setMessage(
        `${acceptedCount} file(s) accepted across ${batches.length} upload batch(es). ` +
        'Make sure the document worker is running.'
      )

      if (issues.length) {
        setError(issues.join('\n'))
      }

      setFiles([])
      event.target.reset()
      await Promise.all([loadDocuments(),loadStats(),loadComparisonDocuments(),])
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const reprocess = async () => {
    if (!selected) return
    try {
      await api(`/api/documents/${selected}/reprocess`, { method: 'POST' })
      setMessage('Reprocessing added to the queue.')
      await Promise.all([refreshSelected(selected),loadDocuments(),loadComparisonDocuments(),])
    } catch (e) { setError(e.message) }
  }

  const deleteDocument = async (documentId, filename) => {
    const confirmed = window.confirm(
      `Permanently delete "${filename}" and all associated extracted data, validation findings, search data and processing history? This cannot be undone.`,
    )
    if (!confirmed) return
    setDeleteBusyId(documentId); setError(''); setMessage('')
    try {
      const result = await api(`/api/documents/${documentId}`, { method: 'DELETE' })
      if (selected === documentId) {
        setSelected(null); setDetail(null); setQueueStatus(null); setHistory([])
        setEdits({}); setLineItemEdits([])
      }
      setCompareIds(current => current.filter(id => id !== documentId))
      setComparison(null)
      setMessage(result.file_deleted === false
        ? `Deleted ${filename} and its database records. The quarantined file still needs storage cleanup.`
        : `Deleted ${filename} and all associated document data.`)
      await Promise.all([loadDocuments(),loadStats(),loadComparisonDocuments(),])
    } catch (e) {
      setError(e.message)
    } finally {
      setDeleteBusyId(null)
    }
  }

  const runComparison = async () => {
    if (compareIds.length < 2 || compareIds.length > 10) {
      setError('Select between two and ten completed documents to compare.')
      return
    }
    setComparing(true); setError(''); setMessage('')
    try {
      const result = await api('/api/documents/compare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_ids: compareIds }),
      })
      setComparison(result)
    } catch (e) { setError(e.message) } finally { setComparing(false) }
  }

  const saveCorrections = async () => {
    if (!selected || !detail) return
    setSaving(true); setError(''); setMessage('')
    try {
      const payload = {}
      for (const field of ['invoice_number', 'invoice_date', 'supplier_name', 'customer_name', 'currency']) {
        if ((edits[field] ?? '') !== (detail.extracted_data?.[field] ?? '')) payload[field] = edits[field] || null
      }
      for (const field of ['subtotal', 'tax', 'total']) {
        if (String(edits[field] ?? '') !== String(detail.extracted_data?.[field] ?? '')) {
          payload[field] = edits[field] === '' || edits[field] == null ? null : Number(edits[field])
        }
      }
      const updatedItems = toLineItemPayload(lineItemEdits)
      const originalItems = (detail.extracted_data?.line_items || []).map(item => ({
        description: item.description ?? null, quantity: item.quantity ?? null,
        unit_price: item.unit_price ?? null, amount: item.amount ?? null,
      }))
      if (JSON.stringify(updatedItems) !== JSON.stringify(originalItems)) payload.line_items = updatedItems
      if (!Object.keys(payload).length) { setMessage('No field changes to save.'); return }
      const result = await api(`/api/documents/${selected}/corrections`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fields: payload, corrected_by: authUser?.email || 'reviewer', expected_version: detail.version }),
      })
      setDetail(result); setMessage('Corrections saved. Validation findings have been recalculated.')
      await loadDocuments(); await refreshSelected(selected)
    } catch (e) { setError(e.message) } finally { setSaving(false) }
  }

  const queueLabel = queueStatus?.queue_status || (detail?.status === 'completed' ? 'completed' : detail?.status || 'not queued')
  const canReprocess = detail && !['pending', 'processing'].includes(detail.status)

  if (authChecking) return <main className="shell auth-shell"><section className="panel auth-card"><h1>Document Intelligence</h1><p>Checking your secure workspace session…</p></section></main>
  if (!authUser) return <main className="shell auth-shell">
    <section className="panel auth-card">
      <p className="eyebrow">SECURE WORKSPACE</p>
      <h1>{setupRequired ? 'Create administrator account' : 'Sign in'}</h1>
      <p className="subhead">{setupRequired ? 'Set up the first administrator for this workspace.' : 'Sign in to access your organization documents.'}</p>
      {(error || message) && <div className={`notice ${error ? 'notice-error' : 'notice-success'}`} role="status">{error || message}</div>}
      <form className="auth-form" onSubmit={submitAuth}>
        <label>Email<input type="email" autoComplete="username" required maxLength={254} value={authForm.email} onChange={e => setAuthForm(old => ({ ...old, email: e.target.value }))} /></label>
        <label>Password<input type="password" autoComplete={setupRequired ? 'new-password' : 'current-password'} required minLength={12} maxLength={256} value={authForm.password} onChange={e => setAuthForm(old => ({ ...old, password: e.target.value }))} /></label>
        {setupRequired && <label>Workspace name<input required maxLength={160} value={authForm.tenant_name} onChange={e => setAuthForm(old => ({ ...old, tenant_name: e.target.value }))} /></label>}
        {setupRequired && bootstrapTokenRequired && <label>One-time bootstrap token<input type="password" autoComplete="off" required value={authForm.bootstrap_token} onChange={e => setAuthForm(old => ({ ...old, bootstrap_token: e.target.value }))} /></label>}
        <button className="primary-button" disabled={authBusy}>{authBusy ? 'Please wait…' : setupRequired ? 'Create workspace' : 'Sign in'}</button>
      </form>
      <small className="muted">Passwords must contain at least 12 characters.</small>
    </section>
  </main>

  return <main className="shell">
    <header className="topbar">
      <div><p className="eyebrow">DOCUMENT OPERATIONS</p><h1>Document Intelligence</h1><p className="subhead">Extract, validate, compare and review invoice data in one workspace.</p></div>
      <div className="account-actions"><span className="local-pill"><span className="dot"/> {DEMO_MODE ? 'Public demo · shared workspace' : `${authUser.email} · ${authUser.role}`}</span>{!DEMO_MODE && <button className="secondary-button" onClick={logout}>Sign out</button>}</div>
    </header>
    {DEMO_MODE && <div className="notice notice-demo" role="note">Public demo workspace: documents and changes are shared with all visitors. Please use sample files only; do not upload confidential or personal information.</div>}
    {(message || error) && <div className={`notice ${error ? 'notice-error' : 'notice-success'}`} role="status">{error || message}<button className="notice-close" onClick={() => { setError(''); setMessage('') }} aria-label="Dismiss message">×</button></div>}

    <section className="stats-grid">
      <div className="stat-card"><span>Documents matching filters</span><strong>{stats.total}</strong><small>Across all result pages</small></div>
      <div className="stat-card"><span>Completed</span><strong>{stats.completed}</strong><small>Ready for review</small></div>
      <div className="stat-card"><span>Queued / processing</span><strong>{stats.queued}</strong><small>Requires the worker process</small></div>
      <div className="stat-card"><span>Failed</span><strong>{stats.failed}</strong><small>Can be investigated and reprocessed</small></div>
    </section>

    <section className="upload-card panel">
      <div className="section-heading"><div><p className="eyebrow">INGESTION</p><h2>Upload documents</h2></div><span className="file-hint">PDF · JPG · PNG · TIFF · XLSX · XLS · CSV</span></div>
      <form onSubmit={upload} className="upload-form">
        <label className="file-picker"><input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv" onChange={e => setFiles(Array.from(e.target.files || []))}/><span className="upload-icon">↑</span><span><b>Select files to process</b><small>{files.length ? `${files.length} selected` : 'Multiple files supported · 50 MB maximum per file'}</small></span></label>
        <button className="primary-button" disabled={busy || !files.length}>{busy ? 'Uploading…' : 'Upload and process'}</button>
      </form>
      <p className="worker-note">Processing is handled by a separate local worker. Keep the worker terminal running while documents are being processed.</p>
    </section>

    <div className="workspace-grid">
      <section className="panel documents-panel">
        <div className="section-heading"><div><p className="eyebrow">LIBRARY</p><h2>Document library</h2></div><span className="count-pill">{stats.total}</span></div>
        <label className="search-box"><span>⌕</span><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search invoice, supplier, customer or extracted text" /></label>
        <div className="search-options"><label>Search mode <select value={searchMode} onChange={e => setSearchMode(e.target.value)}><option value="keyword">Keyword</option><option value="semantic">Semantic</option><option value="hybrid">Hybrid</option></select></label><small>Using: {searchModeUsed.replaceAll('_', ' ')}</small></div>
        <details className="search-filters">
          <summary>Advanced filters</summary>
          <div className="filter-grid">
            <label>Status<select value={stateFilter} onChange={e => setStateFilter(e.target.value)}><option value="">All statuses</option><option value="pending">Pending</option><option value="processing">Processing</option><option value="completed">Completed</option><option value="failed">Failed</option></select></label>
            <label>File type<select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}><option value="">All types</option>{['pdf','jpg','jpeg','png','tif','tiff','xlsx','xls','csv'].map(type => <option key={type} value={type}>{type.toUpperCase()}</option>)}</select></label>
            <label>Supplier<input value={supplierFilter} onChange={e => setSupplierFilter(e.target.value)} placeholder="Supplier name" /></label>
            <label>Invoice number<input value={invoiceFilter} onChange={e => setInvoiceFilter(e.target.value)} placeholder="Invoice number" /></label>
            <label>Invoice date from<input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} /></label>
            <label>Invoice date to<input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} /></label>
          </div>
          <button className="text-button" type="button" onClick={() => { setStateFilter(''); setTypeFilter(''); setSupplierFilter(''); setInvoiceFilter(''); setDateFrom(''); setDateTo('') }}>Clear filters</button>
        </details>
        <div className="document-list">
          {documents.length === 0 ? <div className="empty-state"><span>▤</span><b>No matching documents</b><small>Upload a supported file or change your search filters.</small></div> : documents.map(doc => <div key={doc.id} className="document-row-wrap">
            <button className={`document-row ${selected === doc.id ? 'selected' : ''}`} onClick={() => openDocument(doc.id)}>
              <span className="file-type">{doc.file_type.toUpperCase().slice(0,4)}</span><span className="doc-main"><b title={doc.original_filename}>{doc.original_filename}</b><small>{new Date(doc.created_at).toLocaleString()}</small></span><span className={`status status-${doc.status}`}>{doc.status}</span>
            </button>
            <button
              className="delete-document-button"
              type="button"
              title={['pending', 'processing'].includes(doc.status) ? 'Wait for processing to finish before deleting' : `Delete ${doc.original_filename}`}
              aria-label={`Delete ${doc.original_filename}`}
              disabled={deleteBusyId === doc.id || ['pending', 'processing'].includes(doc.status)}
              onClick={() => deleteDocument(doc.id, doc.original_filename)}
            >{deleteBusyId === doc.id ? 'Deleting…' : 'Delete'}</button>
          </div>)}
        </div>
        <div className="pagination-controls">
          <button className="secondary-button" type="button" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 50))}>Previous</button>
          <span>Showing {documents.length ? offset + 1 : 0}–{offset + documents.length}</span>
          <button className="secondary-button" type="button" disabled={!hasNext} onClick={() => setOffset(value => value + 50)}>Next</button>
        </div>
        <div className="compare-panel">
          <h3>Cross-document verification</h3>
          <p>Compare extracted invoice fields across PDFs, images, and spreadsheets to find mismatches.</p>

          <label className="compare-label" htmlFor="compare-documents">
  Completed documents (select 2 to 10)
</label>

<small className="muted">
  {comparisonDocumentsLoading
    ? 'Loading completed documents...'
    : `${comparisonDocuments.length} completed documents available`}
</small>

<select
  id="compare-documents"
  className="compare-select"
  multiple
  size={Math.min(5, Math.max(2, comparisonDocuments.length))}
  value={compareIds}
  disabled={comparisonDocumentsLoading}
  onChange={event => {
    setCompareIds(
      Array.from(event.target.selectedOptions, option => option.value)
    )
    setComparison(null)
  }}
>
  {comparisonDocuments.map(doc => (
    <option key={doc.id} value={doc.id}>
      {doc.original_filename}
    </option>
  ))}
</select>
          <button className="secondary-button compare-button" onClick={runComparison} disabled={comparing || compareIds.length < 2 || compareIds.length > 10}>{comparing ? 'Comparing…' : 'Compare selected documents'}</button>
          {comparison && <div className="comparison-result" role="status"><b>{comparison.matching ? 'No differences found in selected fields' : `${comparison.differences.length} difference(s) found`}</b><small>{comparison.documents.length} documents compared</small>{comparison.differences.map((difference, index) => <div className="comparison-difference" key={`${difference.field}-${index}`}><strong>{difference.field.replaceAll('_', ' ')}</strong><p>{difference.message}</p><pre>{JSON.stringify(difference.values, null, 2)}</pre></div>)}</div>}
        </div>
      </section>

      <section className="panel detail-panel">
        {!detail ? <div className="empty-detail"><div className="detail-symbol">✳</div><h2>Document review</h2><p>Select a document to inspect extracted fields, processing status and validation findings.</p></div> : <>
          <div className="section-heading"><div><p className="eyebrow">REVIEW WORKSPACE</p><h2>Invoice details</h2></div><div className="detail-actions"><button className="secondary-button" onClick={reprocess} disabled={!canReprocess}>{detail.status === 'pending' || detail.status === 'processing' ? 'Processing…' : 'Reprocess'}</button><button className="danger-button" type="button" onClick={() => deleteDocument(detail.id, detail.original_filename)} disabled={deleteBusyId === detail.id || ['pending', 'processing'].includes(detail.status)}>{deleteBusyId === detail.id ? 'Deleting…' : 'Delete document'}</button></div></div>
          <div className="selected-file"><span className="file-type large">{detail.file_type.toUpperCase().slice(0,4)}</span><div><b>{detail.original_filename}</b><small>{detail.page_count != null ? `${detail.page_count} page(s) / sheet(s)` : 'Page count unavailable'} · {detail.extraction_method || 'awaiting extraction'}</small></div></div>
          <div className={`queue-status status-${queueLabel}`}><strong>Processing: {queueLabel.replaceAll('_', ' ')}</strong>{queueStatus?.attempt_count ? <span>Attempt {queueStatus.attempt_count} of {queueStatus.max_attempts}</span> : null}{queueStatus?.last_error ? <p>{queueStatus.last_error}</p> : null}</div>
          {detail.status === 'failed' && <div className="validation-block error-block"><b>Processing failed</b><p>{detail.processing_error || 'Check the original file and retry.'}</p></div>}
          {detail.status === 'pending' && <p className="worker-note">The file is saved and queued. If it remains pending, confirm the worker terminal is running.</p>}
          <div className="field-grid">
            {[['invoice_number','Invoice number','text'],['invoice_date','Invoice date','text'],['supplier_name','Supplier','text'],['customer_name','Customer','text'],['subtotal','Subtotal','number'],['tax','Tax','number'],['total','Total','number'],['currency','Currency','text']].map(([key,label,type]) => <label className="field" key={key}><span>{label}</span><input type={type} step={type === 'number' ? '0.01' : undefined} value={edits[key] ?? ''} onChange={e => setEdits(old => ({...old,[key]:e.target.value}))} disabled={detail.status !== 'completed'} /></label>)}
          </div>
          <div className="validation-section"><div className="section-heading compact-heading"><h3>Line items</h3><button className="text-button" type="button" onClick={() => setLineItemEdits(items => [...items, {description:'',quantity:'',unit_price:'',amount:''}])} disabled={detail.status !== 'completed'}>+ Add line item</button></div>
            {lineItemEdits.length ? <div className="line-item-editor">{lineItemEdits.map((item, index) => <div className="line-edit-row" key={index}>
              <label><span>Description</span><input value={item.description} disabled={detail.status !== 'completed'} onChange={e => setLineItemEdits(items => items.map((old, i) => i === index ? {...old, description:e.target.value} : old))}/></label>
              <label><span>Quantity</span><input type="number" step="any" value={item.quantity} disabled={detail.status !== 'completed'} onChange={e => setLineItemEdits(items => items.map((old, i) => i === index ? {...old, quantity:e.target.value} : old))}/></label>
              <label><span>Unit price</span><input type="number" step="any" value={item.unit_price} disabled={detail.status !== 'completed'} onChange={e => setLineItemEdits(items => items.map((old, i) => i === index ? {...old, unit_price:e.target.value} : old))}/></label>
              <label><span>Amount</span><input type="number" step="any" value={item.amount} disabled={detail.status !== 'completed'} onChange={e => setLineItemEdits(items => items.map((old, i) => i === index ? {...old, amount:e.target.value} : old))}/></label>
              <button className="remove-item-button" type="button" aria-label={`Remove line item ${index + 1}`} onClick={() => setLineItemEdits(items => items.filter((_, i) => i !== index))} disabled={detail.status !== 'completed'}>Remove</button>
            </div>)}</div> : <p className="muted">No line items confidently extracted. Add them after checking the source document.</p>}
          </div>
          <button className="primary-button save-button" onClick={saveCorrections} disabled={detail.status !== 'completed' || saving}>{saving ? 'Saving…' : 'Save corrections'}</button>
          <div className="validation-section"><h3>Validation findings</h3>{!(detail.validation_errors?.length || detail.validation_warnings?.length) ? <p className="clean-state">No validation findings recorded.</p> : <div className="finding-list">{[...(detail.validation_errors || []).map(x=>({...x, severity:'error'})), ...(detail.validation_warnings || []).map(x=>({...x,severity:'warning'}))].map((finding,i)=><div className={`finding finding-${finding.severity}`} key={`${finding.code}-${i}`}><b>{finding.severity === 'error' ? 'Error' : 'Review'} · {finding.field || finding.code}</b><p>{finding.message}</p></div>)}</div>}</div>
          <div className="validation-section"><h3>Source evidence</h3>{detail.field_evidence && Object.values(detail.field_evidence).some(value => (typeof value === 'string' && value.length > 0) || (Array.isArray(value) && value.length > 0)) ? <div className="evidence-list">{Object.entries(detail.field_evidence).map(([field,value]) => <div className={`evidence-item ${value ? '' : 'evidence-missing'}`} key={field}><b>{field.replaceAll('_',' ')}</b>{Array.isArray(value) ? (value.length ? value.map((snippet,index)=><p key={index}>{snippet}</p>) : <p>No direct line-item source snippet found.</p>) : <p>{value || 'No direct matching source line found. Verify against the original document.'}</p>}</div>)}</div> : <p className="muted">No direct source-text evidence was recorded.</p>}</div>
          <details className="source-text"><summary>View extracted source text</summary><pre>{detail.extracted_text || 'No text stored.'}</pre></details>
          <details className="source-text">
  <summary>Processing history ({history.length})</summary>

  {history.length ? (
    <div className="history-list">
      {history.map((event, index) => {
        const changes = getHistoryChanges(event)

        return (
          <div
            className="history-event"
            key={`${event.event_type}-${index}`}
          >
            <b>{event.event_type.replaceAll('_', ' ')}</b>
            <small>{new Date(event.created_at).toLocaleString()}</small>
            <p>{event.message}</p>

            {event.details?.corrected_by && (
              <small>
                Reviewer: {event.details.corrected_by}
              </small>
            )}

            {changes.length > 0 && (
              <div className="history-changes">
                <b>Changed values</b>

                {changes.map(change => (
                  <div className="history-change" key={change.field}>
                    <strong>{change.field.replaceAll('_', ' ')}</strong>

                    <div className="history-value-pair">
                      <div>
                        <small>Before</small>
                        <pre>{formatHistoryValue(change.before)}</pre>
                      </div>

                      <div>
                        <small>After</small>
                        <pre>{formatHistoryValue(change.after)}</pre>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  ) : (
    <p className="muted">No processing events found.</p>
  )}
</details>
        </>}
      </section>
    </div>
    <footer><span>AI-Powered Document Intelligence System</span><span>Extraction results require human review for financial decisions.</span></footer>
  </main>
}
