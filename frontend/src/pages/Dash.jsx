import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, get } from '../api.js'
import { Avatar, BadgeDot, Frame, P, Radar, Seg, fmt, starText, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'
import { GoalCard, Recommendations, Upcoming } from '../widgets.jsx'

const dayKey = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)

export default function Dash() {
  const { stats, badges, flash, openLog, bump, tick } = useSession()
  const [diary, setDiary] = useState([])
  const [watch, setWatch] = useState([])
  const [taste, setTaste] = useState(null)
  const [similar, setSimilar] = useState([])
  const [tab, setTab] = useState('all')
  const [hover, setHover] = useState(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    Promise.all([get('/diary', { limit: 200 }), get('/watchlist'), get('/me/taste'), get('/me/similar')])
      .then(([d, w, t, s]) => { setDiary(d); setWatch(w); setTaste(t); setSimilar(s) }).catch((e) => flash(e.message, 'err'))
  }, [tick])

  const rm = async (path, msg) => { try { await del(path); flash(msg); bump() } catch (e) { flash(e.message, 'err') } }
  const byDay = {}
  diary.forEach((e) => { (byDay[e.watched_on] = byDay[e.watched_on] || []).push(e) })
  const today = new Date()
  const start = new Date(today); start.setDate(today.getDate() - 34)
  const days = Array.from({ length: 35 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return { d, key: dayKey(d), entries: byDay[dayKey(d)] || [] } })
  const cap = hover == null ? 'Hover a day to see what you watched' : `${days[hover].d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })} · ${days[hover].entries.length ? days[hover].entries.map((e) => `${e.title} ${starText(e.stars)}`).join(', ') : 'No film logged'}`
  const wl = watch.filter((f) => tab === 'all' || (tab === 'short' && f.runtime && f.runtime <= 120) || (tab === 'top' && f.rating >= 4))
  const cards = [['Films this year', stats?.films_this_year ?? 0, `${stats?.films ?? 0} in your diary overall`, P.m, '#fffdf8', '-1.5deg'],
    ['Hours watched', stats?.hours_this_year ?? 0, 'this year, give or take the credits', P.c, '#fffdf8', '1deg'],
    ['Average rating', fmt(stats?.avg_stars), 'across everything you have rated', P.g, '#201f1d', '-.5deg'],
    ['Reviews written', stats?.reviews ?? 0, 'published and spoiler-checked', P.j, '#201f1d', '1.5deg']]

  return (
    <div className="pad" style={{ paddingTop: 28 }}>
      <div className="row wrap between" style={{ alignItems: 'flex-end', gap: 30, marginBottom: 30 }}>
        <div>
          <div className="kicker" style={{ marginBottom: 10 }}>{today.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</div>
          <div className="display" style={{ fontSize: 'clamp(46px,6.5vw,84px)' }}>Your <em className="m">CineLog</em></div>
        </div>
        <div className="row wrap">
          <Link className="pill pop" to="/me/year">Year in review</Link>
          <a className="pill out sm" href="/api/diary/export?format=csv">Export CSV</a>
          <a className="pill out sm" href="/api/diary/export?format=json">Export JSON</a>
          <button className="pill ink" onClick={() => openLog()}>Log a film</button>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 20, marginBottom: 40 }}>
        {cards.map(([l, v, note, c, fg, rot]) => (
          <div key={l} className="stat" style={{ background: c, color: fg, transform: `rotate(${rot})` }}>
            <div className="kicker" style={{ color: 'inherit', letterSpacing: '.12em' }}>{l}</div><b>{v}</b><div className="lede" style={{ fontSize: 17 }}>{note}</div>
          </div>
        ))}
      </div>

      <div className="split" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(280px,440px)', gap: 40 }}>
        <div>
          <div className="row wrap" style={{ alignItems: 'baseline', gap: 20, marginBottom: 22 }}>
            <h2 className="h2">Watchlist</h2><span className="lede muted" style={{ fontSize: 20 }}>{watch.length} film{watch.length === 1 ? '' : 's'}</span><span className="grow" />
            <Seg value={tab} onChange={setTab} options={[['all', 'All'], ['short', 'Under 2 hours'], ['top', 'Highly rated']]} />
          </div>
          {wl.length === 0 ? (
            <div className="empty"><div style={{ marginBottom: 16 }}>Nothing here yet.</div><Link to="/discover" className="pill ink sm">Find something on Discover</Link></div>
          ) : (
            <div className="grid four">
              {wl.map((f) => (
                <div key={f.id} className="col" style={{ gap: 10, position: 'relative' }}>
                  <Frame film={f} className="hov" top={f.runtime ? `${f.runtime} min` : f.year} />
                  <button className="xbtn" title="Remove" onClick={() => rm(`/watchlist/${f.id}`, 'Removed from watchlist')}>×</button>
                  <div className="row between" style={{ gap: 8 }}><span className="hfont" style={{ fontSize: 17, lineHeight: 1.15 }}>{f.title}</span><button className="pill out xs" onClick={() => openLog({ film: f })}>Log</button></div>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 48 }}><Recommendations limit={6} /></div>

          <h2 className="h2" style={{ margin: '44px 0 20px' }}>Diary</h2>
          {diary.length === 0 ? <div className="empty">Your diary is empty. Log the last film you watched.</div> : (
            <div className="card flat" style={{ padding: '8px 18px' }}>
              <table className="table">
                <tbody>{diary.slice(0, 40).map((e) => (
                  <tr key={e.id}>
                    <td style={{ width: 54 }}><Frame film={{ id: e.film_id, title: e.title, poster: e.poster }} className="sm plain" plain style={{ width: 44 }} /></td>
                    <td><Link to={`/films/${e.film_id}`} className="hfont" style={{ fontSize: 19 }}>{e.title}</Link> {e.rewatch && <span className="tag" style={{ marginLeft: 6 }}>rewatch</span>}
                      <div className="small muted">{new Date(e.watched_on).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })} · {e.format === 'OTT' ? 'At home' : e.format === 'Theatre' ? 'Cinema' : 'IMAX'}</div></td>
                    <td className="starline" style={{ whiteSpace: 'nowrap' }}>{starText(e.stars)}</td>
                    <td style={{ width: 40 }}><button className="small under muted" onClick={() => rm(`/diary/${e.id}`, 'Diary entry deleted')}>delete</button></td>
                  </tr>))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="col" style={{ gap: 24 }}>
          <GoalCard />
          <Upcoming />
          <div className="card">
            <div className="row between" style={{ alignItems: 'baseline', marginBottom: 16 }}><h3 className="h3" style={{ fontSize: 32 }}>Last five weeks</h3><span className="hfont" style={{ color: 'oklch(0.55 0.21 32)' }}>{stats?.streak ?? 0}-day streak · best {stats?.longest_streak ?? 0}</span></div>
            <div className="cal" style={{ marginBottom: 6 }}>{days.slice(0, 7).map((x) => <span key={x.key} className="center small" style={{ color: 'var(--n7)' }}>{x.d.toLocaleDateString(undefined, { weekday: 'narrow' })}</span>)}</div>
            <div className="cal" onMouseLeave={() => setHover(null)}>
              {days.map((x, i) => <div key={x.key} onMouseEnter={() => setHover(i)} className={(x.entries.length ? 'on ' : '') + (i === 34 ? 'today' : '')} style={x.entries.length ? { background: tone(x.entries[0].film_id).bg } : undefined} />)}
            </div>
            <div className="lede" style={{ marginTop: 16, padding: '12px 16px', borderRadius: 16, background: 'var(--tint)', fontSize: 18, minHeight: 48 }}>{cap}</div>
          </div>
          <div className="card">
            <div className="row between" style={{ alignItems: 'baseline', marginBottom: 16 }}><h3 className="h3" style={{ fontSize: 32 }}>Badges</h3><span className="muted">{badges.filter((b) => b.earned).length} of {badges.length} earned</span></div>
            <div className="col" style={{ gap: 14 }}>
              {[...badges].sort((a, b) => (b.earned - a.earned) || (b.percent - a.percent)).slice(0, showAll ? 99 : 6).map((b, k) => (
                <div key={b.key} className="row" style={{ gap: 14 }}>
                  <BadgeDot badge={b} k={k} />
                  <div className="grow">
                    <div className="row between" style={{ gap: 8 }}><span className="hfont" style={{ fontSize: 18 }}>{b.name}</span><span className="small muted" style={{ whiteSpace: 'nowrap' }}>{b.earned ? 'Earned' : `${b.value} / ${b.target}`}</span></div>
                    <div className="small muted" style={{ marginBottom: 6 }}>{b.description}</div>
                    <div className="meter" style={{ height: 7 }}><div style={{ width: `${b.percent}%`, background: P[b.color] }} /></div>
                  </div>
                </div>))}
            </div>
            {badges.length > 6 && <button className="pill out sm" style={{ marginTop: 16 }} onClick={() => setShowAll(!showAll)}>{showAll ? 'Show fewer' : `Show all ${badges.length}`}</button>}
          </div>
          <div className="card">
            <h3 className="h3" style={{ fontSize: 32, marginBottom: 12 }}>Taste radar</h3>
            {taste && taste.ready ? <Radar data={taste.radar} />
              : <div className="lede" style={{ fontSize: 19 }}>Rate the craft of {taste ? Math.max(0, taste.needed - taste.ratings) : 3} more film{taste && taste.needed - taste.ratings === 1 ? '' : 's'} (story, acting, visuals, music, pacing) to draw your radar.</div>}
          </div>
          <div className="card" style={{ background: P.t, color: '#fffdf8' }}>
            <h3 className="h3" style={{ fontSize: 32, marginBottom: 12 }}>Similar tastes</h3>
            {similar.length === 0 ? <div className="lede" style={{ fontSize: 18 }}>People who rated five or more of the same films as you will appear here.</div>
              : similar.map((u) => (
                <Link key={u.user_id} to={`/users/${u.user_id}`} className="row" style={{ padding: '9px 0' }}>
                  <Avatar name={u.name} id={u.user_id} size={34} /><span className="grow hfont" style={{ fontSize: 18 }}>{u.name}</span><span className="hfont" style={{ fontSize: 18 }}>{Math.round(u.similarity * 100)}% match</span>
                </Link>))}
          </div>
        </div>
      </div>
    </div>
  )
}
