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

async function request<T>(path: string, method: 'GET' | 'POST', credentials?: Credentials): Promise<T> {
  const headers = new Headers({ Accept: 'application/json' })
  if (method === 'POST') headers.set('X-DocMind-Request', '1')
  if (credentials) headers.set('Content-Type', 'application/json')

  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers,
    body: credentials ? JSON.stringify(credentials) : undefined,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, body?.error_code ?? 'UNAVAILABLE')
  }

  return (response.status === 204 ? undefined : await response.json()) as T
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
