import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { del, get, patch, post, put } from '../api.js'
import { AVATARS, BadgeDot, ClubChip, Frame, LikeBtn, LoadError, P, ReviewText, Switch, fmt, starText, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'
import { CriticPanel, GoalCard, MatchCard } from '../widgets.jsx'

export default function Profile() {
  const { id } = useParams()
  const { user, flash, refresh, logout, tick } = useSession()
  const [p, setP] = useState(null)
  const [edit, setEdit] = useState(false)
  const [name, setName] = useState('')
  const [optOut, setOptOut] = useState(false)
  const [safe, setSafe] = useState(true)
  const [bio, setBio] = useState('')
  const [avatar, setAvatar] = useState('')
  const [pwForm, setPwForm] = useState({ current: '', next: '' })
  const [lists, setLists] = useState([])
  const [err, setErr] = useState(null)

  const load = useCallback(() => get(`/users/${id}`).then((d) => { setErr(null); setP(d) }).catch((e) => { setErr(e); flash(e.message, 'err') }), [id])
  useEffect(() => { setP(null); load(); get('/lists', { tab: 'new', user_id: id }).then(setLists).catch(() => setLists([])) }, [load, tick])
  if (!p && err) return <LoadError error={err} onRetry={load} />
  if (!p) return <div className="pad muted" style={{ paddingTop: 40 }}>Loading…</div>

  const t = tone(p.id, 3)
  const follow = async () => {
    try { p.following ? await del(`/follow/${p.id}`) : await put(`/follow/${p.id}`); flash(p.following ? `Unfollowed ${p.name}` : `Following ${p.name}`); load() }
    catch (e) { flash(e.message, 'err') }
  }
  const save = async (e) => {
    e.preventDefault()
    try { await patch('/auth/me', { display_name: name, email_opt_out: optOut, bio, avatar, spoiler_safe: safe }); await refresh(); setEdit(false); flash('Profile updated'); load() } catch (ex) { flash(ex.message, 'err') }
  }
  const changePw = async (e) => {
    e.preventDefault()
    try { await post('/auth/change-password', { current_password: pwForm.current, new_password: pwForm.next }); setPwForm({ current: '', next: '' }); flash('Password changed; your other devices were signed out') }
    catch (ex) { flash(ex.message, 'err') }
  }
  const s = p.stats
  const stats = [[s.films, 'Films'], [s.reviews, 'Reviews'], [fmt(s.avg_stars), 'Avg rating'], [s.followers, 'Followers'], [s.following, 'Following']]

  return (
    <div>
      <div className="hero" style={{ margin: '24px clamp(12px,3vw,40px) 0', height: 250, background: t.bg === P.g ? P.j : t.bg }}>
        <div className="blob" style={{ left: '38%', top: -120, width: 380, height: 380, background: P.g }} />
        <div className="blob" style={{ right: -60, top: 40, width: 300, height: 300, background: P.m, mixBlendMode: 'multiply' }} />
        <div style={{ position: 'absolute', left: '60%', bottom: -90, width: 200, height: 200, background: P.c, transform: 'rotate(20deg)' }} />
      </div>
      <div className="row wrap" style={{ alignItems: 'flex-end', gap: 32, padding: '0 clamp(20px,6vw,84px)', marginTop: -80, position: 'relative' }}>
        <div className="avatar" style={{ width: 170, height: 170, background: t.bg === P.c || t.bg === P.v ? P.j : t.bg, font: '500 italic 84px var(--font-heading)', boxShadow: '0 0 0 8px #f8f1e4, 0 0 0 9.5px #201f1d', cursor: 'default' }}>{AVATARS[p.avatar] ? <span aria-hidden="true" style={{ fontStyle: 'normal', fontSize: 84 }}>{AVATARS[p.avatar]}</span> : p.name[0].toUpperCase()}</div>
        <div className="grow" style={{ paddingBottom: 6 }}>
          <div className="display" style={{ fontSize: 'clamp(40px,5vw,66px)', lineHeight: 1 }}>{p.name}</div>
          <div className="row wrap" style={{ gap: 8, marginTop: 8 }}>{p.roles.length ? p.roles.map((r) => <span key={r} className="tag" style={{ textTransform: 'capitalize' }}>{r}</span>) : <span className="muted">Film lover</span>}
            {s.streak > 0 && <span className="muted">· {s.streak}-day streak</span>}</div>
          {p.bio && <div style={{ marginTop: 10, maxWidth: 620, fontSize: 17, lineHeight: 1.45 }}>{p.bio}</div>}
        </div>
        <div className="row" style={{ paddingBottom: 12 }}>
          {p.is_me ? <>
            <button className="pill pop" onClick={() => { setName(user.display_name); setOptOut(user.email_opt_out); setBio(user.bio || ''); setAvatar(user.avatar || ''); setSafe(user.spoiler_safe !== false); setEdit(!edit) }}>Edit profile</button>
            <button className="pill ghost" onClick={logout}>Sign out</button>
          </> : user && <button className={'pill ' + (p.following ? 'pop on' : 'ink')} onClick={follow}>{p.following ? '✓ Following' : 'Follow'}</button>}
        </div>
      </div>

      <div className="split" style={{ padding: '30px clamp(20px,6vw,84px) 20px' }}>
        <div>
          {edit && (
            <form className="card col" style={{ marginBottom: 30 }} onSubmit={save}>
              <label className="lab">Display name<input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required /></label>
              <label className="lab">About you<textarea className="input" style={{ minHeight: 80 }} value={bio} onChange={(e) => setBio(e.target.value)} maxLength={300} placeholder="A line or two about your taste in films" /><span className="small muted" style={{ textTransform: 'none', letterSpacing: 0 }}>{bio.length}/300</span></label>
              <div className="lab">Picture
                <div className="avatar-pick" role="group" aria-label="Choose a profile picture">
                  <button type="button" aria-pressed={avatar === ''} aria-label="Use my initial" onClick={() => setAvatar('')} style={{ font: '600 italic 20px var(--font-heading)' }}>{(name || '?')[0].toUpperCase()}</button>
                  {Object.entries(AVATARS).map(([k, em]) => <button type="button" key={k} aria-pressed={avatar === k} aria-label={k} onClick={() => setAvatar(k)}>{em}</button>)}
                </div>
              </div>
              <Switch on={!optOut} onChange={(v) => setOptOut(!v)}>Email me about club polls and moderation decisions</Switch>
              <Switch on={safe} onChange={setSafe}>Spoiler-safe reading: fold away reviews that might spoil a film I have not logged yet</Switch>
              <div className="row"><button className="pill ink sm">Save</button><button type="button" className="pill ghost sm" onClick={() => setEdit(false)}>Cancel</button></div>
            </form>
          )}
          {edit && user.has_password && (
            <form className="card col" style={{ marginBottom: 30 }} onSubmit={changePw}>
              <div className="hfont" style={{ fontSize: 24 }}>Change password</div>
              <label className="lab">Current password<input className="input" type="password" autoComplete="current-password" value={pwForm.current} onChange={(e) => setPwForm({ ...pwForm, current: e.target.value })} required /></label>
              <label className="lab">New password (8+ characters)<input className="input" type="password" autoComplete="new-password" minLength={8} maxLength={128} value={pwForm.next} onChange={(e) => setPwForm({ ...pwForm, next: e.target.value })} required /></label>
              <div><button className="pill ink sm">Change password</button></div>
            </form>
          )}
          <div className="row wrap" style={{ gap: 40, padding: '18px 0', borderTop: '1.5px solid #201f1d', borderBottom: '1px solid rgba(32,31,29,.16)', marginBottom: 36 }}>
            {stats.map(([v, l]) => <div key={l}><div style={{ font: '400 46px/1 var(--font-heading)' }}>{v}</div><div className="kicker" style={{ letterSpacing: '.12em' }}>{l}</div></div>)}
          </div>
          <h2 className="h2" style={{ fontSize: 44, marginBottom: 20 }}>Favourite <em className="m">four</em></h2>
          {p.favourites.length === 0 ? <div className="empty" style={{ marginBottom: 44 }}>{p.is_me ? 'Rate a few films and your top four land here.' : 'No rated films yet.'}</div> : (
            <div className="grid four" style={{ marginBottom: 44 }}>
              {p.favourites.map((f, k) => (
                <div key={f.id} className="col" style={{ gap: 8 }}>
                  <Frame film={f} className="hov" style={{ transform: `rotate(${['-2deg', '1.5deg', '-1deg', '2deg'][k]})` }} />
                  <span className="starline center">{starText(f.stars)}</span>
                </div>))}
            </div>
          )}
          <h2 className="h2" style={{ fontSize: 44, marginBottom: 20 }}>Recent reviews</h2>
          {p.reviews.length === 0 ? <div className="empty">No reviews yet.</div> : (
            <div className="col" style={{ gap: 16 }}>
              {p.reviews.map((v) => (
                <div key={v.id} className="card flat row" style={{ gap: 18, padding: 16, borderRadius: 24, alignItems: 'flex-start' }}>
                  <div style={{ width: 70, flex: 'none' }}><Frame film={v.film} className="sm plain" plain /></div>
                  <div className="col review" style={{ gap: 6, display: 'flex', padding: 0 }}>
                    <div className="row wrap" style={{ gap: 10, alignItems: 'baseline' }}><Link to={`/films/${v.film.id}`} className="hfont" style={{ fontSize: 21 }}>{v.film.title}</Link><span className="starline">{starText(v.stars)}</span></div>
                    <ReviewText review={v} />
                    <span className="row small" style={{ color: 'var(--n7)', gap: 14 }}><LikeBtn kind="review" id={v.id} likes={v.likes} liked={v.liked} canLike={!!user} own={!!user && user.id === p.id} />{new Date(v.created_at + 'Z').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                  </div>
                </div>))}
            </div>
          )}
          {lists.length > 0 && <>
            <h2 className="h2" style={{ fontSize: 44, margin: '44px 0 20px' }}>Lists</h2>
            <div className="col" style={{ gap: 14 }}>
              {lists.map((l) => (
                <Link key={l.id} to={`/lists/${l.id}`} className="card flat row lift" style={{ borderRadius: 24, padding: '14px 18px' }}>
                  <div className="row" style={{ gap: 0, paddingLeft: 4 }}>{l.films.slice(0, 3).map((f) => <div key={f.id} style={{ width: 46, marginRight: -14 }}><Frame film={f} className="sm" plain onClick={() => {}} /></div>)}</div>
                  <div className="grow" style={{ marginLeft: 22 }}><div className="hfont" style={{ fontSize: 22, lineHeight: 1.1 }}>{l.title}</div><div className="small muted">{l.count} film{l.count === 1 ? '' : 's'} · ♥ {l.likes}</div></div>
                </Link>))}
            </div>
          </>}
        </div>
        <div className="col" style={{ gap: 24 }}>
          <div className="card">
            <h3 className="h3" style={{ fontSize: 32, marginBottom: 18 }}>Badge shelf</h3>
            {p.badges.filter((b) => b.earned).length === 0 && <div className="muted" style={{ marginBottom: 14 }}>No badges yet. The first one comes with the first film logged.</div>}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: '16px 10px' }}>
              {[...p.badges].sort((a, b) => b.earned - a.earned).slice(0, 9).map((b, k) => (
                <div key={b.key} className="col center" style={{ alignItems: 'center', gap: 8 }}><BadgeDot badge={b} size={74} k={k} /><span className="hfont" style={{ fontSize: 15, lineHeight: 1.1, opacity: b.earned ? 1 : .55 }}>{b.name}</span></div>))}
            </div>
          </div>
          {!p.is_me && user && <MatchCard uid={p.id} />}
          {p.is_me && <CriticPanel />}
          {p.is_me && <GoalCard compact />}
          <div className="card">
            <h3 className="h3" style={{ fontSize: 32, marginBottom: 16 }}>Clubs</h3>
            {p.clubs.length === 0 ? <div className="muted">Not in any public clubs yet.</div> : <div className="row wrap" style={{ gap: 10 }}>{p.clubs.map((c) => <ClubChip key={c.id} club={c} small />)}</div>}
          </div>
          {p.is_me && <div className="card"><h3 className="h3" style={{ fontSize: 32, marginBottom: 10 }}>Your CineLog</h3><div className="muted" style={{ marginBottom: 14 }}>Watchlist, diary calendar, taste radar and exports.</div><Link to="/me" className="pill ink sm">Open dashboard</Link></div>}
        </div>
      </div>
    </div>
  )
}
