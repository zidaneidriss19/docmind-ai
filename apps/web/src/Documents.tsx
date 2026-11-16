import { useEffect, useRef, useState } from 'react'
import { Check, Database, EllipsisVertical, File, FileText, FolderOpen, LayoutGrid, List, RefreshCw, Search, TriangleAlert } from 'lucide-react'
import { ApiError } from './auth'
import {
  deleteDocument, downloadDocument, fileSize, listDocuments, retryDocument,
} from './documentApi'
import type { DocumentStatus, DocumentSummary } from './documentApi'
import Modal from './Modal'
import './Documents.css'

const statusLabels: Record<DocumentStatus, string> = {
  UPLOADED: 'En attente d’indexation',
  PROCESSING: 'Indexation en cours',
  READY: 'Prêt',
  FAILED: 'Échec de l’indexation',
}

const processingErrors: Record<string, string> = {
  NO_EXTRACTABLE_TEXT: 'Ce PDF ne contient pas de texte extractible.',
  PDF_PAGE_LIMIT: 'Ce PDF dépasse la limite de 500 pages.',
  PDF_TEXT_LIMIT: 'Ce PDF contient trop de texte à indexer.',
  INVALID_PDF: 'Le PDF est illisible.',
  PDF_INTEGRITY_ERROR: 'Le fichier stocké ne correspond plus au PDF importé.',
  ENCRYPTED_PDF: 'Ce PDF est protégé par un mot de passe.',
  WORKER_INTERRUPTED: 'L’indexation a été interrompue. Tu peux la relancer.',
}

const date = new Intl.DateTimeFormat('fr', { dateStyle: 'medium' })

function documentError(reason: unknown) {
  if (reason instanceof ApiError) {
    switch (reason.code) {
      case 'PDF_TOO_LARGE':
        return 'Le PDF dépasse la limite de 20 Mio.'
      case 'ENCRYPTED_PDF':
        return 'Choisis un PDF sans mot de passe.'
      case 'INVALID_PDF':
      case 'INVALID_FILENAME':
        return 'Le fichier choisi doit être un PDF valide.'
      case 'DOCUMENT_NOT_FOUND':
        return 'Le document n’est plus disponible. Actualise la liste.'
      case 'DOCUMENT_NOT_FAILED':
        return 'L’état du document a changé. Actualise la liste.'
    }
  }
  return 'L’opération a échoué. Réessaie dans un instant.'
}

