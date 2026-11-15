import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, get, has, post, put } from '../api.js'
import { FilmSearch, P, Seg } from '../ui.jsx'
import { useSession } from '../App.jsx'

const ROLES = ['viewer', 'critic', 'convener', 'moderator', 'admin']

function Users() {
  const { flash } = useSession()
  const [users, setUsers] = useState([])
  const [reason, setReason] = useState('')
  const load = () => get('/admin/users').then(setUsers).catch((e) => flash(e.message, 'err'))
  useEffect(() => { load() }, [])
  const change = async (u, role) => {
    const on = u.roles.includes(role)
    try { await post(`/admin/users/${u.id}/roles`, { role, action: on ? 'revoke' : 'grant', reason }); flash(`${role} ${on ? 'removed from' : 'granted to'} ${u.display_name}`); load() } catch (e) { flash(e.message, 'err') }
  }
  return (
    <div className="card flat" style={{ overflowX: 'auto' }}>
      <div className="row wrap" style={{ gap: 12, marginBottom: 12 }}>
        <input className="input" style={{ maxWidth: 420 }} maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for the next role change (optional, saved in the audit log and sent to them)" />
      </div>
      <table className="table">
        <thead><tr><th>Person</th><th>Roles (click to grant or revoke)</th><th>Standing</th></tr></thead>
        <tbody>{users.map((u) => (
          <tr key={u.id}>
            <td><div className="hfont" style={{ fontSize: 19 }}><Link to={`/users/${u.id}`}>{u.display_name}</Link></div><div className="small muted">{u.email}</div></td>
            <td><div className="row wrap" style={{ gap: 8 }}>{ROLES.map((r) => <button key={r} disabled={r === 'viewer'} className={'pill sm out' + (u.roles.includes(r) ? ' on' : '')} style={{ textTransform: 'capitalize' }} onClick={() => change(u, r)}>{u.roles.includes(r) ? '✓ ' : ''}{r}</button>)}</div></td>
            <td className="small" style={{ whiteSpace: 'nowrap' }}>{u.muted_until ? <span className="tag" style={{ background: P.t, color: '#fffdf8' }}>muted</span> : null} {u.strikes ? <span className="tag">{u.strikes} strike{u.strikes === 1 ? '' : 's'}</span> : <span className="muted">clean</span>}</td>
          </tr>))}
        </tbody>
      </table>
    </div>
  )
}

const ROLE_COLOR = { viewer: P.g, critic: P.j, convener: P.c, moderator: P.t, admin: P.m }
const Tick = ({ on, color }) => <td style={{ textAlign: 'center', width: 82 }}>{on ? <span className="sticker" style={{ display: 'inline-grid', width: 26, height: 26, padding: 0, background: color, boxShadow: 'none', fontSize: 15, fontStyle: 'normal' }}>✓</span> : <span style={{ color: 'rgba(32,31,29,.2)' }}>·</span>}</td>

