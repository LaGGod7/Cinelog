import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get, post } from '../api.js'
import { clickable, P } from '../ui.jsx'
import { useSession } from '../App.jsx'

export default function Auth() {
  const [mode, setMode] = useState('login')
  const [f, setF] = useState({ email: '', password: '', display_name: '' })
  const [err, setErr] = useState('')
  const { refresh, flash } = useSession()
  const nav = useNavigate()
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const login = mode === 'login'
  const forgot = mode === 'forgot'
  const [sent, setSent] = useState('')

  const submit = async (e) => {
    e.preventDefault(); setErr('')
    if (forgot) {
      try { const r = await post('/auth/forgot', { email: f.email }); setSent(r.message) }
      catch (ex) { setErr(ex.status === 429 ? 'Too many attempts. Wait a minute and try again.' : ex.message) }
      return
    }
    try {
      const u = await post(login ? '/auth/login' : '/auth/register', login ? { email: f.email, password: f.password } : f)
      await refresh(); flash(`Welcome, ${(u.user || u).display_name.split(' ')[0]}`); nav('/')
    } catch (ex) { setErr(ex.status === 429 ? 'Too many attempts. Wait a minute and try again.' : ex.message) }
  }
  return (
    <div className="two pad" style={{ paddingTop: 36 }}>
      <div>
        <div className="display">{forgot ? <>Locked <em className="m">out?</em></> : login ? <>Welcome <em className="m">back.</em></> : <>Start your <em className="m">diary.</em></>}</div>
        <div className="lede" style={{ marginTop: 18, color: 'var(--n4)', maxWidth: 520 }}>Log films, rate the craft, join a club and read reviews with the plot twists safely blurred.</div>
        <div className="row wrap" style={{ gap: 18, marginTop: 34 }}>
          {[['diary', P.c, '#fffdf8', '6deg'], ['clubs', P.g, '#201f1d', '-8deg'], ['no spoilers', P.m, '#fffdf8', '4deg']].map(([t, bg, fg, rot]) => <div key={t} className="sticker" style={{ width: 86, height: 86, background: bg, color: fg, transform: `rotate(${rot})`, fontSize: 16 }}>{t}</div>)}
        </div>
      </div>
      <form className="card col" style={{ borderRadius: 32, padding: 34, maxWidth: 480, width: '100%', justifySelf: 'center', boxShadow: '0 6px 0 #201f1d, var(--line)' }} onSubmit={submit}>
        <div className="h2" style={{ fontSize: 44 }}>{forgot ? 'Reset password' : login ? 'Sign in' : 'Create account'}</div>
        {forgot && <div className="muted">Enter the email you signed up with. If it has an account, we send a link that lets you choose a new password.</div>}
        {!login && !forgot && <label className="lab">Display name<input className="input" value={f.display_name} onChange={set('display_name')} maxLength={80} required /></label>}
        <label className="lab">Email<input className="input" type="email" value={f.email} onChange={set('email')} required /></label>
        {!forgot && <label className="lab">Password<input className="input" type="password" value={f.password} onChange={set('password')} minLength={login ? 1 : 8} required /></label>}
        {err && <div role="alert" style={{ color: P.m, fontWeight: 600 }}>{err}</div>}
        {sent && <div role="status" style={{ fontWeight: 600 }}>{sent} The link works for 60 minutes.</div>}
        <button className="pill ink" style={{ padding: '14px 26px' }}>{forgot ? 'Send reset link' : login ? 'Sign in' : 'Create account'}</button>
        {!forgot && <a className="pill out" href="/api/auth/google/login">Continue with Google</a>}
        {login && <span className="under muted center" style={{ alignSelf: 'center' }} {...clickable(() => { setMode('forgot'); setErr(''); setSent('') })}>Forgot your password?</span>}
        <span className="under muted center" style={{ alignSelf: 'center' }} {...clickable(() => { setMode(login ? 'register' : 'login'); setErr(''); setSent('') })}>{login ? 'New here? Create an account' : forgot ? 'Back to sign in' : 'Already have an account? Sign in'}</span>
        {mode === 'register' && <div className="small muted center">The first account on a fresh install becomes the administrator.</div>}
      </form>
    </div>
  )
}
