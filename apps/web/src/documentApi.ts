import { authenticatedRequest } from './auth'

export type DocumentStatus = 'UPLOADED' | 'PROCESSING' | 'READY' | 'FAILED'

export interface DocumentSummary {
  id: string
  filename: string
  size_bytes: number
  page_count: number | null
  status: DocumentStatus
  created_at: string
}

interface DocumentPage {
  items: DocumentSummary[]
  next_offset: number | null
}

const documents = '/documents'
export const PAGE_SIZE = 20

export const listDocuments = (offset: number) =>
  authenticatedRequest<DocumentPage>(`${documents}?offset=${offset}&limit=${PAGE_SIZE}`, 'GET')

export function uploadDocument(file: File) {
  const form = new FormData()
  form.append('file', file)
  return authenticatedRequest<DocumentSummary>(documents, 'POST', form)
}

export const deleteDocument = (id: string) =>
  authenticatedRequest(`${documents}/${id}`, 'DELETE')

export const retryDocument = (id: string) =>
  authenticatedRequest(`${documents}/${id}/retry`, 'POST')

export async function downloadDocument(document: DocumentSummary) {
  const file = await authenticatedRequest<Blob>(`${documents}/${document.id}/file`, 'GET', undefined, 'blob')
  const url = URL.createObjectURL(file)
  const link = window.document.createElement('a')
  link.href = url
  link.download = document.filename
  window.document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
