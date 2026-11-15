import React, { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { del, get, post, put } from './api.js'
import { clickable, Avatar, Frame, P, Poster, fmt, starText, tone } from './ui.jsx'
import { useSession } from './App.jsx'

/** A progress ring. `children` sit in the middle. */
export function Ring({ percent = 0, size = 132, stroke = 14, color = P.m, children }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r
  return (
    <div style={{ position: 'relative', width: size, height: size, flex: 'none' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(32,31,29,.12)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(100, percent) / 100)} style={{ transition: 'stroke-dashoffset .6s ease' }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', textAlign: 'center' }}>{children}</div>
    </div>
  )
}

/** "I want to watch N films this year" with a ring, pace and a nudge. */
export function GoalCard({ compact }) {
  const { flash, tick } = useSession()
  const year = new Date().getFullYear()
  const [goal, setGoal] = useState(undefined)
  const [editing, setEditing] = useState(false)
  const [target, setTarget] = useState('')
  const load = useCallback(() => get('/me/goal').then((d) => setGoal(d.goal)).catch(() => setGoal(null)), [])
  useEffect(() => { load() }, [load, tick])
  const save = async (e) => {
    e.preventDefault()
    try { const d = await put('/me/goal', { target: Number(target) }); setGoal(d.goal); setEditing(false); flash(`Goal set: ${d.goal.target} films in ${year}`) } catch (ex) { flash(ex.message, 'err') }
  }
  if (goal === undefined) return null
  const form = (
    <form className="row wrap" style={{ gap: 10 }} onSubmit={save}>
      <input className="input" type="number" min={1} max={1000} style={{ width: 110 }} placeholder="e.g. 52" value={target} onChange={(e) => setTarget(e.target.value)} required autoFocus />
      <button className="pill ink sm">Save</button>
      {goal && <button type="button" className="pill ghost sm" onClick={() => setEditing(false)}>Cancel</button>}
    </form>
  )
  return (
    <div className="card" style={{ background: goal?.reached ? P.j : undefined }}>
      <div className="row between" style={{ alignItems: 'baseline', marginBottom: 12 }}>
        <h3 className="h3" style={{ fontSize: compact ? 28 : 32 }}>{year} goal</h3>
        {goal && !editing && <button className="small under muted" onClick={() => { setTarget(String(goal.target)); setEditing(true) }}>change</button>}
      </div>
      {!goal || editing ? (
        <div className="col" style={{ gap: 12 }}>
          <div className="lede" style={{ fontSize: 19 }}>How many films do you want to watch in {year}?</div>
          {form}
        </div>
      ) : (
        <div className="row" style={{ gap: 20 }}>
          <Ring percent={goal.percent} color={goal.reached ? P.c : P.m} size={compact ? 104 : 124}>
            <span><span className="hfont" style={{ fontSize: 34, lineHeight: 1 }}>{goal.done}</span><span className="muted" style={{ display: 'block', fontSize: 13 }}>of {goal.target}</span></span>
          </Ring>
          <div className="col" style={{ gap: 6 }}>
            <div className="hfont" style={{ fontSize: 22, lineHeight: 1.15 }}>
              {goal.reached ? 'Goal reached. Take a bow.' : goal.ahead_by >= 0 ? `${Math.round(goal.ahead_by)} ahead of pace` : `${Math.abs(Math.round(goal.ahead_by))} behind pace`}
            </div>
            {!goal.reached && goal.per_week_needed != null && <div className="small muted">{goal.per_week_needed} film{goal.per_week_needed === 1 ? '' : 's'} a week to finish by 31 Dec · {goal.days_left} days left</div>}
          </div>
        </div>
      )}
    </div>
  )
}

/** Film cards that say why they are suggested. */
export function FilmStrip({ items, onPick }) {
  const nav = useNavigate()
  return (
    <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(168px,1fr))', gap: 22 }}>
      {items.map((f) => (
        <div key={f.id} className="col" style={{ gap: 8 }}>
          <Frame film={f} className="hov" top={f.year} onClick={() => (onPick ? onPick(f) : nav(`/films/${f.id}`))} />
          <span className="hfont" style={{ fontSize: 18, lineHeight: 1.12 }}>{f.title}</span>
          {f.reason && <span className="small muted" style={{ fontStyle: 'italic', lineHeight: 1.35 }}>{f.reason}</span>}
        </div>
      ))}
    </div>
  )
}

export function Recommendations({ limit = 6, title = true }) {
  const { tick } = useSession()
  const [rec, setRec] = useState(null)
  useEffect(() => { get('/me/recommendations', { limit }).then(setRec).catch(() => setRec(null)) }, [limit, tick])
  if (!rec) return null
  return (
    <div>
      {title && <div className="row between wrap" style={{ marginBottom: 18, alignItems: 'baseline' }}>
        <h2 className="h2">Picked <em className="m">for you</em></h2>
        {!rec.ready && <span className="lede muted" style={{ fontSize: 18 }}>Log {rec.needed - rec.logged} more film{rec.needed - rec.logged === 1 ? '' : 's'} and these get personal</span>}
      </div>}
      {rec.items.length === 0 ? <div className="empty">You have seen everything we know. Sync the catalogue for more.</div> : <FilmStrip items={rec.items} />}
    </div>
  )
}

export function FilmOfDay() {
  const { openLog } = useSession()
  const nav = useNavigate()
  const [d, setD] = useState(null)
  useEffect(() => { get('/discover/film-of-the-day').then(setD).catch(() => setD(null)) }, [])
  if (!d || !d.film) return null
  const f = d.film, t = tone(f.id)
  return (
    <div className="feat" style={{ background: t.bg, color: t.fg }}>
      <div className="frame" style={{ borderRadius: 18, cursor: 'pointer' }} {...clickable(() => nav(`/films/${f.id}`))}><Poster film={f} top="Film of the day" /></div>
      <div className="col" style={{ gap: 12, minWidth: 0 }}>
        <div className="kicker" style={{ color: 'inherit' }}>Film of the day · {new Date(d.date + 'T00:00').toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</div>
        <div className="display" style={{ fontSize: 'clamp(36px,4.6vw,62px)', lineHeight: .92 }}>{f.title}</div>
        <div>{[f.year, f.runtime && `${f.runtime} min`, f.genres?.slice(0, 2).join(' / ')].filter(Boolean).join(' · ')}{f.rating != null && <span> · ★ {fmt(f.rating)}</span>}</div>
        {f.overview && <div className="lede" style={{ maxWidth: 560, display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{f.overview}</div>}
        <div className="row wrap">
          <button className="pill ink" onClick={() => openLog({ film: f })}>{d.watched ? 'Log another watch' : 'I have seen it'}</button>
          <Link to={`/films/${f.id}`} className="pill out" style={{ color: '#201f1d' }}>Open film</Link>
        </div>
      </div>
    </div>
  )
}

export function CriticsPicks() {
  const [picks, setPicks] = useState([])
  useEffect(() => { get('/critics/picks', { limit: 6 }).then(setPicks).catch(() => setPicks([])) }, [])
  if (picks.length === 0) return null
  return (
    <div>
      <h2 className="h2" style={{ marginBottom: 18 }}>Critics’ <em className="j">picks</em></h2>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: 20 }}>
        {picks.map((p) => (
          <Link key={p.film.id} to={`/films/${p.film.id}`} className="card flat row lift" style={{ borderRadius: 24, padding: 14, alignItems: 'flex-start', gap: 14 }}>
            <div style={{ width: 80, flex: 'none' }}><Frame film={p.film} className="sm plain" plain onClick={() => {}} /></div>
            <div className="col" style={{ gap: 6 }}>
              <span className="hfont" style={{ fontSize: 21, lineHeight: 1.1 }}>{p.film.title}</span>
              <span style={{ font: '400 italic 15px/1.45 var(--font-body)' }}>“{p.blurb}”</span>
              <span className="small"><span className="tag" style={{ background: P.j }}>Critic</span> {p.critic.name}</span>
            </div>
          </Link>))}
      </div>
    </div>
  )
}

export function Upcoming() {
  const [rows, setRows] = useState([])
  const { tick } = useSession()
  useEffect(() => { get('/me/upcoming', { limit: 4 }).then(setRows).catch(() => setRows([])) }, [tick])
  if (rows.length === 0) return null
  return (
    <div className="card flat">
      <div className="row between" style={{ alignItems: 'baseline', marginBottom: 12 }}>
        <h3 className="h3" style={{ fontSize: 30 }}>Coming up</h3>
        <a className="small under muted" href="/api/me/calendar.ics" title="Add to Google Calendar, Apple Calendar or Outlook">add to my calendar</a>
      </div>
      {rows.map((w) => {
        const d = new Date(w.starts_at + 'Z')
        return (
          <Link key={w.id} to={`/clubs/${w.club_id}`} className="row rule-top" style={{ padding: '10px 0', gap: 14 }}>
            <div className="sticker" style={{ width: 54, height: 54, background: P.g, fontSize: 14, flex: 'none' }}><span>{d.toLocaleDateString(undefined, { day: 'numeric' })}<span style={{ display: 'block', fontSize: 11 }}>{d.toLocaleDateString(undefined, { month: 'short' })}</span></span></div>
            <div className="grow"><div className="hfont" style={{ fontSize: 19, lineHeight: 1.1 }}>{w.film.title}</div><div className="small muted">{w.club} · {d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}{w.rsvp ? ' · you are going' : ''}</div></div>
          </Link>)
      })}
    </div>
  )
}

/** How alike you and another person are, from the films you both rated. */
export function MatchCard({ uid }) {
  const [m, setM] = useState(null)
  useEffect(() => { setM(null); get(`/users/${uid}/match`).then(setM).catch(() => setM(null)) }, [uid])
  if (!m) return null
  if (m.score == null) return <div className="card"><h3 className="h3" style={{ fontSize: 30, marginBottom: 8 }}>Taste match</h3><div className="muted">Log a few films each and we will tell you how alike you are.</div></div>
  const color = m.score >= 70 ? P.j : m.score >= 50 ? P.g : P.t
  return (
    <div className="card">
      <h3 className="h3" style={{ fontSize: 30, marginBottom: 14 }}>Taste match</h3>
      <div className="row" style={{ gap: 18 }}>
        <Ring percent={m.score} color={color} size={104} stroke={12}><span className="hfont" style={{ fontSize: 30 }}>{m.score}%</span></Ring>
        <div className="col" style={{ gap: 4 }}>
          <span className="hfont" style={{ fontSize: 24, lineHeight: 1.1 }}>{m.label}</span>
          <span className="small muted">{m.basis === 'ratings' ? `from ${m.rated_together} films you both rated` : 'from the genres you both watch (rate the same films for a sharper score)'}</span>
        </div>
      </div>
      {m.shared_genres.length > 0 && <div className="row wrap" style={{ gap: 6, marginTop: 14 }}>{m.shared_genres.map((g) => <span key={g} className="tag line">{g}</span>)}</div>}
      {m.both_loved.length > 0 && <>
        <div className="kicker rule-top" style={{ margin: '16px 0 10px', paddingTop: 12 }}>You both loved</div>
        <div className="row wrap" style={{ gap: 10 }}>{m.both_loved.map((f) => <div key={f.id} style={{ width: 62 }}><Frame film={f} className="sm" /></div>)}</div>
      </>}
      {m.disagree.length > 0 && <>
        <div className="kicker rule-top" style={{ margin: '16px 0 8px', paddingTop: 12 }}>Where you split</div>
        {m.disagree.map((f) => <div key={f.id} className="row small" style={{ padding: '4px 0', gap: 8 }}><Link to={`/films/${f.id}`} className="hfont grow" style={{ fontSize: 16 }}>{f.title}</Link><span className="starline">{f.you}★</span><span className="muted">vs</span><span className="starline">{f.them}★</span></div>)}
      </>}
    </div>
  )
}

export function FriendsWatched({ filmId }) {
  const { user, tick } = useSession()
  const [d, setD] = useState(null)
  useEffect(() => { if (user) get(`/films/${filmId}/friends`).then(setD).catch(() => setD(null)); else setD(null) }, [filmId, user, tick])
  if (!user || !d) return null
  return (
    <div className="card flat">
      <h3 className="h3" style={{ marginBottom: 6 }}>Friends who watched</h3>
      {d.count === 0 ? <div className="small muted">Nobody you follow has logged this yet.</div> : <>
        <div className="small muted" style={{ marginBottom: 8 }}>{d.count} {d.count === 1 ? 'person' : 'people'} you follow{d.avg != null && ` · average ★ ${fmt(d.avg)}`}</div>
        {d.friends.map((f) => (
          <div key={f.user_id} className="row rule-top" style={{ padding: '8px 0', gap: 10 }}>
            <Avatar name={f.name} id={f.user_id} avatar={f.avatar} size={34} to={`/users/${f.user_id}`} />
            <Link to={`/users/${f.user_id}`} className="hfont grow" style={{ fontSize: 18 }}>{f.name}{f.reviewed && <span className="small muted" style={{ fontFamily: 'var(--font-body)', fontWeight: 400 }}> · reviewed</span>}</Link>
            <span className="starline">{f.stars ? starText(f.stars) : <span className="small muted">no rating</span>}</span>
          </div>))}
      </>}
    </div>
  )
}

/** Critics' score next to everyone else's: the same diary data, split by role. */
export function SplitScore({ split }) {
  if (!split) return null
  const cell = (label, s, color) => (
    <div className="col" style={{ gap: 2, alignItems: 'center', flex: 1 }}>
      <span style={{ font: '400 44px/1 var(--font-heading)' }}>{fmt(s.avg)}</span>
      <span className="tag" style={{ background: color }}>{label}</span>
      <span className="small muted">{s.n} rating{s.n === 1 ? '' : 's'}</span>
    </div>
  )
  return <div className="row rule-top" style={{ paddingTop: 12, marginTop: 12 }}>{cell('Viewers', split.viewers, P.g)}{cell('Critics', split.critics, P.j)}</div>
}

/** The critic's own pick box on a film page (only rendered for people holding critic.pick). */
export function PickEditor({ film, onSaved }) {
  const { flash } = useSession()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const save = async () => { try { await put(`/films/${film.id}/pick`, { blurb: text }); flash('Your pick is live'); setOpen(false); onSaved() } catch (e) { flash(e.message, 'err') } }
  const drop = async () => { try { await del(`/films/${film.id}/pick`); flash('Pick removed'); onSaved() } catch (e) { flash(e.message, 'err') } }
  return (
    <div className="card flat" style={{ background: 'var(--tint)' }}>
      <div className="row between"><h3 className="h3" style={{ fontSize: 26 }}>Critic’s pick</h3>{film.my_pick && <button className="small under muted" onClick={drop}>remove mine</button>}</div>
      {!open ? <button className="pill ink sm" style={{ marginTop: 10 }} onClick={() => setOpen(true)}>{film.my_pick ? 'Edit my pick' : 'Recommend this film'}</button> : (
        <div className="col" style={{ gap: 10, marginTop: 10 }}>
          <textarea className="input" style={{ minHeight: 80 }} maxLength={280} value={text} onChange={(e) => setText(e.target.value)} placeholder="One or two sentences. No spoilers: everyone will see this." />
          <div className="row"><button className={'pill ink sm' + (text.trim().length >= 10 ? '' : ' off')} onClick={save}>Publish</button><button className="pill ghost sm" onClick={() => setOpen(false)}>Cancel</button></div>
        </div>)}
    </div>
  )
}

/** Apply to become a critic, or see where the application stands. */
export function CriticPanel() {
  const { flash, refresh, tick } = useSession()
  const [s, setS] = useState(null)
  const [statement, setStatement] = useState('')
  const [links, setLinks] = useState('')
  const load = useCallback(() => get('/me/critic').then(setS).catch(() => setS(null)), [])
  useEffect(() => { load() }, [load, tick])
  if (!s) return null
  const app = s.application
  const submit = async (e) => {
    e.preventDefault()
    try { await post('/critics/apply', { statement, links }); flash('Application sent. A moderator will take a look.'); setStatement(''); setLinks(''); load() } catch (ex) { flash(ex.message, 'err') }
  }
  const withdraw = async () => { try { await del('/critics/apply'); flash('Application withdrawn'); load() } catch (ex) { flash(ex.message, 'err') } }
  const bar = (label, p) => (
    <div key={label}>
      <div className="row between small"><span>{label}</span><span className="muted">{Math.min(p.have, p.need)} / {p.need}</span></div>
      <div className="meter" style={{ height: 7 }}><div style={{ width: `${Math.min(100, (100 * p.have) / p.need)}%`, background: P.j }} /></div>
    </div>
  )
  return (
    <div className="card" style={s.is_critic ? { background: P.j } : undefined}>
      <h3 className="h3" style={{ fontSize: 32, marginBottom: 10 }}>{s.is_critic ? 'You are a critic' : 'Become a critic'}</h3>
      {s.is_critic ? (
        <div className="col" style={{ gap: 8 }}>
          <div>Your reviews carry a Critic badge, your ratings count in the critic score on every film, and you can publish a pick on any film page.</div>
          <button className="small under muted" style={{ alignSelf: 'flex-start' }} onClick={refresh}>refresh</button>
        </div>
      ) : app && app.state === 'pending' ? (
        <div className="col" style={{ gap: 10 }}>
          <div className="lede" style={{ fontSize: 19 }}>Your application is waiting for a moderator.</div>
          <div className="small muted">Sent {new Date(app.created_at + 'Z').toLocaleDateString()}</div>
          <button className="pill out sm" style={{ alignSelf: 'flex-start' }} onClick={withdraw}>Withdraw</button>
        </div>
      ) : (
        <div className="col" style={{ gap: 12 }}>
          {app && app.state === 'rejected' && <div className="small" style={{ padding: '10px 14px', borderRadius: 14, background: 'var(--tint)' }}><b>Not approved this time.</b> {app.note}</div>}
          <div className="muted">Critics are verified by a moderator. They get a badge, their own score on each film and the right to publish picks.</div>
          {bar('Films logged', s.progress.films)}{bar('Reviews published', s.progress.reviews)}
          {s.progress.eligible ? (
            <form className="col" style={{ gap: 10 }} onSubmit={submit}>
              <textarea className="input" style={{ minHeight: 96 }} minLength={40} maxLength={1500} required value={statement} onChange={(e) => setStatement(e.target.value)} placeholder="Why should we verify you? Where have you written about film? (40+ characters)" />
              <input className="input" maxLength={300} value={links} onChange={(e) => setLinks(e.target.value)} placeholder="Links to your writing (optional)" />
              <div><button className="pill ink sm">Apply</button></div>
            </form>
          ) : <div className="small muted">Reach both targets and the application opens.</div>}
        </div>
      )}
    </div>
  )
}
