"""Sprint 2 / Gate 3 partial-test register, one block per engine.

Every test name starts with its register ID (TC-E<engine>-<nn>) so the IDs in docs/sprint2/09_test_register.md can be
found with `pytest -k tc_e1_06` and so on. Each engine has a normal case, a boundary/invalid case and a failure case,
plus the concurrency / transaction / security / API checks that apply to it.

E1 Search & Spoiler (DSA)     - Goureesh N Doddamani
E2 Storage & Transaction (DBMS) - Manish Singri
E3 Background Job Scheduler (OS) - Ashutosh Kulkarni
E4 CN & Web (security, API)    - Omkar Anantapur
"""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.dsa.aho_corasick import AhoCorasick
from app.dsa.inverted_index import InvertedIndex
from app.dsa.lru import LRUCache
from app.dsa.trie import Trie
from app.main import create_app
from app.models import AuditLog
from app.scheduler.pool import BATCH, USER, BoundedPriorityQueue, Job, QueueFull, WorkerPool
from app.security import TokenBucket
from app.spoiler.shield import FilmInfo, SpoilerShield
from app.spoiler.wordlist import terms_from_cast
from tests.conftest import Api, grant, make_settings
from tests.test_api import setup_club
from tests.test_spoiler_ml import make_passages

PLOT = ("Mara steals the crown jewels from the palace. Her brother Tobin betrays her to the king. "
        "In the finale Mara dies in the burning tower.")


@pytest.fixture(scope="module")
def shield_and_info():
    ps = make_passages(PLOT)
    sh = SpoilerShield()
    filler = [f"story number {i} about {w} and a {w2} journey across {w3}" for i, (w, w2, w3) in enumerate(
        [("pirates", "dangerous", "space"), ("farmers", "quiet", "valleys"), ("robots", "strange", "cities")] * 6)]
    sh.fit_space(ps + filler)
    info = FilmInfo(1, 1, terms_from_cast(["Mara Vell", "Tobin Vell"]) + [("burning tower", "plot")], ps, [])
    return sh, info


def blurred(result) -> bool:
    return any(s.blurred for s in result.segments)


# =====================================================================================================  E1
def test_tc_e1_01_trie_returns_top10_by_popularity_for_prefix():
    t = Trie(k=10)
    for i in range(25):
        t.insert(f"Dark Film {i:02d}", i, popularity=float(i))
    t.insert("Drishyam", 100, popularity=5.0)
    got = t.search("dark")
    assert len(got) == 10
    assert got == list(range(24, 14, -1))  # most popular first, never more than 10


def test_tc_e1_02_trie_boundary_one_letter_and_unknown_prefix():
    t = Trie(k=10)
    t.insert("Drishyam", 1, popularity=1.0)
    assert t.search("zz") == []          # nothing matches: empty list, no error
    assert t.search("DRI") == [1]        # case does not matter


def test_tc_e1_03_aho_corasick_matches_whole_words_only():
    ac = AhoCorasick.from_terms([("tower", "plot"), ("mara", "name")])
    hits = {h[2] for h in ac.search("Mara climbs the tower. Towering heights, Marathon.")}
    assert hits == {"tower", "mara"}
    assert all(h[2] != "tower" or h[0] == 16 for h in ac.search("Mara climbs the tower. Towering"))


def test_tc_e1_04_spoiler_sentence_is_blurred(shield_and_info):
    sh, info = shield_and_info
    r = sh.scan("Nice cast. Mara dies in the burning tower at the end. Good music.", info)
    assert blurred(r) and r.risk >= 0.7
    assert [s.blurred for s in r.segments] == [False, True, False]  # only the spoiler sentence


def test_tc_e1_05_clean_review_is_not_blurred(shield_and_info):
    sh, info = shield_and_info
    r = sh.scan("Nice cast. The score is lovely. Mara is a likeable lead.", info)
    assert not blurred(r)


