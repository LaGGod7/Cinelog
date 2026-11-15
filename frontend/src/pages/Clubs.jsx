import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get, has, post } from '../api.js'
import { clickable, P, Switch, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'

export default function Clubs() {
  const { user, flash } = useSession()
  const [clubs, setClubs] = useState(null)
  const [filter, setFilter] = useState('all')
  const [f, setF] = useState({ name: '', description: '', is_public: true })
  const nav = useNavigate()
  const load = () => get('/clubs').then(setClubs).catch((e) => flash(e.message, 'err'))
  useEffect(() => { load() }, [user])

  const join = async (c, e) => {
    e.stopPropagation()
    if (!user) { nav('/login'); return }
    try { await post(`/clubs/${c.id}/join`); flash(`Welcome to ${c.name}!`); load() } catch (ex) { flash(ex.message, 'err') }
  }
  const create = async (e) => {
    e.preventDefault()
    try { const c = await post('/clubs', f); flash(`${c.name} is open`); nav(`/clubs/${c.id}`) } catch (ex) { flash(ex.message, 'err') }
  }
  const all = clubs || []
  const feat = all.find((c) => c.open_polls > 0) || all[0]
  const list = all.filter((c) => c !== feat).filter((c) => filter === 'all' || (filter === 'mine' && c.mine) || (filter === 'voting' && c.open_polls > 0))
  const JoinBtn = ({ c, big }) => c.mine
    ? <span className={'pill on ' + (big ? 'pop' : 'out sm')} style={{ color: '#201f1d' }}>✓ Joined</span>
    : c.is_public ? <button className={'pill ' + (big ? 'pop' : 'ink sm')} style={big ? { color: '#201f1d' } : undefined} onClick={(e) => join(c, e)}>Join</button> : <span className="tag line">Private</span>

  return (
    <div className="pad" style={{ paddingTop: 28 }}>
      <div className="two" style={{ marginBottom: 36 }}>
        <div>
          <div className="display" style={{ fontSize: 'clamp(50px,7.6vw,100px)', lineHeight: .9 }}>Find your <em className="m">people.</em></div>
          <div className="lede" style={{ margin: '18px 0 26px', color: 'var(--n4)', fontSize: 24 }}>Film clubs with a shared watchlist and a live poll to pick the next screening. One member, one vote.</div>
          <div className="row wrap" style={{ gap: 10 }}>
            {[['all', 'All clubs'], ['mine', 'My clubs'], ['voting', 'Voting now']].map(([k, t]) => (
              <button key={k} className={'pill pop'} style={filter === k ? { background: '#201f1d', color: '#fffdf8' } : undefined} onClick={() => setFilter(k)}>{t}</button>))}
          </div>
        </div>
        {feat && (
          <div className="hero lift" {...clickable(() => nav(`/clubs/${feat.id}`), 'link')} style={{ cursor: 'pointer', padding: 32, borderRadius: 34, background: P.t, color: '#fffdf8' }}>
            <div className="blob" style={{ right: -60, top: -60, width: 240, height: 240, background: P.g }} />
            <div className="pill xs" style={{ position: 'relative', background: '#201f1d', cursor: 'inherit', padding: '6px 14px' }}><span style={{ width: 9, height: 9, borderRadius: '50%', background: P.j }} />{feat.open_polls > 0 ? `Voting now · ${feat.open_polls} open poll${feat.open_polls === 1 ? '' : 's'}` : 'Featured club'}</div>
            <div style={{ position: 'relative', font: '400 clamp(40px,4.6vw,60px)/.95 var(--font-heading)', letterSpacing: '-.03em', margin: '18px 0 10px' }}>{feat.name}</div>
            <div className="lede" style={{ position: 'relative', fontSize: 21, marginBottom: 20 }}>{feat.description || 'A film club on CineLog.'}</div>
            <div className="row" style={{ position: 'relative', gap: 16 }}><span>{feat.members} member{feat.members === 1 ? '' : 's'}</span><span className="end"><JoinBtn c={feat} big /></span></div>
          </div>
        )}
      </div>

      {clubs && all.length === 0 && <div className="empty">No clubs yet.{has(user, 'club.create') ? ' Start the first one below.' : ' A club convener can start one.'}</div>}
      <div className="grid cards">
        {list.map((c) => {
          const t = tone(c.id, 1)
          return (
            <div key={c.id} className="card lift" {...clickable(() => nav(`/clubs/${c.id}`), 'link')} style={{ cursor: 'pointer', padding: 0, overflow: 'hidden', borderRadius: 28 }}>
              <div style={{ position: 'relative', height: 120, background: t.bg, overflow: 'hidden', borderBottom: '1.5px solid #201f1d' }}>
                <div className="blob" style={{ right: -30, top: -40, width: 160, height: 160, background: t.ac, opacity: .8 }} />
                <div className="avatar" style={{ position: 'absolute', left: 22, bottom: -26, width: 72, height: 72, background: '#fffdf8', fontSize: 34, transform: 'rotate(-8deg)' }}>{c.name[0]}</div>
              </div>
              <div className="col" style={{ padding: '34px 22px 22px', gap: 8 }}>
                <div style={{ font: '400 30px/1.05 var(--font-heading)' }}>{c.name}</div>
                <div style={{ fontSize: 14.5, color: 'var(--n4)', minHeight: 44 }}>{c.description}</div>
                <div className="row small muted" style={{ marginTop: 6 }}>
                  <span>{c.members} member{c.members === 1 ? '' : 's'}</span>
                  {c.open_polls > 0 && <span className="row" style={{ gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: '50%', background: 'oklch(0.65 0.15 160)' }} />voting now</span>}
                  <span className="end"><JoinBtn c={c} /></span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {has(user, 'club.create') && (
        <form className="card col" style={{ maxWidth: 560, marginTop: 44 }} onSubmit={create}>
          <h3 className="h3" style={{ fontSize: 34 }}>Start a <em className="m">club</em></h3>
          <label className="lab">Name<input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} minLength={2} maxLength={100} required /></label>
          <label className="lab">What is it about?<textarea className="input" style={{ minHeight: 80 }} value={f.description} maxLength={1000} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
          <Switch on={f.is_public} onChange={(v) => setF({ ...f, is_public: v })}>Public: anyone can find and join it</Switch>
          <div><button className="pill ink">Create club</button></div>
        </form>
      )}
    </div>
  )
}
