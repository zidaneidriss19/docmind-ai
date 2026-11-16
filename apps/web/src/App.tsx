import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, login, logout, register, restoreSession } from './auth'
import type { Profile } from './auth'
import Documents from './Documents'
import './App.css'

function errorText(error: unknown) {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'INVALID_CREDENTIALS':
        return 'Adresse e-mail ou mot de passe incorrect.'
      case 'EMAIL_ALREADY_REGISTERED':
        return 'Un compte utilise déjà cette adresse e-mail.'
      case 'VALIDATION_ERROR':
        return 'Vérifie l’adresse e-mail et le mot de passe.'
    }
  }
  return 'Le service est temporairement indisponible. Réessaie dans un instant.'
}

function App() {
  const [profile, setProfile] = useState<Profile | null | undefined>()
  const [creating, setCreating] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const expireSession = useCallback(() => setProfile(null), [])

  useEffect(() => {
    let active = true
    restoreSession().then(
      (user) => { if (active) setProfile(user) },
      (reason: unknown) => {
        if (!active) return
        setProfile(null)
        setError(errorText(reason))
      },
    )
    return () => { active = false }
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const credentials = { email, password }
    setError('')
    setBusy(true)
    try {
      if (creating) {
        await register(credentials)
        setCreating(false)
      }
      setProfile(await login(credentials))
      setPassword('')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function signOut() {
    setError('')
    setBusy(true)
    try {
      await logout()
      setProfile(null)
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className={profile ? "shell signed-in" : "shell"} aria-busy={busy || profile === undefined}>
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">D</span>
        DocMind AI
      </div>

      <section className="panel" aria-labelledby="page-title">
        {!profile && <h1 id="page-title">{creating ? 'Créer un compte' : 'Se connecter'}</h1>}

        {profile === undefined ? (
          <p role="status">Vérification de la session…</p>
        ) : profile ? (
          <>
            <div className="account-header">
              <div>
                <h1 id="page-title">Ton espace</h1>
                <p>{profile.email}</p>
              </div>
              <button className="secondary" type="button" onClick={signOut} disabled={busy}>
                Se déconnecter
              </button>
            </div>
            <Documents onSessionExpired={expireSession} />
          </>
        ) : (
          <>
            <form onSubmit={submit}>
              <div className="field">
                <label htmlFor="email">Adresse e-mail</label>
                <input id="email" type="email" autoComplete="username" required
                  maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="password">Mot de passe</label>
                <input id="password" type="password"
                  autoComplete={creating ? 'new-password' : 'current-password'}
                  aria-describedby={creating ? 'password-hint' : undefined}
                  required minLength={creating ? 12 : 1} maxLength={128}
                  value={password} onChange={(event) => setPassword(event.target.value)} />
                {creating && <small id="password-hint">De 12 à 128 caractères.</small>}
              </div>
              <button className="primary" disabled={busy}>
                {busy ? 'En cours…' : creating ? 'Créer mon compte' : 'Se connecter'}
              </button>
            </form>
            <button className="switch" type="button" disabled={busy} onClick={() => {
              setCreating(!creating)
              setPassword('')
              setError('')
            }}>
              {creating ? 'J’ai déjà un compte' : 'Créer un compte'}
            </button>
          </>
        )}

        {error && <p role="alert" className="error">{error}</p>}
      </section>
    </main>
  )
}

export default App
