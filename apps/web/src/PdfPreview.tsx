import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, Maximize, Minus, Plus } from 'lucide-react'
import { getDocument as loadPdf, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { Citation } from './chatApi'
import { chatError } from './chatErrors'
import { getDocument, openDocumentFile } from './documentApi'

GlobalWorkerOptions.workerSrc = workerUrl
type Jump = { page: number }
type Rect = { left: number; top: number; width: number; height: number }
type Highlight = { id: string; number: number; rects: Rect[] }
const NO_CITATIONS: Citation[] = []
const normalized = (text: string) => text.replace(/\s+/g, ' ').trim().toLowerCase()

function locateCitations(layer: TextLayer, container: HTMLElement, citations: Citation[], page: number): Highlight[] {
  let text = ''
  const runs = layer.textContentItemsStr.flatMap((raw, index) => {
    const value = normalized(raw)
    const node = layer.textDivs[index]?.firstChild
    if (!value || !(node instanceof Text)) return []
    if (text) text += ' '
    const start = text.length
    text += value
    const offsets: number[] = []
    for (const word of raw.matchAll(/\S+/g)) {
      const from = word.index
      if (offsets.length) offsets.push(from - 1)
      for (let i = 0; i < word[0].length; i++) offsets.push(from + i)
    }
    return [{ node, start, end: text.length, offsets }]
  })
  const bounds = container.getBoundingClientRect()
  return citations.flatMap((citation, index) => {
    if (citation.page_number !== page) return []
    const excerpt = normalized(citation.excerpt)
    const start = excerpt ? text.indexOf(excerpt) : -1
    if (start < 0) return []
    const end = start + excerpt.length
    const rects = runs.flatMap((run) => {
      if (run.end <= start || run.start >= end) return []
      const from = run.offsets[Math.max(start, run.start) - run.start]
      const to = run.offsets[Math.min(end, run.end) - run.start - 1]
      if (from === undefined || to === undefined) return []
      const range = document.createRange()
      range.setStart(run.node, from)
      range.setEnd(run.node, to + 1)
      return Array.from(range.getClientRects(), (box) => ({
        left: box.left - bounds.left, top: box.top - bounds.top, width: box.width, height: box.height,
      }))
    })
    return rects.length ? [{ id: citation.id, number: index + 1, rects }] : []
  })
}

function Thumbnail({ pdf, page, selected, onSelect }: {
  pdf: PDFDocumentProxy; page: number; selected: boolean; onSelect: () => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const target = canvas.current
    if (!target) return
    let active = true
    let render: RenderTask | undefined
    void pdf.getPage(page).then((source) => {
      if (!active) return
      const natural = source.getViewport({ scale: 1 })
      const viewport = source.getViewport({ scale: 130 / natural.width })
      target.width = Math.ceil(viewport.width)
      target.height = Math.ceil(viewport.height)
      render = source.render({ canvas: target, viewport })
      return render.promise
    }).catch(() => undefined)
    return () => { active = false; render?.cancel() }
  }, [pdf, page])

  return <button type="button" className="page-thumb" aria-current={selected ? 'page' : undefined}
    aria-label={`Afficher la page ${page}`} onClick={onSelect}>
    <canvas ref={canvas} aria-hidden="true" />
    <span>{page}</span>
  </button>
}

