import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from './auth'
import {
  PAGE_SIZE, deleteDocument, downloadDocument, listDocuments, retryDocument, uploadDocument,
} from './documentApi'
import type { DocumentStatus, DocumentSummary } from './documentApi'
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

const number = new Intl.NumberFormat('fr', { maximumFractionDigits: 1 })
const date = new Intl.DateTimeFormat('fr', { dateStyle: 'medium' })
const maxBytes = 20 * 1024 * 1024

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${number.format(bytes / 1024)} Kio`
  return `${number.format(bytes / (1024 * 1024))} Mio`
}

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

export default function Documents({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [page, setPage] = useState<Awaited<ReturnType<typeof listDocuments>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [removing, setRemoving] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let current = true
    let poll: number | undefined
    listDocuments(offset).then(
      (result) => {
        if (!current) return
        setPage(result)
        setLoading(false)
        if (result.items.some(({ status }) => status === 'UPLOADED' || status === 'PROCESSING')) {
          poll = window.setTimeout(() => setReload((value) => value + 1), 3000)
        }
      },
      (reason: unknown) => {
        if (!current) return
        if (reason instanceof ApiError && reason.status === 401) onSessionExpired()
        else setError(documentError(reason))
        setLoading(false)
      },
    )
    return () => {
      current = false
      window.clearTimeout(poll)
    }
  }, [offset, reload, onSessionExpired])

  function load(newOffset = offset) {
    setLoading(true)
    setOffset(newOffset)
    setReload((value) => value + 1)
  }

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

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const file = input.current?.files?.[0]
    if (!file) return
    if (file.size > maxBytes) {
      setError('Le PDF dépasse la limite de 20 Mio.')
      return
    }
    void perform(async () => {
      const document = await uploadDocument(file)
      if (input.current) input.current.value = ''
      setNotice(`${document.filename} a été importé.`)
      load(0)
    })
  }

  function remove(document: DocumentSummary) {
    void perform(async () => {
      await deleteDocument(document.id)
      setRemoving(null)
      setNotice(`${document.filename} a été retiré de tes documents.`)
      load(offset > 0 && page?.items.length === 1 ? offset - PAGE_SIZE : offset)
    })
  }

  return (
    <section className="document-area" aria-labelledby="documents-title">
      <h2 id="documents-title">Mes documents</h2>
      <form className="upload-form" onSubmit={upload}>
        <div className="field">
          <label htmlFor="document-file">Fichier PDF</label>
          <input id="document-file" type="file" ref={input} accept=".pdf,application/pdf"
            required disabled={busy} aria-describedby="file-hint" />
          <small id="file-hint">20 Mio maximum. Le fichier doit être sans mot de passe.</small>
        </div>
        <button className="primary" disabled={busy}>Importer</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="document-notice" role="status">{notice}</p>}
      <div className="list-heading">
        <h3>Fichiers importés</h3>
        <button className="secondary" type="button" disabled={busy || loading} onClick={() => {
          setError('')
          load()
        }}>Actualiser</button>
      </div>
      <div aria-busy={loading || busy}>
        {loading && <p role="status">Chargement des documents…</p>}
        {!loading && page?.items.length === 0 && <p>Aucun document importé.</p>}
        <ul className="document-list">
          {page?.items.map((document) => (
            <li key={document.id} className="document-item">
              <div className="document-info">
                <strong>{document.filename}</strong>
                <span>{fileSize(document.size_bytes)} · {date.format(new Date(document.created_at))}</span>
                <span className="document-status" aria-live="polite">
                  {statusLabels[document.status]}
                  {document.page_count !== null && ' · ' + document.page_count + (document.page_count === 1 ? ' page' : ' pages')}
                </span>
                {document.status === 'FAILED' && document.processing_error && (
                  <span>{processingErrors[document.processing_error] ?? 'Le service est indisponible. Tu peux relancer l’indexation.'}</span>
                )}
              </div>
              {removing === document.id ? (
                <div className="document-actions" role="group" aria-label={`Supprimer ${document.filename}`}>
                  <span>Supprimer ce PDF ?</span>
                  <button className="secondary danger" type="button" disabled={busy || loading}
                    onClick={() => remove(document)}>Confirmer</button>
                  <button className="secondary" type="button" disabled={busy}
                    onClick={() => setRemoving(null)}>Annuler</button>
                </div>
              ) : (
                <div className="document-actions">
                  <button className="secondary" type="button" disabled={busy || loading}
                    aria-label={`Télécharger ${document.filename}`}
                    onClick={() => void perform(() => downloadDocument(document))}>Télécharger</button>
                  {document.status === 'FAILED' && <button className="secondary" type="button"
                    disabled={busy || loading} onClick={() => void perform(async () => {
                      await retryDocument(document.id)
                      load()
                    })}>Relancer</button>}
                  <button className="secondary danger" type="button" disabled={busy || loading}
                    aria-label={`Supprimer ${document.filename}`}
                    onClick={() => setRemoving(document.id)}>Supprimer</button>
                </div>
              )}
            </li>
          ))}
        </ul>
        {(offset > 0 || page?.next_offset != null) && (
          <nav className="document-actions" aria-label="Pages des documents">
            <button type="button" className="secondary" disabled={offset === 0 || loading || busy}
              onClick={() => load(Math.max(0, offset - PAGE_SIZE))}>Précédent</button>
            <button type="button" className="secondary" disabled={page?.next_offset == null || loading || busy}
              onClick={() => { if (page?.next_offset != null) load(page.next_offset) }}>Suivant</button>
          </nav>
        )}
      </div>
    </section>
  )
}
