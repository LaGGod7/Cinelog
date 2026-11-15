import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { del, get, put } from '../api.js'
import { clickable, FilmSearch, Frame, Icon, P, Poster, Seg, fmt, starText, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'

const PAGE = 24
const DOTS = [P.c, P.t, P.g, P.j, P.m, P.v]

export default function Discover() {
  const { user, flash, openLog, refreshStats, tick } = useSession()
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [genres, setGenres] = useState([])
  const [genre, setGenre] = useState('')
  const [decade, setDecade] = useState('')
  const [sort, setSort] = useState('popular')
  const [q, setQ] = useState('')
  const [data, setData] = useState({ total: 0, films: [] })
  const [results, setResults] = useState(null) // search results when a query is typed
  const [searching, setSearching] = useState(false) // a slow lookup (new films come from TMDB) shows a hint instead of nothing
  const [feat, setFeat] = useState(null)
  const [spinning, setSpinning] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => { get('/genres').then((g) => setGenres(g.slice(0, 9))).catch(() => {}) }, [])
  const load = useCallback(async (offset = 0) => {
    const d = await get('/films', { genre, decade, sort, limit: PAGE, offset })
    setData((cur) => (offset ? { total: d.total, films: [...cur.films, ...d.films] } : d))
    if (!offset) setFeat((f) => f && d.films.some((x) => x.id === f.id) ? d.films.find((x) => x.id === f.id) : d.films[0] || null)
    setLoading(false)
  }, [genre, decade, sort])
  useEffect(() => { load(0).catch((e) => { flash(e.message, 'err'); setLoading(false) }) }, [load, tick])
  useEffect(() => {
    if (!q.trim()) { setResults(null); setSearching(false); return }
    let stale = false // ignore an older, slower answer
    const t = setTimeout(() => {
      setSearching(true)
      get('/films/search', { q }).then((r) => { if (!stale) { setResults(r); setSearching(false) } }).catch(() => { if (!stale) { setResults([]); setSearching(false) } })
    }, 220)
    return () => { stale = true; clearTimeout(t) }
  }, [q])

  const spin = () => {
    const pool = data.films; if (spinning || pool.length < 2) return
    let n = 0; setSpinning(true)
    const iv = setInterval(() => { n++; setFeat(pool[Math.floor(Math.random() * pool.length)]); if (n > 12) { clearInterval(iv); setSpinning(false) } }, 75)
  }
  const toggle = async (f, e) => {
    e && e.stopPropagation()
    if (!user) { nav('/login'); return }
    try {
      f.on_watchlist ? await del(`/watchlist/${f.id}`) : await put(`/watchlist/${f.id}`)
      const on = !f.on_watchlist
      setData((d) => ({ ...d, films: d.films.map((x) => (x.id === f.id ? { ...x, on_watchlist: on } : x)) }))
      setFeat((x) => (x && x.id === f.id ? { ...x, on_watchlist: on } : x))
      flash(on ? `${f.title} added to your watchlist` : 'Removed from watchlist'); refreshStats()
    } catch (ex) { flash(ex.message, 'err') }
  }
  const list = results ?? data.films
  const ft = feat ? tone(feat.id) : null

  return (
    <div>
      <div className="two pad" style={{ paddingTop: 36, paddingBottom: 36 }}>
        <div>
          <div className="display" style={{ fontSize: 'clamp(48px,7.4vw,96px)' }}>Find your next <em className="m">favourite</em> film.</div>
          <div style={{ marginTop: 30 }}>
            <FilmSearch value={q} onValue={setQ} onPick={(h) => nav(`/films/${h.id}`)} placeholder="Search by title" autoFocus={params.get('focus') === '1'} />
          </div>
          {genres.length > 0 && <>
            <div className="kicker" style={{ margin: '30px 0 12px' }}>I’m in the mood for…</div>
            <div className="row wrap" style={{ gap: 10 }}>
              {[{ genre: '' }, ...genres].map((g, i) => {
                const on = genre === g.genre, c = i === 0 ? '#201f1d' : DOTS[(i - 1) % 6], lightC = c === P.g || c === P.j
                return (
                  <button key={g.genre || 'all'} className="pill pop" onClick={() => setGenre(g.genre)}
                    style={{ padding: '10px 18px 10px 12px', background: on ? c : undefined, color: on && !lightC ? '#fffdf8' : undefined, boxShadow: on ? '0 4px 0 #201f1d, var(--line)' : undefined, transform: on ? 'translateY(-2px)' : undefined }}>
                    <span style={{ width: 18, height: 18, borderRadius: '50%', background: i === 0 ? `conic-gradient(${P.m},${P.g},${P.j},${P.c},${P.m})` : c, boxShadow: '0 0 0 2px #fffdf8' }} />
                    {g.genre || 'Everything'}
                  </button>
                )
              })}
            </div>
          </>}
        </div>
        {feat && (
          <div className="feat" style={{ background: ft.bg, color: ft.fg }}>
            <Frame film={feat} top={feat.year} style={{ boxShadow: 'var(--line)', alignSelf: 'start' }} />
            <div className="col" style={{ minWidth: 0 }}>
              <div className="kicker" style={{ color: 'inherit' }}>{spinning ? 'Spinning the reel…' : 'Tonight’s pick'}</div>
              <div style={{ font: '400 clamp(32px,3.4vw,48px)/.95 var(--font-heading)', letterSpacing: '-.03em', cursor: 'pointer' }} {...clickable(() => nav(`/films/${feat.id}`), 'link')}>{feat.title}</div>
              <div>{[feat.year, feat.runtime && `${feat.runtime} min`, ...(feat.genres || []).slice(0, 2)].filter(Boolean).join(' · ')}</div>
              <div className="row" style={{ alignItems: 'baseline', gap: 10 }}><span style={{ font: '400 44px/1 var(--font-heading)' }}>{fmt(feat.rating)}</span><span style={{ fontSize: 20, letterSpacing: 3 }}>{starText(feat.rating)}</span></div>
              <div className="lede" style={{ fontSize: 20, display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{feat.overview}</div>
              <div className="row wrap" style={{ gap: 10, marginTop: 'auto' }}>
                <button className="pill ink" onClick={spin}><Icon name="spin" size={17} />Spin again</button>
                <button className={'pill out' + (feat.on_watchlist ? ' on' : '')} style={{ color: '#201f1d' }} onClick={(e) => toggle(feat, e)}>{feat.on_watchlist ? '✓ On watchlist' : '+ Watchlist'}</button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="row wrap" style={{ margin: '0 var(--pad)', padding: '16px 0', gap: 22, borderTop: '1.5px solid #201f1d', borderBottom: '1px solid rgba(32,31,29,.16)' }}>
        <span className="kicker">Decade</span>
        <Seg value={decade} onChange={setDecade} options={[['', 'All'], ['2020', '2020s'], ['2010', '2010s'], ['2000', '2000s'], ['1990', '1990s']]} />
        <span className="kicker" style={{ marginLeft: 16 }}>Sort</span>
        <div className="row" style={{ gap: 18 }}>
          {[['popular', 'Trending'], ['top', 'Top rated'], ['new', 'Newest']].map(([k, t]) => (
            <button key={k} className="hfont" onClick={() => setSort(k)} style={{ fontSize: 16, paddingBottom: 3, borderBottom: `2.5px solid ${sort === k ? P.m : 'transparent'}`, color: sort === k ? '#201f1d' : '#7d7979' }}>{t}</button>
          ))}
        </div>
        <span className="end lede" style={{ fontSize: 18 }}>{searching ? 'Searching…' : results ? `${results.length} match${results.length === 1 ? '' : 'es'}` : `${data.total} film${data.total === 1 ? '' : 's'}`}</span>
      </div>

      <div className="pad" style={{ paddingTop: 28 }}>
        {!loading && list.length === 0 && <div className="empty">{results ? 'No film by that name. Try fewer letters.' : 'Nothing in that corner yet. Try another mood or decade.'}</div>}
        <div className="grid">
          {list.map((f) => (
            <div key={f.id} className="fcard" {...clickable(() => nav(`/films/${f.id}`), 'link')}>
              <div className="frame hov" style={{ position: 'relative' }}>
                <Poster film={f} top={f.year} />
                <div className="over">
                  <div className="row" style={{ alignItems: 'baseline', gap: 6 }}><span style={{ font: '400 38px/1 var(--font-heading)' }}>{fmt(f.rating)}</span><span style={{ color: P.g, letterSpacing: 1, fontSize: 13 }}>{starText(f.rating)}</span></div>
                  <p>{f.overview}</p>
                  <div className="col" style={{ gap: 6, marginTop: 'auto' }}>
                    {'on_watchlist' in f && <button className="pill xs" style={{ background: f.on_watchlist ? P.g : '#fffdf8', color: '#201f1d', padding: 8 }} onClick={(e) => toggle(f, e)}>{f.on_watchlist ? '✓ Saved' : '+ Watchlist'}</button>}
                    <button className="pill xs" style={{ boxShadow: 'inset 0 0 0 1.5px #fffdf8', padding: 7 }} onClick={(e) => { e.stopPropagation(); openLog({ film: f }) }}>Rate &amp; review</button>
                  </div>
                </div>
              </div>
              {f.on_watchlist && <div className="sticker saved-badge">Saved</div>}
              <div className="row between" style={{ alignItems: 'baseline', gap: 8 }}><span className="hfont" style={{ fontSize: 18, lineHeight: 1.15 }}>{f.title}</span><span style={{ flex: 'none', fontSize: 14 }}>{f.rating != null ? `★ ${fmt(f.rating)}` : ''}</span></div>
              <span className="small muted" style={{ marginTop: -6 }}>{[f.year, (f.genres || [])[0]].filter(Boolean).join(' · ')}</span>
            </div>
          ))}
        </div>
        {!results && data.films.length < data.total && <div className="center" style={{ marginTop: 34 }}><button className="pill pop" onClick={() => load(data.films.length)}>Show more films</button></div>}
      </div>
    </div>
  )
}
