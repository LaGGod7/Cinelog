"""Things that keep the site quick: page views never wait on writers, TMDB lookups never hold anyone up."""
import threading
import time

import httpx
import pytest
from sqlalchemy import text

from tests.test_phase1 import NEW, _fake_tmdb


def test_read_sessions_cannot_write(app):
    with pytest.raises(Exception, match="readonly"):
        with app.state.db.session(readonly=True) as s:
            s.execute(text("INSERT INTO outbox (to_email, subject, body, status, created_at) VALUES ('a','b','c','queued','2020-01-01')"))
    with app.state.db.session() as s:  # and the pooled connection is a normal one again afterwards
        s.execute(text("INSERT INTO outbox (to_email, subject, body, status, created_at) VALUES ('a','b','c','queued','2020-01-01')"))


def test_page_views_do_not_wait_for_a_long_write(app, admin, films):
    """A writer holds the database lock for a while (a catalogue sync, a review scan...). Reading pages must carry on."""
    started, release = threading.Event(), threading.Event()

    def long_write():
        with app.state.db.session() as s:
            s.execute(text("UPDATE films SET popularity = popularity"))  # takes the write lock
            started.set()
            release.wait(10)

    t = threading.Thread(target=long_write); t.start()
    assert started.wait(5)
    try:
        t0 = time.time()
        for url in ("/films", "/genres", f"/films/{films[0]}", "/auth/me", "/films/autocomplete?q=ros", "/notifications"):
            assert admin.get(url).status_code == 200, url
        assert time.time() - t0 < 3, "page views queued behind the writer"
    finally:
        release.set(); t.join()


def test_tmdb_calls_run_in_parallel_not_one_after_another(app, admin, films):
    import app.services.online as online
    many = [{"id": 700 + i, "title": f"Parallel Movie {i}", "release_date": "2026-01-01"} for i in range(5)]
    _fake_tmdb(app, many)
    real = app.state.tmdb.details
    delay = 0.4

    def slow_details(tid, attempts=5):
        time.sleep(delay)
        return real(tid, attempts)
    app.state.tmdb.details = slow_details
    t0 = time.time()
    ids = online.find_online(app, "parallel movie", 5)
    took = time.time() - t0
    assert len(ids) == 5
    assert took < delay * 3, f"details were fetched one by one ({took:.1f}s)"  # 5 in a row would be 2.0s


def test_a_slow_tmdb_lookup_does_not_freeze_other_requests(app, admin, films):
    _fake_tmdb(app, NEW)
    real = app.state.tmdb.search

    def slow_search(q, page=1, attempts=5):
        time.sleep(1.0)
        return real(q, page, attempts)
    app.state.tmdb.search = slow_search
    out = {}
    t = threading.Thread(target=lambda: out.update(r=admin.get("/films/search", params={"q": "brand new"}).json())); t.start()
    time.sleep(0.2)
    t0 = time.time()
    assert admin.get("/films").status_code == 200 and admin.get("/auth/me").status_code == 200
    other = time.time() - t0
    t.join()
    assert other < 0.8, f"other pages waited {other:.1f}s for the TMDB lookup"
    assert len(out["r"]) == 2


def test_after_a_tmdb_failure_the_next_searches_skip_tmdb_for_a_while(app, admin, films):
    seen = _fake_tmdb(app, NEW, fail=True)
    admin.get("/films/search", params={"q": "nothing here"})
    n = len(seen)
    assert n >= 1
    for q in ("nothing here a", "nothing here ab", "other words"):
        assert admin.get("/films/search", params={"q": q}).status_code == 200
    assert len(seen) == n  # cool-off: no more waiting on a service that is down
    assert admin.get("/admin/stats").json()["tmdb"]["ok"] is False
    app.state.tmdb_down_until = 0  # cool-off over: it tries again
    admin.get("/films/search", params={"q": "again please"})
    assert len(seen) == n + 1


def test_tmdb_client_single_attempt_does_not_sleep():
    sleeps = []
    from app.clients.tmdb import TMDBClient, TMDBError
    c = TMDBClient("k", rate=10000, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
                   sleep=sleeps.append)
    with pytest.raises(TMDBError):
        c.search("x", attempts=1)
    assert sleeps == []  # one try means no waiting around


# ---------------------------------------------------------------- one-port production serving
def _site(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>CineLog</title><div id=root></div>")
    (dist / "assets" / "app-abc123.js").write_text("console.log('hi')" * 200)
    (tmp_path / "secret.txt").write_text("outside the site")
    a = create_app(make_settings(str(tmp_path), serve_frontend=True, frontend_dist=str(dist)))
    return a, TestClient(a)


def test_built_site_is_served_next_to_the_api_under_api_prefix(tmp_path):
    a, c = _site(tmp_path)
    with c:
        home = c.get("/")
        assert home.status_code == 200 and "<div id=root>" in home.text and home.headers["cache-control"] == "no-cache"
        assert "default-src 'self'" in home.headers["content-security-policy"]
        assert c.get("/films/12").text == home.text                       # an app page: index.html, so refresh works
        assert c.get("/clubs").text == home.text                          # same URL as an API route, but the browser gets the page
        js = c.get("/assets/app-abc123.js")
        assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
        assert js.headers.get("content-encoding") == "gzip"               # compressed on the way out
        assert c.get("/missing.png").status_code == 404                   # a missing file is a 404, not the app page
        assert c.get("/../secret.txt").status_code in (200, 404) and "outside the site" not in c.get("/../secret.txt").text
        assert c.get("/%2e%2e/secret.txt").status_code in (200, 404) and "outside the site" not in c.get("/%2e%2e/secret.txt").text
        assert c.get("/api/health").json()["ok"] is True                  # the API, with the prefix the front end uses
        assert c.get("/api/films").json()["total"] == 0
        r = c.post("/api/auth/register", json={"email": "a@x.io", "password": "password123", "display_name": "A"})
        assert r.status_code == 201
        assert c.get("/api/auth/me").json()["email"] == "a@x.io"         # cookies work on the one origin
        assert c.post("/films").status_code == 404                        # unprefixed API is not exposed any more


def test_site_not_served_unless_asked(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        assert c.get("/health").json()["ok"] is True                      # tests/dev: plain API at the root
