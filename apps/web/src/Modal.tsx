import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

export default function Modal({ title, onClose, children, wide = false }: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => { element?.close() }
  }, [])

  return (
    <dialog ref={dialog} className={wide ? 'workspace-dialog wide' : 'workspace-dialog'}
      aria-labelledby="dialog-title" onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}>
      <header className="dialog-heading">
        <h2 id="dialog-title">{title}</h2>
        <button className="icon-button" type="button" aria-label="Fermer" onClick={onClose}>×</button>
      </header>
      {children}
    </dialog>
  )
}
