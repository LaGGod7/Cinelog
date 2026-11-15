import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { get, has, post } from '../api.js'
import { clickable, P, Seg } from '../ui.jsx'
import { useSession } from '../App.jsx'

function Item({ r, done }) {
  const { flash, user } = useSession()
  const [sel, setSel] = useState([])
  const [terms, setTerms] = useState('')
  const [note, setNote] = useState('')
  const act = async (path, body, msg) => {
    try { await post(`/moderation/${r.id}/${path}`, { ...body, note }); flash(msg); done() }
    catch (e) { flash(e.status === 409 ? 'Another moderator already handled this review' : e.message, e.status === 409 ? 'ok' : 'err'); if (e.status === 409) done() }
  }
  const sanction = async (path, body, msg) => {
    try { await post(`/moderation/users/${r.author.id}/${path}`, body); flash(msg) } catch (e) { flash(e.message, 'err') }
  }
  const toggle = (i) => setSel(sel.includes(i) ? sel.filter((x) => x !== i) : [...sel, i])
  return (
    <div className="card flat col" style={{ borderRadius: 24 }}>
      <div className="row wrap" style={{ gap: 10 }}>
        <span className="tag" style={{ background: r.state === 'hidden' ? P.t : P.g, color: r.state === 'hidden' ? '#fffdf8' : undefined, textTransform: 'capitalize' }}>{r.state === 'hidden' ? 'Hidden by reports' : 'Uncertain'}</span>
        <Link to={`/films/${r.film_id}`} className="hfont" style={{ fontSize: 22 }}>{r.film_title}</Link>
        <span className="muted">by <Link to={`/users/${r.author.id}`} className="under">{r.author.name}</Link></span>
        <span className="end small muted">risk {(r.risk ?? 0).toFixed(2)} · {r.reports} report{r.reports === 1 ? '' : 's'} · priority {r.score}</span>
      </div>
      <p style={{ margin: 0, font: '400 15.5px/1.8 var(--font-body)' }}>
        {r.segments.map((s) => <span key={s.idx} title={(s.reasons || []).join(' · ') || 'not flagged'} {...clickable(() => toggle(s.idx))} className={'seg-mod' + (s.blurred ? ' flag' : '') + (sel.includes(s.idx) ? ' sel' : '')}>{s.text} </span>)}
      </p>
      <div className="small muted">Highlighted sentences are what the shield blurred. Click sentences to select the real spoilers; hover one to see why it was flagged.</div>
      <input className="input" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note to the author (optional for a decision, required for a warning). They will read it, and it is kept as a training label." />
      <div className="row wrap rule-top" style={{ paddingTop: 14 }}>
        <button className="pill ink sm" onClick={() => act('approve', {}, 'Approved as written')}>Approve as is</button>
        <button className={'pill out sm' + (sel.length ? '' : ' off')} onClick={() => act('reblur', { segments: sel, terms: terms.split(',').map((t) => t.trim()).filter(Boolean) }, 'Published with your selection blurred')}>Blur selected ({sel.length})</button>
        <input className="input" style={{ width: 260, padding: '7px 14px' }} placeholder="extra spoiler terms, comma separated" value={terms} onChange={(e) => setTerms(e.target.value)} />
        <button className="pill ghost sm end" onClick={() => act('remove', { confirm_spoiler: false }, 'Review removed')}>Remove</button>
        <button className="pill ghost sm" onClick={() => act('remove', { confirm_spoiler: true }, 'Removed, and the shield learned from it')}>Remove &amp; teach shield</button>
      </div>
      {has(user, 'user.sanction') && r.author.id !== user.id && (
        <div className="row wrap small" style={{ gap: 10 }}>
          <span className="muted">Author:</span>
          <button className="pill out xs" onClick={() => sanction('strike', { reason: note, review_id: r.id }, 'Warning recorded and sent')}>Warn (strike)</button>
          <button className="pill out xs" onClick={() => sanction('mute', { days: 3, reason: note }, 'Muted for 3 days')}>Mute 3 days</button>
          <span className="muted">Three warnings in 30 days mute the account automatically. You cannot act on an equal or higher role.</span>
        </div>)}
    </div>
  )
}

