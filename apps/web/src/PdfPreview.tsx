import { useEffect, useRef, useState } from 'react'
import { getDocument as loadPdf, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { Citation } from './chatApi'
import { chatError } from './chatErrors'
import { getDocument, openDocumentFile } from './documentApi'
import Modal from './Modal'

GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfPreview({ citation, onClose, onSessionExpired }: {
  citation: Citation
  onClose: () => void
  onSessionExpired: () => void
}) {
  const [file, setFile] = useState<{ pdf: PDFDocumentProxy; name: string; url: string } | null>(null)
  const [page, setPage] = useState(citation.page_number)
  const [error, setError] = useState('')
  const [renderError, setRenderError] = useState('')
  const [pageText, setPageText] = useState('')
  const [width, setWidth] = useState(320)
  const canvas = useRef<HTMLCanvasElement>(null)
  const frame = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let active = true
    let job: ReturnType<typeof loadPdf> | undefined
    let url: string | undefined

    async function load() {
      const [document, blob] = await Promise.all([
        getDocument(citation.document_id), openDocumentFile(citation.document_id),
      ])
      const data = new Uint8Array(await blob.arrayBuffer())
      if (!active) return
      url = URL.createObjectURL(blob)
      job = loadPdf({ data, useSystemFonts: true })
      const pdf = await job.promise
      if (!active) return
      setPage(Math.min(citation.page_number, pdf.numPages))
      setFile({ pdf, name: document.filename, url })
    }

    load().catch((reason: unknown) => {
      if (active) setError(chatError(reason, onSessionExpired))
    })
    return () => {
      active = false
      void job?.destroy().catch(() => undefined)
      if (url) URL.revokeObjectURL(url)
    }
  }, [citation.document_id, citation.page_number, onSessionExpired])

  useEffect(() => {
    const element = frame.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.max(160, Math.floor(entry.contentRect.width)))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!file || !canvas.current) return
    const target = canvas.current
    let active = true
    let render: RenderTask | undefined

    async function draw(pdf: PDFDocumentProxy) {
      const current = await pdf.getPage(page)
      if (!active) return
      const original = current.getViewport({ scale: 1 })
      const cssScale = Math.min(width / original.width, 1.5, 1500 / original.height)
      const viewport = current.getViewport({ scale: cssScale * Math.min(window.devicePixelRatio || 1, 2) })
      target.width = Math.ceil(viewport.width)
      target.height = Math.ceil(viewport.height)
      target.style.width = Math.ceil(original.width * cssScale) + 'px'
      target.style.height = Math.ceil(original.height * cssScale) + 'px'
      render = current.render({ canvas: target, viewport })
      await render.promise
      const content = await current.getTextContent()
      if (!active) return
      setPageText(content.items.map((item) => 'str' in item ? item.str : '').join(' '))
      setRenderError('')
    }

    draw(file.pdf).catch(() => {
      if (active) setRenderError('Cette page ne peut pas être affichée. Tu peux télécharger le PDF.')
    })
    return () => { active = false; render?.cancel() }
  }, [file, page, width])

  function go(newPage: number) {
    setPageText('')
    setRenderError('')
    setPage(newPage)
  }

  return (
    <Modal title={file?.name ?? 'Source du PDF'} onClose={onClose} wide>
      <div className="pdf-tools">
        <button className="secondary" type="button" aria-label="Page précédente"
          disabled={!file || page <= 1} onClick={() => go(page - 1)}>←</button>
        <span role="status">Page {page}{file && ' / ' + file.pdf.numPages}</span>
        <button className="secondary" type="button" aria-label="Page suivante"
          disabled={!file || page >= file.pdf.numPages} onClick={() => go(page + 1)}>→</button>
        {file && <a className="secondary download-link" href={file.url} download={file.name}>Télécharger le PDF</a>}
      </div>
      {citation.excerpt && <blockquote className="source-excerpt">{citation.excerpt}</blockquote>}
      {error && <p role="alert" className="error">{error}</p>}
      {renderError && <p role="alert" className="error">{renderError}</p>}
      {!file && !error && <p role="status">Ouverture du PDF…</p>}
      <div className="pdf-frame" ref={frame}>
        <canvas ref={canvas} role="img" aria-label={`Aperçu de la page ${page}`} hidden={!file || Boolean(renderError)} />
        {pageText && <p className="sr-only">{pageText}</p>}
      </div>
    </Modal>
  )
}
