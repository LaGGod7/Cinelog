"""Job functions run by the scheduler engine + helpers to submit them."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable, List

from sqlalchemy import select

from ..clients.tmdb import TMDBError
from ..models import Film, FilmPlot, Outbox, Poll, Review, User
from ..scheduler.pool import BATCH, USER, Job
from .catalog import set_plot, upsert_tmdb_film
from .reviews import scan_review

log = logging.getLogger("cinelog.jobs")


def submit_scan(app, review_id: int) -> None:
    app.state.pool.submit(Job(f"scan:{review_id}", lambda: scan_review(app, review_id), USER, max_retries=3))


def queue_emails(db, users: Iterable[User], subject: str, body: str) -> List[int]:
    ids = []
    for u in users:
        if u.email_opt_out:
            continue
        o = Outbox(to_email=u.email, subject=subject, body=body)
        db.add(o); db.flush()
        ids.append(o.id)
    return ids


def dispatch_emails(app, ids: List[int]) -> None:
    for oid in ids:
        app.state.pool.submit(Job(f"mail:{oid}", lambda oid=oid: _send_email(app, oid), BATCH, max_retries=3))


def _send_email(app, outbox_id: int) -> None:
    with app.state.db.session() as s:
        o = s.get(Outbox, outbox_id)
        if o is None or o.status in ("sent", "logged"):
            return
        o.status = app.state.mailer.send(o.to_email, o.subject, o.body)


def fetch_plot_job(app, film_id: int) -> None:
    with app.state.db.session() as s:
        f = s.get(Film, film_id)
        if f is None or f.plot_checked:
            return
        text = app.state.wiki.plot_for(f.title, f.year) if app.state.wiki else ""
        if text:
            set_plot(s, f, text, "wikipedia")
        else:
            f.plot_checked = True  # looked, nothing found: don't hammer Wikipedia


def submit_plot_fetch(app, film_id: int) -> None:
    app.state.pool.submit(Job(f"plot:{film_id}", lambda: fetch_plot_job(app, film_id), BATCH, max_retries=2))


def sync_catalog(app, pages: int = 5) -> dict:
    """Batch job: pull popular films from TMDB (rate-limited, cached), upsert, queue plot fetches, rebuild index."""
    tmdb = app.state.tmdb
    if tmdb is None:
        raise TMDBError("TMDB_API_KEY not configured")
    status = app.state.sync_status
    status.update({"running": True, "synced": 0, "errors": 0})
    new_ids: List[int] = []
    # popular titles, plus what is in cinemas now and what is coming (so new releases are there without a search)
    feeds = [(tmdb.popular, p) for p in range(1, pages + 1)]
    feeds += [(tmdb.now_playing, p) for p in (1, 2)] + [(tmdb.upcoming, 1)]
    for feed, page in feeds:
        try:
            items = feed(page)
        except Exception as exc:  # noqa: BLE001  - one failing feed must not stop the others
            status["errors"] += 1
            log.warning("sync feed %s page %s failed: %s", getattr(feed, "__name__", feed), page, exc)
            continue
        for item in items:
            try:
                d = tmdb.details(item["id"])
                with app.state.db.session() as s:
                    f = upsert_tmdb_film(s, d)
                    s.flush()
                    if not f.plot_checked:
                        new_ids.append(f.id)
                status["synced"] += 1
            except Exception as exc:  # noqa: BLE001
                status["errors"] += 1
                log.warning("sync item %s failed: %s", item.get("id"), exc)
    with app.state.db.session() as s:
        app.state.search.rebuild(s)
    for fid in new_ids:
        submit_plot_fetch(app, fid)
    status["running"] = False
    return dict(status)


def refresh_search(app) -> bool:
    """Rebuild the search index if films were added/changed outside this process (import scripts)."""
    with app.state.db.session() as s:
        return app.state.search.refresh_if_changed(s)


def submit_sync(app, pages: int = 5) -> None:
    app.state.pool.submit(Job("sync", lambda: sync_catalog(app, pages), BATCH, max_retries=2))


def refit_shield_space(app) -> None:
    """(Re)fit the hashed idf table on our own plot corpus when no trained bundle provides one."""
    if app.state.shield.ml is not None:
        return
    with app.state.db.session() as s:
        texts = [t for (t,) in s.execute(select(FilmPlot.text).where(FilmPlot.kind == "plot"))]
    if texts:
        app.state.shield.fit_space(texts)


def close_due_polls(app) -> int:
    from .polls import finalize_poll
    n = 0
    with app.state.db.session() as s:
        for p in s.scalars(select(Poll).where(Poll.state == "open", Poll.deadline.is_not(None),
                                              Poll.deadline <= dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))):
            try:
                finalize_poll(s, p)
                n += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("closing poll %s failed: %s", p.id, exc)
    return n


def recover_pending(app) -> int:
    """After a restart, re-queue reviews that were still waiting for their scan (no lost jobs)."""
    with app.state.db.session() as s:
        ids = [i for (i,) in s.execute(select(Review.id).where(Review.state == "pending_scan"))]
    for i in ids:
        submit_scan(app, i)
    return len(ids)
