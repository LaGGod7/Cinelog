import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get, post } from './api.js'
import { ago, clickable } from './ui.jsx'

const ICON = { like: '♥', follow: '＋', reply: '💬', moderation: '⚑', badge: '★', security: '🔒', role: '🛡', critic: '✒' }

/** The bell: unread count in the nav, list in a dropdown. Polls once a minute while the tab is visible. */
export default function Notifications({ tick }) {
  const [data, setData] = useState({ unread: 0, items: [] })
  const [open, setOpen] = useState(false)
  const box = useRef()
  const nav = useNavigate()

  const load = useCallback(() => get('/notifications').then(setData).catch(() => {}), [])
  useEffect(() => {
    load()
    const t = setInterval(() => { if (!document.hidden) load() }, 60000)
    return () => clearInterval(t)
  }, [load, tick])
  useEffect(() => {
    if (!open) return undefined
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])

  const readAll = async () => { try { const r = await post('/notifications/read', {}); setData((d) => ({ unread: r.unread, items: d.items.map((n) => ({ ...n, read: true })) })) } catch { /* ignore */ } }
  const go = async (n) => {
    setOpen(false)
    if (!n.read) { try { const r = await post('/notifications/read', { ids: [n.id] }); setData((d) => ({ unread: r.unread, items: d.items.map((x) => (x.id === n.id ? { ...x, read: true } : x)) })) } catch { /* ignore */ } }
    if (n.link) nav(n.link)
  }

  return (
    <div className="bellwrap" ref={box}>
      <button className="pill out sm bell" aria-label={`Notifications, ${data.unread} unread`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }}>
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {data.unread > 0 && <span className="count">{data.unread > 99 ? '99+' : data.unread}</span>}
      </button>
      {open && (
        <div className="notif card" role="dialog" aria-label="Notifications">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <b className="hfont" style={{ fontSize: 22 }}>Notifications</b>
            {data.unread > 0 && <button className="pill ghost xs" onClick={readAll}>Mark all read</button>}
          </div>
          {data.items.length === 0 && <div className="muted" style={{ padding: '14px 0' }}>Nothing yet. Likes, follows, replies and moderator decisions show up here.</div>}
          <div className="notif-list">
            {data.items.map((n) => (
              <div key={n.id} className={'notif-item' + (n.read ? '' : ' unread')} {...clickable(() => go(n), 'link')}>
                <span className="notif-ic" aria-hidden="true">{ICON[n.kind] || '•'}</span>
                <span className="grow"><span>{n.text}</span><span className="small muted" style={{ display: 'block' }}>{ago(n.at)}</span></span>
                {!n.read && <i className="notif-dot" aria-label="unread" />}
              </div>))}
          </div>
        </div>
      )}
    </div>
  )
}
