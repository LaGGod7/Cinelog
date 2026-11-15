import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { get, post } from '../api.js'
import { clickable, Avatar, FilmSearch, Frame, LikeBtn, P, Seg, fgOn, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'

const FAN = [['0px', '60px', '-12deg'], ['90px', '20px', '-5deg'], ['190px', '0px', '2deg'], ['290px', '25px', '8deg'], ['380px', '70px', '14deg']]
const ROT = ['-4deg', '2deg', '-2deg', '3deg', '-1deg']

export function NewList({ onClose }) {
  const { flash, bump } = useSession()
  const nav = useNavigate()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [films, setFilms] = useState([])
  const save = async (e) => {
    e.preventDefault()
    try {
      const l = await post('/lists', { title, description, film_ids: films.map((f) => f.id) })
      flash(`“${l.title}” is live`)
      if (l.new_badges?.length) setTimeout(() => flash(`Badge earned: ${l.new_badges.map((b) => b.name).join(', ')}`), 3300)
      bump(); nav(`/lists/${l.id}`)
    } catch (ex) { flash(ex.message, 'err') }
  }
  return (
    <div className="backdrop" onClick={onClose}>
      <form className="modal col" style={{ gap: 16 }} onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <button type="button" className="close" onClick={onClose} aria-label="Close">×</button>
        <div className="h2" style={{ fontSize: 52 }}>A new <em className="c">list</em></div>
        <label className="lab">Title<input className="input" value={title} onChange={(e) => setTitle(e.target.value)} minLength={2} maxLength={120} placeholder="Films that feel like Sunday" required autoFocus /></label>
        <label className="lab">What ties them together?<textarea className="input" style={{ minHeight: 80 }} maxLength={1000} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        <FilmSearch placeholder="Add films…" onPick={(h) => setFilms((cur) => (cur.some((f) => f.id === h.id) ? cur : [...cur, h]))} />
        <div className="row wrap" style={{ gap: 8 }}>
          {films.map((f) => <span key={f.id} className="pill sm out on" {...clickable(() => setFilms(films.filter((x) => x.id !== f.id)))}>{f.title} ×</span>)}
          {films.length === 0 && <span className="muted">You can also add films later from any film page.</span>}
        </div>
        <div className="row"><span className="end" /><button type="button" className="pill ghost" onClick={onClose}>Cancel</button><button className="pill ink">Create list</button></div>
      </form>
    </div>
  )
}

export default function Lists() {
  const { user, tick } = useSession()
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const [tab, setTab] = useState('popular')
  const [lists, setLists] = useState(null)
  const making = params.get('new') === '1'
  useEffect(() => { get('/lists', { tab }).then(setLists).catch(() => setLists([])) }, [tab, tick, user])

  const all = lists || []
  const feat = tab === 'popular' ? all[0] : null
  const rest = feat ? all.slice(1) : all
  const ft = feat ? tone(feat.id, 2) : null
  const open = () => (user ? setParams({ new: '1' }) : nav('/login'))

  return (
    <div className="pad" style={{ paddingTop: 28 }}>
      <div className="row wrap between" style={{ alignItems: 'flex-end', marginBottom: 30, gap: 20 }}>
        <div className="display" style={{ fontSize: 'clamp(48px,7vw,92px)', lineHeight: .9 }}>Lists, <em className="c">lovingly made</em></div>
        <button className="pill ink" onClick={open}>+ New list</button>
      </div>

      {feat && (
        <div className="hero two" {...clickable(() => nav(`/lists/${feat.id}`), 'link')} style={{ cursor: 'pointer', gap: 40, padding: 'clamp(24px,3vw,40px) clamp(22px,3.4vw,48px)', background: ft.bg, color: ft.fg, marginBottom: 34 }}>
          <div>
            <div className="tag line" style={{ padding: '5px 13px', fontSize: 14, marginBottom: 16 }}>Most loved list</div>
            <div style={{ font: '400 clamp(40px,5vw,68px)/.95 var(--font-heading)', letterSpacing: '-.03em', marginBottom: 16, textWrap: 'balance' }}>{feat.title}</div>
            {feat.description && <div className="lede" style={{ fontSize: 22, marginBottom: 22 }}>{feat.description}</div>}
            <div className="row wrap" style={{ gap: 14 }}><Avatar name={feat.author.name} id={feat.author.id} size={34} to={`/users/${feat.author.id}`} />{feat.author.name} · {feat.count} film{feat.count === 1 ? '' : 's'}
              <LikeBtn variant="pill" kind="list" id={feat.id} likes={feat.likes} liked={feat.liked} canLike={!!user} onNeedLogin={() => nav('/login')} /></div>
          </div>
          <div className="fan" style={{ height: 300, maxWidth: 560 }}>
            {feat.films.map((f, k) => <Frame key={f.id} film={f} onClick={() => {}} style={{ width: 170, borderRadius: 16, left: FAN[k][0], top: FAN[k][1], transform: `rotate(${FAN[k][2]})`, boxShadow: '0 5px 0 #201f1d, var(--line)' }} />)}
          </div>
        </div>
      )}

      <div style={{ marginBottom: 24 }}><Seg value={tab} onChange={setTab} options={[['popular', 'Popular'], ['new', 'New'], ...(user ? [['friends', 'From friends']] : [])]} /></div>
      {lists && all.length === 0 && <div className="empty">{tab === 'friends' ? 'No lists from you or the people you follow yet.' : 'No lists yet. Make the first one.'}</div>}
      <div className="grid cards">
        {rest.map((l) => (
          <div key={l.id} className="card lift col" style={{ borderRadius: 28, padding: 20, gap: 14, cursor: 'pointer' }} {...clickable(() => nav(`/lists/${l.id}`), 'link')}>
            <div className="row" style={{ gap: 0, padding: '8px 40px 8px 6px', minHeight: 150, overflow: 'hidden', margin: '-4px -8px 0' }}>
              {l.films.map((f, k) => <div key={f.id} style={{ width: 86, flex: '0 1 86px', minWidth: 40, marginRight: -30 }}><Frame film={f} className="sm" onClick={() => {}} style={{ transform: `rotate(${ROT[k]})` }} /></div>)}
              {l.films.length === 0 && <span className="muted">No films yet</span>}
            </div>
            <div style={{ font: '400 30px/1.05 var(--font-heading)', letterSpacing: '-.02em', textWrap: 'balance' }}>{l.title}</div>
            <div style={{ fontSize: 14.5, color: 'var(--n4)' }}>{l.description}</div>
            <div className="row" style={{ gap: 10, marginTop: 'auto', fontSize: 14 }}>
              <Avatar name={l.author.name} id={l.author.id} size={28} to={`/users/${l.author.id}`} /><Link to={`/users/${l.author.id}`} onClick={(e) => e.stopPropagation()}>{l.author.name}</Link>
              <span style={{ color: 'var(--n7)' }}>· {l.count} film{l.count === 1 ? '' : 's'}</span>
              <span className="end"><LikeBtn variant="pill" kind="list" id={l.id} likes={l.likes} liked={l.liked} canLike={!!user} onNeedLogin={() => nav('/login')} /></span>
            </div>
          </div>))}
      </div>
      {making && user && <NewList onClose={() => setParams({})} />}
    </div>
  )
}
