"""Password reset, session revocation, profile bio/avatar, in-app notifications and schema migrations."""
import datetime as dt
import re

from sqlalchemy import create_engine, inspect, select, text

from app.migrations import MIGRATIONS, migrate
from app.models import Outbox, PasswordReset, now


def _reset_link(app, email):
    with app.state.db.session() as s:
        rows = list(s.scalars(select(Outbox).where(Outbox.to_email == email, Outbox.subject.like("Reset%"))
                              .order_by(Outbox.id)))
    assert rows, "no reset e-mail was queued"
    return re.search(r"token=([\w-]+)", rows[-1].body).group(1)


# ---------------------------------------------------------------- password reset
def test_forgot_password_answers_the_same_for_unknown_and_known_addresses(app, admin, new_client):
    anon = new_client()
    known = anon.post("/auth/forgot", {"email": "admin@x.io"})
    unknown = anon.post("/auth/forgot", {"email": "nobody@x.io"})
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()
    with app.state.db.session() as s:
        mails = [o.to_email for o in s.scalars(select(Outbox).where(Outbox.subject.like("Reset%")))]
    assert mails == ["admin@x.io"]  # no mail for the address that has no account


def test_reset_flow_sets_new_password_once_and_kills_old_sessions(app, admin, new_client):
    victim = new_client(); victim.register("v@x.io", "Vic", "oldpassword1")
    assert victim.get("/auth/me").status_code == 200
    anon = new_client()
    assert anon.post("/auth/forgot", {"email": "v@x.io"}).status_code == 200
    tok = _reset_link(app, "v@x.io")
    with app.state.db.session() as s:  # only the hash is stored
        assert s.scalar(select(PasswordReset.token_hash)) != tok

    assert anon.post("/auth/reset", {"token": "x" * 40, "password": "brandnewpass1"}).status_code == 400
    assert anon.post("/auth/reset", {"token": tok, "password": "short"}).status_code == 400
    import time
    time.sleep(1.1)  # the old session was issued in an earlier second than the reset
    assert anon.post("/auth/reset", {"token": tok, "password": "brandnewpass1"}).status_code == 200
    assert anon.post("/auth/reset", {"token": tok, "password": "another-pass-2"}).status_code == 400  # single use

    assert victim.get("/auth/me").status_code == 401  # the session from before the reset is void
    assert new_client().post("/auth/login", {"email": "v@x.io", "password": "oldpassword1"}).status_code == 401
    fresh = new_client()
    assert fresh.post("/auth/login", {"email": "v@x.io", "password": "brandnewpass1"}).status_code == 200
    assert fresh.get("/auth/me").status_code == 200
    kinds = [n["kind"] for n in fresh.get("/notifications").json()["items"]]
    assert "security" in kinds  # told in-app that the password changed


def test_expired_reset_link_is_refused_and_requests_are_throttled(app, admin, new_client):
    anon = new_client()
    anon.post("/auth/forgot", {"email": "admin@x.io"})
    anon.post("/auth/forgot", {"email": "admin@x.io"})  # inside the cool-down: ignored
    with app.state.db.session() as s:
        assert len(list(s.scalars(select(PasswordReset)))) == 1
        assert len(list(s.scalars(select(Outbox).where(Outbox.subject.like("Reset%"))))) == 1
        s.execute(text("UPDATE password_resets SET expires_at = :t"), {"t": now() - dt.timedelta(minutes=1)})
    tok = _reset_link(app, "admin@x.io")
    assert anon.post("/auth/reset", {"token": tok, "password": "brandnewpass1"}).status_code == 400


def test_a_new_reset_request_does_not_leave_an_old_link_usable_after_success(app, admin, new_client):
    anon = new_client()
    anon.post("/auth/forgot", {"email": "admin@x.io"})
    first = _reset_link(app, "admin@x.io")
    with app.state.db.session() as s:  # skip the cool-down
        s.execute(text("UPDATE password_resets SET created_at = :t"), {"t": now() - dt.timedelta(minutes=5)})
    anon.post("/auth/forgot", {"email": "admin@x.io"})
    second = _reset_link(app, "admin@x.io")
    assert first != second
    assert anon.post("/auth/reset", {"token": second, "password": "brandnewpass1"}).status_code == 200
    assert anon.post("/auth/reset", {"token": first, "password": "brandnewpass2"}).status_code == 400


def test_forgot_is_not_blocked_by_csrf_for_a_signed_in_browser(app, admin):
    # the admin fixture is signed in; the form must still work (it carries no session secret of its own)
    assert admin.c.post("/auth/forgot", json={"email": "admin@x.io"}).status_code == 200


def test_admin_can_read_the_dev_mailbox_but_nobody_else(app, admin, new_client):
    new_client().post("/auth/forgot", {"email": "admin@x.io"})
    box = admin.get("/admin/outbox").json()
    assert any("/reset?token=" in m["body"] for m in box)
    other = new_client(); other.register("o@x.io", "Other")
    assert other.get("/admin/outbox").status_code == 403
    assert new_client().get("/admin/outbox").status_code == 401