def test_tc_e1_06_zero_width_space_cannot_hide_a_spoiler(shield_and_info):
    """DEF-07: 'burn\\u200bing tower' scored 0.15 and was shown unblurred before Sprint 2."""
    sh, info = shield_and_info
    r = sh.scan("The burn​ing tower scene is the end.", info)
    assert blurred(r) and r.risk >= 0.7


def test_tc_e1_07_no_break_space_cannot_hide_a_spoiler(shield_and_info):
    """DEF-08: 'burning\\u00a0tower' scored 0.54 and was not blurred before Sprint 2."""
    sh, info = shield_and_info
    r = sh.scan("The burning tower scene is the end.", info)
    assert blurred(r) and r.risk >= 0.7


def test_tc_e1_08_empty_and_symbol_only_reviews_do_not_crash(shield_and_info):
    sh, info = shield_and_info
    for text in ("", "   ", "​​", "!!! ??? ...", "🍿🍿🍿"):
        r = sh.scan(text, info)
        assert not blurred(r)


def test_tc_e1_09_normalize_keeps_indic_joiners_and_emoji():
    from app.spoiler.text import normalize_text
    assert normalize_text("क्‍ष") == "क्‍ष"            # joiner between Devanagari letters stays
    assert normalize_text("👩‍💻") == "👩‍💻"            # emoji sequence stays
    assert normalize_text("d​ies­") == "dies"           # hidden characters inside English words go


def test_tc_e1_10_inverted_index_filters_by_genre_and_year():
    ix = InvertedIndex()
    ix.add(1, {"title": "Dark Orbit"}, year=2021, genres=["Sci-Fi"], cast=["Lee Cho"], popularity=5)
    ix.add(2, {"title": "Dark Harbour"}, year=2015, genres=["Drama"], cast=["Ines Roy"], popularity=9)
    assert ix.search("dark", genre="Sci-Fi") == [1]
    assert ix.search("dark", year=2015) == [2]
    assert ix.search("dark", genre="Horror") == []