function Permissions() {
  const { user } = useSession()
  const [d, setD] = useState(null)
  const [hist, setHist] = useState([])
  useEffect(() => { get('/admin/permissions').then(setD).catch(() => {}); get('/admin/audit', { prefix: 'role.', limit: 40 }).then(setHist).catch(() => {}) }, [])
  if (!d) return <div className="muted">Loading…</div>
  let group = null
  return (
    <div className="col" style={{ gap: 28 }}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(210px,1fr))', gap: 16 }}>
        {d.roles.map((r) => (
          <div key={r.name} className="card flat col" style={{ gap: 6, borderRadius: 22, background: user.roles.includes(r.name) ? ROLE_COLOR[r.name] : undefined }}>
            <div className="row between"><b className="hfont" style={{ fontSize: 22, textTransform: 'capitalize' }}>{r.name}</b><span className="small">{r.people} {r.people === 1 ? 'person' : 'people'}</span></div>
            <div className="small" style={{ lineHeight: 1.4 }}>{r.description}</div>
          </div>))}
      </div>
      <div className="card flat" style={{ overflowX: 'auto' }}>
        <h3 className="h3" style={{ marginBottom: 4 }}>Site permissions</h3>
        <div className="small muted" style={{ marginBottom: 10 }}>Read from the table the server enforces. A ticked cell means that role is allowed; everything else is denied. Your column is highlighted.</div>
        <table className="table">
          <thead><tr><th>What it allows</th>{d.roles.map((r) => <th key={r.name} style={{ textAlign: 'center', textTransform: 'capitalize', background: user.roles.includes(r.name) ? 'rgba(255,214,77,.35)' : undefined }}>{r.name}</th>)}</tr></thead>
          <tbody>{d.permissions.map((p) => {
            const head = p.group !== group; group = p.group
            return (<React.Fragment key={p.key}>
              {head && <tr><td colSpan={d.roles.length + 1} className="kicker" style={{ paddingTop: 18, borderTop: '1.5px solid #201f1d' }}>{p.group}</td></tr>}
              <tr><td><div>{p.description}</div><code className="small muted">{p.key}</code></td>{d.roles.map((r) => <Tick key={r.name} on={p.roles.includes(r.name)} color={ROLE_COLOR[r.name]} />)}</tr>
            </React.Fragment>)
          })}</tbody>
        </table>
      </div>
      <div className="card flat" style={{ overflowX: 'auto' }}>
        <h3 className="h3" style={{ marginBottom: 4 }}>Inside a club</h3>
        <div className="small muted" style={{ marginBottom: 10 }}>Club roles apply only in that club. A site moderator or admin gets no extra power inside someone else’s club.</div>
        <table className="table">
          <thead><tr><th>Action</th>{d.club_roles.map((r) => <th key={r} style={{ textAlign: 'center' }}>{r.replace('_', '-')}</th>)}</tr></thead>
          <tbody>{d.club_actions.map((a) => <tr key={a.key}><td>{a.description}</td>{d.club_roles.map((r) => <Tick key={r} on={a.roles.includes(r)} color={P.c} />)}</tr>)}</tbody>
        </table>
      </div>
      <div className="card flat col" style={{ gap: 8 }}>
        <h3 className="h3">House rules</h3>
        {d.rules.map((r) => <div key={r} className="row" style={{ alignItems: 'flex-start', gap: 10 }}><span style={{ color: P.m }}>●</span><span>{r}</span></div>)}
      </div>
      <div className="card flat" style={{ overflowX: 'auto' }}>
        <h3 className="h3" style={{ marginBottom: 8 }}>Recent role changes</h3>
        {hist.length === 0 ? <div className="muted">No role has been granted or revoked yet.</div> : (
          <table className="table small"><thead><tr><th>When</th><th>By</th><th>Change</th><th>Person</th><th>Why</th></tr></thead>
            <tbody>{hist.map((a) => <tr key={a.id}><td style={{ whiteSpace: 'nowrap' }}>{new Date(a.at + 'Z').toLocaleString()}</td><td>{a.actor ?? 'system'}</td><td className="hfont" style={{ fontSize: 16 }}>{a.action.replace('role.', '')}</td><td>{a.target}</td><td>{a.detail}</td></tr>)}</tbody></table>)}
      </div>
    </div>
  )
}

function Mailbox() {
  const [rows, setRows] = useState([])
  useEffect(() => { get('/admin/outbox', { limit: 30 }).then(setRows).catch(() => {}) }, [])
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="muted">Every email the site sends. With no SMTP server configured, nothing leaves this machine, so password-reset links can be copied from here.</div>
      {rows.length === 0 && <div className="empty">No emails yet.</div>}
      {rows.map((m) => (
        <div key={m.id} className="card flat col" style={{ gap: 6 }}>
          <div className="row wrap" style={{ gap: 10 }}><b className="hfont" style={{ fontSize: 18 }}>{m.subject}</b><span className="tag">{m.status}</span><span className="small muted">to {m.to} · {new Date(m.at + 'Z').toLocaleString()}</span></div>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0 }}>{m.body}</pre>
        </div>))}
    </div>
  )
}

function Audit() {
  const [rows, setRows] = useState([])
  useEffect(() => { get('/admin/audit', { limit: 150 }).then(setRows).catch(() => {}) }, [])
  return (
    <div className="card flat" style={{ overflowX: 'auto' }}>
      <table className="table small">
        <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
        <tbody>{rows.map((a) => <tr key={a.id}><td style={{ whiteSpace: 'nowrap' }}>{new Date(a.at + 'Z').toLocaleString()}</td><td>{a.actor ?? 'system'}</td><td className="hfont" style={{ fontSize: 16 }}>{a.action}</td><td>{a.target}</td><td className="muted">{a.detail}</td></tr>)}</tbody>
      </table>
      {rows.length === 0 && <div className="muted" style={{ padding: 16 }}>Nothing logged yet.</div>}
    </div>
  )
}

