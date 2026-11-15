import React, { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { post } from '../api.js'
import { P } from '../ui.jsx'
import { useSession } from '../App.jsx'

/** Landing page of the e-mailed link: /reset?token=... */
export default function Reset() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const { flash, refresh } = useSession()
  const nav = useNavigate()

  const submit = async (e) => {
    e.preventDefault(); setErr('')
    if (pw !== pw2) { setErr('The two passwords do not match.'); return }
    setBusy(true)
    try { await post('/auth/reset', { token, password: pw }); await refresh(); flash('Password changed. Sign in with the new one.'); nav('/login') }
    catch (ex) { setErr(ex.message) } finally { setBusy(false) }
  }
  return (
    <div className="pad" style={{ paddingTop: 36, display: 'grid', placeItems: 'center' }}>
      {!token ? (
        <div className="card col" style={{ maxWidth: 480, padding: 34 }}>
          <div className="h2" style={{ fontSize: 40 }}>No reset link</div>
          <div className="muted">Open the link from the email, or ask for a new one.</div>
          <Link to="/login" className="pill ink">Back to sign in</Link>
        </div>
      ) : (
        <form className="card col" style={{ borderRadius: 32, padding: 34, maxWidth: 480, width: '100%', boxShadow: '0 6px 0 #201f1d, var(--line)' }} onSubmit={submit}>
          <div className="h2" style={{ fontSize: 44 }}>Choose a new password</div>
          <label className="lab">New password<input className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} minLength={8} maxLength={128} autoComplete="new-password" required /></label>
          <label className="lab">Repeat it<input className="input" type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} minLength={8} maxLength={128} autoComplete="new-password" required /></label>
          <div className="small muted">At least 8 characters. Every device you were signed in on will be signed out.</div>
          {err && <div role="alert" style={{ color: P.m, fontWeight: 600 }}>{err} {err.includes('expired') && <Link to="/login" className="under">Ask for a new link</Link>}</div>}
          <button className="pill ink" style={{ padding: '14px 26px' }} disabled={busy}>{busy ? 'Saving…' : 'Save password'}</button>
        </form>
      )}
    </div>
  )
}