# =====================================================================================================  E2
def test_tc_e2_01_vote_is_saved_once(admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    pid, opt = poll["id"], poll["options"][0]["id"]
    assert conv.post(f"/polls/{pid}/open").status_code == 200
    m0 = members[0][0]
    assert m0.post(f"/polls/{pid}/vote", {"option_id": opt}).status_code == 200
    second = m0.post(f"/polls/{pid}/vote", {"option_id": opt})
    assert second.status_code == 409 and "already voted" in second.json()["detail"]


def test_tc_e2_02_vote_on_draft_or_closed_poll_is_rejected(admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    pid, opt = poll["id"], poll["options"][0]["id"]
    m0 = members[0][0]
    assert m0.post(f"/polls/{pid}/vote", {"option_id": opt}).status_code == 409     # draft: not open yet
    conv.post(f"/polls/{pid}/open")
    m0.post(f"/polls/{pid}/vote", {"option_id": opt})
    assert conv.post(f"/polls/{pid}/close").status_code == 200
    m1 = members[1][0]
    assert m1.post(f"/polls/{pid}/vote", {"option_id": opt}).status_code == 409     # closed


def test_tc_e2_03_invalid_state_change_returns_409_and_changes_nothing(admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    pid = poll["id"]
    conv.post(f"/polls/{pid}/open")
    assert conv.post(f"/polls/{pid}/cancel").status_code == 409   # open -> cancelled is not allowed
    assert conv.get(f"/polls/{pid}").json()["state"] == "open"


def test_tc_e2_04_audit_log_cannot_be_edited_or_deleted(app):
    S = app.state.db.Session
    with S() as s:
        s.add(AuditLog(actor_id=1, action="test.write", target="x")); s.commit()
    with S() as s:                                   # edit attempt
        row = s.query(AuditLog).filter_by(action="test.write").one()
        row.detail = "tampered"
        with pytest.raises(RuntimeError, match="append-only"):
            s.flush()
        s.rollback()
    with S() as s:                                   # delete attempt
        s.delete(s.query(AuditLog).filter_by(action="test.write").one())
        with pytest.raises(RuntimeError, match="append-only"):
            s.flush()
        s.rollback()
    with S() as s:                                   # the row is unchanged
        row = s.query(AuditLog).filter_by(action="test.write").one()
        assert row.detail == ""


def test_tc_e2_05_review_shorter_than_10_characters_is_rejected_with_400(admin, films):
    """DEF-09: the design (S4.3) says 400 for invalid input; the build returned 422 before Sprint 2."""
    r = admin.post(f"/films/{films[0]}/reviews", {"text": "too short"})
    assert r.status_code == 400
    assert "text" in r.json()["detail"]          # the message names the field


def test_tc_e2_06_twenty_simultaneous_votes_from_one_member_store_one_row(admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films, n_members=1)
    pid, opt = poll["id"], poll["options"][0]["id"]
    conv.post(f"/polls/{pid}/open")
    m0 = members[0][0]
    codes, start = [], threading.Barrier(20)

    def go():
        start.wait()
        codes.append(m0.post(f"/polls/{pid}/vote", {"option_id": opt}).status_code)

    ts = [threading.Thread(target=go) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert codes.count(200) == 1 and codes.count(409) == 19
    assert sum(o["votes"] for o in conv.get(f"/polls/{pid}").json()["options"]) == 1


# =====================================================================================================  E3
def test_tc_e3_01_user_jobs_run_before_batch_jobs():
    order = []
    pool = WorkerPool(workers=1, capacity=16)
    for i in range(3):
        pool.submit(Job(f"batch-{i}", lambda i=i: order.append(f"batch-{i}"), priority=BATCH))
    pool.submit(Job("user-0", lambda: order.append("user-0"), priority=USER))
    pool.start()
    assert pool.wait_idle(5)
    pool.shutdown()
    assert order[0] == "user-0" and order[1:] == ["batch-0", "batch-1", "batch-2"]  # FIFO inside a priority


def test_tc_e3_02_bounded_queue_rejects_when_full():
    q = BoundedPriorityQueue(2)
    q.put(Job("a", lambda: None)); q.put(Job("b", lambda: None))
    t0 = time.time()
    with pytest.raises(QueueFull):
        q.put(Job("c", lambda: None), timeout=0.2)
    assert time.time() - t0 < 1.0 and len(q) == 2  # producer gave up quickly, nothing was lost


def test_tc_e3_03_failing_job_is_retried_3_times_then_marked_failed():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("TMDB down")

    pool = WorkerPool(workers=2, capacity=8, backoff_base=0.01).start()
    pool.submit(Job("sync-film-7", boom, priority=BATCH, max_retries=3))
    assert pool.wait_idle(10)
    pool.shutdown()
    assert len(calls) == 4                         # first try + 3 retries
    assert pool.stats["retried"] == 3 and pool.stats["failed"] == 1
    assert pool.failed_jobs == ["sync-film-7"]


def test_tc_e3_04_lru_evicts_least_recently_used_and_counts_it():
    c = LRUCache(2)
    c.put("film-1", "A"); c.put("film-2", "B")
    assert c.get("film-1") == "A"                 # film-1 is now most recent
    c.put("film-3", "C")                          # evicts film-2
    assert c.get("film-2") is None and c.get("film-1") == "A"
    assert c.evictions == 1 and c.hits == 2 and c.misses == 1


def test_tc_e3_05_hundred_jobs_from_8_threads_all_finish_once():
    done, lock = [], threading.Lock()
    pool = WorkerPool(workers=4, capacity=256).start()

    def producer(p):
        for j in range(100 // 8 + (1 if p < 100 % 8 else 0)):
            def work(p=p, j=j):
                with lock:
                    done.append((p, j))
            pool.submit(Job(f"scan-{p}-{j}", work, priority=USER))

    ts = [threading.Thread(target=producer, args=(p,)) for p in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert pool.wait_idle(10)
    pool.shutdown()
    assert len(done) == 100 and len(set(done)) == 100 and pool.stats["failed"] == 0


# =====================================================================================================  E4
def test_tc_e4_01_login_sets_http_only_session_cookie(new_client):
    c = new_client()
    c.register("omkar@x.io", "Omkar")
    c.post("/auth/logout")
    r = c.post("/auth/login", {"email": "omkar@x.io", "password": "password123"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite" in cookie


def test_tc_e4_02_fifth_auth_attempt_in_a_minute_gets_429(tmp_path):
    """Sign-up and sign-in share one budget of 5 attempts per minute per address (FR-01)."""
    a = create_app(make_settings(str(tmp_path), login_per_minute=5))
    with TestClient(a):
        c = Api(a)
        c.register("rate@x.io")                                                   # attempt 1
        codes = [c.post("/auth/login", {"email": "rate@x.io", "password": "wrong-pass"}).status_code
                 for _ in range(5)]                                               # attempts 2..6
    assert codes[:4] == [401] * 4 and codes[4] == 429


def test_tc_e4_03_token_bucket_refills_over_time():
    now = [0.0]
    b = TokenBucket(capacity=5, refill_per_sec=5 / 60, clock=lambda: now[0])
    assert [b.allow("1.2.3.4") for _ in range(6)] == [True] * 5 + [False]
    now[0] += 12.0                               # 12 s later: one token back
    assert b.allow("1.2.3.4") and not b.allow("1.2.3.4")
    assert b.allow("5.6.7.8")                    # other addresses are not affected


def test_tc_e4_04_no_token_gets_401_and_wrong_role_gets_403(new_client, admin):
    anon = new_client()
    assert anon.get("/moderation/queue").status_code == 401
    viewer = new_client(); viewer.register("viewer@x.io")
    assert viewer.get("/moderation/queue").status_code == 403       # deny by default
    assert viewer.get("/admin/stats").status_code == 403


def test_tc_e4_05_tampered_or_garbage_token_is_rejected(app, new_client):
    c = new_client(); c.register("t@x.io")
    tok = c.c.cookies.get("cl_session")
    fresh = TestClient(app)
    assert fresh.get("/auth/me", cookies={"cl_session": tok}).status_code == 200        # the real token works
    bad = tok[:-3] + ("aaa" if not tok.endswith("aaa") else "bbb")
    assert fresh.get("/auth/me", cookies={"cl_session": bad}).status_code == 401        # changed signature
    assert fresh.get("/auth/me", cookies={"cl_session": "abc.def.ghi"}).status_code == 401


def test_tc_e4_06_malformed_json_gets_400_with_a_clear_message(new_client):
    """DEF-09 (API side): malformed input must give 400 and name the problem, never a stack trace."""
    c = new_client(); c.register("m@x.io")
    r = c.c.post("/auth/login", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body and "Traceback" not in r.text


def test_tc_e4_07_missing_csrf_header_is_refused(new_client, films):
    c = new_client(); c.register("csrf@x.io")
    r = c.c.post(f"/films/{films[0]}/reviews", json={"text": "A long enough honest review text."})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]


def test_tc_e4_08_convener_of_one_club_cannot_manage_another(admin, new_client, films):
    conv, club, members, poll = setup_club(admin, new_client, films)
    other = new_client(); ou = other.register("other@x.io", "Other"); grant(admin, ou["id"], "convener")
    assert other.post(f"/polls/{poll['id']}/open").status_code == 403
    assert other.post(f"/clubs/{club['id']}/members", {"email": "x@x.io"}).status_code == 403


def test_tc_e3_06_health_reports_cache_counters_for_the_soak_test(admin, films):
    admin.post(f"/films/{films[0]}/reviews", {"text": "Mara dies in the burning tower. What an ending."})
    caches = admin.get("/health").json()["shield"]["caches"]
    assert set(caches) == {"automata", "plot_tfidf", "plot_embeddings"}
    for c in caches.values():
        assert {"size", "capacity", "hits", "misses", "evictions", "hit_rate"} <= set(c)
    assert caches["automata"]["capacity"] == 128 and caches["plot_tfidf"]["capacity"] == 256
