import React, { useEffect, useState } from 'react'
import { get, post } from './api.js'
import { clickable, FilmSearch, Frame, Poster, Stars, Switch, rateLabel } from './ui.jsx'
import { useSession } from './App.jsx'

const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)

/** "Log a film": pick a film, rate it, optionally review it. Posts a diary entry and (if there is text) a review. */
export default function LogModal({ preset, onClose }) {
  const { flash, bump, stats } = useSession()
  const [film, setFilm] = useState(preset.film || null)
  const [popular, setPopular] = useState([])
  const [r, setR] = useState(preset.stars || 0)
  const [when, setWhen] = useState('Today')
  const [date, setDate] = useState(iso(new Date()))
  const [rewatch, setRewatch] = useState(false)
  const [format, setFormat] = useState('OTT')
  const [text, setText] = useState('')
  const [spoiler, setSpoiler] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (!film) get('/films', { limit: 12 }).then((d) => setPopular(d.films)).catch(() => {}) }, [film])
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [onClose])

  const pickWhen = (w) => {
    setWhen(w)
    const d = new Date(); if (w === 'Yesterday') d.setDate(d.getDate() - 1)
    if (w !== 'Earlier') setDate(iso(d))
  }
  const submit = async () => {
    if (!r || busy) return
    setBusy(true)
    try {
      const entry = await post('/diary', { film_id: film.id, stars: r, watched_on: date, rewatch, format })
      const won = (entry.new_badges || []).map((b) => b.name)
      const body = text.trim()
      let note = ''
      if (body.length >= 10) {
        try {
          await post(`/films/${film.id}/reviews`, { text: spoiler ? `||${body}||` : body })
          note = ' Your review is being checked for spoilers.'
        } catch (ex) { note = ex.status === 409 ? ' (You have already reviewed this film.)' : ` (Review not saved: ${ex.message})` }
      } else if (body) note = ' (Reviews need at least 10 characters.)'
      const fresh = await get('/me/stats').catch(() => null)
      flash(fresh && fresh.streak > (stats?.streak || 0) ? `Logged! Your streak is now ${fresh.streak} day${fresh.streak === 1 ? '' : 's'}.${note}` : `Added to your diary.${note}`)
      if (won.length) setTimeout(() => flash(`Badge earned: ${won.join(', ')}`), 3300)
      bump(); onClose()
    } catch (ex) { flash(ex.message, 'err') } finally { setBusy(false) }
  }

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        {!film ? (<>
          <div className="h2" style={{ marginBottom: 20, fontSize: 52 }}>What did you <em className="m">watch?</em></div>
          <FilmSearch onPick={setFilm} autoFocus />
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(100px,1fr))', gap: 14, marginTop: 22 }}>
            {popular.map((f) => (
              <div key={f.id} className="col" style={{ gap: 6 }}>
                <Frame film={f} className="sm hov" onClick={() => setFilm(f)} />
                <span className="hfont" style={{ fontSize: 14, lineHeight: 1.15 }}>{f.title}</span>
              </div>
            ))}
          </div>
          {popular.length === 0 && <div className="empty" style={{ marginTop: 20 }}>No films in the catalogue yet.</div>}
        </>) : (<>
          <div className="row" style={{ gap: 22, marginBottom: 24 }}>
            <div className="frame sm" style={{ width: 96, flex: 'none', transform: 'rotate(-3deg)', cursor: 'default' }}><Poster film={film} /></div>
            <div>
              <div className="kicker">I watched…</div>
              <div className="h2" style={{ fontSize: 46, margin: '4px 0' }}>{film.title}</div>
              <div className="small muted">{film.year}{!preset.film && <> · <span className="under" style={{ color: 'var(--ink)' }} {...clickable(() => setFilm(null))}>change film</span></>}</div>
            </div>
          </div>
          <div className="row" style={{ gap: 20, padding: '18px 22px', borderRadius: 24, background: 'var(--paper)', marginBottom: 20 }}>
            <Stars value={r} onChange={setR} size={50} />
            <div><div style={{ font: '400 40px/1 var(--font-heading)' }}>{r ? r.toFixed(1) : '–'}</div><div className="lede" style={{ fontSize: 18 }}>{rateLabel(r)}</div></div>
          </div>
          <div className="row wrap" style={{ gap: 10, marginBottom: 18 }}>
            <span className="kicker" style={{ marginRight: 4 }}>Watched</span>
            {['Today', 'Yesterday', 'Earlier'].map((w) => <button key={w} className={'pill sm ' + (when === w ? 'ink' : 'out')} onClick={() => pickWhen(w)}>{w}</button>)}
            {when === 'Earlier' && <input type="date" className="input" style={{ width: 170, padding: '7px 14px' }} max={iso(new Date())} value={date} onChange={(e) => setDate(e.target.value)} />}
            <button className={'pill sm out' + (rewatch ? ' on' : '')} onClick={() => setRewatch(!rewatch)}>↻ Rewatch</button>
          </div>
          <div className="row wrap" style={{ gap: 8, marginBottom: 18 }}>
            <span className="kicker" style={{ marginRight: 4 }}>Where</span>
            {[['OTT', 'At home'], ['Theatre', 'Cinema'], ['IMAX', 'IMAX']].map(([k, t]) => <button key={k} className={'pill sm ' + (format === k ? 'ink' : 'out')} onClick={() => setFormat(k)}>{t}</button>)}
          </div>
          <textarea className="input" maxLength={5000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Write your review (optional). Plot giveaways are blurred automatically; wrap anything in ||double bars|| to hide it yourself." />
          <div className="row wrap" style={{ gap: 14, marginTop: 18 }}>
            <Switch on={spoiler} onChange={setSpoiler}>Whole review contains spoilers</Switch>
            <span className="small end" style={{ color: 'var(--n7)' }}>{text.length} / 5000</span>
            <button className="pill ghost" onClick={onClose}>Cancel</button>
            <button className={'pill ink' + (r && !busy ? '' : ' off')} onClick={submit}>{busy ? 'Posting…' : 'Post to diary'}</button>
          </div>
        </>)}
      </div>
    </div>
  )
}
