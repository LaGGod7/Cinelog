import React, { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { del, get, pollSocket, post, put } from '../api.js'
import { clickable, Avatar, FilmSearch, Frame, LikeBtn, P, Seg, ago, fgOn, tone } from '../ui.jsx'
import { useSession } from '../App.jsx'
import { CalendarTab, InsightsTab } from './ClubPanels.jsx'

const when = (iso) => new Date(iso + 'Z').toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

function PollCard({ poll: initial, canManage, isMember, onChange }) {
  const { user, flash } = useSession()
  const [poll, setPoll] = useState(initial)
  const [date, setDate] = useState('')
  useEffect(() => setPoll(initial), [initial])
  // live results: the server pushes the new counts to everyone watching this poll
  useEffect(() => {
    if (poll.state !== 'open') return
    return pollSocket(poll.id, (p) => setPoll((cur) => ({ ...p, my_vote: cur.my_vote ?? p.my_vote })))
  }, [poll.id, poll.state])

  const act = async (path, body, msg) => { try { setPoll(await post(`/polls/${poll.id}/${path}`, body)); msg && flash(msg); onChange() } catch (e) { flash(e.message, 'err') } }
  const vote = async (oid) => {
    try { setPoll(await post(`/polls/${poll.id}/vote`, { option_id: oid })); flash('Vote counted') }
    catch (e) { flash(e.status === 409 ? 'You have already voted in this poll' : e.message, 'err') }
  }
  const max = Math.max(1, ...poll.options.map((o) => o.votes))
  const tagBg = { open: P.j, draft: 'var(--tint)', closed: P.g, cancelled: 'var(--tint)' }[poll.state]

  return (
    <div className="card flat" style={{ borderRadius: 24 }}>
      <div className="row wrap" style={{ gap: 10, marginBottom: 6 }}>
        <span className="tag" style={{ background: tagBg, textTransform: 'capitalize' }}>{poll.state === 'open' ? 'Voting open' : poll.state}</span>
        <span className="small muted">{poll.total_votes} vote{poll.total_votes === 1 ? '' : 's'}{poll.deadline && poll.state !== 'closed' ? ` · closes ${when(poll.deadline)}` : ''}</span>
      </div>
      <div className="hfont" style={{ fontSize: 26, lineHeight: 1.15, marginBottom: 14 }}>{poll.title}</div>
      <div className="col" style={{ gap: 12 }}>
        {poll.options.map((o) => {
          const win = poll.winner_film_id === o.film_id, mine = poll.my_vote === o.id
          return (
            <div key={o.id} className="row" style={{ gap: 14 }}>
              <div style={{ width: 44, flex: 'none' }}><Frame film={{ id: o.film_id, title: o.title, poster: o.poster }} className="sm plain" plain /></div>
              <div className="grow">
                <div className="row between" style={{ marginBottom: 5 }}>
                  <Link to={`/films/${o.film_id}`} className="hfont" style={{ fontSize: 19 }}>{o.title} {win && <span className="tag" style={{ marginLeft: 6 }}>Winner</span>}{mine && <span className="tag" style={{ marginLeft: 6, background: P.j }}>Your vote</span>}</Link>
                  <span className="hfont" style={{ fontSize: 19 }}>{o.votes}</span>
                </div>
                <div className="meter"><div style={{ width: `${(o.votes / max) * 100}%`, background: win ? P.t : mine ? P.j : undefined }} /></div>
              </div>
              {poll.state === 'open' && user && isMember && !poll.my_vote && <button className="pill ink sm" onClick={() => vote(o.id)}>Vote</button>}
            </div>
          )
        })}
      </div>
      {poll.screening_date && <div className="lede" style={{ fontSize: 19, marginTop: 14 }}>Screening on {when(poll.screening_date)}</div>}
      {poll.state === 'open' && user && !isMember && <div className="small muted" style={{ marginTop: 12 }}>Join the club to vote.</div>}
      {canManage && (
        <div className="row wrap rule-top" style={{ marginTop: 16, paddingTop: 14 }}>
          {poll.state === 'draft' && <><button className="pill ink sm" onClick={() => act('open', {}, 'Voting is open')}>Open voting</button><button className="pill ghost sm" onClick={() => act('cancel', {}, 'Poll cancelled')}>Cancel poll</button></>}
          {poll.state === 'open' && <button className="pill out sm" onClick={() => act('close', {}, 'Poll closed. The result is final.')}>Close now</button>}
          {poll.state === 'closed' && poll.winner_film_id && <>
            <input type="datetime-local" className="input" style={{ width: 230, padding: '7px 14px' }} value={date} onChange={(e) => setDate(e.target.value)} />
            <button className={'pill out sm' + (date ? '' : ' off')} onClick={() => act('screening', { when: new Date(date).toISOString() }, 'Screening date set')}>{poll.screening_date ? 'Change' : 'Set'} screening date</button>
          </>}
        </div>
      )}
    </div>
  )
}

const TAGS = { Discussion: 'j', 'Hot take': 't', Recommendation: 'g', Question: 'c', Welcome: 'm' }
const since = (iso) => ago(new Date(iso + 'Z').getTime() / 1000)

function Thread({ t: initial, isMember, onChange }) {
  const { user, flash, bump } = useSession()
  const [t, setT] = useState(initial)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  useEffect(() => setT((cur) => ({ ...initial, reply_list: cur.reply_list })), [initial])
  const expand = async () => { if (!open && !t.reply_list) { try { setT(await get(`/threads/${t.id}`)) } catch (e) { flash(e.message, 'err') } } setOpen(!open) }
  const send = async (e) => {
    e.preventDefault()
    try { setT(await post(`/threads/${t.id}/replies`, { body: text })); setText(''); bump() } catch (ex) { flash(ex.message, 'err') }
  }
  const remove = async () => { if (!window.confirm('Remove this thread and its replies?')) return; try { await del(`/threads/${t.id}`); flash('Thread removed'); onChange() } catch (e) { flash(e.message, 'err') } }
  const c = TAGS[t.tag] || 'j'
  return (
    <div className="card flat" style={{ display: 'grid', gridTemplateColumns: '64px minmax(0,1fr)', gap: 16, padding: '18px 20px', borderRadius: 24 }}>
      <LikeBtn variant="vote" kind="thread" id={t.id} likes={t.votes} liked={t.voted} canLike={!!user} />
      <div className="col" style={{ gap: 7, minWidth: 0 }}>
        <div className="row wrap" style={{ gap: 10 }}><span className="tag" style={{ background: P[c], color: fgOn(c) }}>{t.tag}</span>
          <span className="small" style={{ color: 'var(--n7)' }}><Link to={`/users/${t.author.id}`}>{user && user.id === t.author.id ? 'You' : t.author.name}</Link> · {since(t.created_at)}</span></div>
        <div className="hfont" style={{ fontSize: 23, lineHeight: 1.15, cursor: 'pointer' }} {...clickable(expand)}>{t.title}</div>
        {t.body && <div style={{ fontSize: 15, lineHeight: 1.55, color: 'var(--n4)', whiteSpace: 'pre-wrap' }}>{t.body}</div>}
        <div className="row small" style={{ gap: 16, color: 'var(--n6)' }}>
          <span className="under" {...clickable(expand)}>{t.replies} repl{t.replies === 1 ? 'y' : 'ies'}{open ? ' · hide' : ''}</span>
          {t.can_remove && <span className="under" {...clickable(remove)}>remove</span>}
        </div>
        {open && <div className="col rule-top" style={{ gap: 12, paddingTop: 12, marginTop: 4 }}>
          {(t.reply_list || []).map((r) => (
            <div key={r.id} className="row" style={{ alignItems: 'flex-start' }}>
              <Avatar name={r.author.name} id={r.author.id} size={32} to={`/users/${r.author.id}`} />
              <div><span className="hfont" style={{ fontSize: 17 }}>{r.author.name}</span> <span className="small" style={{ color: 'var(--n7)' }}>{since(r.created_at)}</span><div style={{ whiteSpace: 'pre-wrap' }}>{r.body}</div></div>
            </div>))}
          {isMember ? (
            <form className="field" style={{ boxShadow: 'none', background: 'var(--tint)', padding: '6px 6px 6px 18px' }} onSubmit={send}>
              <input placeholder="Write a reply…" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} required style={{ fontSize: 16 }} />
              <button className="pill ink sm">Reply</button>
            </form>) : <div className="small muted">Join the club to reply.</div>}
        </div>}
      </div>
    </div>
  )
}

