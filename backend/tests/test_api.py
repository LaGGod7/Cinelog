import datetime as dt
import threading
import time

from conftest import Api, grant, make_settings


def wait_scans(app):
    assert app.state.pool.wait_idle(20)


# ---------------------------------------------------------------- auth, CSRF, rate limit
def test_register_login_logout_and_generic_errors(new_client):
    c = new_client()
    u = c.register("a@x.io", "Ann")
    assert u["roles"] == ["admin", "viewer"]  # first account owns the install
    assert c.get("/auth/me").json()["email"] == "a@x.io"
    c.post("/auth/logout")
    assert c.get("/auth/me").status_code == 401
    bad1 = c.post("/auth/login", {"email": "a@x.io", "password": "wrong-pass"})
    bad2 = c.post("/auth/login", {"email": "nobody@x.io", "password": "wrong-pass"})
    assert bad1.status_code == bad2.status_code == 401 and bad1.json() == bad2.json()
    assert c.post("/auth/login", {"email": "a@x.io", "password": "password123"}).status_code == 200


def test_password_is_bcrypt_hashed(app, new_client):
    new_client().register("h@x.io")
    from sqlalchemy import select
    from app.models import User
    with app.state.db.session() as s:
        h = s.scalar(select(User.password_hash))
    assert h.startswith("$2") and "password123" not in h


def test_csrf_required_for_cookie_sessions(new_client):
    c = new_client()
    c.register("a@x.io")
    r = c.c.post("/auth/logout")  # no header
    assert r.status_code == 403
    assert c.post("/auth/logout").status_code == 200