function System() {
  const { flash, user } = useSession()
  const [st, setSt] = useState(null)
  const load = () => get('/admin/stats').then(setSt).catch((e) => flash(e.message, 'err'))
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [])
  const run = async (fn, ok) => { try { await fn(); flash(ok); load() } catch (e) { flash(e.status === 503 ? 'Set TMDB_API_KEY in backend/.env and restart the API first' : e.message, 'err') } }
  if (!st) return <div className="muted">Loading…</div>
  const sh = st.shield
  const tiles = [['Films indexed', st.films_indexed, P.c, '#fffdf8'], ['Jobs done', st.jobs.done, P.j, '#201f1d'], ['Jobs waiting', st.queue_depth, P.g, '#201f1d'], ['Jobs failed', st.jobs.failed, P.m, '#fffdf8']]
  return (
    <div className="col" style={{ gap: 24 }}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 20 }}>
        {tiles.map(([l, v, c, fg], k) => <div key={l} className="stat" style={{ background: c, color: fg, transform: `rotate(${['-1.5deg', '1deg', '-.5deg', '1.5deg'][k]})` }}><div className="kicker" style={{ color: 'inherit' }}>{l}</div><b>{v}</b></div>)}
      </div>
      <div className="grid cards">
        <div className="card flat col">
          <h3 className="h3">Spoiler shield</h3>
          <div className="row wrap" style={{ gap: 8 }}>
            <span className="tag">Word lists + plot matching: on</span>
            <span className="tag" style={{ background: sh.ml ? P.j : 'var(--tint)' }}>Trained model: {sh.ml ? 'loaded' : 'not trained'}</span>
            <span className="tag" style={{ background: sh.rnn_meta?.active ? P.j : 'var(--tint)' }} title="BiGRU + attention, blended with the trained model">Recurrent model: {!sh.rnn ? 'not installed' : sh.rnn_meta.active ? 'active' : sh.rnn_meta.tuned ? 'no gain, not used' : 'installed, run tune_shield.bat'}</span>
            <span className="tag" style={{ background: sh.semantic ? P.j : 'var(--tint)' }} title="Compares each sentence with what happens late in the film's plot, in meaning rather than words">Semantic plot match: {sh.semantic ? 'on' : 'off (pip install onnxruntime tokenizers)'}</span>
            <span className="tag" style={{ background: sh.dl ? P.j : 'var(--tint)' }}>Deep model: {sh.dl ? 'loaded' : 'not installed'}</span>
          </div>
          {sh.rnn && sh.rnn_meta?.auc && <div className="small muted">
            Accuracy on unseen films (AUC): trained model {sh.rnn_meta.auc.ml_only?.toFixed(3)} · recurrent {sh.rnn_meta.auc.rnn_only?.toFixed(3)} · blend {sh.rnn_meta.auc.blend?.toFixed(3)}
            {sh.rnn_meta.auc_gain_95ci && ` (blend gain ${sh.rnn_meta.auc_gain_95ci[0] >= 0 ? '+' : ''}${sh.rnn_meta.auc_gain_95ci[0].toFixed(3)} to ${sh.rnn_meta.auc_gain_95ci[1] >= 0 ? '+' : ''}${sh.rnn_meta.auc_gain_95ci[1].toFixed(3)}; if the range includes 0 the gain may be luck)`}
          </div>}
          {sh.ml_meta && Object.keys(sh.ml_meta).length > 0 && <pre>{JSON.stringify(sh.ml_meta, null, 1)}</pre>}
          {has(user, 'model.manage') && <div><button className="pill out sm" onClick={() => run(() => post('/admin/model/reload'), 'Model files reloaded')}>Reload model files</button></div>}
        </div>
        <div className="card flat col">
          <h3 className="h3">Catalogue</h3>
          <div className="muted">Imports popular films from TMDB, then fetches each plot from Wikipedia as spoiler context.</div>
          <div className="row wrap" style={{ gap: 8 }}>
            {!st.tmdb.configured ? <span className="tag" style={{ background: P.m, color: '#fffdf8' }}>TMDB key missing: set TMDB_API_KEY in backend/.env</span>
              : st.tmdb.ok === false ? <span className="tag" style={{ background: P.m, color: '#fffdf8' }} title={st.tmdb.error}>TMDB failing: {st.tmdb.error}</span>
              : <span className="tag" style={{ background: st.tmdb.ok ? P.j : 'var(--tint)' }}>TMDB: {st.tmdb.ok ? 'last call worked' : 'key set, not used yet'}</span>}
          </div>
          <pre>{JSON.stringify(st.sync, null, 1)}</pre>
          {has(user, 'catalog.sync') && <div><button className="pill ink sm" onClick={() => run(() => post('/admin/sync?pages=3'), 'Catalogue sync queued')}>Sync from TMDB</button></div>}
        </div>
        <div className="card flat col"><h3 className="h3">Email outbox</h3><pre>{JSON.stringify(st.outbox, null, 1)}</pre><div className="small muted">Without SMTP settings, emails are written to the API log instead of being sent.</div></div>
        {st.failed_jobs.length > 0 && <div className="card flat col"><h3 className="h3">Failed jobs</h3><pre>{JSON.stringify(st.failed_jobs, null, 1)}</pre></div>}
      </div>
    </div>
  )
}