function Queue() {
  const [q, setQ] = useState(null)
  const { flash } = useSession()
  const load = () => get('/moderation/queue').then(setQ).catch((e) => flash(e.message, 'err'))
  useEffect(() => { load() }, [])
  return q === null ? <div className="muted">Loading…</div> : q.length === 0 ? <div className="empty">The queue is clear.</div>
    : <div className="col" style={{ gap: 18 }}>{q.map((r) => <Item key={r.id} r={r} done={load} />)}</div>
}

function Applications() {
  const { flash } = useSession()
  const [rows, setRows] = useState(null)
  const [state, setState] = useState('pending')
  const [notes, setNotes] = useState({})
  const load = () => get('/critics/applications', { state }).then(setRows).catch((e) => flash(e.message, 'err'))
  useEffect(() => { setRows(null); load() }, [state])
  const decide = async (a, what) => {
    try { await post(`/critics/applications/${a.id}/${what}`, { note: notes[a.id] || '' }); flash(what === 'approve' ? `${a.applicant.name} is now a critic` : 'Application declined'); load() }
    catch (e) { flash(e.message, 'err') }
  }
  return (
    <div className="col" style={{ gap: 18 }}>
      <Seg value={state} onChange={setState} options={[['pending', 'Waiting'], ['approved', 'Approved'], ['rejected', 'Declined'], ['all', 'All']]} />
      {rows === null ? <div className="muted">Loading…</div> : rows.length === 0 ? <div className="empty">No applications here.</div> : rows.map((a) => (
        <div key={a.id} className="card flat col" style={{ borderRadius: 24 }}>
          <div className="row wrap" style={{ gap: 10, alignItems: 'baseline' }}>
            <Link to={`/users/${a.applicant.id}`} className="hfont" style={{ fontSize: 24 }}>{a.applicant.name}</Link>
            <span className="tag" style={{ background: a.state === 'approved' ? P.j : a.state === 'rejected' ? P.t : P.g, color: a.state === 'rejected' ? '#fffdf8' : undefined, textTransform: 'capitalize' }}>{a.state}</span>
            <span className="small muted">{a.applicant.films} films · {a.applicant.reviews} reviews · {a.applicant.followers} followers · member since {new Date(a.applicant.member_since + 'Z').toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}</span>
          </div>
          <p style={{ margin: 0, fontStyle: 'italic' }}>“{a.statement}”</p>
          {a.links && <div className="small">Links: {a.links.split(/\s+/).map((l, i) => /^https?:\/\//.test(l) ? <a key={i} className="under" href={l} target="_blank" rel="noreferrer noopener" style={{ marginRight: 8 }}>{l}</a> : <span key={i} style={{ marginRight: 8 }}>{l}</span>)}</div>}
          {a.state === 'pending' ? (
            <div className="row wrap rule-top" style={{ paddingTop: 12 }}>
              <input className="input" style={{ flex: 1, minWidth: 220 }} maxLength={400} placeholder="Note to the applicant (required if you decline)" value={notes[a.id] || ''} onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} />
              <button className="pill ink sm" onClick={() => decide(a, 'approve')}>Approve</button>
              <button className="pill out sm" onClick={() => decide(a, 'reject')}>Decline</button>
            </div>
          ) : <div className="small muted">Decided by {a.decided_by || 'a moderator'}{a.note ? ` · “${a.note}”` : ''}</div>}
        </div>))}
    </div>
  )
}

function Desk() {
  const [st, setSt] = useState(null)
  useEffect(() => { get('/moderation/stats').then(setSt).catch(() => {}) }, [])
  if (!st) return <div className="muted">Loading…</div>
  const tiles = [['Hidden by reports', st.queue.reported, P.t, '#fffdf8'], ['Uncertain', st.queue.uncertain, P.g, '#201f1d'], ['Labelled “possible”', st.queue.warned, P.j, '#201f1d'], ['Critic applications', st.critic_applications_waiting, P.c, '#fffdf8']]
  const acts = Object.entries(st.last_7_days).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...acts.map(([, n]) => n))
  return (
    <div className="col" style={{ gap: 24 }}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 20 }}>
        {tiles.map(([l, v, c, fg], k) => <div key={l} className="stat" style={{ background: c, color: fg, transform: `rotate(${['-1.5deg', '1deg', '-.5deg', '1.5deg'][k]})` }}><div className="kicker" style={{ color: 'inherit' }}>{l}</div><b>{v}</b></div>)}
      </div>
      <div className="grid cards">
        <div className="card flat col">
          <h3 className="h3">Last 7 days</h3>
          {acts.length === 0 && <div className="muted">Nothing decided yet.</div>}
          {acts.map(([k, n]) => <div key={k}><div className="row between small"><span>{k.replace('.', ' · ')}</span><b>{n}</b></div><div className="meter"><div style={{ width: `${(100 * n) / max}%` }} /></div></div>)}
        </div>
        <div className="card flat col">
          <h3 className="h3">Decisions, 30 days</h3>
          {st.decisions_30_days.length === 0 && <div className="muted">No decisions yet.</div>}
          {st.decisions_30_days.map((m) => <div key={m.id ?? 'x'} className="row between"><span className="hfont" style={{ fontSize: 18 }}>{m.name}</span><b>{m.n}</b></div>)}
          <div className="small muted rule-top" style={{ paddingTop: 8 }}>{st.strikes_30_days} warning{st.strikes_30_days === 1 ? '' : 's'} issued in 30 days</div>
        </div>
        <div className="card flat col">
          <h3 className="h3">Most reported films</h3>
          {st.most_reported_films.length === 0 && <div className="muted">No reports yet.</div>}
          {st.most_reported_films.map((f) => <div key={f.id} className="row between"><Link to={`/films/${f.id}`} className="hfont" style={{ fontSize: 18 }}>{f.title}</Link><span className="small muted">{f.reports} report{f.reports === 1 ? '' : 's'}</span></div>)}
        </div>
        <div className="card flat col">
          <h3 className="h3">Decisions as training data</h3>
          <div className="small muted">Each approve, re-blur and confirmed-spoiler removal is a labelled example. Download them to train the shield on your own community's judgement.</div>
          <div><a className="pill out sm" href="/api/moderation/labels?limit=5000" download="cinelog_labels.json">Download labels (JSON)</a></div>
        </div>
      </div>
    </div>
  )
}

export default function Moderation() {
  const { user } = useSession()
  const [params, setParams] = useSearchParams()
  const tabs = [['queue', 'Review queue', has(user, 'review.moderate')], ['critics', 'Critic applications', has(user, 'critic.review')], ['desk', 'Desk stats', has(user, 'review.moderate')]].filter((t) => t[2])
  const tab = tabs.some((t) => t[0] === params.get('tab')) ? params.get('tab') : tabs[0]?.[0]
  return (
    <div className="pad" style={{ paddingTop: 28 }}>
      <div className="display" style={{ fontSize: 'clamp(44px,6.4vw,84px)' }}>The <em className="t">moderation</em> desk</div>
      <div className="lede" style={{ margin: '16px 0 24px', color: 'var(--n4)', maxWidth: 760 }}>Reviews hidden by reader reports or left uncertain by the shield, riskiest first. Every decision is logged, sent to the author with your note, and teaches the film’s spoiler context.</div>
      <div style={{ marginBottom: 26 }}><Seg value={tab} onChange={(t) => setParams({ tab: t })} options={tabs.map(([k, n]) => [k, n])} /></div>
      {tab === 'queue' && <Queue />}{tab === 'critics' && <Applications />}{tab === 'desk' && <Desk />}
    </div>
  )
}