def test_login_rate_limit_429_on_sixth_attempt(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    app = create_app(make_settings(str(tmp_path), login_per_minute=5))
    with TestClient(app):
        c = Api(app)
        codes = [c.post("/auth/login", {"email": "a@x.io", "password": "whatever1"}).status_code for _ in range(7)]
        assert codes[:5] == [401] * 5 and codes[5] == 429


def test_forged_and_expired_tokens_rejected(app, new_client):
    import jwt
    c = new_client()
    forged = jwt.encode({"sub": "1", "exp": int(time.time()) + 100}, "not-the-key", algorithm="HS256")
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    old = jwt.encode({"sub": "1", "exp": int(time.time()) - 10}, app.state.settings.secret_key, algorithm="HS256")
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    none = jwt.encode({"sub": "1"}, "", algorithm="none")
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {none}"}).status_code == 401


def test_google_callback_creates_viewer(app, new_client):
    app.state.google_exchange = lambda code: {"sub": "g-1", "email": "g@gmail.com", "name": "Gee"}
    c = new_client()
    c.c.cookies.set("cl_oauth_state", "abc")
    r = c.c.get("/auth/google/callback?code=x&state=abc", follow_redirects=False)
    assert r.status_code in (302, 307)
    me = c.get("/auth/me").json()
    assert me["email"] == "g@gmail.com" and me["roles"] == ["viewer"]
    bad = new_client()
    bad.c.cookies.set("cl_oauth_state", "abc")
    assert bad.c.get("/auth/google/callback?code=x&state=zzz", follow_redirects=False).status_code == 400


# ---------------------------------------------------------------- RBAC
def test_rbac_matrix_deny_by_default(admin, new_client, films):
    v = new_client(); viewer = v.register("v@x.io", "V")
    assert v.get("/admin/users").status_code == 403
    assert v.get("/moderation/queue").status_code == 403
    assert v.post("/clubs", {"name": "My club"}).status_code == 403
    assert v.post(f"/films/{films[0]}/spoiler-terms", {"terms": ["twist"]}).status_code == 403
    assert v.post("/admin/sync").status_code == 403
    anon = new_client()
    assert anon.get("/diary").status_code == 401
    assert anon.post(f"/films/{films[0]}/reviews", {"text": "long enough text here"}).status_code == 401
    grant(admin, viewer["id"], "convener")
    assert v.post("/clubs", {"name": "My club"}).status_code == 201  # role change applies on the next request
    assert v.get("/admin/users").status_code == 403  # still not an admin


def test_admin_roles_audit_and_last_admin(admin, new_client):
    v = new_client(); u = v.register("v@x.io")
    grant(admin, u["id"], "moderator")
    assert "moderator" in admin.get("/admin/users", params={"q": "v@x"}).json()[0]["roles"]
    log = admin.get("/admin/audit").json()
    assert any(a["action"] == "role.grant" and a["detail"] == "moderator" for a in log)
    me = admin.get("/auth/me").json()
    r = admin.post(f"/admin/users/{me['id']}/roles", {"role": "admin", "action": "revoke"})
    assert r.status_code == 409  # last admin cannot be removed
    assert admin.post(f"/admin/users/{u['id']}/roles", {"role": "wizard", "action": "grant"}).status_code == 422


def test_audit_log_is_append_only(app, admin):
    import pytest
    from sqlalchemy import select
    from app.models import AuditLog
    with pytest.raises(RuntimeError):
        with app.state.db.session() as s:
            a = s.scalar(select(AuditLog))
            a.action = "tampered"
    with pytest.raises(RuntimeError):
        with app.state.db.session() as s:
            s.delete(s.scalar(select(AuditLog)))


# ---------------------------------------------------------------- search
def test_search_endpoints(films, new_client):
    c = new_client()
    ac = c.get("/films/autocomplete", params={"q": "ro"}).json()
    assert [f["title"] for f in ac] == ["Rosewood Heist"]
    assert c.get("/films/autocomplete", params={"q": "r"}).json() == []  # 1 letter -> nothing
    assert c.get("/films/autocomplete", params={"q": "harb"}).json()[0]["title"] == "Quiet Harbour"
    s = c.get("/films/search", params={"q": "heist"}).json()
    assert s[0]["title"] == "Rosewood Heist"
    assert c.get("/films/search", params={"genre": "sci-fi"}).json()[0]["title"] == "Dark Orbit"
    assert c.get("/films/search", params={"cast": "lee cho"}).json()[0]["title"] == "Dark Orbit"
    assert c.get("/films/search", params={"year": 2015}).json()[0]["title"] == "Quiet Harbour"
    assert c.get("/films/search", params={"q": "zzzz"}).json() == []
    # a half-typed title still finds the film (whole-word index first, then title prefixes from the trie), filters still apply
    assert c.get("/films/search", params={"q": "rosew"}).json()[0]["title"] == "Rosewood Heist"
    assert c.get("/films/search", params={"q": "harb", "year": 2015}).json()[0]["title"] == "Quiet Harbour"
    assert c.get("/films/search", params={"q": "harb", "year": 1901}).json() == []


# ---------------------------------------------------------------- diary / ratings / watchlist
def test_diary_watchlist_aspects_and_taste(admin, films):
    f = films[0]
    assert admin.put(f"/watchlist/{f}").json()["on_watchlist"]
    e = admin.post("/diary", {"film_id": f, "watched_on": "2026-01-02", "stars": 4.5, "format": "IMAX", "notes": "private"})
    assert e.status_code == 201 and not e.json()["rewatch"]
    assert admin.get("/watchlist").json() == []  # watched films leave the watchlist
    again = admin.post("/diary", {"film_id": f, "watched_on": "2026-01-02", "stars": 4})
    assert again.json()["rewatch"]  # same film again -> rewatch
    assert admin.post("/diary", {"film_id": f, "stars": 4.3}).status_code == 422
    assert admin.post("/diary", {"film_id": f, "stars": 5.5}).status_code == 422
    assert len(admin.get("/diary").json()) == 2
    t = admin.get("/me/taste").json()
    assert not t["ready"]
    assert admin.put(f"/films/{f}/aspects", {"values": {"story": 4, "acting": 5}}).status_code == 200
    assert not admin.get("/me/taste").json()["ready"]  # only 2 ratings so far
    admin.put(f"/films/{films[1]}/aspects", {"values": {"story": 2}})
    t = admin.get("/me/taste").json()
    assert t["ready"] and t["radar"]["story"] == 3.0 and t["radar"]["acting"] == 5.0
    assert admin.put(f"/films/{f}/aspects", {"values": {"story": 9}}).status_code == 422
    assert admin.put(f"/films/{f}/aspects", {"values": {"humour": 3}}).status_code == 422
    d = admin.get(f"/films/{f}").json()
    assert d["aspects"]["story"]["avg"] == 4.0
    csv = admin.get("/diary/export", params={"format": "csv"})
    assert "Rosewood Heist" in csv.text and "private" in csv.text
    assert admin.get("/diary/export").json()[0]["notes"] == "private"


# ---------------------------------------------------------------- spoiler shield through the review lifecycle
def post_review(c, film, text):
    r = c.post(f"/films/{film}/reviews", {"text": text})
    assert r.status_code == 202, r.text
    return r.json()


def test_review_scanned_before_visible_and_blurred(app, admin, new_client, films):
    f = films[0]
    w = new_client(); w.register("w@x.io", "Writer")
    rev = post_review(w, f, "Gorgeous visuals and great music. Mara dies in the burning tower at the end. Highly recommended!")
    assert rev["state"] in ("pending_scan", "published")
    wait_scans(app)
    reader = new_client()
    listing = reader.get(f"/films/{f}/reviews").json()
    assert len(listing) == 1
    segs = listing[0]["segments"]
    blurred = [s for s in segs if s["blurred"]]
    assert blurred and all("text" not in s and "reasons" not in s for s in blurred)  # nothing leaks to readers
    assert any("Gorgeous visuals" in s.get("text", "") for s in segs)
    rev_id = listing[0]["id"]
    shown = reader.get(f"/reviews/{rev_id}/segments/{blurred[0]['idx']}").json()
    assert "burning tower" in shown["text"]  # Reveal fetches the text for this reader only
    own = w.get(f"/reviews/{rev_id}").json()
    assert any(s.get("reasons") for s in own["segments"] if s["blurred"])  # writer sees WHY it was blurred
    assert w.post(f"/films/{f}/reviews", {"text": "second review text"}).status_code == 409


def test_pending_review_invisible_until_scan(app, admin, new_client, films):
    app.state.pool.shutdown(wait=True)  # no workers -> scan cannot finish
    w = new_client(); w.register("w@x.io")
    rev = post_review(w, films[1], "A calm film about the sea and loneliness.")
    assert rev["state"] == "pending_scan"
    assert new_client().get(f"/films/{films[1]}/reviews").json() == []
    assert new_client().get(f"/reviews/{rev['id']}").status_code == 404
    assert w.get(f"/reviews/{rev['id']}").json()["state"] == "pending_scan"
    from app.scheduler.pool import WorkerPool
    from app.services import jobs
    app.state.pool = WorkerPool(2).start()  # simulate a server restart: the in-memory queue is gone
    assert jobs.recover_pending(app) == 1  # restart recovery: no lost scans
    wait_scans(app)
    assert w.get(f"/reviews/{rev['id']}").json()["state"] == "published"


def test_writer_tags_and_clean_review(app, admin, new_client, films):
    f = films[1]
    w = new_client(); w.register("w@x.io")
    rev = post_review(w, f, "Lovely film overall. ||He was a ghost all along|| I cried anyway.")
    wait_scans(app)
    segs = w.get(f"/reviews/{rev['id']}").json()["segments"]
    assert any(s["blurred"] and "ghost" in s["text"] for s in segs)
    assert not any(s["blurred"] and "Lovely" in s["text"] for s in segs)


def test_three_reports_hide_and_moderator_flow(app, admin, new_client, films):
    f = films[0]
    w = new_client(); w.register("w@x.io", "Writer")
    post_review(w, f, "Wonderful movie, the cast is great and the soundtrack is lovely.")
    wait_scans(app)
    rid = w.get("/auth/me") and new_client().get(f"/films/{f}/reviews").json()[0]["id"]
    assert w.post(f"/reviews/{rid}/report", {}).status_code == 400  # own review
    readers = []
    for i in range(3):
        r = new_client(); r.register(f"r{i}@x.io"); readers.append(r)
    assert readers[0].post(f"/reviews/{rid}/report", {}).json() == {"reports": 1, "hidden": False}
    assert readers[0].post(f"/reviews/{rid}/report", {}).json()["ignored"]  # repeat ignored
    assert readers[1].post(f"/reviews/{rid}/report", {}).json()["hidden"] is False
    assert readers[2].post(f"/reviews/{rid}/report", {}).json() == {"reports": 3, "hidden": True}
    assert new_client().get(f"/films/{f}/reviews").json() == []  # hidden reviews never listed
    m = new_client(); mu = m.register("m@x.io"); grant(admin, mu["id"], "moderator")
    q = m.get("/moderation/queue").json()
    assert q[0]["id"] == rid and q[0]["state"] == "hidden" and q[0]["reports"] == 3
    assert readers[0].get("/moderation/queue").status_code == 403
    ok = m.post(f"/moderation/{rid}/approve")
    assert ok.json()["state"] == "published"
    # second moderator acting on an already-published review: invalid transition -> 409
    assert m.post(f"/moderation/{rid}/remove", {}).json()["state"] == "removed"
    assert m.post(f"/moderation/{rid}/approve").status_code == 409  # Removed is final
    assert m.post(f"/moderation/{rid}/remove", {}).status_code == 409
    log = admin.get("/admin/audit").json()
    assert {"review.auto_hide", "review.approve", "review.remove"} <= {a["action"] for a in log}
    # writer was notified by e-mail (dev outbox)
    assert app.state.pool.wait_idle(10)
    assert admin.get("/admin/stats").json()["outbox"].get("logged", 0) >= 1


def test_moderator_reblur_teaches_rag_and_wordlist(app, admin, new_client, films):
    f = films[2]
    w = new_client(); w.register("w@x.io")
    post_review(w, f, "Fantastic visuals throughout. The captain sacrifices himself to restart the reactor. Go watch it.")
    wait_scans(app)
    rid = new_client().get(f"/films/{f}/reviews").json()[0]["id"]
    m = new_client(); mu = m.register("m@x.io"); grant(admin, mu["id"], "moderator")
    segs = w.get(f"/reviews/{rid}").json()["segments"]
    idx = [s["idx"] for s in segs if "sacrifices" in s.get("text", "")][0]
    assert m.post(f"/moderation/{rid}/reblur", {"segments": [idx]}).json()["state"] == "published"
    assert m.post(f"/films/{f}/spoiler-terms", {"terms": ["reactor", "the"]}).json()["added"] == ["reactor"]
    # a later review repeating the confirmed spoiler gets blurred thanks to retrieval over confirmed spoilers
    w2 = new_client(); w2.register("w2@x.io")
    post_review(w2, f, "Meh. The captain sacrifices himself to restart the reactor, obviously. Fine otherwise.")
    wait_scans(app)
    listing = new_client().get(f"/films/{f}/reviews").json()
    newest = listing[0]
    assert any(s["blurred"] for s in newest["segments"])
    assert any(t["term"] == "reactor" for t in m.get(f"/films/{f}/spoiler-terms").json())


def test_reveal_only_published(app, admin, new_client, films):
    f = films[0]
    w = new_client(); w.register("w@x.io")
    post_review(w, f, "Nice. ||the butler did it|| Great.")
    wait_scans(app)
    rid = new_client().get(f"/films/{f}/reviews").json()[0]["id"]
    assert new_client().get(f"/reviews/{rid}/segments/1").status_code == 200
    assert new_client().get(f"/reviews/{rid}/segments/99").status_code == 404


# ---------------------------------------------------------------- clubs and polls
def setup_club(admin, new_client, films, n_members=3, deadline=None):
    conv = new_client(); cu = conv.register("conv@x.io", "Conv"); grant(admin, cu["id"], "convener")
    club = conv.post("/clubs", {"name": "Midnight Club", "is_public": False}).json()
    members = []
    for i in range(n_members):
        m = new_client(); mu = m.register(f"m{i}@x.io", f"M{i}")
        assert conv.post(f"/clubs/{club['id']}/members", {"email": f"m{i}@x.io"}).status_code == 201
        members.append((m, mu))
    body = {"title": "Pick Friday's film", "film_ids": films[:2]}
    if deadline:
        body["deadline"] = deadline
    poll = conv.post(f"/clubs/{club['id']}/polls", body).json()
    return conv, club, members, poll


def test_club_permissions_private_and_roles(admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    stranger = new_client(); stranger.register("s@x.io")
    assert stranger.get(f"/clubs/{club['id']}").status_code == 403  # private
    assert stranger.get(f"/polls/{poll['id']}").status_code == 403
    assert stranger.post(f"/clubs/{club['id']}/join").status_code == 403
    m0 = members[0][0]
    assert m0.post(f"/clubs/{club['id']}/polls", {"title": "x y", "film_ids": films[:2]}).status_code == 403
    assert m0.put(f"/clubs/{club['id']}/watchlist/{films[0]}").status_code == 403
    assert conv.put(f"/clubs/{club['id']}/watchlist/{films[0]}").status_code == 200
    assert m0.get(f"/clubs/{club['id']}").json()["watchlist"][0]["title"] == "Rosewood Heist"
    cid = conv.get("/auth/me").json()["id"]
    assert conv.delete(f"/clubs/{club['id']}/members/{cid}").status_code == 409  # hand over first
    assert m0.post(f"/clubs/{club['id']}/members", {"email": "s@x.io"}).status_code == 403
    # convener appoints a co-convener, who can then manage
    assert conv.post(f"/clubs/{club['id']}/members", {"email": "m0@x.io", "role": "co_convener"}).status_code == 201
    assert m0.put(f"/clubs/{club['id']}/watchlist/{films[1]}").status_code == 200


def test_poll_lifecycle_one_vote_and_frozen_result(app, admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    pid, opt = poll["id"], poll["options"]
    m0 = members[0][0]
    assert m0.post(f"/polls/{pid}/vote", {"option_id": opt[0]["id"]}).status_code == 409  # still Draft
    assert conv.post(f"/polls/{pid}/open").json()["state"] == "open"
    assert conv.post(f"/polls/{pid}/open").status_code == 409  # Open -> Open invalid
    assert conv.post(f"/polls/{pid}/cancel").status_code == 409  # only Draft can be cancelled
    assert m0.post(f"/polls/{pid}/vote", {"option_id": opt[1]["id"]}).status_code == 200
    assert m0.post(f"/polls/{pid}/vote", {"option_id": opt[0]["id"]}).status_code == 409  # already voted
    assert members[1][0].post(f"/polls/{pid}/vote", {"option_id": opt[1]["id"]}).status_code == 200
    assert members[2][0].post(f"/polls/{pid}/vote", {"option_id": opt[0]["id"]}).status_code == 200
    assert members[2][0].post(f"/polls/{pid}/vote", {"option_id": 99999}).status_code in (409, 422)
    outsider = new_client(); outsider.register("o@x.io")
    assert outsider.post(f"/polls/{pid}/vote", {"option_id": opt[0]["id"]}).status_code == 403
    closed = conv.post(f"/polls/{pid}/close").json()
    assert closed["state"] == "closed" and closed["winner_film_id"] == opt[1]["film_id"] and closed["total_votes"] == 3
    assert m0.post(f"/polls/{pid}/vote", {"option_id": opt[0]["id"]}).status_code == 409  # closed
    assert conv.post(f"/polls/{pid}/close").status_code == 409
    sc = conv.post(f"/polls/{pid}/screening", {"when": "2030-01-01T19:00:00"})
    assert sc.status_code == 200 and sc.json()["screening_date"].startswith("2030-01-01")
    hist = m0.get(f"/clubs/{club['id']}/polls").json()
    assert hist[0]["state"] == "closed" and hist[0]["total_votes"] == 3
    assert app.state.pool.wait_idle(10)  # notification e-mails ran
    assert admin.get("/admin/stats").json()["outbox"].get("logged", 0) >= 4


def test_draft_poll_can_be_cancelled(admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    assert conv.post(f"/polls/{poll['id']}/cancel").json()["state"] == "cancelled"
    assert conv.post(f"/polls/{poll['id']}/open").status_code == 409


def test_poll_closes_at_deadline(app, admin, new_client, films):
    soon = (dt.datetime.utcnow() + dt.timedelta(seconds=1)).isoformat()
    conv, club, members, poll = setup_club(admin, new_client, films, deadline=soon)
    conv.post(f"/polls/{poll['id']}/open")
    opt = poll["options"]
    assert members[0][0].post(f"/polls/{poll['id']}/vote", {"option_id": opt[0]["id"]}).status_code == 200
    time.sleep(1.3)
    r = members[1][0].post(f"/polls/{poll['id']}/vote", {"option_id": opt[0]["id"]})
    assert r.status_code == 409  # vote arriving after the deadline is rejected
    assert members[1][0].get(f"/polls/{poll['id']}").json()["state"] == "closed"


def test_100_concurrent_votes_no_duplicates(app, admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films, n_members=100)
    pid, opt = poll["id"], poll["options"]
    conv.post(f"/polls/{pid}/open")
    results = []

    def go(i, api):
        # every member also double-clicks: two simultaneous votes from the same account
        for _ in range(2):
            r = api.post(f"/polls/{pid}/vote", {"option_id": opt[i % 2]["id"]})
            results.append(r.status_code)

    threads = [threading.Thread(target=go, args=(i, m)) for i, (m, _) in enumerate(members)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert results.count(200) == 100 and results.count(409) == 100
    assert conv.get(f"/polls/{pid}").json()["total_votes"] == 100  # 0 duplicate votes
    from sqlalchemy import func, select
    from app.models import Vote
    with app.state.db.session() as s:
        assert s.scalar(select(func.count(func.distinct(Vote.user_id)))) == 100


def test_websocket_live_poll_results(app, admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    pid, opt = poll["id"], poll["options"]
    conv.post(f"/polls/{pid}/open")
    watcher = members[1][0]
    with watcher.c.websocket_connect(f"/ws/polls/{pid}") as ws:
        first = ws.receive_json()
        assert first["total_votes"] == 0
        assert members[0][0].post(f"/polls/{pid}/vote", {"option_id": opt[0]["id"]}).status_code == 200
        live = ws.receive_json()
        assert live["total_votes"] == 1 and live["options"][0]["votes"] == 1
    stranger = new_client(); stranger.register("s@x.io")
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with stranger.c.websocket_connect(f"/ws/polls/{pid}") as ws:
            ws.receive_json()


# ---------------------------------------------------------------- social
def test_follow_feed_and_similarity(admin, new_client, films):
    a = new_client(); au = a.register("a@x.io", "Ann")
    b = new_client(); bu = b.register("b@x.io", "Bob")
    assert b.put(f"/follow/{bu['id']}").status_code == 400
    assert b.put(f"/follow/{au['id']}").json()["following"]
    a.post("/diary", {"film_id": films[0], "stars": 5})
    a.post("/diary", {"film_id": films[1], "stars": 3})
    feed = b.get("/feed").json()
    assert [x["film"] for x in feed if "film" in x] == ["Quiet Harbour", "Rosewood Heist"] and feed[0]["user"] == "Ann"
    assert [x["badge"] for x in feed if x["type"] == "badge"] == ["First Reel"]
    b.delete(f"/follow/{au['id']}")
    assert b.get("/feed").json() == []
    # similarity needs >= 5 co-rated films
    from app.services.catalog import upsert_tmdb_film
    app = a.c.app
    extra = []
    with app.state.db.session() as s:
        for i in range(10, 16):
            extra.append(upsert_tmdb_film(s, {"id": i, "title": f"Extra {i}", "release_date": "2000-01-01"}).id)
    for f in extra:
        a.put(f"/films/{f}/aspects", {"values": {"story": 4}})
        b.put(f"/films/{f}/aspects", {"values": {"story": 4}})
    sim = b.get("/me/similar").json()
    assert sim and sim[0]["name"] == "Ann" and sim[0]["similarity"] > 0.99
    assert admin.get("/me/similar").json() == []


def test_health_and_security_headers(app, new_client):
    r = new_client().get("/health")
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.json()["jobs"]["failed"] == 0


def test_browse_stats_and_profile(app, admin, films):
    import datetime as dt
    from app.routers.browse import streak_of
    today = dt.date(2026, 10, 4)
    assert streak_of([today, today - dt.timedelta(1), today - dt.timedelta(3)], today) == 2
    assert streak_of([today - dt.timedelta(1)], today) == 1 and streak_of([], today) == 0

    fid = films[0]
    assert admin.post("/diary", json={"film_id": fid, "stars": 4.5}).status_code == 201
    assert admin.put(f"/watchlist/{films[1]}").status_code == 200
    r = admin.get("/films", params={"sort": "top"}).json()
    assert r["total"] == 3 and r["films"][0]["id"] == fid and r["films"][0]["rating"] == 4.5
    assert any(f["on_watchlist"] for f in r["films"])
    assert admin.get("/films", params={"sort": "nope"}).status_code == 422
    g = admin.get("/genres").json()
    assert g and admin.get("/films", params={"genre": g[0]["genre"]}).json()["total"] == g[0]["films"]
    d = admin.get(f"/films/{fid}").json()
    assert d["rating"] == {"avg": 4.5, "n": 1, "hist": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0]} and d["my_stars"] == 4.5
    st = admin.get("/me/stats").json()
    assert st["films"] == 1 and st["avg_stars"] == 4.5 and st["streak"] == 1 and st["watchlist"] == 1
    me = admin.get("/auth/me").json()
    p = admin.get(f"/users/{me['id']}").json()
    assert p["is_me"] and p["favourites"][0]["id"] == fid and p["stats"]["films"] == 1
    assert admin.get("/users/99999").status_code == 404
    assert admin.get("/watchlist").json()[0]["id"] == films[1]
    assert admin.get("/diary").json()[0]["year"] is not None


def test_badges_streaks_likes_lists_threads_watchalongs(app, admin, new_client, films):
    import datetime as dt
    from app.gamification import BADGES, METRICS, streaks
    today = dt.date(2026, 10, 4)
    days = [today - dt.timedelta(d) for d in (0, 1, 2, 5, 6, 7, 8)]
    assert streaks(days, today) == {"current": 3, "longest": 4}
    assert streaks([], today) == {"current": 0, "longest": 0}
    assert all(b.metric in METRICS for b in BADGES) and len({b.key for b in BADGES}) == len(BADGES)

    # ---- badges: first log earns First Reel exactly once and it is reported back
    r = admin.post("/diary", json={"film_id": films[0], "stars": 4}).json()
    assert [b["key"] for b in r["new_badges"]] == ["first_reel"]
    assert admin.post("/diary", json={"film_id": films[1], "stars": 3}).json()["new_badges"] == []
    mine = {b["key"]: b for b in admin.get("/me/badges").json()}
    assert mine["first_reel"]["earned"] and mine["regular"]["value"] == 2 and not mine["regular"]["earned"]
    assert mine["club_captain"]["percent"] == 0
    me = admin.get("/auth/me").json()
    assert admin.get(f"/users/{me['id']}").json()["badges"][0]["earned"]
    assert admin.get("/users/9999/badges").status_code == 404

    b = new_client(); bid = b.register("bea@example.com", "Bea")["id"]

    # ---- reviews can be liked once; author sees their own pending review
    rid = admin.post(f"/films/{films[1]}/reviews", json={"text": "A calm and lovely film about a harbour town."}).json()["id"]
    assert app.state.pool.wait_idle(10)
    assert b.put(f"/likes/review/{rid}").json() == {"liked": True, "likes": 1}
    assert b.put(f"/likes/review/{rid}").json()["likes"] == 1
    lst = b.get(f"/films/{films[1]}/reviews", params={"sort": "popular"}).json()
    assert lst[0]["likes"] == 1 and lst[0]["liked"] is True
    assert admin.get(f"/films/{films[1]}/reviews").json()[0]["liked"] is False
    assert b.delete(f"/likes/review/{rid}").json() == {"liked": False, "likes": 0}
    assert b.put("/likes/review/99999").status_code == 404 and b.put(f"/likes/nonsense/{rid}").status_code == 404
    assert b.get(f"/films/{films[1]}/reviews", params={"sort": "friends"}).json() == []

    # ---- lists
    l = b.post("/lists", json={"title": "Sunday films", "description": "slow", "film_ids": [films[0], films[0], 99999]}).json()
    assert l["count"] == 1 and l["mine"]
    lid = l["id"]
    assert b.put(f"/lists/{lid}/films/{films[2]}").json()["count"] == 2
    assert admin.put(f"/lists/{lid}/films/{films[1]}").status_code == 200  # admin is a moderator: may fix lists
    v = new_client(); v.register("vic@example.com", "Vic")
    assert v.put(f"/lists/{lid}/films/{films[1]}").status_code == 403
    assert v.patch(f"/lists/{lid}", json={"title": "Hacked"}).status_code == 403
    assert v.put(f"/likes/list/{lid}").json()["likes"] == 1
    got = v.get(f"/lists/{lid}").json()
    assert got["liked"] and [f["id"] for f in got["films"]] == [films[0], films[2], films[1]] and not got["mine"]
    assert v.get("/lists").json()[0]["id"] == lid and v.get("/lists", params={"tab": "friends"}).json() == []
    assert b.delete(f"/lists/{lid}/films/{films[2]}").json()["count"] == 2
    assert b.patch(f"/lists/{lid}", json={"title": "Sunday films, again"}).json()["title"] == "Sunday films, again"

    # ---- club discussion: members only, upvotes, replies
    cid = admin.post("/clubs", json={"name": "Talkers", "description": "", "is_public": True}).json()["id"]
    assert b.post(f"/clubs/{cid}/threads", json={"title": "Hello there"}).status_code == 403
    assert b.post(f"/clubs/{cid}/join").status_code == 200
    t = b.post(f"/clubs/{cid}/threads", json={"title": "What should we watch?", "body": "Ideas please", "tag": "Question"}).json()
    assert b.post(f"/clubs/{cid}/threads", json={"title": "Bad tag", "tag": "Nope"}).status_code == 422
    assert admin.put(f"/likes/thread/{t['id']}").json()["likes"] == 1
    full = admin.post(f"/threads/{t['id']}/replies", json={"body": "Dark Orbit!"}).json()
    assert full["replies"] == 1 and full["reply_list"][0]["author"]["name"]
    assert v.post(f"/threads/{t['id']}/replies", json={"body": "not a member"}).status_code == 403
    row = v.get(f"/clubs/{cid}/threads").json()[0]
    assert row["votes"] == 1 and row["replies"] == 1 and row["can_remove"] is False
    assert v.delete(f"/threads/{t['id']}").status_code == 403
    assert admin.delete(f"/threads/{t['id']}").json() == {"ok": True} and admin.get(f"/clubs/{cid}/threads").json() == []

    # ---- watch-alongs: conveners schedule, members RSVP, a poll's screening date creates one
    soon = (dt.datetime.utcnow() + dt.timedelta(days=2)).isoformat()
    assert b.post(f"/clubs/{cid}/watchalongs", json={"film_id": films[0], "starts_at": soon}).status_code == 403
    past = (dt.datetime.utcnow() - dt.timedelta(days=2)).isoformat()
    assert admin.post(f"/clubs/{cid}/watchalongs", json={"film_id": films[0], "starts_at": past}).status_code == 422
    w = admin.post(f"/clubs/{cid}/watchalongs", json={"film_id": films[0], "starts_at": soon}).json()
    assert w["going"] == 0 and w["film"]["id"] == films[0]
    assert v.put(f"/watchalongs/{w['id']}/rsvp").status_code == 403
    assert b.put(f"/watchalongs/{w['id']}/rsvp").json()["going"] == 1 and b.put(f"/watchalongs/{w['id']}/rsvp").json()["going"] == 1
    assert b.delete(f"/watchalongs/{w['id']}/rsvp").json()["going"] == 0
    for f in films[:2]:
        admin.put(f"/clubs/{cid}/watchlist/{f}")
    pid = admin.post(f"/clubs/{cid}/polls", json={"title": "Next", "film_ids": films[:2]}).json()["id"]
    admin.post(f"/polls/{pid}/open"); b.post(f"/polls/{pid}/vote", json={"option_id": admin.get(f"/polls/{pid}").json()["options"][1]["id"]})
    admin.post(f"/polls/{pid}/close")
    assert admin.post(f"/polls/{pid}/screening", json={"when": soon}).status_code == 200
    was = admin.get(f"/clubs/{cid}/watchalongs").json()
    assert len(was) == 2 and sum(x["from_poll"] for x in was) == 1
    admin.post(f"/polls/{pid}/screening", json={"when": soon})  # changing the date updates, never duplicates
    assert len(admin.get(f"/clubs/{cid}/watchalongs").json()) == 2
    assert admin.delete(f"/watchalongs/{w['id']}").json() == {"ok": True}

    # ---- leaderboard + feed show the new activity; convening a club earned a badge
    v.put(f"/follow/{bid}")
    kinds = {x["type"] for x in v.get("/feed").json()}
    assert "list" in kinds
    board = admin.get("/leaderboard/streaks").json()
    assert board[0]["me"] and board[0]["days"] == 1
    assert {x["key"] for x in admin.get("/me/badges").json() if x["earned"]} >= {"first_reel", "club_captain"}