function Words() {
  const { flash } = useSession()
  const [film, setFilm] = useState(null)
  const [terms, setTerms] = useState([])
  const [add, setAdd] = useState('')
  const [plot, setPlot] = useState('')
  const loadTerms = (f) => get(`/films/${f.id}/spoiler-terms`).then(setTerms).catch((e) => flash(e.message, 'err'))
  const pick = (f) => { setFilm(f); loadTerms(f) }
  const addTerms = async (e) => {
    e.preventDefault()
    try { const r = await post(`/films/${film.id}/spoiler-terms`, { terms: add.split(',').map((s) => s.trim()).filter(Boolean) }); flash(`${r.added.length} term${r.added.length === 1 ? '' : 's'} added`); setAdd(''); loadTerms(film) } catch (ex) { flash(ex.message, 'err') }
  }
  return (
    <div className="col" style={{ gap: 24, maxWidth: 860 }}>
      <FilmSearch placeholder="Find a film to edit its spoiler context…" onPick={pick} />
      {film && <div className="card flat col">
        <h3 className="h3" style={{ fontSize: 34 }}>{film.title} <span className="muted" style={{ fontSize: 20 }}>{film.year}</span></h3>
        <div className="kicker">Word list · gold = plot term (always blurs), plain = character name (weak signal)</div>
        <div className="row wrap" style={{ gap: 8 }}>
          {terms.length === 0 && <span className="muted">No terms yet.</span>}
          {terms.map((t) => <span key={t.id} className="tag" title={`${t.kind} · ${t.source}`} style={{ background: t.kind === 'plot' ? P.g : 'var(--tint)', fontSize: 15, padding: '5px 8px 5px 13px' }}>{t.term}
            <button style={{ marginLeft: 8 }} aria-label={`Remove ${t.term}`} onClick={async () => { try { await del(`/films/${film.id}/spoiler-terms/${t.id}`); loadTerms(film) } catch (ex) { flash(ex.message, 'err') } }}>×</button></span>)}
        </div>
        <form className="row" onSubmit={addTerms}><input className="input" placeholder="add plot terms, comma separated" value={add} onChange={(e) => setAdd(e.target.value)} required /><button className="pill ink sm">Add</button></form>
        <div className="kicker rule-top" style={{ paddingTop: 16 }}>Plot synopsis used for matching (never shown to readers)</div>
        <textarea className="input" value={plot} onChange={(e) => setPlot(e.target.value)} placeholder="Paste a plot synopsis (50+ characters). It replaces the current one." />
        <div><button className={'pill out sm' + (plot.length >= 50 ? '' : ' off')} onClick={async () => { try { const r = await put(`/films/${film.id}/plot`, { text: plot }); flash(`Saved ${r.passages} passages`); setPlot(''); loadTerms(film) } catch (ex) { flash(ex.message, 'err') } }}>Save plot</button></div>
      </div>}
    </div>
  )
}

export default function Admin() {
  const { user } = useSession()
  const tabs = [['system', 'System', has(user, 'audit.read')], ['users', 'People & roles', has(user, 'role.manage')], ['perms', 'Permissions', has(user, 'audit.read')], ['words', 'Spoiler context', has(user, 'wordlist.edit')], ['audit', 'Audit log', has(user, 'audit.read')], ['mail', 'Mailbox', has(user, 'role.manage')]].filter((t) => t[2])
  const [tab, setTab] = useState(tabs[0]?.[0])
  return (
    <div className="pad" style={{ paddingTop: 28 }}>
      <div className="display" style={{ fontSize: 'clamp(44px,6.4vw,84px)', marginBottom: 24 }}>Behind the <em className="c">curtain</em></div>
      <div style={{ marginBottom: 28 }}><Seg value={tab} onChange={setTab} options={tabs.map(([k, n]) => [k, n])} /></div>
      {tab === 'system' && <System />}{tab === 'users' && <Users />}{tab === 'perms' && <Permissions />}{tab === 'words' && <Words />}{tab === 'audit' && <Audit />}{tab === 'mail' && <Mailbox />}
    </div>
  )
}
