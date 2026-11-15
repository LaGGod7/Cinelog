const BASE = '/api'

function cookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : ''
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
  }
}

function explain(detail) {
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join('; ')
  return detail
}

export async function api(path, { method = 'GET', body, params } = {}) {
  let url = BASE + path
  if (params) {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null))
    if ([...q].length) url += '?' + q
  }
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-CSRF-Token'] = cookie('cl_csrf')
  const res = await fetch(url, { method, headers, credentials: 'include', body: body !== undefined ? JSON.stringify(body) : undefined })
  let data = null
  const text = await res.text()
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) throw new ApiError(res.status, explain(data && data.detail !== undefined ? data.detail : data) || res.statusText)
  return data
}

export const get = (p, params) => api(p, { params })
export const post = (p, body = {}) => api(p, { method: 'POST', body })
export const put = (p, body) => api(p, { method: 'PUT', body })
export const patch = (p, body) => api(p, { method: 'PATCH', body })
export const del = (p) => api(p, { method: 'DELETE' })

export function pollSocket(pollId, onMessage) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  let ws, closed = false, retry
  const open = () => {
    ws = new WebSocket(`${proto}://${location.host}${BASE}/ws/polls/${pollId}`)
    ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)) } catch { /* ignore */ } }
    ws.onclose = () => { if (!closed) retry = setTimeout(open, 2000) }
  }
  open()
  return () => { closed = true; clearTimeout(retry); ws && ws.close() }
}

export const posterUrl = (p) => (p ? `https://image.tmdb.org/t/p/w342${p}` : null)
export const ASPECTS = ['story', 'acting', 'visuals', 'music', 'pacing']
export const has = (user, perm) => !!user && user.permissions.includes(perm)