export default function PdfPreview({ documentId, jump, citations = NO_CITATIONS, onSessionExpired }: {
  documentId: string
  jump: Jump
  citations?: Citation[]
  onSessionExpired: () => void
}) {
  const [file, setFile] = useState<{ pdf: PDFDocumentProxy; name: string; url: string } | null>(null)
  const [navigation, setNavigation] = useState({ jump, page: jump.page, input: String(jump.page) })
  const page = Math.min(
    navigation.jump === jump ? navigation.page : jump.page,
    file?.pdf.numPages ?? jump.page,
  )
  const pageInput = navigation.jump === jump ? navigation.input : String(page)
  const [zoom, setZoom] = useState(100)
  const [error, setError] = useState('')
  const [renderError, setRenderError] = useState('')
  const [width, setWidth] = useState(320)
  const [marks, setMarks] = useState<{ page: number; jump: Jump; items: Highlight[] } | null>(null)
  const visibleMarks = marks?.page === page && marks.jump === jump ? marks.items : []
  const canvas = useRef<HTMLCanvasElement>(null)
  const textLayer = useRef<HTMLDivElement>(null)
  const frame = useRef<HTMLDivElement>(null)
  const reader = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let active = true
    let task: ReturnType<typeof loadPdf> | undefined
    let url: string | undefined
    async function load() {
      const [document, blob] = await Promise.all([getDocument(documentId), openDocumentFile(documentId)])
      const data = new Uint8Array(await blob.arrayBuffer())
      if (!active) return
      url = URL.createObjectURL(blob)
      task = loadPdf({ data, useSystemFonts: true })
      const pdf = await task.promise
      if (active) setFile({ pdf, name: document.filename, url })
    }
    load().catch((reason: unknown) => { if (active) setError(chatError(reason, onSessionExpired)) })
    return () => {
      active = false
      void task?.destroy().catch(() => undefined)
      if (url) URL.revokeObjectURL(url)
    }
  }, [documentId, onSessionExpired])

  useEffect(() => { frame.current?.scrollTo(0, 0) }, [jump])

  useEffect(() => {
    const element = frame.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(100, Math.floor(entry.contentRect.width))))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const target = canvas.current
    const layer = textLayer.current
    if (!file || !target || !layer) return
    let active = true
    let render: RenderTask | undefined
    let overlay: TextLayer | undefined
    async function draw(pdf: PDFDocumentProxy) {
      const source = await pdf.getPage(Math.min(page, pdf.numPages))
      if (!active || !target || !layer) return
      const original = source.getViewport({ scale: 1 })
      const scale = Math.min(Math.max(100, width - 32) / original.width, 1.4) * zoom / 100
      const cssViewport = source.getViewport({ scale })
      const viewport = source.getViewport({ scale: scale * Math.min(window.devicePixelRatio || 1, 2) })
      target.width = Math.ceil(viewport.width)
      target.height = Math.ceil(viewport.height)
      target.style.width = Math.ceil(cssViewport.width) + 'px'
      target.style.height = Math.ceil(cssViewport.height) + 'px'
      render = source.render({ canvas: target, viewport })
      await render.promise
      if (!active) return
      setRenderError('')
      layer.style.setProperty('--total-scale-factor', String(cssViewport.scale * cssViewport.userUnit))
      overlay = new TextLayer({ textContentSource: source.streamTextContent(), container: layer, viewport: cssViewport })
      await overlay.render()
      if (!active) return
      const items = locateCitations(overlay, layer, citations.map((citation) =>
        citation.document_id === documentId ? citation : { ...citation, page_number: -1 },
      ), page)
      setMarks({ page, jump, items })
      const first = items[0]?.rects[0]
      if (first && page === jump.page) frame.current?.scrollTo(0, Math.max(0, first.top - 85))
    }
    draw(file.pdf).catch(() => { if (active) setRenderError('Aperçu indisponible pour cette page.') })
    return () => { active = false; render?.cancel(); overlay?.cancel(); layer.replaceChildren() }
  }, [file, page, width, zoom, jump, citations, documentId])

  function go(value: number) {
    const target = Math.min(file?.pdf.numPages ?? 1, Math.max(1, Math.trunc(value) || 1))
    setNavigation({ jump, page: target, input: String(target) })
    frame.current?.scrollTo(0, 0)
  }

  const count = file?.pdf.numPages ?? 0
  const first = Math.min(Math.max(1, page - 2), Math.max(1, count - 4))
  const pages = Array.from({ length: Math.min(5, count) }, (_, index) => first + index)

  return (
    <div className="reader" ref={reader}>
      <aside className="reader-thumbs" aria-label="Miniatures du PDF">
        <h2>Pages</h2>
        {file && pages.map((number) =>
          <Thumbnail key={number} pdf={file.pdf} page={number} selected={number === page} onSelect={() => go(number)} />
        )}
      </aside>
      <div className="reader-main">
        <div className="reader-toolbar" aria-label="Commandes du PDF">
          <div className="reader-controls">
            <button type="button" aria-label="Page précédente" disabled={page <= 1 || !file} onClick={() => go(page - 1)}><ChevronLeft /></button>
            <form className="reader-page" onSubmit={(event) => { event.preventDefault(); go(Number(pageInput)) }}>
              <input aria-label="Numéro de page" value={pageInput} inputMode="numeric" maxLength={4}
                disabled={!file} onChange={(event) => setNavigation({ jump, page, input: event.target.value.replace(/\D/g, '') })}
                onBlur={() => go(Number(pageInput))} />
              <span aria-live="polite">/ {count || '–'}</span>
            </form>
            <button type="button" aria-label="Page suivante" disabled={page >= count} onClick={() => go(page + 1)}><ChevronRight /></button>
          </div>
          <div className="reader-controls reader-zoom">
            <button type="button" aria-label="Réduire le zoom" disabled={zoom <= 50 || !file} onClick={() => setZoom(zoom - 25)}><Minus /></button>
            <button type="button" aria-label="Réinitialiser le zoom" disabled={!file} onClick={() => setZoom(100)}>{zoom} %</button>
            <button type="button" aria-label="Agrandir le zoom" disabled={zoom >= 200 || !file} onClick={() => setZoom(zoom + 25)}><Plus /></button>
          </div>
          {file && <div className="reader-controls">
            <a href={file.url} download={file.name} aria-label="Télécharger le PDF" title={file.name}><Download /></a>
            {document.fullscreenEnabled && <button type="button" aria-label="Plein écran" onClick={() => {
              const action = document.fullscreenElement ? document.exitFullscreen() : reader.current?.requestFullscreen()
              void action?.catch(() => undefined)
            }}><Maximize /></button>}
          </div>}
        </div>
        {error && <p role="alert" className="error">{error}</p>}
        {renderError && <p role="alert" className="error">{renderError}</p>}
        {!file && !error && <p className="reader-loading" role="status">Ouverture du PDF…</p>}
        <div className="reader-frame" ref={frame} tabIndex={0} role="region" aria-label={file?.name ?? 'Document PDF'}>
          <div className="pdf-sheet" hidden={!file || Boolean(renderError)}>
            <canvas ref={canvas} aria-hidden="true" />
            <div className="textLayer" ref={textLayer} />
            <div className="pdf-citation-overlay" aria-hidden="true">
              {visibleMarks.map(({ id, number, rects }) => {
                const last = rects[rects.length - 1]
                return (
                  <div key={id}>
                    {rects.map((rect, index) => <span key={index} className="cited-text" style={rect} />)}
                    <span className="pdf-citation-badge" style={{ top: last.top, left: `min(${last.left + last.width + 4}px, calc(100% - 3.55rem))` }}>
                      <b>{number}</b> p.{page}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
