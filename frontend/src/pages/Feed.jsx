import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { del, get, put } from '../api.js'
import { clickable, Avatar, P, ago, fgOn, starText, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'

/** What one feed entry says and points at, by type. New activity types only need a case here. */
function describe(e) {
  if (e.type === 'badge') return { verb: 'earned the badge', obj: e.badge, to: `/users/${e.user_id}`, bg: P[e.badge_color], fg: fgOn(e.badge_color), thumb: e.badge, round: true }
  if (e.type === 'list') { const t = tone(e.list_id, 2); return { verb: 'made a list', obj: e.list, to: `/lists/${e.list_id}`, bg: t.bg, fg: t.fg, thumb: `${e.count} film${e.count === 1 ? '' : 's'}` } }
  const t = tone(e.film_id)
  return { verb: e.type === 'reviewed' ? 'reviewed' : 'watched', obj: e.film, to: `/films/${e.film_id}`, bg: t.bg, fg: t.fg, thumb: e.film }
}

export default function Feed() {
  const { user, flash, openLog, tick } = useSession()
  const [feed, setFeed] = useState(null)
  const [similar, setSimilar] = useState([])
  const [following, setFollowing] = useState([])
  const [board, setBoard] = useState([])
  const nav = useNavigate()
  const load = () => Promise.all([get('/feed', { limit: 30 }), get('/me/similar'), get('/me/following'), get('/leaderboard/streaks')])
    .then(([f, s, fl, b]) => { setFeed(f); setSimilar(s); setFollowing(fl); setBoard(b) }).catch((e) => flash(e.message, 'err'))
  useEffect(() => { load() }, [tick])
  const isF = (uid) => following.some((u) => u.user_id === uid)
  const toggle = async (uid, name) => {
    try { isF(uid) ? await del(`/follow/${uid}`) : await put(`/follow/${uid}`); flash(isF(uid) ? `Unfollowed ${name}` : `Following ${name}`); load() } catch (e) { flash(e.message, 'err') }
  }

  return (
    <div className="split pad" style={{ paddingTop: 28 }}>
      <div>
        <div className="display" style={{ fontSize: 'clamp(44px,6.4vw,84px)', marginBottom: 26 }}>What your <em className="m">people</em> are watching</div>
        <div className="field lift" style={{ cursor: 'pointer', padding: '12px 12px 12px 14px', marginBottom: 28 }} {...clickable(() => openLog())}>
          <Avatar name={user.display_name} id={user.id} size={42} style={{ boxShadow: 'none' }} />
          <span className="grow" style={{ font: '400 italic 18px var(--font-body)', color: 'var(--n7)' }}>What did you watch, {user.display_name.split(' ')[0]}?</span>
          <span className="pill ink sm" style={{ padding: '11px 20px', fontSize: 16 }}>Log a film</span>
        </div>
        {feed && feed.length === 0 && <div className="empty">Nothing yet. Follow someone and their diary, lists and badges show up here.</div>}
        <div className="col" style={{ gap: 18 }}>
          {(feed || []).map((e, k) => {
            const d = describe(e)
            return (
              <div key={k} className="card flat" style={{ display: 'grid', gridTemplateColumns: '52px minmax(0,1fr) auto', gap: 16, padding: '20px 22px' }}>
                <Avatar name={e.user} id={e.user_id} size={52} to={`/users/${e.user_id}`} />
                <div className="col" style={{ gap: 8, minWidth: 0 }}>
                  <div style={{ font: '400 20px/1.25 var(--font-heading)' }}>
                    <Link to={`/users/${e.user_id}`} style={{ fontWeight: 600 }}>{(e.user || '').split(' ')[0]}</Link> {d.verb}{' '}
                    <Link to={d.to} style={{ fontWeight: 600, fontStyle: 'italic', textDecoration: 'underline', textDecorationColor: d.bg, textDecorationThickness: 3, textUnderlineOffset: 4 }}>{d.obj}</Link>{' '}
                    <span className="starline" style={{ fontSize: 16 }}>{starText(e.stars)}</span>
                  </div>
                  {e.excerpt && <div style={{ font: '400 15.5px/1.6 var(--font-body)', color: '#2d2b2b' }}>{e.excerpt}</div>}
                  <div className="row small muted" style={{ gap: 14 }}><span>{ago(e.at)}</span>{e.has_spoilers && <span className="tag" style={{ background: P.t, color: '#fffdf8' }}>spoilers hidden</span>}</div>
                </div>
                <div {...clickable(() => nav(d.to), 'link')} className="sticker" style={{ width: 84, height: 84, borderRadius: d.round ? '50%' : 14, background: d.bg, color: d.fg, transform: `rotate(${['-4deg', '3deg', '-2deg', '5deg'][k % 4]})`, cursor: 'pointer', fontSize: 15, overflow: 'hidden' }}>{d.thumb}</div>
              </div>
            )
          })}
        </div>
      </div>
      <div className="col" style={{ gap: 24, paddingTop: 12 }}>
        <div className="card" style={{ background: P.t, color: '#fffdf8' }}>
          <h3 className="h3" style={{ fontSize: 32, marginBottom: 16 }}>Streak leaderboard</h3>
          {board.map((l, k) => (
            <Link key={l.user_id} to={`/users/${l.user_id}`} className="row" style={{ padding: '9px 12px', margin: '0 -12px', borderRadius: 16, background: l.me ? '#fffdf8' : 'transparent', color: l.me ? '#201f1d' : '#fffdf8' }}>
              <span style={{ width: 22, font: '400 22px var(--font-heading)' }}>{k + 1}</span>
              <Avatar name={l.name} id={l.user_id} size={34} />
              <span className="grow hfont" style={{ fontSize: 18 }}>{l.me ? 'You' : l.name}</span>
              <span className="hfont" style={{ fontSize: 18 }}>{l.days} day{l.days === 1 ? '' : 's'}</span>
            </Link>))}
          {board.length < 2 && <div className="small" style={{ marginTop: 10, opacity: .9 }}>Follow people to race them.</div>}
        </div>
        <div className="card">
          <h3 className="h3" style={{ fontSize: 32, marginBottom: 6 }}>People to follow</h3>
          <div className="small muted" style={{ marginBottom: 8 }}>Matched on films you have both rated (five or more in common).</div>
          {similar.length === 0 && <div className="muted">No matches yet. Rate the craft on a few more films.</div>}
          {similar.map((u) => (
            <div key={u.user_id} className="row rule-top" style={{ padding: '10px 0' }}>
              <Avatar name={u.name} id={u.user_id} to={`/users/${u.user_id}`} />
              <div className="grow"><Link to={`/users/${u.user_id}`} className="hfont" style={{ fontSize: 18 }}>{u.name}</Link><div className="small muted">{Math.round(u.similarity * 100)}% taste match</div></div>
              <button className={'pill sm ' + (isF(u.user_id) ? 'out on' : 'ink')} onClick={() => toggle(u.user_id, u.name)}>{isF(u.user_id) ? '✓ Following' : 'Follow'}</button>
            </div>))}
        </div>
        <div className="card">
          <h3 className="h3" style={{ fontSize: 32, marginBottom: 12 }}>Following</h3>
          {following.length === 0 && <div className="muted">You are not following anyone yet. Open a profile from a review and press Follow.</div>}
          {following.map((u) => (
            <div key={u.user_id} className="row rule-top" style={{ padding: '10px 0' }}>
              <Avatar name={u.name} id={u.user_id} to={`/users/${u.user_id}`} />
              <Link to={`/users/${u.user_id}`} className="grow hfont" style={{ fontSize: 18 }}>{u.name}</Link>
              <button className="pill sm out on" onClick={() => toggle(u.user_id, u.name)}>✓ Following</button>
            </div>))}
        </div>
      </div>
    </div>
  )
}
