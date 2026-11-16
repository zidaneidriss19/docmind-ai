import { authenticatedRequest } from './auth'

export interface Conversation {
  id: string
  title: string
  document_ids: string[]
  created_at: string
  updated_at: string
}

export interface Citation {
  id: string
  document_id: string
  chunk_id: string
  page_number: number
  excerpt: string
}

export interface Message {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  created_at: string
}

interface Page<T> {
  items: T[]
  next_offset: number | null
}

const root = '/conversations'
export const listConversations = (offset = 0) =>
  authenticatedRequest<Page<Conversation>>(`${root}?offset=${offset}`, 'GET')

export const getConversation = (id: string) =>
  authenticatedRequest<Conversation>(`${root}/${id}`, 'GET')

export const createConversation = (title: string, document_ids: string[]) =>
  authenticatedRequest<Conversation>(root, 'POST', { title, document_ids })

export const changeSources = (id: string, document_ids: string[]) =>
  authenticatedRequest<Conversation>(`${root}/${id}/documents`, 'PUT', { document_ids })

export const removeConversation = (id: string) =>
  authenticatedRequest<void>(`${root}/${id}`, 'DELETE')

export const listMessages = (id: string, offset = 0) =>
  authenticatedRequest<Page<Message>>(`${root}/${id}/messages?offset=${offset}&limit=30&order=desc`, 'GET')

export const askQuestion = (id: string, content: string) =>
  authenticatedRequest<Message>(`${root}/${id}/messages`, 'POST', { content })