function WatchRow({ w, isMember, manage, onChange }) {
  const { user, flash, bump } = useSession()
  const act = async (fn, msg) => { try { const r = await fn(); msg && flash(msg); if (r && r.new_badges?.length) setTimeout(() => flash(`Badge earned: ${r.new_badges.map((b) => b.name).join(', ')}`), 3300); bump(); onChange() } catch (e) { flash(e.message, 'err') } }
  return (
    <div className="card flat row" style={{ gap: 20, padding: 16, borderRadius: 24, opacity: w.past ? .6 : 1 }}>
      <div style={{ width: 80, flex: 'none' }}><Frame film={w.film} className="sm plain" plain /></div>
      <div className="grow">
        <div className="kicker" style={{ letterSpacing: '.12em' }}>{when(w.starts_at)}{w.past ? ' · finished' : ''}</div>
        <Link to={`/films/${w.film.id}`} style={{ display: 'block', font: '400 32px/1.05 var(--font-heading)', margin: '4px 0' }}>{w.film.title}</Link>
        <div className="small muted">{w.going} going{w.from_poll ? ' · chosen by poll' : ''}</div>
      </div>
      {manage && !w.past && <button className="small under muted" onClick={() => window.confirm('Cancel this watch-along?') && act(() => del(`/watchalongs/${w.id}`), 'Watch-along cancelled')}>cancel</button>}
      {!w.past && user && isMember && <button className={'pill pop' + (w.rsvp ? ' on' : '')} style={w.rsvp ? undefined : { background: '#201f1d', color: '#fffdf8' }}
        onClick={() => act(() => (w.rsvp ? del(`/watchalongs/${w.id}/rsvp`) : put(`/watchalongs/${w.id}/rsvp`)), w.rsvp ? 'RSVP withdrawn' : 'You are going')}>{w.rsvp ? '✓ Going' : 'RSVP'}</button>}
    </div>
  )
}

