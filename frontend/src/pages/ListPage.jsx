import React, { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, del, get, put } from '../api.js'
import { Avatar, FilmSearch, Frame, LikeBtn, fmt, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'

export default function ListPage() {
  const { id } = useParams()
  const { user, flash, bump } = useSession()
  const nav = useNavigate()
  const [l, setL] = useState(null)
  const [edit, setEdit] = useState(null)
  const load = useCallback(() => get(`/lists/${id}`).then(setL).catch((e) => { flash(e.message, 'err'); nav('/lists') }), [id])
  useEffect(() => { load() }, [load])
  if (!l) return <div className="pad muted" style={{ paddingTop: 40 }}>Loading…</div>
  const t = tone(l.id, 2)
  const run = async (fn, ok) => { try { await fn(); ok && flash(ok); await load() } catch (e) { flash(e.message, 'err') } }
  const remove = async () => { if (!window.confirm(`Delete “${l.title}”? This cannot be undone.`)) return; try { await del(`/lists/${id}`); flash('List deleted'); bump(); nav('/lists') } catch (e) { flash(e.message, 'err') } }
  const save = async (e) => { e.preventDefault(); await run(() => api(`/lists/${id}`, { method: 'PATCH', body: edit }), 'List updated'); setEdit(null) }

  return (
    <div>
      <div className="hero" style={{ margin: '24px clamp(12px,3vw,40px) 0', background: t.bg, color: t.fg, padding: 'clamp(24px,3vw,40px) clamp(22px,3.4vw,48px)' }}>
        <div className="blob" style={{ right: -120, top: -160, width: 480, height: 480, background: t.ac, opacity: .6 }} />
        <div style={{ position: 'relative' }}>
          <Link to="/lists" className="link">← All lists</Link>
          {edit ? (
            <form className="col" style={{ marginTop: 16, maxWidth: 720, color: '#201f1d' }} onSubmit={save}>
              <input className="input" value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} minLength={2} maxLength={120} required />
              <textarea className="input" style={{ minHeight: 80 }} value={edit.description} maxLength={1000} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
              <div className="row"><button className="pill ink sm">Save</button><button type="button" className="pill out sm" onClick={() => setEdit(null)}>Cancel</button></div>
            </form>
          ) : <>
            <div className="display" style={{ fontSize: 'clamp(42px,6vw,80px)', lineHeight: .95, margin: '14px 0 12px' }}>{l.title}</div>
            {l.description && <div className="lede" style={{ maxWidth: 760 }}>{l.description}</div>}
          </>}
          <div className="row wrap" style={{ gap: 14, marginTop: 20 }}>
            <Avatar name={l.author.name} id={l.author.id} size={34} to={`/users/${l.author.id}`} />
            <Link to={`/users/${l.author.id}`}>{l.author.name}</Link><span>· {l.count} film{l.count === 1 ? '' : 's'}</span>
            <LikeBtn variant="pill" kind="list" id={l.id} likes={l.likes} liked={l.liked} canLike={!!user} onNeedLogin={() => nav('/login')} />
            {l.mine && !edit && <><button className="pill out sm" style={{ color: '#201f1d' }} onClick={() => setEdit({ title: l.title, description: l.description })}>Edit</button>
              <button className="pill out sm" style={{ color: '#201f1d' }} onClick={remove}>Delete list</button></>}
          </div>
        </div>
      </div>
      <div className="pad" style={{ paddingTop: 34 }}>
        {l.mine && <div style={{ maxWidth: 620, marginBottom: 28 }}><FilmSearch placeholder="Add a film to this list…" onPick={(h) => run(() => put(`/lists/${id}/films/${h.id}`), `${h.title} added`)} /></div>}
        {l.films.length === 0 ? <div className="empty">This list is empty.</div> : (
          <div className="grid">
            {l.films.map((f, k) => (
              <div key={f.id} className="col" style={{ gap: 10, position: 'relative' }}>
                <Frame film={f} className="hov" top={`No. ${k + 1}`} />
                {l.mine && <button className="xbtn" title="Remove from list" onClick={() => run(() => del(`/lists/${id}/films/${f.id}`), 'Removed')}>×</button>}
                <div className="row between" style={{ alignItems: 'baseline', gap: 8 }}><span className="hfont" style={{ fontSize: 18, lineHeight: 1.15 }}>{f.title}</span><span style={{ flex: 'none', fontSize: 14 }}>{f.rating != null ? `★ ${fmt(f.rating)}` : ''}</span></div>
                <span className="small muted" style={{ marginTop: -6 }}>{[f.year, (f.genres || [])[0]].filter(Boolean).join(' · ')}</span>
              </div>))}
          </div>)}
      </div>
    </div>
  )
}
