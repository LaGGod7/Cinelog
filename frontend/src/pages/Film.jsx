import React, { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ASPECTS, del, get, has, patch, post, put } from '../api.js'
import { clickable, Avatar, Frame, LikeBtn, LoadError, P, Poster, ReviewText, Seg, Stars, Switch, fmt, rateLabel, starText, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'
import { FriendsWatched, PickEditor, SplitScore } from '../widgets.jsx'

export default function Film() {
  const { id } = useParams()
  const { user, flash, openLog, refreshStats, tick } = useSession()
  const nav = useNavigate()
  const [film, setFilm] = useState(null)
  const [reviews, setReviews] = useState([])
  const [tab, setTab] = useState('popular')
  const [critics, setCritics] = useState(false)
  const [myLists, setMyLists] = useState(null)
  const [mine, setMine] = useState({})
  const [more, setMore] = useState([])
  const [err, setErr] = useState(null)
  const [editing, setEditing] = useState(null)   // { id, text } while someone edits their own review
  const [shown, setShown] = useState({})         // reviews the reader chose to open despite the "possible spoilers" label

  const load = useCallback(async () => {
    const f = await get(`/films/${id}`)
    setFilm(f); setMine(f.my_aspects || {})
    setReviews(await get(`/films/${id}/reviews`, { sort: tab, critic_only: critics ? 'true' : '' }))
    if (f.genres[0]) get('/films', { genre: f.genres[0], limit: 4 }).then((d) => setMore(d.films.filter((x) => x.id !== f.id).slice(0, 3))).catch(() => {})
  }, [id, tab, critics])
  useEffect(() => { setErr(null); load().catch((e) => { setErr(e); flash(e.message, 'err') }) }, [load, tick])
  // a review just posted is scanned in the background; poll briefly until it is published
  useEffect(() => {
    if (!reviews.some((r) => r.state === 'pending_scan')) return
    const t = setTimeout(() => load().catch(() => {}), 1200)
    return () => clearTimeout(t)
  }, [reviews, load])

  if (!film && err) return <LoadError error={err} onRetry={() => { setErr(null); load().catch(setErr) }} />
  if (!film) return <div className="pad muted" style={{ paddingTop: 40 }}>Loading…</div>
  const t = tone(film.id)
  const hist = film.rating.hist, hMax = Math.max(1, ...hist)
  const myBucket = film.my_stars ? Math.round(film.my_stars * 2) - 1 : -1
  // Spoiler-safe reading: a review the shield is unsure about stays folded away until you have seen the film (or choose to open it)
  const safe = (user ? user.spoiler_safe : true) && !film.i_watched
  const folded = (v) => safe && v.warn && !shown[v.id] && !(user && user.id === v.author.id)

  const toggle = async () => {
    if (!user) { nav('/login'); return }
    try { film.on_watchlist ? await del(`/watchlist/${id}`) : await put(`/watchlist/${id}`); flash(film.on_watchlist ? 'Removed from watchlist' : `${film.title} added to your watchlist`); refreshStats(); load() }
    catch (ex) { flash(ex.message, 'err') }
  }
  const openLists = async () => {
    if (myLists) { setMyLists(null); return }
    try {
      const ls = await get('/lists', { tab: 'new', user_id: user.id })
      const full = await Promise.all(ls.map((l) => get(`/lists/${l.id}`)))
      setMyLists(full.map((l) => ({ id: l.id, title: l.title, has: l.films.some((f) => f.id === film.id) })))
    } catch (ex) { flash(ex.message, 'err') }
  }
  const addTo = async (l) => {
    try {
      l.has ? await del(`/lists/${l.id}/films/${id}`) : await put(`/lists/${l.id}/films/${id}`)
      setMyLists(myLists.map((x) => (x.id === l.id ? { ...x, has: !l.has } : x))); flash(l.has ? `Removed from ${l.title}` : `Added to ${l.title}`)
    } catch (ex) { flash(ex.message, 'err') }
  }
  const saveAspects = async () => { try { await put(`/films/${id}/aspects`, { values: mine }); flash('Craft ratings saved'); load() } catch (ex) { flash(ex.message, 'err') } }
  const saveEdit = async () => {
    try { await patch(`/reviews/${editing.id}`, { text: editing.text }); setEditing(null); flash('Saved - it will reappear once it has been checked for spoilers again'); load() }
    catch (ex) { flash(ex.message, 'err') }
  }
  const removeReview = async (rid) => {
    if (!window.confirm('Delete your review? This can\'t be undone.')) return
    try { await del(`/reviews/${rid}`); flash('Review deleted'); load() } catch (ex) { flash(ex.message, 'err') }
  }
  const report = async (rid) => {
    try { const r = await post(`/reviews/${rid}/report`, { reason: 'spoiler' }); flash(r.ignored ? 'You already reported this review' : 'Reported. A moderator will take a look.'); load() }
    catch (ex) { flash(ex.message, 'err') }
  }

  return (
    <div>
      <div className="hero" style={{ margin: '24px clamp(12px,3vw,40px) 0', background: t.bg, color: t.fg, padding: 'clamp(22px,3vw,40px) clamp(20px,3.2vw,44px)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,230px),1fr))', gap: 'clamp(20px,3vw,44px)', alignItems: 'start' }}>
        <div className="blob" style={{ right: -160, top: -200, width: 620, height: 620, background: t.ac, opacity: .55 }} />
        <div style={{ position: 'relative', maxWidth: 290 }}><div className="frame" style={{ borderRadius: 22, boxShadow: 'var(--line)', transform: 'rotate(-2deg)', cursor: 'default' }}><Poster film={film} top={film.year} /></div></div>
        <div className="col" style={{ position: 'relative', gap: 16, minWidth: 0, gridColumn: 'span 2' }}>
          <Link to="/discover" className="link" style={{ alignSelf: 'flex-start' }}>← Back to Discover</Link>
          <div className="row wrap" style={{ gap: 8 }}>{film.genres.map((g) => <span key={g} className="tag line" style={{ padding: '5px 13px', fontSize: 14 }}>{g}</span>)}</div>
          <div className="display" style={{ fontSize: 'clamp(44px,6.6vw,92px)', lineHeight: .88 }}>{film.title}</div>
          <div style={{ fontSize: 16 }}>{[film.year, film.runtime && `${film.runtime} min`].filter(Boolean).join(' · ')}</div>
          {film.overview && <div className="lede" style={{ maxWidth: 620 }}>{film.overview}</div>}
          <div className="card row wrap" style={{ gap: 20, padding: '14px 22px', borderRadius: 24, color: '#201f1d', alignSelf: 'flex-start', marginTop: 8 }}>
            <span className="kicker">Your rating</span>
            <Stars value={film.my_stars || 0} onChange={(v) => openLog({ film, stars: v })} />
            <span className="lede" style={{ fontSize: 19, minWidth: 120 }}>{rateLabel(film.my_stars)}</span>
          </div>
          <div className="row wrap" style={{ gap: 10, marginTop: 4 }}>
            <button className="pill ink" onClick={() => openLog({ film })}>Write a review</button>
            <button className={'pill out' + (film.on_watchlist ? ' on' : '')} style={{ color: '#201f1d' }} onClick={toggle}>{film.on_watchlist ? '✓ On watchlist' : '+ Watchlist'}</button>
            {user && <button className="pill out" style={{ color: '#201f1d' }} onClick={openLists}>+ List</button>}
          </div>
          {myLists && (
            <div className="card row wrap" style={{ color: '#201f1d', padding: '14px 18px', borderRadius: 22, gap: 8, alignSelf: 'flex-start' }}>
              <span className="kicker" style={{ marginRight: 4 }}>Add to</span>
              {myLists.length === 0 && <span className="muted">You have no lists yet.</span>}
              {myLists.map((l) => <button key={l.id} className={'pill out sm' + (l.has ? ' on' : '')} onClick={() => addTo(l)}>{l.has ? '✓ ' : ''}{l.title}</button>)}
              <Link to="/lists?new=1" className="pill ink sm">New list</Link>
            </div>)}
        </div>
        <div className="col" style={{ position: 'relative', gap: 16, color: '#201f1d' }}>
          <div className="card">
            <div className="row" style={{ alignItems: 'baseline', gap: 10 }}><span style={{ font: '400 76px/.9 var(--font-heading)' }}>{fmt(film.rating.avg)}</span><span className="starline" style={{ fontSize: 18 }}>{starText(film.rating.avg)}</span></div>
            <div className="small muted" style={{ margin: '4px 0 14px' }}>{film.rating.n} rating{film.rating.n === 1 ? '' : 's'} · {film.reviews} review{film.reviews === 1 ? '' : 's'}</div>
            <div className="bars">{hist.map((x, i) => <div key={i} style={{ height: `${Math.round((x / hMax) * 100)}%`, background: i === myBucket ? P.m : undefined }} />)}</div>
            <div className="row between small" style={{ color: 'var(--n7)', marginTop: 4 }}><span>½</span><span>★★★★★</span></div>
            {film.rating.n > 0 && <SplitScore split={film.rating_split} />}
          </div>
          {!film.has_plot_context && <div className="card small" style={{ padding: '14px 18px', borderRadius: 20 }}>No plot on file for this film yet, so spoiler detection relies on the general model and word lists only.</div>}
        </div>
      </div>

      <div className="split pad" style={{ paddingTop: 44 }}>
        <div>
          <div className="row wrap" style={{ alignItems: 'baseline', gap: 20, marginBottom: 22 }}>
            <h2 className="h2">Reviews</h2>
            <Seg value={tab} onChange={setTab} options={[['popular', 'Popular'], ['recent', 'Recent'], ...(user ? [['friends', 'Friends']] : [])]} />
            <Switch on={critics} onChange={setCritics}>Critics only</Switch>
          </div>
          {reviews.length === 0 && tab === 'friends' && <div className="empty">Nobody you follow has reviewed this yet.</div>}
          {reviews.length === 0 && tab !== 'friends' && <div className="empty">No reviews yet. <span className="under" {...clickable(() => openLog({ film }))}>Write the first one</span></div>}
          <div className="col" style={{ gap: 18 }}>
            {reviews.map((v) => (
              <div key={v.id} className="card flat review" style={{ borderRadius: 24 }}>
                <Avatar name={v.author.name} id={v.author.id} size={52} to={`/users/${v.author.id}`} />
                <div className="col" style={{ gap: 8, minWidth: 0 }}>
                  <div className="row wrap" style={{ gap: 10 }}>
                    <Link to={`/users/${v.author.id}`} className="hfont" style={{ fontSize: 19 }}>{v.author.name}</Link>
                    {user && user.id === v.author.id && <span className="tag">You</span>}
                    {v.author.critic && <span className="tag" style={{ background: P.j }}>Critic</span>}
                    {v.state !== 'published' && v.state !== 'pending_scan' && <span className="tag" style={{ background: P.t, color: '#fffdf8' }}>{v.state}</span>}
                    <span className="small" style={{ color: 'var(--n7)' }}>{new Date(v.created_at + 'Z').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                  </div>
                  {editing && editing.id === v.id ? (
                    <div className="col" style={{ gap: 10 }}>
                      <textarea className="input" rows={6} value={editing.text} maxLength={5000} aria-label="Edit your review"
                        onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
                      <div className="row" style={{ gap: 12 }}>
                        <button className="pill ink sm" onClick={saveEdit} disabled={editing.text.trim().length < 10}>Save</button>
                        <button className="small under muted" onClick={() => setEditing(null)}>Cancel</button>
                      </div>
                    </div>
                  ) : folded(v) ? (
                    <div className="row wrap" style={{ gap: 12, padding: '10px 14px', borderRadius: 16, background: 'var(--tint)' }}>
                      <span style={{ fontSize: 18 }}>⚠</span>
                      <span className="grow small">This review might give away the plot, and you have not logged this film yet.</span>
                      <button className="pill out xs" onClick={() => setShown({ ...shown, [v.id]: true })}>Read it anyway</button>
                    </div>
                  ) : <ReviewText review={v} />}
                  {user && user.id === v.author.id && !editing && ['published', 'hidden', 'pending_scan'].includes(v.state) && <div className="row" style={{ gap: 14 }}>
                    {v.state === 'published' && <button className="small under muted" onClick={() => setEditing({ id: v.id, text: v.text })}>Edit</button>}
                    <button className="small under muted" onClick={() => removeReview(v.id)}>Delete</button>
                  </div>}
                  {v.state === 'published' && <div className="row" style={{ gap: 18 }}>
                    <LikeBtn kind="review" id={v.id} likes={v.likes} liked={v.liked} canLike={!!user} own={!!user && user.id === v.author.id} onNeedLogin={() => nav('/login')} />
                    {user && user.id !== v.author.id && has(user, 'review.report') && <span className="small under muted" {...clickable(() => report(v.id))}>Report a spoiler</span>}
                  </div>}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="col" style={{ gap: 24 }}>
          {film.picks.length > 0 && (
            <div className="card flat col" style={{ gap: 10, background: P.j }}>
              <h3 className="h3">Critics recommend</h3>
              {film.picks.map((p) => <div key={p.user_id}><span style={{ font: '400 italic 16px/1.45 var(--font-body)' }}>“{p.blurb}”</span><div className="small"><Link to={`/users/${p.user_id}`} className="under">{p.name}</Link></div></div>)}
            </div>)}
          {has(user, 'critic.pick') && <PickEditor film={film} onSaved={() => load().catch(() => {})} />}
          <FriendsWatched filmId={film.id} />
          <div className="card flat">
            <h3 className="h3" style={{ marginBottom: 6 }}>The craft</h3>
            <div className="small muted" style={{ marginBottom: 8 }}>How everyone rated it, and your own take.</div>
            {ASPECTS.map((a) => (
              <div key={a} className="aspect rule-top">
                <span>{a}</span>
                <div className="meter"><div style={{ width: `${((film.aspects[a]?.avg || 0) / 5) * 100}%` }} /></div>
                <span className="small muted" style={{ font: '400 13px var(--font-body)' }}>{film.aspects[a] ? fmt(film.aspects[a].avg) : '–'}</span>
                {user && <Stars size={17} value={mine[a]} onChange={(v) => setMine({ ...mine, [a]: v })} />}
              </div>
            ))}
            {user ? <button className={'pill out sm' + (Object.keys(mine).length ? '' : ' off')} style={{ marginTop: 12 }} onClick={saveAspects}>Save my ratings</button>
              : <div className="small muted" style={{ marginTop: 10 }}><Link to="/login" className="under">Sign in</Link> to rate story, acting, visuals, music and pacing.</div>}
          </div>
          {film.cast.length > 0 && (
            <div className="card flat">
              <h3 className="h3" style={{ marginBottom: 14 }}>Cast</h3>
              {film.cast.slice(0, 6).map((c, k) => (
                <div key={k} className="row rule-top" style={{ padding: '9px 0' }}>
                  <div className="avatar" style={{ width: 38, height: 38, fontSize: 16, background: [P.g, P.j, P.m, P.t][k % 4], boxShadow: 'none', cursor: 'default' }}>{c.actor[0]}</div>
                  <div><div className="hfont" style={{ fontSize: 18, lineHeight: 1.1 }}>{c.actor}</div>{c.character && <div className="small muted">{c.character}</div>}</div>
                </div>
              ))}
            </div>
          )}
          {more.length > 0 && (
            <div>
              <h3 className="h3" style={{ marginBottom: 14 }}>More {film.genres[0]}</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 14 }}>{more.map((f) => <Frame key={f.id} film={f} className="sm hov" />)}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
