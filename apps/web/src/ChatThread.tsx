import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, FileText, Layers3, MessagesSquare, Send, Sparkles, Trash2, UserRound } from 'lucide-react'
import type { FormEvent, KeyboardEvent } from 'react'
import { askQuestion, listMessages } from './chatApi'
import type { Citation, Conversation, Message } from './chatApi'
import { chatError } from './chatErrors'
import { getDocument } from './documentApi'
import type { DocumentSummary } from './documentApi'


export default function ChatThread({ conversation, onSources, onRemove, onSessionExpired, onCitation, onDocument }: {
  conversation: Conversation
  onSources: () => void
  onRemove: () => void
  onCitation: (source: Citation) => void
  onDocument: (id: string) => void
  onSessionExpired: () => void
}) {
  const [messages, setMessages] = useState<Message[]>([])
  const [next, setNext] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'chat' | 'sources'>('chat')
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [loadingSources, setLoadingSources] = useState(false)
  const timeline = useRef<HTMLDivElement>(null)
  const jumpToLatest = useRef(true)
  const conversationId = conversation.id
  const numDocuments = conversation.document_ids.length

  useEffect(() => {
    let active = true
    listMessages(conversationId).then(
      (page) => {
        if (!active) return
        jumpToLatest.current = true
        setMessages([...page.items].reverse())
        setNext(page.next_offset)
        setLoading(false)
      },
      (reason: unknown) => {
        if (!active) return
        setError(chatError(reason, onSessionExpired))
        setLoading(false)
      },
    )
    return () => { active = false }
  }, [conversationId, onSessionExpired])

  useEffect(() => {
    if (!jumpToLatest.current || !timeline.current) return
    timeline.current.scrollTop = timeline.current.scrollHeight
    jumpToLatest.current = false
  }, [messages, pending])

  useEffect(() => {
    if (tab !== 'sources') return
    let active = true
    void Promise.allSettled(conversation.document_ids.map(getDocument)).then((results) => {
      if (!active) return
      setDocuments(results.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []))
      setLoadingSources(false)
    })
    return () => { active = false }
  }, [tab, conversation.document_ids])

  async function older() {
    if (next === null) return
    setLoadingOlder(true)
    setError('')
    try {
      const page = await listMessages(conversationId, next)
      setMessages((current) => {
        const present = new Set(current.map((message) => message.message_id))
        return [...[...page.items].reverse().filter((message) => !present.has(message.message_id)), ...current]
      })
      setNext(page.next_offset)
    } catch (reason) {
      setError(chatError(reason, onSessionExpired))
    } finally {
      setLoadingOlder(false)
    }
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = question.trim()
    if (!text || sending || loading || !numDocuments) return

    setSending(true)
    setError('')
    setQuestion('')
    jumpToLatest.current = true
    setPending(text)
    try {
      const response = await askQuestion(conversationId, text)
      const echo: Message = {
        message_id: 'local-' + response.message_id,
        role: 'user',
        content: text,
        citations: [],
        created_at: response.created_at,
      }
      jumpToLatest.current = true
      setPending('')
      setMessages((current) => [...current, echo, response])
    } catch (reason) {
      setError(chatError(reason, onSessionExpired))
      setQuestion(text)
    }
    try {
      const page = await listMessages(conversationId)
      jumpToLatest.current = true
      setMessages([...page.items].reverse())
      setNext(page.next_offset)
    } catch (reason) {
      const message = chatError(reason, onSessionExpired)
      setError((current) => current || message)
    } finally {
      setPending('')
      setSending(false)
    }
  }

  function handleEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <section className="chat-thread" aria-label="Chat documentaire">
      <nav className="chat-tabs" aria-label="Chat et sources">
        <button type="button" aria-pressed={tab === 'chat'} onClick={() => setTab('chat')}>
          <MessagesSquare aria-hidden="true" /> Chat
        </button>
        <button type="button" aria-pressed={tab === 'sources'} onClick={() => {
          if (tab === 'sources') return
          setLoadingSources(true)
          setTab('sources')
        }}><Layers3 aria-hidden="true" /> Sources</button>
      </nav>
      {tab === 'sources' && (
        <div className="sources-tab">
          <div className="sources-heading">
            <h2>Documents associés</h2>
            <button className="secondary" type="button" onClick={onSources} disabled={sending}>Modifier</button>
          </div>
          {loadingSources && <p role="status">Chargement des sources…</p>}
          {!loadingSources && !documents.length && <p>Aucun PDF disponible.</p>}
          <ul>
            {documents.map((document) => (
              <li key={document.id}>
                <button type="button" className="source-file" onClick={() => onDocument(document.id)}>
                  <FileText aria-hidden="true" /><span>{document.filename}</span><ArrowUpRight aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
          <button className="secondary danger" type="button" onClick={onRemove} disabled={sending}>
            <Trash2 aria-hidden="true" /> Supprimer la conversation
          </button>
        </div>
      )}
      <div className="message-pane" hidden={tab !== 'chat'} ref={timeline} role="region" tabIndex={0} aria-label="Historique de la conversation">
        {next !== null && (
          <button className="secondary history-more" type="button" onClick={older} disabled={loadingOlder || sending}>
            {loadingOlder ? 'Chargement…' : 'Charger les messages précédents'}
          </button>
        )}
        {loading && <p role="status">Chargement de la conversation…</p>}
        {!loading && !messages.length && !pending && (
          <div className="chat-empty">
            <h2>Pose ta première question</h2>
            <p>Les réponses s’appuient sur les PDF de cette conversation.</p>
          </div>
        )}
        <ol className="message-list" aria-live="polite" aria-relevant="additions">
          {messages.map((message) => (
            <li className={`message ${message.role}`} key={message.message_id}>
                            <span className="message-icon" aria-hidden="true">{message.role === 'user' ? <UserRound /> : <Sparkles />}</span>
              <span className="sr-only">{message.role === 'user' ? 'Toi' : 'DocMind AI'}</span>
              <p>{message.content}</p>
              {message.citations.length > 0 && (
                <details className="citation-list" open><summary>Citations ({message.citations.length})</summary>
                  {message.citations.map((source, index) => (
                    <button className="citation-card" type="button" key={source.id} onClick={() => onCitation(source)}>
                                            <span className="citation-number">{index + 1}</span>
                      <span className="citation-label">Page {source.page_number}</span>
                      <ArrowUpRight aria-hidden="true" />
                      <small>{source.excerpt}</small>
                    </button>
                  ))}
                </details>
              )}
            </li>
          ))}
          {pending && <li className="message user"><span className="sr-only">Toi</span><p>{pending}</p></li>}
        </ol>
        {sending && <p className="chat-progress" role="status">Recherche dans les PDF et rédaction de la réponse…</p>}
      </div>
      <form className="composer" hidden={tab !== 'chat'} onSubmit={send}>
        {error && <p className="error" role="alert">{error}</p>}
        {!numDocuments && <p role="status">Ajoute un PDF prêt dans Sources pour poursuivre.</p>}
        <label htmlFor="chat-question">Ta question</label>
        <div className="composer-row">
          <textarea id="chat-question" placeholder="Que disent les PDF sur ce sujet ?" rows={2}
            value={question} maxLength={4000} onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleEnter} disabled={sending || loading || !numDocuments} />
          <button className="workspace-primary send-button" aria-label="Envoyer" disabled={!question.trim() || sending || loading || !numDocuments}>
            <Send aria-hidden="true" />
          </button>
        </div>
      </form>
    </section>
  )
}
