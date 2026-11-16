export interface Profile {
  id: string
  email: string
  role: 'USER' | 'ADMIN'
  created_at: string
}

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string) {
    super(code)
    this.status = status
    this.code = code
  }
}

interface Credentials {
  email: string
  password: string
}

type Method = 'GET' | 'POST' | 'DELETE'
type Body = Credentials | FormData
type ResponseFormat = 'json' | 'blob'

async function request<T>(
  path: string, method: Method, body?: Body, format: ResponseFormat = 'json',
): Promise<T> {
  const headers = new Headers({ Accept: format === 'blob' ? 'application/pdf' : 'application/json' })
  if (method !== 'GET') headers.set('X-DocMind-Request', '1')
  if (body && !(body instanceof FormData)) headers.set('Content-Type', 'application/json')

  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers,
    body: body instanceof FormData ? body : body && JSON.stringify(body),
  })
  if (!response.ok) {
    const problem = await response.json().catch(() => null)
    throw new ApiError(response.status, problem?.error_code ?? 'UNAVAILABLE')
  }

  if (response.status === 204) return undefined as T
  return (format === 'blob' ? await response.blob() : await response.json()) as T
}

export const register = (credentials: Credentials) =>
  request<Profile>('/auth/register', 'POST', credentials)

export const login = (credentials: Credentials) =>
  request<Profile>('/auth/login', 'POST', credentials)

export const logout = () => request<void>('/auth/logout', 'POST')

async function readProfile(): Promise<Profile | null> {
  try {
    return await request<Profile>('/users/me', 'GET')
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
  }

  try {
    return await request<Profile>('/auth/refresh', 'POST')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

let pendingProfile: Promise<Profile | null> | undefined

export function restoreSession() {
  pendingProfile ??= readProfile().finally(() => { pendingProfile = undefined })
  return pendingProfile
}

export async function authenticatedRequest<T>(
  path: string, method: Method, body?: Body, format?: ResponseFormat,
): Promise<T> {
  try {
    return await request<T>(path, method, body, format)
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    if (!await restoreSession()) throw error
    return request<T>(path, method, body, format)
  }
}
