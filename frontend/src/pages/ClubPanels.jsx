import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get } from '../api.js'
import { Frame, P, fmt } from '../ui.jsx'
import { Ring } from '../widgets.jsx'

const DAYNAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const pad = (n) => String(n).padStart(2, '0')

/** A month grid of the club's watch-alongs and poll deadlines, with an .ics link for phone calendars. */
export function CalendarTab({ clubId }) {
  const now = new Date()
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() + 1 })
  const [cal, setCal] = useState(null)
  const [pick, setPick] = useState(null)
  useEffect(() => { setCal(null); setPick(null); get(`/clubs/${clubId}/calendar`, { month: `${ym.y}-${pad(ym.m)}` }).then(setCal).catch(() => setCal({ events: [], days: 30, first_weekday: 0 })) }, [clubId, ym])
  const go = (d) => setYm(({ y, m }) => { const n = m - 1 + d; return { y: y + Math.floor(n / 12), m: ((n % 12) + 12) % 12 + 1 } })
  const label = new Date(ym.y, ym.m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  const byDay = {}
  ;(cal?.events || []).forEach((e) => { const d = new Date(e.at + 'Z').getDate(); (byDay[d] = byDay[d] || []).push(e) })
  const today = now.getFullYear() === ym.y && now.getMonth() + 1 === ym.m ? now.getDate() : null
  const cells = cal ? [...Array(cal.first_weekday).fill(null), ...Array.from({ length: cal.days }, (_, i) => i + 1)] : []
  const sel = pick ? byDay[pick] || [] : []
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="row wrap between">
        <div className="row"><button className="pill out sm" onClick={() => go(-1)} aria-label="Previous month">←</button><h3 className="h3" style={{ minWidth: 190, textAlign: 'center' }}>{label}</h3><button className="pill out sm" onClick={() => go(1)} aria-label="Next month">→</button></div>
        <a className="pill out sm" href={`/api/clubs/${clubId}/calendar.ics`} title="Works with Google Calendar, Apple Calendar and Outlook">Add to my calendar (.ics)</a>
      </div>
      <div className="card flat" style={{ padding: 14 }}>
        <div className="cal" style={{ gap: 6, marginBottom: 6 }}>{DAYNAMES.map((d) => <span key={d} className="center small muted">{d}</span>)}</div>
        <div className="cal" style={{ gap: 6 }}>
          {cells.map((d, i) => d == null ? <div key={i} style={{ background: 'transparent' }} /> : (
            <button key={i} onClick={() => setPick(pick === d ? null : d)} aria-label={`${d} ${label}${byDay[d] ? `, ${byDay[d].length} event${byDay[d].length === 1 ? '' : 's'}` : ''}`}
              style={{ aspectRatio: '1', borderRadius: 12, padding: 4, textAlign: 'left', verticalAlign: 'top', background: byDay[d] ? (byDay[d].some((e) => e.type === 'watchalong') ? P.g : P.j) : '#efe6d4', boxShadow: pick === d ? '0 0 0 2.5px #201f1d' : today === d ? '0 0 0 2px #201f1d' : 'none', position: 'relative', fontSize: 13 }}>
              <b className="hfont" style={{ fontSize: 16 }}>{d}</b>
              {byDay[d] && <span style={{ position: 'absolute', left: 5, right: 5, bottom: 4, fontSize: 10, lineHeight: 1.1, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{byDay[d][0].title}</span>}
            </button>))}
        </div>
      </div>
      {cal && cal.events.length === 0 && <div className="empty">Nothing scheduled in {label}.</div>}
      {(pick ? sel : cal?.events || []).map((e) => {
        const d = new Date(e.at + 'Z')
        return (
          <div key={e.type + e.id} className="card flat row" style={{ gap: 14, borderRadius: 22, padding: 14 }}>
            <div className="sticker" style={{ width: 56, height: 56, background: e.type === 'watchalong' ? P.g : P.j, flex: 'none', fontSize: 14 }}><span>{d.getDate()}<span style={{ display: 'block', fontSize: 11 }}>{d.toLocaleDateString(undefined, { month: 'short' })}</span></span></div>
            <div className="grow"><div className="hfont" style={{ fontSize: 21, lineHeight: 1.1 }}>{e.title}</div>
              <div className="small muted">{d.toLocaleString(undefined, { weekday: 'long', hour: 'numeric', minute: '2-digit' })}{e.type === 'watchalong' ? ` · ${e.going} going${e.rsvp ? ' · you are in' : ''}` : ' · poll deadline'}</div></div>
            {e.film && <div style={{ width: 44 }}><Frame film={e.film} className="sm plain" plain /></div>}
          </div>)
      })}
    </div>
  )
}

function Tile({ label, value, note, bg, fg = '#201f1d', rot }) {
  return <div className="stat" style={{ background: bg, color: fg, transform: `rotate(${rot})`, padding: '16px 20px' }}><div className="kicker" style={{ color: 'inherit' }}>{label}</div><b style={{ fontSize: 52 }}>{value}</b>{note && <div className="small">{note}</div>}</div>
}

/** For conveners and co-conveners: how the club is doing. */
export function InsightsTab({ clubId }) {
  const [a, setA] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { get(`/clubs/${clubId}/analytics`).then(setA).catch(setErr) }, [clubId])
  if (err) return <div className="empty">Analytics are for the club’s conveners.</div>
  if (!a) return <div className="muted">Loading…</div>
  const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)}%`)
  const maxPosts = Math.max(1, ...a.discussion.weekly.map((w) => w.posts))
  return (
    <div className="col" style={{ gap: 24 }}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(190px,1fr))', gap: 16 }}>
        <Tile label="Members" value={a.members.total} note={Object.entries(a.members.by_role).map(([r, n]) => `${n} ${r.replace('_', '-')}`).join(' · ')} bg={P.m} fg="#fffdf8" rot="-1.2deg" />
        <Tile label="Poll turnout" value={pct(a.polls.participation)} note={`${a.polls.closed} closed · ${a.polls.open} open`} bg={P.g} rot=".8deg" />
        <Tile label="Watch-along RSVPs" value={pct(a.watchalongs.rsvp_rate)} note={a.watchalongs.avg_rsvps != null ? `${a.watchalongs.avg_rsvps} per screening` : 'no screenings yet'} bg={P.j} rot="-.6deg" />
        <Tile label="Discussion" value={a.discussion.threads + a.discussion.replies} note={`${a.discussion.threads} threads · ${a.discussion.replies} replies`} bg={P.c} fg="#fffdf8" rot="1.2deg" />
      </div>
      <div className="grid cards">
        <div className="card flat col">
          <h3 className="h3">Posts per week</h3>
          <div className="row" style={{ gap: 6, alignItems: 'flex-end', height: 120 }}>
            {a.discussion.weekly.map((w) => <div key={w.week} title={`week of ${w.week}: ${w.posts}`} style={{ flex: 1, height: Math.max(4, (w.posts / maxPosts) * 100), background: P.c, borderRadius: '6px 6px 2px 2px', boxShadow: 'inset 0 0 0 1.5px #201f1d' }} />)}
          </div>
          <div className="small muted">last eight weeks</div>
          {a.discussion.top_writers.length > 0 && <>
            <div className="kicker rule-top" style={{ paddingTop: 10 }}>Most active</div>
            {a.discussion.top_writers.map((w) => <div key={w.id} className="row between small"><Link to={`/users/${w.id}`} className="hfont" style={{ fontSize: 17 }}>{w.name}</Link><span className="muted">{w.posts} post{w.posts === 1 ? '' : 's'}</span></div>)}
          </>}
        </div>
        <div className="card flat col">
          <h3 className="h3">Recent polls</h3>
          {a.polls.recent.length === 0 && <div className="muted">No polls yet. A first poll is the quickest way to get members talking.</div>}
          {a.polls.recent.map((p) => <div key={p.id} className="row between" style={{ gap: 10 }}><div><div className="hfont" style={{ fontSize: 18, lineHeight: 1.1 }}>{p.title}</div><div className="small muted">{p.state}{p.winner ? ` · won by ${p.winner}` : ''}</div></div><span className="small">{p.votes} vote{p.votes === 1 ? '' : 's'}</span></div>)}
          {a.watchalongs.next && <div className="small rule-top" style={{ paddingTop: 10 }}>Next watch-along: <b>{a.watchalongs.next.title}</b>, {a.watchalongs.next.going} going</div>}
        </div>
        <div className="card flat col">
          <h3 className="h3">How your members rated the club’s films</h3>
          {a.films.length === 0 && <div className="muted">Once members log the films you watch together, their ratings show here.</div>}
          {a.films.map((f) => (
            <div key={f.id} className="row" style={{ gap: 12 }}>
              <div style={{ width: 40, flex: 'none' }}><Frame film={f} className="sm plain" plain /></div>
              <div className="grow"><Link to={`/films/${f.id}`} className="hfont" style={{ fontSize: 18 }}>{f.title}</Link><div className="small muted">watched by {f.watched_by} of {a.members.total}</div></div>
              <span className="starline">★ {fmt(f.avg)}</span>
            </div>))}
        </div>
        <div className="card flat row" style={{ gap: 18 }}>
          <Ring percent={Math.round((a.watchalongs.rsvp_rate || 0) * 100)} size={96} stroke={12} color={P.j}><span className="hfont" style={{ fontSize: 24 }}>{pct(a.watchalongs.rsvp_rate)}</span></Ring>
          <div><h3 className="h3" style={{ fontSize: 26 }}>Showing up</h3><div className="small muted">{a.watchalongs.past} past and {a.watchalongs.upcoming} upcoming watch-along{a.watchalongs.past + a.watchalongs.upcoming === 1 ? '' : 's'}; {a.watchlist} film{a.watchlist === 1 ? '' : 's'} on the club watchlist.</div></div>
        </div>
      </div>
    </div>
  )
}
