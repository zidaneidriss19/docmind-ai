import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, CSSProperties } from 'react'
import { Database, FileText, FolderOpen, Layers3, LogOut, MessageSquare, MessagesSquare, PanelLeftClose, PanelLeftOpen, Plus, SquarePen } from 'lucide-react'
import type { Profile } from './auth'
import ChatThread from './ChatThread'
import { getConversation, listConversations, removeConversation } from './chatApi'
import type { Citation, Conversation } from './chatApi'
import { chatError } from './chatErrors'
import DocumentPicker from './DocumentPicker'
import Documents from './Documents'
import { fileSize, uploadDocument } from './documentApi'
import Modal from './Modal'
import './Workspace.css'

const PdfPreview = lazy(() => import('./PdfPreview'))

type Section = 'chat' | 'documents'
type Dialog = 'create' | 'sources' | 'delete' | null

export default function Workspace({ profile, onSignOut, signOutBusy, onSessionExpired, accountError }: {
  profile: Profile
  onSignOut: () => void
  signOutBusy: boolean
  onSessionExpired: () => void
  accountError: string
}) {
  const [section, setSection] = useState<Section>('chat')
  const [items, setItems] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [current, setCurrent] = useState<Conversation | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [next, setNext] = useState<number | null>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [documentVersion, setDocumentVersion] = useState(0)
  const [library, setLibrary] = useState<{ count: number; bytes: number } | null>(null)
  const [mobileView, setMobileView] = useState<'chat' | 'pdf'>('chat')
  const [selection, setSelection] = useState<{
    conversation: string; documentId: string; jump: { page: number }; citations: Citation[]
  } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const grid = useRef<HTMLDivElement>(null)
  const [pdfOpen, setPdfOpen] = useState(true)
  const [chatShare, setChatShare] = useState(30.5)

  useEffect(() => {
    let active = true
    listConversations().then(
      (page) => {
        if (!active) return
        setItems((previous) => [...new Map([...previous, ...page.items].map((item) => [item.id, item])).values()])
        setNext(page.next_offset)
        setSelectedId((id) => id ?? page.items[0]?.id ?? null)
        setListLoading(false)
      },
      (reason: unknown) => {
        if (!active) return
        setError(chatError(reason, onSessionExpired))
        setListLoading(false)
      },
    )
    return () => { active = false }
  }, [onSessionExpired])

  useEffect(() => {
    if (!selectedId || section !== 'chat') return
    let active = true
    getConversation(selectedId).then(
      (result) => { if (active) setCurrent(result) },
      (reason: unknown) => { if (active) setError(chatError(reason, onSessionExpired)) },
    )
    return () => { active = false }
  }, [selectedId, section, onSessionExpired])

  const active = current?.id === selectedId ? current : items.find((item) => item.id === selectedId)

  async function moreConversations() {
    if (next === null) return
    setListLoading(true)
    setError('')
    try {
      const page = await listConversations(next)
      setItems((previous) => [...new Map([...previous, ...page.items].map((item) => [item.id, item])).values()])
      setNext(page.next_offset)
    } catch (reason) {
      setError(chatError(reason, onSessionExpired))
    } finally {
      setListLoading(false)
    }
  }

  function saved(conversation: Conversation) {
    setItems((previous) => previous.some((item) => item.id === conversation.id)
      ? previous.map((item) => item.id === conversation.id ? conversation : item)
      : [conversation, ...previous])
    if (dialog === 'create') setNext((offset) => offset === null ? null : offset + 1)
    setSelectedId(conversation.id)
    setCurrent(conversation)
    setSelection(null)
    setMobileView('chat')
    setSection('chat')
    setDialog(null)
    setError('')
  }

  async function confirmDelete() {
    if (!active) return
    setDeleting(true)
    setError('')
    try {
      await removeConversation(active.id)
      const remaining = items.filter((item) => item.id !== active.id)
      setItems(remaining)
      setNext((offset) => offset === null ? null : Math.max(0, offset - 1))
      setCurrent(null)
      setSelectedId(remaining[0]?.id ?? null)
      setDialog(null)
    } catch (reason) {
      setError(chatError(reason, onSessionExpired))
    } finally {
      setDeleting(false)
    }
  }

  const defaultJump = useMemo(() => ({ page: 1 }), [])
  const selected = active && selection?.conversation === active.id ? selection : null
  const documentId = selected?.documentId ?? active?.document_ids[0]

  const showCitations = useCallback((citations: Citation[], focused?: Citation) => {
    if (!selectedId) return
    const source = focused ?? citations[0]
    if (!source) {
      setSelection((previous) => previous?.conversation === selectedId
        ? { ...previous, citations: [] } : previous)
      return
    }
    setSelection({ conversation: selectedId, documentId: source.document_id, jump: { page: source.page_number }, citations })
    if (focused) {
      setPdfOpen(true)
      setMobileView('pdf')
    }
  }, [selectedId])

  function openDocument(id: string) {
    if (!active) return
    setSelection((previous) => ({
      conversation: active.id, documentId: id, jump: { page: 1 },
      citations: previous?.conversation === active.id ? previous.citations : [],
    }))
    setPdfOpen(true)
    setMobileView('pdf')
  }

  function resize(next: number) {
    setChatShare(Math.min(48, Math.max(20, next)))
  }

  function resizeFromPointer(x: number) {
    const frame = grid.current?.getBoundingClientRect()
    if (frame?.width) resize(100 * (frame.right - x) / frame.width)
  }

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ''
    if (!file) return
    setUploading(true)
    setError('')
    try {
      await uploadDocument(file)
      setSection('documents')
      setDocumentVersion((version) => version + 1)
    } catch (reason) {
      setError(chatError(reason, onSessionExpired))
    } finally {
      setUploading(false)
    }
  }

  return (
    <main className="workspace" data-mobile-view={mobileView}>
      <header className="workspace-header">
        <div className="brand"><span className="brand-mark" aria-hidden="true">D</span>DocMind AI</div>
        <nav className="workspace-nav" aria-label="Espace DocMind">
          <button type="button" aria-current={section === 'chat' ? 'page' : undefined} onClick={() => { setSection('chat'); setError('') }}>
            <MessagesSquare aria-hidden="true" /> Conversations
          </button>
          <button type="button" aria-current={section === 'documents' ? 'page' : undefined} onClick={() => { setSection('documents'); setError('') }}>
            <Layers3 aria-hidden="true" /> Documents
          </button>
        </nav>
        <div className="workspace-account">
          <span className="account-avatar" title={profile.email} aria-label={profile.email}>{profile.email[0]?.toUpperCase()}</span>
          <button className="account-logout" type="button" disabled={signOutBusy} aria-label="Se déconnecter" title="Se déconnecter" onClick={onSignOut}><LogOut /></button>
        </div>
      </header>
      {(accountError || (error && dialog !== 'delete')) && <p className="workspace-error error" role="alert">{accountError || error}</p>}
      <div ref={grid} style={{ '--chat-width': chatShare + '%' } as CSSProperties}
        className={`workspace-grid ${section === 'documents' ? 'library-layout' : !pdfOpen ? 'reader-collapsed' : ''}`}>
        <aside className="chat-sidebar" aria-label="Navigation et historique">
          <input ref={fileInput} type="file" hidden accept=".pdf,application/pdf" onChange={importFile} />
          <button className="sidebar-new" type="button" disabled={uploading} onClick={() => fileInput.current?.click()}>
            <Plus aria-hidden="true" />{uploading ? 'Import en cours…' : 'Importer un PDF'}
          </button>
          <nav className="sidebar-navigation" aria-label="Bibliothèque">
            <button type="button" aria-current={section === 'documents' ? 'page' : undefined} onClick={() => { setSection('documents'); setError('') }}>
              <FolderOpen aria-hidden="true" /> Mes documents
              {library && <span className="sidebar-count">{library.count}</span>}
            </button>
            <button type="button" aria-current={section === 'chat' ? 'page' : undefined} onClick={() => { setSection('chat'); setError('') }}>
              <MessagesSquare aria-hidden="true" /> Conversations
              {!listLoading && next === null && <span className="sidebar-count">{items.length}</span>}
            </button>
          </nav>
          <div className="sidebar-heading"><h2>Conversations récentes</h2>
            <button className="sidebar-action" type="button" aria-label="Nouvelle conversation" title="Nouvelle conversation" onClick={() => setDialog('create')}><SquarePen /></button>
          </div>
          {!listLoading && !items.length && <p>Aucune conversation.</p>}
          <ul>
            {items.map((conversation) => (
              <li key={conversation.id}>
                <button type="button" aria-current={section === 'chat' && selectedId === conversation.id ? 'true' : undefined}
                  onClick={() => { setSelectedId(conversation.id); setSection('chat'); setMobileView('chat'); setError('') }}>
                  <MessageSquare aria-hidden="true" /><span>{conversation.title}</span>
                </button>
              </li>
            ))}
          </ul>
          {listLoading && <p role="status">Chargement…</p>}
          {next !== null && <button className="sidebar-more" type="button" onClick={moreConversations}
            disabled={listLoading}>Afficher plus</button>}
          {library && <div className="sidebar-storage"><Database aria-hidden="true" /><strong>Stockage</strong><span>{fileSize(library.bytes)}</span></div>}
        </aside>
        {section === 'documents' ? (
          <div className="documents-workspace"><Documents key={documentVersion} onSessionExpired={onSessionExpired} onSummary={setLibrary} /></div>
        ) : active ? (
          <>
            <div className="document-column">
              <div className="document-heading">
                <div>
                  <h1>{active.title}</h1>
                  <p>{active.document_ids.length} {active.document_ids.length === 1 ? 'document' : 'documents'}</p>
                </div>
                <button type="button" className="secondary reader-hide" aria-label="Masquer le PDF"
                  title="Masquer le PDF" aria-expanded={pdfOpen} onClick={() => setPdfOpen(false)}>
                  <PanelLeftClose aria-hidden="true" />
                </button>
              </div>
              {documentId ? (
                <Suspense fallback={<p className="reader-loading" role="status">Chargement du lecteur…</p>}>
                  <PdfPreview key={documentId} documentId={documentId} jump={selected?.jump ?? defaultJump} citations={selected?.citations} onSessionExpired={onSessionExpired} />
                </Suspense>
              ) : <div className="workspace-empty"><p>Ajoute un PDF prêt dans Sources.</p></div>}
            </div>
            <div className="reader-resize" role="separator" tabIndex={0} aria-label="Largeur du panneau PDF"
              aria-orientation="vertical" aria-valuemin={52} aria-valuemax={80} aria-valuenow={Math.round(100 - chatShare)}
              onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); resizeFromPointer(event.clientX) }}
              onPointerMove={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) resizeFromPointer(event.clientX) }}
              onKeyDown={(event) => {
                if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
                event.preventDefault()
                resize(chatShare + (event.key === 'ArrowLeft' ? 2 : -2))
              }} />
            <div className="chat-main">
              {!pdfOpen && (
                <div className="reader-toggle">
                  <button type="button" className="secondary" aria-expanded={false} onClick={() => setPdfOpen(true)}>
                    <PanelLeftOpen aria-hidden="true" /> Afficher le PDF
                  </button>
                </div>
              )}
              <ChatThread key={active.id} conversation={active} onSources={() => setDialog('sources')}
                onRemove={() => { setError(''); setDialog('delete') }} onSessionExpired={onSessionExpired}
                onCitations={showCitations} onDocument={openDocument} />
            </div>
            <div className="mobile-reader-nav">
              <button type="button" aria-pressed={mobileView === 'pdf'} onClick={() => setMobileView('pdf')}><FileText /> PDF</button>
              <button type="button" aria-pressed={mobileView === 'chat'} onClick={() => setMobileView('chat')}><MessagesSquare /> Chat</button>
            </div>
          </>
        ) : !listLoading && (
          <section className="workspace-empty wide-empty" aria-labelledby="empty-title">
            <h1 id="empty-title">Interroge tes PDF</h1>
            <p>Choisis des documents indexés, puis pose une question.</p>
            <button className="workspace-primary" type="button" onClick={() => setDialog('create')}>Créer une conversation</button>
          </section>
        )}
      </div>

      {(dialog === 'create' || (dialog === 'sources' && active)) && (
        <DocumentPicker conversation={dialog === 'sources' ? active ?? null : null}
          onSaved={saved} onClose={() => setDialog(null)} onSessionExpired={onSessionExpired} />
      )}
      {dialog === 'delete' && active && (
        <Modal title="Supprimer la conversation ?" onClose={() => { if (!deleting) setDialog(null) }}>
          <p>« {active.title} » et ses messages seront supprimés.</p>
          {error && <p className="error" role="alert">{error}</p>}
          <footer className="dialog-actions">
            <button className="secondary" type="button" disabled={deleting} onClick={() => setDialog(null)}>Annuler</button>
            <button className="workspace-primary danger-solid" type="button" disabled={deleting} onClick={confirmDelete}>
              {deleting ? 'Suppression…' : 'Supprimer la conversation'}
            </button>
          </footer>
        </Modal>
      )}
    </main>
  )
}
