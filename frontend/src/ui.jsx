import React, { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { del, get, posterUrl, put } from './api.js'

// ---- palette (same six inks as the design) ----
export const P = { m: 'oklch(0.62 0.23 350)', t: 'oklch(0.66 0.21 32)', g: 'oklch(0.84 0.16 85)', j: 'oklch(0.72 0.14 170)', c: 'oklch(0.52 0.2 265)', v: 'oklch(0.55 0.2 300)' }
const KEYS = ['m', 't', 'g', 'j', 'c', 'v']
/** Props that make a non-button element behave like one: focusable, announced as a button/link, Enter/Space activate it. */
export const clickable = (fn, role = 'button') => ({
  onClick: fn, role, tabIndex: 0,
  onKeyDown: (e) => { if (e.target !== e.currentTarget) return; if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(e) } },
})
export const INK = '#201f1d', PAPER = '#fffdf8'
const light = (k) => k === 'g' || k === 'j'
export const fgOn = (k) => (light(k) ? INK : PAPER)
const SH = [['-20%', '45%', '90%', '50%'], ['40%', '-10%', '80%', '0'], ['10%', '12%', '55%', '50%'], ['-30%', '-20%', '100%', '50%'], ['30%', '30%', '120%', '0'], ['50%', '8%', '40%', '50%']]
/** Stable colours for anything with a numeric id (films, users, clubs). */
export function tone(id = 0, salt = 0) {
  const n = Math.abs(Number(id) * 7 + salt) % 6
  const bgK = KEYS[n], acK = KEYS[(n + 2 + (Math.abs(Number(id)) % 3)) % 6]
  return { bgK, bg: P[bgK], ac: P[acK === bgK ? KEYS[(n + 1) % 6] : acK], fg: fgOn(bgK), sh: SH[Math.abs(Number(id)) % 6] }
}
export const starText = (r) => (r ? '★'.repeat(Math.floor(r)) + (r % 1 >= 0.5 ? '½' : '') : '')
export const fmt = (r) => (r == null ? '–' : Number(r).toFixed(1))
export const ago = (ts) => {
  const s = Math.max(1, Math.floor(Date.now() / 1000 - ts))
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export const Icon = ({ name, size = 16 }) => {
  const paths = {
    search: <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>,
    plus: <><path d="M5 12h14" /><path d="M12 5v14" /></>,
    mark: <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z" />,
    spin: <><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" style={{ flex: 'none', fill: 'none', stroke: 'currentColor', strokeWidth: name === 'plus' ? 2.5 : 2, strokeLinecap: 'round', strokeLinejoin: 'round' }}>{paths[name]}</svg>
}
export const Flame = ({ size = 26 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ flex: 'none', fill: P.g, stroke: PAPER, strokeWidth: 1.5, strokeLinejoin: 'round' }}>
    <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z" /></svg>
)

/** Film poster: the real TMDB image when the catalogue has one, otherwise the generated colour-block poster. */
export function Poster({ film, top, plain }) {
  const id = film.id ?? film.film_id ?? 0
  const t = tone(id)
  const url = posterUrl(film.poster)
  return (
    <span className="poster" style={{ background: t.bg, color: t.fg }}>
      {url ? <img src={url} alt={film.title} loading="lazy" /> : <>
        {!plain && <span className="shape" style={{ left: t.sh[0], top: t.sh[1], width: t.sh[2], borderRadius: t.sh[3], background: t.ac }} />}
        <span className="cap">{top != null && <small>{top}</small>}<b>{film.title}</b></span>
      </>}
    </span>
  )
}
export function Frame({ film, to, className = '', style, top, onClick, plain }) {
  const nav = useNavigate()
  const id = film.id ?? film.film_id
  return (
    <div className={'frame ' + className} style={style} {...clickable(onClick || (() => nav(to || `/films/${id}`)))}>
      <Poster film={film} top={top} plain={plain} />
    </div>
  )
}
/** Profile pictures are a fixed set of icons (no uploads: nothing to scan, store or moderate). Keys match the API. */
export const AVATARS = { reel: '🎞️', popcorn: '🍿', clapper: '🎬', camera: '🎥', ticket: '🎟️', mask: '🎭', star: '⭐', projector: '📽️', ghost: '👻', robot: '🤖', rocket: '🚀', cat: '🐱' }
export function Avatar({ name = '?', id = 0, size = 44, to, onClick, style, avatar }) {
  const nav = useNavigate()
  return (
    <div className="avatar" title={name} {...(onClick || to ? clickable(onClick || (() => nav(to)), to ? 'link' : 'button') : {})}
      style={{ width: size, height: size, fontSize: size * 0.43, background: tone(id, 3).bg === P.c || tone(id, 3).bg === P.v ? P.j : tone(id, 3).bg, ...style }}>
      {AVATARS[avatar] ? <span aria-hidden="true" style={{ fontStyle: 'normal', fontSize: size * 0.5 }}>{AVATARS[avatar]}</span> : (name || '?').trim()[0]?.toUpperCase()}
    </div>
  )
}
/** Half-star rating, as in the design: each star has a left and a right hit area. */
export function Stars({ value = 0, onChange, size = 34 }) {
  const [hov, setHov] = useState(null)
  const v = hov ?? value ?? 0
  return (
    <span className={'stars' + (onChange ? ' live' : '')} style={{ fontSize: size }} onMouseLeave={() => setHov(null)}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i}>★<b style={{ width: v >= i + 1 ? '100%' : v >= i + 0.5 ? '50%' : '0%' }}>★</b>
          {onChange && <><i className="l" onMouseEnter={() => setHov(i + 0.5)} onClick={() => onChange(i + 0.5)} /><i className="r" onMouseEnter={() => setHov(i + 1)} onClick={() => onChange(i + 1)} /></>}
        </span>
      ))}
    </span>
  )
}
export const rateLabel = (v) => (v ? ['', 'Not for me', 'Had its moments', 'Good', 'Really liked it', 'All-time favourite'][Math.ceil(v)] : 'Tap a star to rate')
export function Seg({ value, onChange, options }) {
  return <div className="seg">{options.map(([k, t]) => <button key={k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>{t}</button>)}</div>
}
export function Switch({ on, onChange, children }) {
  return <span className={'switch' + (on ? ' on' : '')} {...clickable(() => onChange(!on), 'switch')} aria-checked={on}><i />{children}</span>
}
/** Film search box with the Trie-backed autocomplete. */
export function FilmSearch({ onPick, placeholder = 'Start typing a film title…', value, onValue, autoFocus, className = 'field', children }) {
  const [inner, setInner] = useState('')
  const q = value ?? inner, setQ = onValue ?? setInner
  const [hits, setHits] = useState([])
  const [open, setOpen] = useState(false)
  const timer = useRef()
  useEffect(() => {
    clearTimeout(timer.current)
    if (q.trim().length < 1) { setHits([]); return }
    let stale = false // a slower, older answer (e.g. one that had to ask TMDB) must not overwrite the newer one
    timer.current = setTimeout(() => get('/films/autocomplete', { q }).then((h) => { if (!stale) setHits(h) }).catch(() => { if (!stale) setHits([]) }), 140)
    return () => { stale = true; clearTimeout(timer.current) }
  }, [q])
  return (
    <div className="ac">
      <div className={className}>
        <Icon name="search" size={20} />
        <input value={q} autoFocus={autoFocus} placeholder={placeholder} onChange={(e) => { setQ(e.target.value); setOpen(true) }}
          onBlur={() => setTimeout(() => setOpen(false), 180)} onFocus={() => setOpen(true)} />
        {children}
      </div>
      {open && hits.length > 0 && (
        <ul className="ac-list">{hits.map((h) => <li key={h.id} onMouseDown={() => { onPick(h); setOpen(false) }}>{h.title} <span>{h.year}</span></li>)}</ul>
      )}
    </div>
  )
}
export function Radar({ data, size = 260 }) {
  const keys = ['story', 'acting', 'visuals', 'music', 'pacing']
  const c = size / 2, r = size / 2 - 40
  const pt = (i, v) => { const a = (Math.PI * 2 * i) / keys.length - Math.PI / 2; return [c + Math.cos(a) * r * (v / 5), c + Math.sin(a) * r * (v / 5)] }
  return (
    <svg width="100%" viewBox={`0 0 ${size} ${size}`} style={{ maxWidth: size, display: 'block', margin: '0 auto' }}>
      {[1, 2, 3, 4, 5].map((l) => <polygon key={l} points={keys.map((_, i) => pt(i, l).join(',')).join(' ')} fill={l === 5 ? '#f3ead9' : 'none'} stroke="rgba(32,31,29,.2)" />)}
      <polygon points={keys.map((k, i) => pt(i, data[k] || 0).join(',')).join(' ')} fill={P.m} fillOpacity=".35" stroke={INK} strokeWidth="1.5" />
      {keys.map((k, i) => { const [x, y] = pt(i, 6.1); return <text key={k} x={x} y={y} textAnchor="middle" dominantBaseline="middle" style={{ font: '600 15px var(--font-heading)', textTransform: 'capitalize' }}>{k}</text> })}
    </svg>
  )
}

/** A review's text. Blurred sentences are never in the page: the text is fetched when the reader presses Show spoiler. */
function Sentence({ rid, seg }) {
  const [text, setText] = useState(null)
  if (!seg.blurred) return <span>{seg.text} </span>
  if (text != null) return <span className="seg-shown">{text} </span>
  const n = Math.max(12, Math.min(seg.length, 140))
  const reveal = async () => { try { setText(seg.text ?? (await get(`/reviews/${rid}/segments/${seg.idx}`)).text) } catch { /* stays hidden */ } }
  return <><span className="seg-blur" aria-hidden="true">{'the quiet light moved over water '.repeat(Math.ceil(n / 33)).slice(0, n)}</span><span className="spoil" {...clickable(reveal)}>Show spoiler</span></>
}
export function ReviewText({ review }) {
  const reasons = [...new Set(review.segments.flatMap((s) => s.reasons || []))]
  if (review.state === 'pending_scan') return <p className="muted"><i>{review.message}</i></p>
  return (
    <>
      {review.warn && <div className="small" style={{ marginBottom: 6, fontStyle: 'italic' }} title="The spoiler shield is not sure: nothing is hidden, but this review may give away the plot.">⚠ Possible spoilers</div>}
      <p>{review.segments.map((s) => <Sentence key={s.idx} rid={review.id} seg={s} />)}</p>
      {review.reports !== undefined && reasons.length > 0 && <div className="small muted">Blurred for readers because: {reasons.join(' · ')}</div>}
    </>
  )
}
export const ClubChip = ({ club, small }) => {
  const t = tone(club.id, 1)
  return (
    <Link to={`/clubs/${club.id}`} className={'chip' + (small ? ' sm' : '')} style={{ background: t.bg, color: t.fg }}>
      <span className="dot">{club.name[0]}</span>{club.name}{club.members != null && <span style={{ font: '400 14px var(--font-body)' }}>{club.members}</span>}
    </Link>
  )
}

/** Heart / upvote for anything likeable (kind = review | list | thread). Optimistic, then settles on the server count. */
export function LikeBtn({ kind, id, likes = 0, liked = false, canLike = true, own = false, onNeedLogin, variant = 'heart' }) {
  const [st, setSt] = useState({ likes, liked })
  useEffect(() => setSt({ likes, liked }), [likes, liked, id])
  const toggle = async (e) => {
    e.stopPropagation(); e.preventDefault()
    if (own) return
    if (!canLike) { onNeedLogin && onNeedLogin(); return }
    const next = !st.liked
    setSt({ liked: next, likes: st.likes + (next ? 1 : -1) })
    try { const r = await (next ? put : del)(`/likes/${kind}/${id}`); setSt({ liked: r.liked, likes: r.likes }) } catch { setSt(st) }
  }
  if (own) return <span className="row small" title="You can't like your own" style={{ gap: 6, color: '#605d5d', font: '400 14px var(--font-body)' }}>♥ {st.likes}</span>
  if (variant === 'vote') return (
    <span className="col" style={{ alignItems: 'center', gap: 2 }}>
      <button onClick={toggle} aria-pressed={st.liked} aria-label="Upvote" className="lift" style={{ width: 40, height: 34, borderRadius: 12, display: 'grid', placeItems: 'center', background: st.liked ? P.m : PAPER, color: st.liked ? PAPER : INK, boxShadow: 'var(--line)', fontSize: 14 }}>▲</button>
      <span className="hfont" style={{ fontSize: 20 }}>{st.likes}</span>
    </span>)
  if (variant === 'pill') return <button onClick={toggle} aria-pressed={st.liked} className="pill sm" style={{ background: st.liked ? P.m : PAPER, color: st.liked ? PAPER : INK, boxShadow: 'var(--line)', padding: '6px 12px', fontSize: 14 }}>♥ {st.likes}</button>
  return (
    <button onClick={toggle} aria-pressed={st.liked} className="row" style={{ gap: 6, color: st.liked ? P.m : '#605d5d', font: '400 14px var(--font-body)' }}>
      <svg width="16" height="16" viewBox="0 0 24 24" style={{ fill: st.liked ? P.m : 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinejoin: 'round' }}><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" /></svg>{st.likes}
    </button>)
}
const ROT = ['6deg', '-8deg', '4deg', '-5deg', '7deg', '-3deg']
/** A badge as a round sticker: filled when earned, pale outline while in progress. */
export function BadgeDot({ badge, size = 52, k = 0, label }) {
  const on = badge.earned, key = badge.color
  return (
    <div title={`${badge.name}: ${badge.description}${on ? '' : ` (${badge.value} / ${badge.target})`}`} className="sticker"
      style={{ flex: 'none', width: size, height: size, padding: size > 70 ? 8 : 0, background: on ? P[key] : '#f3ead9', color: on ? fgOn(key) : '#7d7979',
        boxShadow: on ? '0 3px 0 #201f1d, var(--line)' : 'inset 0 0 0 1.5px rgba(32,31,29,.3)', transform: on ? `rotate(${ROT[k % 6]})` : 'none', fontSize: label ? Math.max(13, size * 0.18) : size * 0.4 }}>
      {label ? badge.name : badge.name[0]}
    </div>)
}

/** Shown when a page's data could not be loaded (instead of an endless "Loading…"). */
export function LoadError({ error, onRetry }) {
  const gone = error && error.status === 404
  return (
    <div className="pad" style={{ paddingTop: 40 }}>
      <div className="card" style={{ padding: 24, maxWidth: 520 }}>
        <h2 className="hfont" style={{ margin: '0 0 8px' }}>{gone ? "We couldn't find that" : 'Something went wrong'}</h2>
        <p className="muted" style={{ margin: '0 0 16px' }}>{gone ? 'It may have been removed, or the link is wrong.' : (error && error.message) || 'The server did not answer.'}</p>
        <div className="row" style={{ gap: 10 }}>
          {!gone && onRetry && <button className="pill ink" onClick={onRetry}>Try again</button>}
          <Link className="pill out" to="/">Go home</Link>
        </div>
      </div>
    </div>)
}
