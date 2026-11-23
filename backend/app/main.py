from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from .clients.mailer import Mailer
from .clients.tmdb import TMDBClient
from .clients.wikipedia import WikipediaClient
from .config import Settings
from .db import Database
from .models import User, UserRole
from .scheduler.pool import BATCH, Job, WorkerPool
from .security import CSRF_COOKIE, SESSION_COOKIE, TokenBucket, client_ip, hash_password
from .services import jobs
from .services.search import SearchService
from .spoiler.shield import SpoilerShield

log = logging.getLogger("cinelog")
SAFE = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT = {"/auth/login", "/auth/register", "/auth/google/callback", "/auth/forgot", "/auth/reset"}


class PollHub:
    """Live poll results over WebSocket (publish-subscribe)."""

    def __init__(self) -> None:
        self.rooms: dict[int, set] = {}

    async def join(self, poll_id: int, ws) -> None:
        self.rooms.setdefault(poll_id, set()).add(ws)

    def leave(self, poll_id: int, ws) -> None:
        self.rooms.get(poll_id, set()).discard(ws)

    async def broadcast(self, poll_id: int, payload: dict) -> None:
        for ws in list(self.rooms.get(poll_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                self.leave(poll_id, ws)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="CineLog", version="1.0")

    @app.exception_handler(RequestValidationError)
    async def _bad_input(_request: Request, exc: RequestValidationError):
        """Invalid input is 400 Bad Request with a message that names the field (S4.3 design; Sprint 2 DEF-09).
        FastAPI's default is 422 with a nested list, which the design and the AI Mentor answers did not match."""
        errs = exc.errors()
        parts = []
        for e in errs:
            loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
            parts.append(f"{'.'.join(loc) or 'request'}: {e.get('msg', 'invalid value')}")
        return JSONResponse({"detail": "; ".join(parts) or "invalid request",
                             "errors": [{"field": ".".join(str(x) for x in e.get("loc", ())), "msg": e.get("msg")} for e in errs]},
                            status_code=400)
    st = app.state
    st.settings = settings
    st.db = Database(settings.database_url)
    st.db.create_all()
    st.pool = WorkerPool(settings.workers, settings.queue_capacity)
    st.search = SearchService()
    st.shield = SpoilerShield(settings.model_dir, use_dl=settings.use_dl)
    st.mailer = Mailer(settings)
    st.tmdb = TMDBClient(settings.tmdb_api_key, settings.tmdb_rate) if settings.tmdb_api_key else None
    st.wiki = WikipediaClient()
    st.hub = PollHub()
    st.sync_status = {"running": False, "synced": 0, "errors": 0}
    st.tmdb_status = {"ok": None, "error": ""}  # result of the last live TMDB call (shown to admins)
    st.google_exchange = None  # overridable in tests
    st.api_bucket = TokenBucket(settings.api_burst, settings.api_rate)
    st.login_bucket = TokenBucket(settings.login_per_minute, settings.login_per_minute / 60.0)
    st.timer = None

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if settings.force_https and request.url.scheme != "https" and request.headers.get("x-forwarded-proto") != "https":
            return RedirectResponse(str(request.url.replace(scheme="https")), status_code=307)
        ip = client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"),
                       settings.trusted_proxies)
        if request.method == "POST" and path in ("/auth/login", "/auth/register", "/auth/forgot", "/auth/reset"):
            if not st.login_bucket.allow(ip):
                return JSONResponse({"detail": "too many attempts, slow down"}, status_code=429)
        if not st.api_bucket.allow(ip):
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        if request.method not in SAFE and path not in CSRF_EXEMPT and request.cookies.get(SESSION_COOKIE):
            if not request.headers.get("x-csrf-token") or request.headers.get("x-csrf-token") != request.cookies.get(CSRF_COOKIE):
                return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https://image.tmdb.org data:; style-src 'self' 'unsafe-inline'"
        if settings.cookie_secure:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    if settings.serve_frontend:
        from pathlib import Path

        from .spa import SPAMiddleware
        if (Path(settings.frontend_dist) / "index.html").is_file():
            app.add_middleware(SPAMiddleware, dist=Path(settings.frontend_dist))
            log.info("serving the website from %s on the same port (API under /api)", settings.frontend_dist)
        else:
            log.warning("SERVE_FRONTEND=1 but %s/index.html does not exist: run `npm run build` in frontend/", settings.frontend_dist)
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)  # outermost: JSON and the site's JS/CSS shrink ~4x

    from .routers import (admin, auth, browse, club_insights, clubs, community, critics, diary, films, insights, moderation,
                          notifications, reviews, social)
    for r in (auth, admin, browse, community, films, diary, reviews, moderation, clubs, social, notifications, critics, insights,
              club_insights):
        app.include_router(r.router)

    @app.get("/health")
    def health():
        return {"ok": True, "queue": len(st.pool.queue), "jobs": st.pool.stats, "films_indexed": st.search.size,
                "shield": st.shield.status()}

    @app.on_event("startup")
    def _startup() -> None:
        _bootstrap(app)
        if settings.start_workers:
            st.pool.start()
            _periodic(app)
            jobs.recover_pending(app)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        if st.timer:
            st.timer.cancel()
        st.pool.shutdown(wait=False)

    return app


def _bootstrap(app: FastAPI) -> None:
    st = app.state
    with st.db.session() as s:
        st.search.rebuild(s)
        from .services.catalog import backfill_actor_terms
        backfill_actor_terms(s)
        email, pw = st.settings.bootstrap_admin_email, st.settings.bootstrap_admin_password
        if email and pw and not s.scalar(select(User).where(User.email == email.lower())):
            u = User(email=email.lower(), display_name="Admin",
                     password_hash=hash_password(pw, st.settings.bcrypt_rounds))
            u.roles = [UserRole(role="viewer"), UserRole(role="admin")]
            s.add(u)
    jobs.refit_shield_space(app)


def _periodic(app: FastAPI) -> None:
    st = app.state

    def tick() -> None:
        try:
            st.pool.submit(Job("close-polls", lambda: jobs.close_due_polls(app), BATCH, max_retries=0))
            st.pool.submit(Job("search-refresh", lambda: jobs.refresh_search(app), BATCH, max_retries=0))
            jobs.maybe_auto_sync(app, time.monotonic())
        finally:
            st.timer = threading.Timer(30.0, tick)
            st.timer.daemon = True
            st.timer.start()

    st.timer = threading.Timer(30.0, tick)
    st.timer.daemon = True
    st.timer.start()


app = None  # `uvicorn app.main:create_app --factory`
