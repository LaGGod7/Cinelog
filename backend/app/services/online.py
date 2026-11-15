"""Live TMDB lookup for titles that are not in the local catalogue yet (new releases, anything outside the first sync).

A person is waiting on this, so it is built to be quick and to never hold anything up:
  * the network calls run in parallel and outside any database transaction (nobody else waits on them);
  * one try per call, no back-off sleeping;
  * after a failure TMDB is not asked again for a short while (otherwise every keystroke would wait for the timeout);
  * answers are remembered, so typing "dune" letter by letter asks TMDB once.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from sqlalchemy import select

from ..dsa.lru import LRUCache
from ..models import Film
from . import jobs
from .catalog import upsert_tmdb_film

log = logging.getLogger("cinelog.online")
MEMO_SECONDS = 600
COOL_OFF_SECONDS = 45  # after a TMDB failure, go straight to "no online results" for this long


def find_online(app, q: str, limit: int = 5) -> List[int]:
    """Search TMDB for q, import the best matches we do not have (with cast/keywords), return local film ids in TMDB's order.

    Never raises: on any TMDB problem the error is remembered for the admin status page and the caller just gets []."""
    st = app.state
    tmdb = st.tmdb
    q = q.strip()
    if tmdb is None or len(q) < 2:
        return []
    if not hasattr(st, "online_memo"):
        st.online_memo = LRUCache(256)  # query -> (when, ids)
        st.tmdb_down_until = 0.0
    key = (q.lower(), limit)
    memo = st.online_memo.get(key)
    if memo and time.monotonic() - memo[0] < MEMO_SECONDS:
        return list(memo[1])
    if time.monotonic() < st.tmdb_down_until:
        return []
    try:
        results = tmdb.search(q, attempts=1)
    except Exception as exc:  # noqa: BLE001  - network down, bad key, rate limit...
        st.tmdb_status = {"ok": False, "error": str(exc)[:200]}
        st.tmdb_down_until = time.monotonic() + COOL_OFF_SECONDS
        log.warning("TMDB search %r failed: %s", q, exc)
        return []
    st.tmdb_status = {"ok": True, "error": ""}
    # released films with a title, best first
    cands = [r for r in results if r.get("release_date") and r.get("title")][:limit]
    if not cands:
        st.online_memo.put(key, (time.monotonic(), []))
        return []

    with app.state.db.session(readonly=True) as s:  # which of these do we already have?
        have: Dict[int, int] = {t: i for t, i in s.execute(select(Film.tmdb_id, Film.id).where(
            Film.tmdb_id.in_([c["id"] for c in cands])))}
    missing = [c["id"] for c in cands if c["id"] not in have]

    details: Dict[int, dict] = {}
    if missing:
        def fetch(tid: int):
            try:
                return tid, tmdb.details(tid, attempts=1)
            except Exception as exc:  # noqa: BLE001
                log.warning("TMDB details %s failed: %s", tid, exc)
                return tid, None
        with ThreadPoolExecutor(max_workers=len(missing)) as pool:  # all of them at once: the wait is one round trip, not five
            details = {tid: d for tid, d in pool.map(fetch, missing) if d}

    new_ids: List[int] = []
    if details:
        with app.state.db.session() as s:  # one short write transaction, no network inside it
            for tid, d in details.items():
                f = upsert_tmdb_film(s, d)
                s.flush()
                have[tid] = f.id
                st.search.add_film(f)
                new_ids.append(f.id)
    ids = [have[c["id"]] for c in cands if c["id"] in have]
    st.online_memo.put(key, (time.monotonic(), list(ids)))
    for fid in new_ids:  # committed above, so the plot jobs in other threads can see the rows
        jobs.submit_plot_fetch(app, fid)
    return ids
