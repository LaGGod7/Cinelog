import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { get, post, has } from './api.js'
import { clickable, Avatar, Flame, Icon } from './ui.jsx'
import LogModal from './LogModal.jsx'
import Home from './pages/Home.jsx'
import Discover from './pages/Discover.jsx'
import Film from './pages/Film.jsx'
import Dash from './pages/Dash.jsx'
import Profile from './pages/Profile.jsx'
import Feed from './pages/Feed.jsx'
import Lists from './pages/Lists.jsx'
import ListPage from './pages/ListPage.jsx'
import Clubs from './pages/Clubs.jsx'
import Club from './pages/Club.jsx'
import Auth from './pages/Auth.jsx'
import Moderation from './pages/Moderation.jsx'
import Admin from './pages/Admin.jsx'
import Reset from './pages/Reset.jsx'
import Year from './pages/Year.jsx'
import Notifications from './Notifications.jsx'

const Ctx = createContext(null)
export const useSession = () => useContext(Ctx)

export default function App() {
  const [user, setUser] = useState(undefined) // undefined = loading, null = signed out
  const [stats, setStats] = useState(null)
  const [toast, setToast] = useState(null)
  const [log, setLog] = useState(null) // null | { film?, stars? }
  const [tick, setTick] = useState(0) // bumps when something was logged, so pages reload their data
  const [badges, setBadges] = useState([])
  const tt = useRef()
  const nav = useNavigate()

  const flash = useCallback((msg, kind = 'ok') => {
    clearTimeout(tt.current); setToast({ msg: String(msg), kind })
    tt.current = setTimeout(() => setToast(null), 3200)
  }, [])
  // Badges are checked after every action; anything newly earned gets its own toast.
  const refreshBadges = useCallback((announce = true) => get('/me/badges').then((b) => {
    setBadges(b)
    const fresh = b.filter((x) => x.new)
    if (announce && fresh.length) setTimeout(() => flash(`Badge earned: ${fresh.map((x) => x.name).join(', ')}`), 3300)
  }).catch(() => setBadges([])), [flash])
  const refreshStats = useCallback(() => { refreshBadges(); return get('/me/stats').then(setStats).catch(() => setStats(null)) }, [refreshBadges])
  const refresh = useCallback(async () => {
    try { setUser(await get('/auth/me')); refreshStats() } catch { setUser(null); setStats(null) }
  }, [refreshStats])
  useEffect(() => { refresh() }, [refresh])

  const openLog = useCallback((preset = {}) => { if (!user) { nav('/login'); return } setLog(preset) }, [user, nav])
  const logout = async () => { try { await post('/auth/logout') } catch { /* ignore */ } setUser(null); setStats(null); setBadges([]); nav('/') }
  const bump = useCallback(() => { setTick((t) => t + 1); refreshStats() }, [refreshStats])

  if (user === undefined) return <div className="center muted" style={{ padding: 80 }}>Loading…</div>
  const ctx = { user, setUser, refresh, stats, refreshStats, badges, flash, openLog, tick, bump, logout }
  const need = (el) => (user ? el : <Navigate to="/login" replace />)

  return (
    <Ctx.Provider value={ctx}>
      <div className="navwrap">
        <div className="nav">
          <Link to="/" className="brand"><i />CineLog</Link>
          <nav className="nav-links">
            <NavLink to="/" end>Home</NavLink>
            <NavLink to="/discover">Discover</NavLink>
            {user && <NavLink to="/feed">Feed</NavLink>}
            <NavLink to="/lists">Lists</NavLink>
            <NavLink to="/clubs">Clubs</NavLink>
            {has(user, 'review.moderate') && <NavLink to="/moderation">Moderation</NavLink>}
            {has(user, 'wordlist.edit') && <NavLink to="/admin">Admin</NavLink>}
          </nav>
          <div className="nav-search" {...clickable(() => nav('/discover?focus=1'), 'link')}><Icon name="search" /><span>Search films</span></div>
          <button className="pill ink sm" onClick={() => openLog()}><Icon name="plus" size={15} /><span className="hide-sm">Log a film</span></button>
          {user ? (<>
            <NavLink to="/me" className={({ isActive }) => 'pill out sm' + (isActive ? ' on' : '')} title="Your CineLog"><Icon name="mark" /><span className="count">{stats?.watchlist ?? 0}</span></NavLink>
            <Notifications tick={tick} />
            <Avatar name={user.display_name} id={user.id} avatar={user.avatar} to={`/users/${user.id}`} />
          </>) : <Link className="pill out sm" to="/login">Sign in</Link>}
        </div>
      </div>
      <div className="page">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/films/:id" element={<Film />} />
          <Route path="/me" element={need(<Dash />)} />
          <Route path="/me/year" element={need(<Year />)} />
          <Route path="/users/:id" element={<Profile />} />
          <Route path="/feed" element={need(<Feed />)} />
          <Route path="/lists" element={<Lists />} />
          <Route path="/lists/:id" element={<ListPage />} />
          <Route path="/clubs" element={<Clubs />} />
          <Route path="/clubs/:id" element={<Club />} />
          <Route path="/login" element={<Auth />} />
          <Route path="/reset" element={<Reset />} />
          <Route path="/moderation" element={need(<Moderation />)} />
          <Route path="/admin" element={need(<Admin />)} />
          <Route path="*" element={<div className="pad"><div className="empty">That page is not on the reel.</div></div>} />
        </Routes>
      </div>
      {log && <LogModal preset={log} onClose={() => setLog(null)} />}
      {toast && <div className={'toast ' + toast.kind}><Flame />{toast.msg}</div>}
    </Ctx.Provider>
  )
}
