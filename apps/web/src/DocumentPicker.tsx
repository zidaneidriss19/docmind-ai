import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Conversation } from './chatApi'
import { changeSources, createConversation } from './chatApi'
import { chatError } from './chatErrors'
import { listDocuments } from './documentApi'
import type { DocumentSummary } from './documentApi'
import Modal from './Modal'

export default function DocumentPicker({ conversation, onSaved, onClose, onSessionExpired }: {
  conversation: Conversation | null
  onSaved: (conversation: Conversation) => void
  onClose: () => void
  onSessionExpired: () => void
}) {
  const [title, setTitle] = useState('')
  const [selected, setSelected] = useState(conversation?.document_ids ?? [])
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [next, setNext] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    listDocuments(0).then(
      (result) => {
        if (!active) return
        setDocuments(result.items)
        setNext(result.next_offset)
        setLoading(false)
      },
      (reason: unknown) => {
        if (!active) return
        setError(chatError(reason, onSessionExpired))
        setLoading(false)
      },
    )
    return () => { active = false }
  }, [onSessionExpired])

  async function moreDocuments() {
    if (next === null) return
    setLoading(true)
    setError('')
    try {
      const result = await listDocuments(next)
      setDocuments((current) => [...new Map([...current, ...result.items].map((item) => [item.id, item])).values()])
      setNext(result.next_offset)
    } catch (reason) {
      setError(chatError(reason, onSessionExpired))
    } finally {
      setLoading(false)
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected.length || (!conversation && !title.trim())) return
    setBusy(true)
    setError('')
    try {
      const result = conversation
        ? await changeSources(conversation.id, selected)
        : await createConversation(title.trim(), selected)
      onSaved(result)
    } catch (reason) {
      setError(chatError(reason, onSessionExpired))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={conversation ? 'Modifier les sources' : 'Nouvelle conversation'} onClose={onClose}>
      <form className="picker-form" onSubmit={save}>
        {!conversation && (
          <label className="field">
            Titre
            <input required maxLength={150} value={title} onChange={(event) => setTitle(event.target.value)}
              placeholder="Ex. Analyse du projet Atlas" disabled={busy} />
          </label>
        )}
        <fieldset>
          <legend>Documents à interroger</legend>
          {!loading && !documents.length && (
            <p>Importe d’abord un PDF dans Documents et attends le statut Prêt.</p>
          )}
          <ul className="picker-list">
            {documents.map((document) => {
              const checked = selected.includes(document.id)
              return (
                <li key={document.id}>
                  <label>
                    <input type="checkbox" checked={checked}
                      disabled={busy || (document.status !== 'READY' && !checked) || (!checked && selected.length >= 10)}
                      onChange={() => setSelected((current) => checked
                        ? current.filter((id) => id !== document.id)
                        : [...current, document.id])}
                    />
                    <span>{document.filename}</span>
                    {document.status !== 'READY' && <small>Indisponible</small>}
                  </label>
                </li>
              )
            })}
          </ul>
          {loading && <p role="status">Chargement des documents…</p>}
          {next !== null && (
            <button className="secondary" type="button" onClick={moreDocuments} disabled={loading || busy}>
              Afficher plus de PDF
            </button>
          )}
        </fieldset>
        <p className="muted">{selected.length} / 10 PDF sélectionnés</p>
        {error && <p role="alert" className="error">{error}</p>}
        <footer className="dialog-actions">
          <button className="secondary" type="button" onClick={onClose}>Annuler</button>
          <button className="workspace-primary" disabled={busy || !selected.length || (!conversation && !title.trim())}>
            {busy ? 'Enregistrement…' : conversation ? 'Enregistrer les sources' : 'Créer la conversation'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
