import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get } from '../api.js'
import { Frame, LoadError, P, Seg, fmt } from '../ui.jsx'
import { Ring } from '../widgets.jsx'
import { useSession } from '../App.jsx'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function Bars({ values, labels, color, height = 110, hi }) {
  const max = Math.max(1, ...values)
  return (
    <div className="row" style={{ gap: 6, alignItems: 'flex-end', height: height + 22 }}>
      {values.map((v, i) => (
        <div key={i} className="col center" style={{ flex: 1, gap: 4, alignItems: 'center', justifyContent: 'flex-end', height: '100%' }} title={`${labels[i]}: ${v}`}>
          <span className="small muted" style={{ fontSize: 11, minHeight: 14 }}>{v || ''}</span>
          <div style={{ width: '100%', height: Math.max(3, (v / max) * height), borderRadius: '8px 8px 2px 2px', background: i === hi ? P.m : color, boxShadow: 'inset 0 0 0 1.5px #201f1d' }} />
          <span className="small" style={{ fontSize: 12 }}>{labels[i]}</span>
        </div>))}
    </div>
  )
}

function Big({ label, value, note, bg, fg = '#201f1d', rot }) {
  return <div className="stat" style={{ background: bg, color: fg, transform: `rotate(${rot})` }}><div className="kicker" style={{ color: 'inherit' }}>{label}</div><b>{value}</b>{note && <div className="lede" style={{ fontSize: 17 }}>{note}</div>}</div>
}