def test_change_password_needs_the_current_one_and_signs_other_devices_out(app, admin, new_client):
    a = new_client(); a.register("p@x.io", "Pat", "firstpass123")
    b = new_client()
    assert b.post("/auth/login", {"email": "p@x.io", "password": "firstpass123"}).status_code == 200
    assert a.post("/auth/change-password", {"current_password": "wrong-one", "new_password": "secondpass12"}).status_code == 403
    import time
    time.sleep(1.1)
    assert a.post("/auth/change-password", {"current_password": "firstpass123", "new_password": "secondpass12"}).status_code == 200
    assert a.get("/auth/me").status_code == 200  # this device stays signed in
    assert b.get("/auth/me").status_code == 401  # the other one does not
    assert new_client().post("/auth/login", {"email": "p@x.io", "password": "secondpass12"}).status_code == 200


# ---------------------------------------------------------------- profile
def test_profile_bio_and_avatar(app, admin, new_client):
    u = new_client(); u.register("b@x.io", "Bea")
    assert u.get("/auth/me").json()["bio"] == "" and u.get("/auth/me").json()["avatar"] == ""
    assert u.patch("/auth/me", {"avatar": "not-a-key"}).status_code == 400
    assert u.patch("/auth/me", {"bio": "x" * 301}).status_code == 400
    r = u.patch("/auth/me", {"bio": "  Horror   fan.\n\nNight owl.  ", "avatar": "ghost"}).json()
    assert r["bio"] == "Horror fan. Night owl." and r["avatar"] == "ghost"
    assert u.patch("/auth/me", {"avatar": ""}).json()["avatar"] == ""


def test_public_profile_shows_bio_and_avatar(app, admin, new_client):
    u = new_client(); me = u.register("b@x.io", "Bea")
    u.patch("/auth/me", {"bio": "Hello there", "avatar": "star"})
    prof = new_client().get(f"/users/{me['id']}").json()
    assert prof["bio"] == "Hello there" and prof["avatar"] == "star"


# ---------------------------------------------------------------- notifications
def test_like_follow_reply_and_moderation_notify_the_right_person(app, admin, new_client, films):
    w = new_client(); wu = w.register("w@x.io", "Writer")
    fan = new_client(); fan.register("f@x.io", "Fan")
    r = w.post(f"/films/{films[1]}/reviews", {"text": "A quiet little film that I enjoyed a lot."}).json()
    assert app.state.pool.wait_idle(20)
    assert fan.put(f"/likes/review/{r['id']}").status_code == 200
    assert fan.put(f"/follow/{wu['id']}").status_code == 200

    got = w.get("/notifications").json()
    assert got["unread"] == 2
    texts = " | ".join(n["text"] for n in got["items"])
    assert "Fan liked your review" in texts and "started following you" in texts
    assert any(n["link"] == f"/films/{films[1]}" for n in got["items"])
    assert fan.get("/notifications").json()["unread"] == 0  # actors are not notified of their own actions

    club = admin.post("/clubs", {"name": "Notes club"}).json()
    w.post(f"/clubs/{club['id']}/join"); fan.post(f"/clubs/{club['id']}/join")
    th = w.post(f"/clubs/{club['id']}/threads", {"title": "Best ending ever?", "body": "discuss"}).json()
    fan.post(f"/threads/{th['id']}/replies", {"body": "Definitely this one"})
    assert any("replied to your thread" in n["text"] for n in w.get("/notifications").json()["items"])

    assert admin.post(f"/moderation/{r['id']}/remove", {}).status_code == 200
    assert any(n["kind"] == "moderation" for n in w.get("/notifications").json()["items"])

    # reading
    ids = [n["id"] for n in w.get("/notifications").json()["items"]][:1]
    assert w.post("/notifications/read", {"ids": ids}).json()["unread"] == w.get("/notifications").json()["unread"]
    assert w.post("/notifications/read", {}).json()["unread"] == 0
    assert all(n["read"] for n in w.get("/notifications").json()["items"])


def test_notifications_are_private_and_need_login(app, admin, new_client):
    assert new_client().get("/notifications").status_code == 401
    a = new_client(); a.register("a@x.io", "A")
    b = new_client(); bu = b.register("b@x.io", "B")
    a.put(f"/follow/{bu['id']}")
    assert b.get("/notifications").json()["unread"] == 1
    assert a.get("/notifications").json()["items"] == []
    a.post("/notifications/read", {})  # cannot touch B's
    assert b.get("/notifications").json()["unread"] == 1


# ---------------------------------------------------------------- migrations
def _old_database(path):
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as c:  # the users table as it was before this release: no bio / avatar / password_changed_at
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(254), display_name VARCHAR(80))"))
        c.execute(text("INSERT INTO users (email, display_name) VALUES ('old@x.io', 'Old')"))
    return eng


def test_migration_upgrades_an_old_database_and_is_idempotent(tmp_path):
    eng = _old_database(tmp_path / "old.db")
    assert migrate(eng) == [m[0] for m in MIGRATIONS]
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    assert {"bio", "avatar", "password_changed_at"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT email, bio, avatar FROM users")).one() == ("old@x.io", "", "")  # data kept, defaults set
        assert c.execute(text("SELECT count(*) FROM schema_version")).scalar() == len(MIGRATIONS)
    assert migrate(eng) == []  # second run does nothing


def test_app_starts_on_an_old_database_file(tmp_path):
    """The real upgrade path: a database from before this release, opened by the new code."""
    from app.db import Database
    path = tmp_path / "legacy.db"
    _old_database(path).dispose()
    db = Database(f"sqlite:///{path}")
    db.create_all()  # creates the missing new tables, then migrates the old one
    names = set(inspect(db.engine).get_table_names())
    assert {"notifications", "password_resets", "schema_version"} <= names
    assert "bio" in {c["name"] for c in inspect(db.engine).get_columns("users")}