export default function Documents({ onSessionExpired, onSummary }: {
  onSessionExpired: () => void
  onSummary: (total: { count: number; bytes: number }) => void
}) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [version, setVersion] = useState(0)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [sort, setSort] = useState('newest')
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const [visible, setVisible] = useState(24)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [removing, setRemoving] = useState<DocumentSummary | null>(null)
  const search = useRef<HTMLInputElement>(null)
  const pending = (document: DocumentSummary) => document.status === 'PROCESSING' || document.status === 'UPLOADED'

  useEffect(() => {
    const focus = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        search.current?.focus()
      }
    }
    window.addEventListener('keydown', focus)
    return () => window.removeEventListener('keydown', focus)
  }, [])

  useEffect(() => {
    let active = true
    let timer: number | undefined
    async function load() {
      try {
        const all = new Map<string, DocumentSummary>()
        let offset: number | null = 0
        while (offset !== null && active) {
          const page = await listDocuments(offset, 100)
          page.items.forEach((document) => all.set(document.id, document))
          offset = page.next_offset
        }
        if (!active) return
        const result = [...all.values()]
        setDocuments(result)
        onSummary({ count: result.length, bytes: result.reduce((total, document) => total + document.size_bytes, 0) })
        if (result.some((item) => item.status === 'UPLOADED' || item.status === 'PROCESSING')) {
          timer = window.setTimeout(() => setVersion((value) => value + 1), 3000)
        }
      } catch (reason) {
        if (!active) return
        if (reason instanceof ApiError && reason.status === 401) onSessionExpired()
        else setError(documentError(reason))
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => { active = false; window.clearTimeout(timer) }
  }, [version, onSessionExpired, onSummary])

  async function perform(action: () => Promise<void>) {
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await action()
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onSessionExpired()
      else setError(documentError(reason))
    } finally {
      setBusy(false)
    }
  }

  const stats = [
    { label: 'Total des documents', count: documents.length, icon: File, color: 'total' },
    { label: 'Prêts', count: documents.filter((item) => item.status === 'READY').length, icon: Check, color: 'ready' },
    { label: 'En cours', count: documents.filter(pending).length, icon: RefreshCw, color: 'pending' },
    { label: 'En échec', count: documents.filter((item) => item.status === 'FAILED').length, icon: TriangleAlert, color: 'failed' },
  ]
  const filtered = documents.filter((document) =>
    document.filename.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) &&
    (status === 'all' || (status === 'pending' ? pending(document) : document.status === status))
  ).sort((first, second) => {
    if (sort === 'name') return first.filename.localeCompare(second.filename, 'fr')
    if (sort === 'oldest') return Date.parse(first.created_at) - Date.parse(second.created_at)
    return Date.parse(second.created_at) - Date.parse(first.created_at)
  })

  return (
    <section className="document-area" aria-labelledby="documents-title">
      <header className="library-heading">
        <h1 id="documents-title"><FolderOpen aria-hidden="true" /> Mes documents{loading ? '' : ` (${documents.length})`}</h1>
        <p>Gère tes PDF, suis leur indexation et retrouve les documents à interroger.</p>
      </header>
      <div className="library-tools">
        <label className="library-search">
          <Search aria-hidden="true" />
          <input ref={search} type="search" aria-label="Rechercher des documents" placeholder="Rechercher des documents…"
            value={query} onChange={(event) => { setQuery(event.target.value); setVisible(24) }} />
          <kbd>Ctrl + K</kbd>
        </label>
        <select aria-label="Filtrer par statut" value={status} onChange={(event) => { setStatus(event.target.value); setVisible(24) }}>
          <option value="all">Tous les statuts</option><option value="READY">Prêts</option>
          <option value="pending">En cours</option><option value="FAILED">En échec</option>
        </select>
        <select aria-label="Trier les documents" value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="newest">Plus récents</option><option value="oldest">Plus anciens</option><option value="name">Nom du fichier</option>
        </select>
        <div className="library-view" aria-label="Mode d’affichage">
          <button type="button" aria-label="Afficher en grille" aria-pressed={view === 'grid'} onClick={() => setView('grid')}><LayoutGrid /></button>
          <button type="button" aria-label="Afficher en liste" aria-pressed={view === 'list'} onClick={() => setView('list')}><List /></button>
        </div>
      </div>
      <div className="library-stats">
        {stats.map(({ label, count, icon: Icon, color }) => (
          <div className="library-stat" key={label}>
            <span className={`stat-icon ${color}`}><Icon aria-hidden="true" /></span>
            <div><strong>{loading ? '–' : count}</strong><span>{label}</span></div>
          </div>
        ))}
      </div>
      {error && !removing && <p className="error" role="alert">{error} <button className="secondary" type="button"
        onClick={() => { setError(''); setVersion((value) => value + 1) }}>Actualiser</button></p>}
      {notice && <p role="status" className="library-notice">{notice}</p>}
      {loading && <p role="status">Chargement des documents…</p>}
      {!loading && !filtered.length && <p>{documents.length ? 'Aucun PDF ne correspond à ces filtres.' : 'Aucun document importé. Utilise « Importer un PDF » pour commencer.'}</p>}
      <ul className={`library-files ${view}`} aria-busy={busy || loading}>
        {filtered.slice(0, visible).map((document) => (
          <li className="library-file" key={document.id}>
            <div className="library-file-top">
              <span className="file-icon" aria-hidden="true"><FileText />PDF</span>
              <div className="library-file-info">
                <strong title={document.filename}>{document.filename}</strong>
                <span><FileText aria-hidden="true" />{document.page_count === null ? 'Pages en attente' : `${document.page_count} page${document.page_count === 1 ? '' : 's'}`}</span>
                <span><Database aria-hidden="true" />{fileSize(document.size_bytes)}</span>
              </div>
              <details className="library-file-menu">
                <summary aria-label={`Actions pour ${document.filename}`}><EllipsisVertical aria-hidden="true" /></summary>
                <div>
                  <button type="button" disabled={busy} onClick={() => void perform(() => downloadDocument(document))}>Télécharger</button>
                  {document.status === 'FAILED' && <button type="button" disabled={busy} onClick={() => void perform(async () => {
                    await retryDocument(document.id)
                    setVersion((value) => value + 1)
                  })}>Relancer</button>}
                  <button type="button" className="danger" disabled={busy} onClick={() => setRemoving(document)}>Supprimer</button>
                </div>
              </details>
            </div>
            <div className="library-file-bottom">
              <span className={`file-status ${document.status.toLowerCase()}`}>
                {document.status === 'READY' ? <Check /> : document.status === 'FAILED' ? <TriangleAlert /> : <RefreshCw />}
                {statusLabels[document.status]}
              </span>
              {pending(document) ? <span className="indexing-track" aria-hidden="true" />
                : <time dateTime={document.created_at}>{date.format(new Date(document.created_at))}</time>}
            </div>
            {document.status === 'FAILED' && document.processing_error && (
              <small className="file-error">{processingErrors[document.processing_error] ?? 'Tu peux relancer l’indexation.'}</small>
            )}
          </li>
        ))}
      </ul>
      {filtered.length > visible && <button className="secondary library-more" type="button" onClick={() => setVisible(visible + 24)}>Afficher plus de PDF</button>}
      {removing && (
        <Modal title="Supprimer ce PDF ?" onClose={() => setRemoving(null)}>
          <p>{removing.filename}</p>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="dialog-actions">
            <button className="secondary" type="button" onClick={() => setRemoving(null)}>Annuler</button>
            <button className="workspace-primary danger-solid" type="button" disabled={busy} onClick={() => void perform(async () => {
              await deleteDocument(removing.id)
              setRemoving(null)
              setNotice(`${removing.filename} a été supprimé.`)
              setVersion((value) => value + 1)
            })}>Confirmer</button>
          </div>
        </Modal>
      )}
    </section>
  )
}
