import { useEffect, useState } from 'react'
import type { Profile } from './auth'
import ChatThread from './ChatThread'
import { getConversation, listConversations, removeConversation } from './chatApi'
import type { Conversation } from './chatApi'
import { chatError } from './chatErrors'
import DocumentPicker from './DocumentPicker'
import Documents from './Documents'
import Modal from './Modal'
import './Workspace.css'

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

  return (
    <main className="workspace">
      <header className="workspace-header">
        <div className="brand"><span className="brand-mark" aria-hidden="true">D</span>DocMind AI</div>
        <nav className="workspace-nav" aria-label="Espace DocMind">
          <button type="button" aria-current={section === 'chat' ? 'page' : undefined}
            onClick={() => setSection('chat')}>Conversations</button>
          <button type="button" aria-current={section === 'documents' ? 'page' : undefined}
            onClick={() => setSection('documents')}>Documents</button>
        </nav>
        <div className="workspace-account">
          <span title={profile.email}>{profile.email}</span>
          <button className="secondary" type="button" disabled={signOutBusy} onClick={onSignOut}>Se déconnecter</button>
        </div>
      </header>
      {accountError && <p className="error" role="alert">{accountError}</p>}
      {section === 'documents' ? (
        <div className="documents-workspace">
          <Documents onSessionExpired={onSessionExpired} />
        </div>
      ) : (
        <div className="workspace-grid">
          <aside className="chat-sidebar" aria-label="Liste des conversations">
            <button className="sidebar-new" type="button" onClick={() => setDialog('create')}>
              <span aria-hidden="true">+</span> Nouvelle conversation
            </button>
            <h2>Historique</h2>
            {!listLoading && !items.length && <p>Aucune conversation.</p>}
            <ul>
              {items.map((conversation) => (
                <li key={conversation.id}>
                  <button type="button" aria-current={selectedId === conversation.id ? 'true' : undefined}
                    onClick={() => { setSelectedId(conversation.id); setError('') }}>
                    {conversation.title}
                  </button>
                </li>
              ))}
            </ul>
            {listLoading && <p role="status">Chargement…</p>}
            {next !== null && <button className="sidebar-more" type="button" onClick={moreConversations}
              disabled={listLoading}>Afficher plus</button>}
          </aside>
          <div className="chat-main">
            {error && dialog !== 'delete' && <p className="error" role="alert">{error}</p>}
            {active ? (
              <ChatThread key={active.id} conversation={active} onSources={() => setDialog('sources')}
                onRemove={() => { setError(''); setDialog('delete') }} onSessionExpired={onSessionExpired} />
            ) : !listLoading && (
              <section className="workspace-empty" aria-labelledby="empty-title">
                <h1 id="empty-title">Interroge tes PDF</h1>
                <p>Choisis des documents indexés, puis pose une question. Tu pourras ouvrir chaque source à la page citée.</p>
                <button className="workspace-primary" type="button" onClick={() => setDialog('create')}>Créer une conversation</button>
              </section>
            )}
          </div>
        </div>
      )}
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
