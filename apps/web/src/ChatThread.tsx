import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { askQuestion, listMessages } from './chatApi'
import type { Citation, Conversation, Message } from './chatApi'
import { chatError } from './chatErrors'

const PdfPreview = lazy(() => import('./PdfPreview'))

export default function ChatThread({ conversation, onSources, onRemove, onSessionExpired }: {
  conversation: Conversation
  onSources: () => void
  onRemove: () => void
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
  const [citation, setCitation] = useState<Citation | null>(null)
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
    <section className="chat-thread" aria-labelledby="thread-title">
      <header className="thread-heading">
        <div>
          <h1 id="thread-title">{conversation.title}</h1>
          <p>{numDocuments} {numDocuments === 1 ? 'PDF sélectionné' : 'PDF sélectionnés'}</p>
        </div>
        <div className="thread-tools">
          <button className="secondary" type="button" onClick={onSources} disabled={sending}>Sources</button>
          <button className="secondary danger" type="button" onClick={onRemove} disabled={sending}>Supprimer</button>
        </div>
      </header>
      <div className="message-pane" ref={timeline} role="region" tabIndex={0} aria-label="Historique de la conversation">
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
              <span className="message-author">{message.role === 'user' ? 'Toi' : 'DocMind AI'}</span>
              <p>{message.content}</p>
              {message.citations.length > 0 && (
                <div className="citation-list" aria-label="Sources de la réponse">
                  {message.citations.map((source, index) => (
                    <button className="citation-card" type="button" key={source.id} onClick={() => setCitation(source)}>
                      <span>Source {index + 1} · Page {source.page_number}</span>
                      <small>{source.excerpt}</small>
                    </button>
                  ))}
                </div>
              )}
            </li>
          ))}
          {pending && <li className="message user"><span className="message-author">Toi</span><p>{pending}</p></li>}
        </ol>
        {sending && <p className="chat-progress" role="status">Recherche dans les PDF et rédaction de la réponse…</p>}
      </div>
      <form className="composer" onSubmit={send}>
        {error && <p className="error" role="alert">{error}</p>}
        {!numDocuments && <p role="status">Ajoute un PDF prêt dans Sources pour poursuivre.</p>}
        <label htmlFor="chat-question">Ta question</label>
        <div className="composer-row">
          <textarea id="chat-question" placeholder="Que disent les PDF sur ce sujet ?" rows={2}
            value={question} maxLength={4000} onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleEnter} disabled={sending || loading || !numDocuments} />
          <button className="workspace-primary" disabled={!question.trim() || sending || loading || !numDocuments}>
            Envoyer
          </button>
        </div>
      </form>
      {citation && (
        <Suspense fallback={<p role="status">Chargement du lecteur PDF…</p>}>
          <PdfPreview citation={citation} onClose={() => setCitation(null)} onSessionExpired={onSessionExpired} />
        </Suspense>
      )}
    </section>
  )
}