export default function Club() {
  const { id } = useParams()
  const { user, flash } = useSession()
  const nav = useNavigate()
  const [club, setClub] = useState(null)
  const [polls, setPolls] = useState([])
  const [tab, setTab] = useState('discussion')
  const [threads, setThreads] = useState([])
  const [was, setWas] = useState([])
  const [nt, setNt] = useState({ title: '', body: '', tag: 'Discussion', open: false })
  const [nw, setNw] = useState({ film: null, when: '' })
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('member')
  const [np, setNp] = useState({ title: '', pick: [], deadline: '' })

  const load = useCallback(async () => {
    const c = await get(`/clubs/${id}`)
    setClub(c); setPolls(await get(`/clubs/${id}/polls`).catch(() => []))
    setThreads(await get(`/clubs/${id}/threads`).catch(() => [])); setWas(await get(`/clubs/${id}/watchalongs`).catch(() => []))
  }, [id])
  useEffect(() => { load().catch((e) => flash(e.message, 'err')) }, [load, user])
  if (!club) return <div className="pad muted" style={{ paddingTop: 40 }}>Loading…</div>

  const t = tone(club.id, 1)
  const manage = club.my_role === 'convener' || club.my_role === 'co_convener'
  const run = async (fn, ok) => { try { await fn(); ok && flash(ok); await load() } catch (e) { flash(e.message, 'err') } }
  const join = () => (user ? run(() => post(`/clubs/${id}/join`), `Welcome to ${club.name}!`) : nav('/login'))
  const next = polls.find((p) => p.state === 'closed' && p.winner_film_id)
  const nextFilm = next && next.options.find((o) => o.film_id === next.winner_film_id)
  const openPoll = polls.find((p) => p.state === 'open')
  const wl = club.watchlist || [], members = club.members || []
  const togglePick = (fid) => setNp((s) => ({ ...s, pick: s.pick.includes(fid) ? s.pick.filter((x) => x !== fid) : [...s.pick, fid] }))
  const postThread = (e) => {
    e.preventDefault()
    run(async () => { const r = await post(`/clubs/${id}/threads`, { title: nt.title, body: nt.body, tag: nt.tag }); if (r.new_badges?.length) setTimeout(() => flash(`Badge earned: ${r.new_badges.map((b) => b.name).join(', ')}`), 3300) }, 'Thread posted')
    setNt({ title: '', body: '', tag: 'Discussion', open: false })
  }
  const postWatch = (e) => {
    e.preventDefault(); if (!nw.film || !nw.when) return
    run(() => post(`/clubs/${id}/watchalongs`, { film_id: nw.film.id, starts_at: new Date(nw.when).toISOString() }), 'Watch-along scheduled')
    setNw({ film: null, when: '' })
  }
  const nextWA = was.find((w) => !w.past)
  const createPoll = (e) => {
    e.preventDefault()
    run(() => post(`/clubs/${id}/polls`, { title: np.title, film_ids: np.pick, deadline: np.deadline ? new Date(np.deadline).toISOString() : null }), 'Poll saved as a draft. Open it when you are ready.')
    setNp({ title: '', pick: [], deadline: '' })
  }

  return (
    <div>
      <div className="hero row wrap" style={{ margin: '24px clamp(12px,3vw,40px) 0', background: t.bg, color: t.fg, padding: 'clamp(24px,3vw,40px) clamp(22px,3.4vw,48px)', alignItems: 'flex-end', gap: 32, minHeight: 220 }}>
        <div className="blob" style={{ right: -80, top: -140, width: 460, height: 460, background: t.ac, opacity: .7 }} />
        <div className="avatar" style={{ position: 'relative', width: 130, height: 130, background: '#fffdf8', font: '500 italic 64px var(--font-heading)', boxShadow: '0 4px 0 #201f1d, var(--line)', transform: 'rotate(-8deg)', cursor: 'default' }}>{club.name[0]}</div>
        <div className="grow" style={{ position: 'relative', minWidth: 240 }}>
          <Link to="/clubs" className="link">← All clubs</Link>
          <div className="display" style={{ fontSize: 'clamp(44px,6vw,80px)', lineHeight: .95, margin: '10px 0 8px' }}>{club.name}</div>
          <div className="lede" style={{ fontSize: 21 }}>{club.description}</div>
        </div>
        <div className="col" style={{ position: 'relative', alignItems: 'flex-end' }}>
          <span>{members.length} member{members.length === 1 ? '' : 's'}{club.is_public ? '' : ' · private'}</span>
          {club.my_role ? <span className="pill pop on" style={{ color: '#201f1d', fontSize: 18, textTransform: 'capitalize' }}>✓ {club.my_role.replace('_', '-')}</span>
            : club.is_public && <button className="pill pop" style={{ color: '#201f1d', fontSize: 18, padding: '13px 26px' }} onClick={join}>Join</button>}
        </div>
      </div>

      <div className="split pad" style={{ paddingTop: 32 }}>
        <div>
          <div style={{ marginBottom: 24 }}><Seg value={tab} onChange={setTab} options={[['discussion', 'Discussion'], ['polls', 'Polls'], ['watch', 'Watch-alongs'], ['calendar', 'Calendar'], ['watchlist', 'Watchlist'], ['members', 'Members'], ...(manage ? [['insights', 'Insights']] : [])]} /></div>

          {tab === 'discussion' && <div className="col" style={{ gap: 16 }}>
            {club.my_role ? (
              <form className="card col" style={{ borderRadius: nt.open ? 26 : 999, padding: nt.open ? 22 : '10px 10px 10px 20px', gap: 12 }} onSubmit={postThread}>
                <div className="row"><input className="grow" style={{ border: 0, outline: 0, background: 'transparent', font: '400 italic 18px var(--font-body)' }} placeholder="Start a thread…" value={nt.title}
                  onFocus={() => setNt({ ...nt, open: true })} onChange={(e) => setNt({ ...nt, title: e.target.value })} minLength={3} maxLength={200} required />
                  {!nt.open && <button className="pill ink sm">Post</button>}</div>
                {nt.open && <>
                  <textarea className="input" style={{ minHeight: 80 }} placeholder="Say a bit more (optional)" value={nt.body} maxLength={4000} onChange={(e) => setNt({ ...nt, body: e.target.value })} />
                  <div className="row wrap" style={{ gap: 8 }}>{Object.keys(TAGS).map((g) => <button type="button" key={g} className={'pill sm out' + (nt.tag === g ? ' on' : '')} onClick={() => setNt({ ...nt, tag: g })}>{g}</button>)}
                    <span className="end" /><button type="button" className="pill ghost sm" onClick={() => setNt({ title: '', body: '', tag: 'Discussion', open: false })}>Cancel</button><button className="pill ink sm">Post thread</button></div>
                </>}
              </form>) : <div className="card flat muted">Join the club to start threads and reply.</div>}
            {threads.length === 0 && <div className="empty">No threads yet. Say hello.</div>}
            {threads.map((t) => <Thread key={t.id} t={t} isMember={!!club.my_role} onChange={load} />)}
          </div>}

          {tab === 'calendar' && <CalendarTab clubId={club.id} />}
          {tab === 'insights' && manage && <InsightsTab clubId={club.id} />}

          {tab === 'watch' && <div className="col" style={{ gap: 16 }}>
            {manage && (
              <form className="card col" onSubmit={postWatch}>
                <div className="kicker">Schedule a watch-along</div>
                {nw.film ? <div className="row"><span className="pill sm out on" {...clickable(() => setNw({ ...nw, film: null }))}>{nw.film.title} ×</span></div>
                  : <FilmSearch className="field" placeholder="Which film?" onPick={(h) => setNw({ ...nw, film: h })} />}
                <div className="row wrap"><input type="datetime-local" className="input" style={{ width: 240, padding: '8px 14px' }} value={nw.when} onChange={(e) => setNw({ ...nw, when: e.target.value })} required />
                  <button className={'pill ink end' + (nw.film && nw.when ? '' : ' off')}>Schedule</button></div>
                <div className="small muted">Setting a screening date on a closed poll also creates one automatically.</div>
              </form>)}
            {was.length === 0 && <div className="empty">No watch-alongs scheduled.</div>}
            {was.map((w) => <WatchRow key={w.id} w={w} isMember={!!club.my_role} manage={manage} onChange={load} />)}
          </div>}

          {tab === 'polls' && <div className="col" style={{ gap: 16 }}>
            {manage && (wl.length >= 2 ? (
              <form className="card col" onSubmit={createPoll}>
                <div className="field" style={{ boxShadow: 'none', background: 'var(--tint)', padding: '10px 18px' }}><input placeholder="Start a poll: what are we watching next?" value={np.title} onChange={(e) => setNp({ ...np, title: e.target.value })} minLength={2} maxLength={160} required /></div>
                <div className="kicker">Pick two or more films from the club watchlist</div>
                <div className="row wrap" style={{ gap: 8 }}>{wl.map((w) => <button type="button" key={w.film_id} className={'pill sm out' + (np.pick.includes(w.film_id) ? ' on' : '')} onClick={() => togglePick(w.film_id)}>{w.title}</button>)}</div>
                <div className="row wrap"><label className="lab" style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>Closes (optional)<input type="datetime-local" className="input" style={{ width: 230, padding: '7px 14px' }} value={np.deadline} onChange={(e) => setNp({ ...np, deadline: e.target.value })} /></label>
                  <button className={'pill ink end' + (np.pick.length >= 2 ? '' : ' off')}>Save draft</button></div>
              </form>
            ) : <div className="card flat muted">Add at least two films to the club watchlist, then you can start a poll.</div>)}
            {polls.length === 0 && <div className="empty">No polls yet.</div>}
            {polls.map((p) => <PollCard key={p.id} poll={p} canManage={manage} isMember={!!club.my_role} onChange={load} />)}
          </div>}

          {tab === 'watchlist' && <>
            {manage && <div style={{ marginBottom: 24 }}><FilmSearch placeholder="Add a film to the club watchlist…" onPick={(h) => run(() => put(`/clubs/${id}/watchlist/${h.id}`), `${h.title} added`)} /></div>}
            {wl.length === 0 ? <div className="empty">The club watchlist is empty.</div> : (
              <div className="grid four">{wl.map((w) => (
                <div key={w.film_id} className="col" style={{ gap: 8, position: 'relative' }}>
                  <Frame film={{ id: w.film_id, title: w.title, poster: w.poster }} className="hov" top={w.year} />
                  {manage && <button className="xbtn" title="Remove" onClick={() => run(() => del(`/clubs/${id}/watchlist/${w.film_id}`), 'Removed')}>×</button>}
                  <span className="hfont" style={{ fontSize: 17, lineHeight: 1.15 }}>{w.title}</span>
                </div>))}
              </div>)}
          </>}

          {tab === 'members' && <>
            {manage && (
              <form className="field" style={{ marginBottom: 24, padding: '10px 10px 10px 20px' }} onSubmit={(e) => { e.preventDefault(); run(() => post(`/clubs/${id}/members`, { email, role }), 'Member added'); setEmail('') }}>
                <input type="email" placeholder="Add a member by email…" value={email} onChange={(e) => setEmail(e.target.value)} required />
                <select value={role} onChange={(e) => setRole(e.target.value)} style={{ border: 0, background: 'var(--tint)', borderRadius: 99, padding: '8px 12px' }}><option value="member">Member</option><option value="co_convener">Co-convener</option></select>
                <button className="pill ink sm">Add</button>
              </form>)}
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 16 }}>
              {members.map((m) => (
                <div key={m.user_id} className="card flat" style={{ padding: 14, borderRadius: 22 }}>
                  <div className="row"><Avatar name={m.name} id={m.user_id} size={48} to={`/users/${m.user_id}`} />
                    <div><Link to={`/users/${m.user_id}`} className="hfont" style={{ fontSize: 18 }}>{m.name}</Link><div className="small muted" style={{ textTransform: 'capitalize' }}>{m.role.replace('_', '-')}</div></div></div>
                  {manage && m.role !== 'convener' && <div className="row small" style={{ marginTop: 10, gap: 14 }}>
                    <span className="under muted" {...clickable(() => run(() => del(`/clubs/${id}/members/${m.user_id}`), 'Member removed'))}>remove</span>
                    {club.my_role === 'convener' && <span className="under muted" {...clickable(() => run(() => post(`/clubs/${id}/transfer/${m.user_id}`), `${m.name} is now the convener`))}>make convener</span>}
                  </div>}
                </div>))}
            </div>
          </>}
        </div>

        <div className="col" style={{ gap: 24 }}>
          <div className="card ink" style={{ boxShadow: `0 4px 0 ${t.bg}, var(--line)` }}>
            <div className="kicker" style={{ color: P.g, letterSpacing: '.12em' }}>{nextWA ? 'Next watch-along' : openPoll ? 'Voting now' : 'Next watch-along'}</div>
            {nextWA ? <>
              <div className="row" style={{ gap: 16, marginTop: 14, alignItems: 'stretch' }}>
                <div style={{ width: 96, flex: 'none' }}><Frame film={nextWA.film} className="sm plain" plain style={{ boxShadow: '0 0 0 1.5px #fffdf8' }} /></div>
                <div className="col" style={{ gap: 6 }}>
                  <div style={{ font: '400 30px/1 var(--font-heading)' }}>{nextWA.film.title}</div>
                  <div className="small" style={{ opacity: .8 }}>{nextWA.going} going{nextWA.from_poll ? ' · chosen by poll' : ''}</div>
                  <div className="lede" style={{ fontSize: 22, color: P.g, marginTop: 'auto' }}>{when(nextWA.starts_at)}</div>
                </div>
              </div>
              <button className="pill" style={{ display: 'flex', width: '100%', marginTop: 18, background: nextWA.rsvp ? P.g : '#fffdf8', color: '#201f1d' }} onClick={() => setTab('watch')}>{nextWA.rsvp ? '✓ You are going' : 'See watch-alongs'}</button>
            </> : <div className="lede" style={{ fontSize: 22, marginTop: 12 }}>{openPoll ? `“${openPoll.title}” is open. ${openPoll.total_votes} vote${openPoll.total_votes === 1 ? '' : 's'} so far.` : 'Nothing scheduled yet.'}</div>}
          </div>
          <div className="card">
            <h3 className="h3" style={{ marginBottom: 14 }}>Club rules</h3>
            {['Spoilers stay out of thread titles.', 'Disagree with the take, not the person.', 'One member, one vote in polls. Results are final once a poll closes.'].map((r, k) => (
              <div key={k} className="row rule-top" style={{ padding: '9px 0', alignItems: 'flex-start' }}><span style={{ font: '400 22px/1 var(--font-heading)', color: t.bg === P.g ? P.t : t.bg, width: 18 }}>{k + 1}</span>{r}</div>))}
          </div>
        </div>
      </div>
    </div>
  )
}