export default function Year() {
  const { user, flash } = useSession()
  const [year, setYear] = useState(null)
  const [r, setR] = useState(null)
  const [err, setErr] = useState(null)
  const load = (y) => get('/me/year', y ? { year: y } : {}).then((d) => { setErr(null); setR(d); setYear(d.year) }).catch(setErr)
  useEffect(() => { load() }, [])
  if (err) return <LoadError error={err} onRetry={() => load(year)} />
  if (!r) return <div className="pad muted" style={{ paddingTop: 40 }}>Loading…</div>
  const copy = async () => { try { await navigator.clipboard.writeText(r.share); flash('Copied. Paste it anywhere.') } catch { flash('Could not copy: select the text on the page instead', 'err') } }
  const years = r.years.length ? r.years : [r.year]

  return (
    <div className="pad" style={{ paddingTop: 28 }}>
      <div className="row wrap between" style={{ gap: 20, alignItems: 'flex-end', marginBottom: 26 }}>
        <div>
          <div className="kicker" style={{ marginBottom: 10 }}>{user.display_name}’s</div>
          <div className="display" style={{ fontSize: 'clamp(46px,7vw,96px)' }}>{r.year} <em className="m">in film</em></div>
        </div>
        <div className="row wrap">
          {years.length > 1 && <Seg value={r.year} onChange={(y) => load(y)} options={years.map((y) => [y, String(y)])} />}
          {!r.empty && <button className="pill out sm" onClick={copy}>Copy summary</button>}
          {!r.empty && <button className="pill out sm" onClick={() => window.print()}>Save as PDF</button>}
        </div>
      </div>

      {r.empty ? (
        <div className="empty"><div style={{ marginBottom: 16 }}>Nothing logged in {r.year} yet.</div><Link to="/discover" className="pill ink sm">Find a film to start</Link></div>
      ) : (<>
        <div className="hero" style={{ background: P.c, color: '#fffdf8', padding: 'clamp(24px,4vw,56px)', marginBottom: 36 }}>
          <div className="blob" style={{ right: -120, top: -160, width: 520, height: 520, background: P.m, opacity: .7 }} />
          <div className="blob" style={{ left: -80, bottom: -200, width: 420, height: 420, background: P.t, opacity: .8 }} />
          <div style={{ position: 'relative' }}>
            <div className="kicker" style={{ color: 'inherit' }}>Your film personality</div>
            <div className="display" style={{ fontSize: 'clamp(40px,6vw,84px)', margin: '8px 0 14px' }}>{r.persona.title}</div>
            <div className="lede" style={{ maxWidth: 560 }}>{r.persona.blurb}</div>
          </div>
        </div>

        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: 20, marginBottom: 44 }}>
          <Big label="Films" value={r.films} note={r.rewatches ? `${r.rewatches} rewatch${r.rewatches === 1 ? '' : 'es'}` : 'all first watches'} bg={P.m} fg="#fffdf8" rot="-1.5deg" />
          <Big label="Hours" value={r.hours} note={r.days_equivalent >= 1 ? `${r.days_equivalent} days, nonstop` : 'of other people’s stories'} bg={P.g} rot="1deg" />
          <Big label="Average" value={fmt(r.avg_stars)} note={`${r.rated} rated`} bg={P.j} rot="-.5deg" />
          <Big label="Best streak" value={r.longest_streak} note={r.longest_streak === 1 ? 'day' : 'days in a row'} bg={P.t} fg="#fffdf8" rot="1.5deg" />
        </div>

        {r.top_films.length > 0 && <>
          <h2 className="h2" style={{ marginBottom: 20 }}>Your top <em className="m">{r.top_films.length}</em></h2>
          <div className="grid four" style={{ marginBottom: 48 }}>
            {r.top_films.map((f, i) => (
              <div key={f.id} className="col" style={{ gap: 8, position: 'relative' }}>
                <Frame film={f} className="hov" style={{ transform: `rotate(${['-2deg', '1.5deg', '-1deg', '2deg', '-1.5deg'][i]})` }} />
                <div className="sticker" style={{ position: 'absolute', left: -10, top: -12, width: 44, height: 44, background: P.g, fontSize: 22, padding: 0 }}>{i + 1}</div>
                <span className="starline center">{'★'.repeat(Math.floor(f.stars))}{f.stars % 1 ? '½' : ''}</span>
              </div>))}
          </div>
        </>}

        <div className="grid cards" style={{ marginBottom: 40 }}>
          <div className="card flat col">
            <h3 className="h3">Month by month</h3>
            <Bars values={r.by_month} labels={MONTHS} color={P.c} hi={MONTHS.indexOf(r.busiest_month)} />
            <div className="small muted">Busiest: {r.busiest_month}</div>
          </div>
          <div className="card flat col">
            <h3 className="h3">Days of the week</h3>
            <Bars values={r.by_weekday} labels={DAYS} color={P.j} hi={DAYS.indexOf(r.busiest_weekday)} />
            <div className="small muted">You watch most on {r.busiest_weekday}s</div>
          </div>
          <div className="card flat col">
            <h3 className="h3">Genres</h3>
            {r.genres.map((g, i) => (
              <div key={g.name}><div className="row between small"><span>{g.name}</span><span className="muted">{g.n}</span></div>
                <div className="meter" style={{ height: 10 }}><div style={{ width: `${(100 * g.n) / r.genres[0].n}%`, background: [P.m, P.t, P.g, P.j, P.c, P.v][i % 6] }} /></div></div>))}
          </div>
          <div className="card flat col">
            <h3 className="h3">How you watch</h3>
            <div className="row" style={{ gap: 20 }}>
              <Ring percent={Math.round(r.big_screen_share * 100)} size={110} color={P.t}><span className="hfont" style={{ fontSize: 26 }}>{Math.round(r.big_screen_share * 100)}%</span></Ring>
              <div className="col" style={{ gap: 4 }}>
                {Object.entries(r.formats).map(([k, v]) => <div key={k} className="small"><b className="hfont" style={{ fontSize: 18 }}>{v}</b> {k === 'OTT' ? 'at home' : k}</div>)}
                <div className="small muted">on the big screen</div>
              </div>
            </div>
            {r.top_decade && <div className="small">Favourite decade: <b className="hfont" style={{ fontSize: 18 }}>{r.top_decade}</b></div>}
          </div>
        </div>

        <div className="grid cards" style={{ marginBottom: 40 }}>
          <div className="card flat col">
            <h3 className="h3">Little facts</h3>
            <div className="small">First of the year: <b>{r.first_film.title}</b> <span className="muted">({r.first_film.on})</span></div>
            <div className="small">Latest: <b>{r.last_film.title}</b> <span className="muted">({r.last_film.on})</span></div>
            {r.longest_film && <div className="small">Longest: <b>{r.longest_film.title}</b> <span className="muted">({r.longest_film.minutes} min)</span></div>}
            {r.shortest_film && r.shortest_film.title !== r.longest_film?.title && <div className="small">Shortest: <b>{r.shortest_film.title}</b> <span className="muted">({r.shortest_film.minutes} min)</span></div>}
            {r.top_actor && <div className="small">Most seen: <b>{r.top_actor.name}</b> <span className="muted">in {r.top_actor.films} films</span></div>}
            <div className="small">You wrote <b>{r.reviews}</b> review{r.reviews === 1 ? '' : 's'}, earned <b>{r.likes_received}</b> like{r.likes_received === 1 ? '' : 's'} and <b>{r.badges_earned}</b> badge{r.badges_earned === 1 ? '' : 's'}.</div>
          </div>
          {r.goal && <div className="card flat row" style={{ gap: 20 }}>
            <Ring percent={r.goal.percent} color={r.goal.reached ? P.j : P.m}><span><span className="hfont" style={{ fontSize: 34 }}>{r.goal.done}</span><span className="muted" style={{ display: 'block', fontSize: 13 }}>of {r.goal.target}</span></span></Ring>
            <div><h3 className="h3" style={{ fontSize: 28 }}>The goal</h3><div className="muted">{r.goal.reached ? 'Reached. Take a bow.' : `${r.goal.target - r.goal.done} to go`}</div></div>
          </div>}
        </div>
        <pre className="card flat small" style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--font-body)' }}>{r.share}</pre>
      </>)}
    </div>
  )
}
