import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { get } from '../api.js'
import { clickable, Avatar, BadgeDot, ClubChip, Flame, Frame, P, ago, fmt, starText } from '../ui.jsx'
import { useSession } from '../App.jsx'
import { CriticsPicks, FilmOfDay, Recommendations, Upcoming } from '../widgets.jsx'

export default function Home() {
  const { user, stats, badges, openLog, tick } = useSession()
  const [films, setFilms] = useState([])
  const [feed, setFeed] = useState([])
  const [clubs, setClubs] = useState([])
  const nav = useNavigate()
  useEffect(() => {
    get('/films', { limit: 6 }).then((d) => setFilms(d.films)).catch(() => {})
    get('/clubs').then(setClubs).catch(() => {})
    if (user) get('/feed', { limit: 8 }).then(setFeed).catch(() => {}); else setFeed([])
  }, [user, tick])

  const earned = [...badges].filter((b) => b.earned).sort((a, b) => (b.earned_at || '').localeCompare(a.earned_at || ''))
  const first = user ? user.display_name.split(' ')[0] : null
  const fan = [[0, '0px', '70px', '-10deg'], [1, '320px', '150px', '9deg'], [2, '150px', '20px', '-1deg']].filter(([i]) => films[i])
  const stickers = stats ? [[`${stats.films} films`, P.c, '#fffdf8', '6deg'], [`${stats.reviews} reviews`, P.m, '#fffdf8', '-8deg'], [`${stats.following} following`, P.j, '#201f1d', '4deg']] : []

  return (
    <div>
      <div className="two pad" style={{ paddingTop: 36, paddingBottom: 40 }}>
        <div>
          {user
            ? <div className="display">Hey {first}, <em className="m">what did you watch</em> today?</div>
            : <div className="display">Log what you watch. <em className="m">Skip the spoilers.</em></div>}
          <div className="field lift" {...clickable(() => openLog())} style={{ cursor: 'pointer', marginTop: 34, maxWidth: 600, padding: '10px 10px 10px 24px' }}>
            <span className="grow" style={{ font: '400 italic 19px var(--font-body)', color: 'var(--n7)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>Start typing a film title…</span>
            <span style={{ fontSize: 22, letterSpacing: 3, color: '#d7d3d3' }}>★★★★★</span>
            <span className="pill ink" style={{ padding: '13px 24px' }}>Log it</span>
          </div>
          {user ? (
            <div className="row wrap" style={{ gap: 22, marginTop: 40 }}>
              <Link to="/me" className="pill" style={{ background: P.t, color: '#fffdf8', transform: 'rotate(-3deg)', boxShadow: '0 3px 0 #201f1d', padding: '12px 22px 12px 14px', fontSize: 22 }}>
                <Flame />{stats?.streak ?? 0}-day streak
              </Link>
              {earned.length > 0
                ? earned.slice(0, 3).map((b, k) => <BadgeDot key={b.key} badge={b} size={84} k={k} label />)
                : stickers.map(([t, bg, fg, rot]) => <div key={t} className="sticker" style={{ width: 84, height: 84, background: bg, color: fg, fontSize: 17, transform: `rotate(${rot})` }}>{t}</div>)}
              <Link to="/me" className="under" style={{ font: '400 italic 16px var(--font-body)', color: 'var(--n6)' }}>{earned.length ? `see all badges (${earned.length} of ${badges.length})` : 'see all badges'}</Link>
            </div>
          ) : (
            <div className="row wrap" style={{ marginTop: 34 }}>
              <Link to="/login" className="pill ink">Create your diary</Link>
              <Link to="/discover" className="pill out">Browse films</Link>
            </div>
          )}
        </div>
        <div className="fan">
          {fan.map(([i, x, y, rot]) => <Frame key={films[i].id} film={films[i]} style={{ left: x, top: y, transform: `rotate(${rot})` }} />)}
          {stats?.avg_stars != null && <div className="sticker" style={{ position: 'absolute', left: 300, top: 40, width: 110, height: 110, background: P.g, transform: 'rotate(14deg)', font: '600 32px/.9 var(--font-heading)', pointerEvents: 'none' }}>
            <span>{fmt(stats.avg_stars)}<span style={{ display: 'block', font: '400 italic 13px var(--font-body)' }}>your avg</span></span></div>}
          {fan.length > 0 && <div className="pill" style={{ position: 'absolute', left: 20, bottom: 30, background: P.j, transform: 'rotate(-8deg)', boxShadow: '0 3px 0 #201f1d, var(--line)', font: '600 italic 19px var(--font-heading)', pointerEvents: 'none' }}>spoilers stay blurred</div>}
        </div>
      </div>

      <div className="pad" style={{ paddingBottom: 40 }}><FilmOfDay /></div>

      {user && <div className="pad" style={{ paddingBottom: 40 }}><Recommendations limit={6} /></div>}

      {user && (
        <div className="pad" style={{ paddingTop: 24, paddingBottom: 30 }}>
          <div className="row between" style={{ marginBottom: 20, alignItems: 'baseline' }}>
            <h2 className="h2">Your friends are <em className="c">watching</em></h2>
            <Link to="/feed" className="pill out sm">Open feed</Link>
          </div>
          {feed.length === 0 ? <div className="empty">Follow a few people and their films show up here. <Link to="/feed" className="under">Find people</Link></div> : (
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 20 }}>
              {feed.filter((e) => e.film_id).slice(0, 4).map((e, k) => (
                <div key={k} className="card lift col" style={{ borderRadius: 24, padding: 16, cursor: 'pointer' }} {...clickable(() => nav(`/films/${e.film_id}`), 'link')}>
                  <div className="row" style={{ gap: 14, alignItems: 'flex-start' }}>
                    <div style={{ width: 74, flex: 'none' }}><Frame film={{ id: e.film_id, title: e.film, poster: e.poster }} className="sm plain" plain /></div>
                    <div className="col" style={{ gap: 5, minWidth: 0 }}>
                      <div className="row" style={{ gap: 8 }}><Avatar name={e.user} id={e.user_id} size={26} /><span className="hfont">{(e.user || '').split(' ')[0]}</span></div>
                      <span className="hfont" style={{ fontSize: 19, lineHeight: 1.1 }}>{e.film}</span>
                      <span className="starline">{starText(e.stars)}</span>
                    </div>
                  </div>
                  {e.excerpt && <div style={{ font: '400 14px/1.5 var(--font-body)', color: 'var(--n4)' }}>{e.excerpt}</div>}
                  <div className="small" style={{ color: 'var(--n7)' }}>{e.type === 'reviewed' ? 'reviewed' : 'watched'} · {ago(e.at)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="pad" style={{ paddingBottom: 40 }}><CriticsPicks /></div>

      {user && <div className="pad" style={{ paddingBottom: 40, maxWidth: 640 }}><Upcoming /></div>}

      <div className="pad" style={{ paddingTop: 20 }}>
        <h2 className="h2" style={{ marginBottom: 20 }}>Clubs you might <em className="m">click with</em></h2>
        {clubs.length === 0 ? <div className="empty">No clubs yet. <Link to="/clubs" className="under">Start one</Link></div>
          : <div className="row wrap" style={{ gap: 14 }}>{clubs.slice(0, 6).map((c) => <ClubChip key={c.id} club={c} />)}</div>}
      </div>
    </div>
  )
}
