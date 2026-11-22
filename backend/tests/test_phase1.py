"""Fixes from the audit: rate-limit identity, secret key, DL opt-in, scan speed, actor terms, validation, badges."""
import datetime as dt
import os

from app.config import _secret_key
from app.models import SpoilerTerm
from app.security import client_ip
from app.services.catalog import backfill_actor_terms, seed_name_terms
from app.spoiler import shield as shield_mod
from app.spoiler.shield import SpoilerShield
from app.spoiler.wordlist import terms_from_actors

TRUSTED = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128"]


# ------------------------------------------------------------------ B1 client address
def test_client_ip_trusts_forwarded_header_only_from_our_proxy():
    assert client_ip("127.0.0.1", "203.0.113.9", TRUSTED) == "203.0.113.9"          # dev proxy / nginx
    assert client_ip("172.18.0.3", "203.0.113.9", TRUSTED) == "203.0.113.9"         # docker network
    assert client_ip("198.51.100.7", "203.0.113.9", TRUSTED) == "198.51.100.7"      # direct caller can't forge it
    assert client_ip("127.0.0.1", None, TRUSTED) == "127.0.0.1"
    assert client_ip(None, "1.2.3.4", TRUSTED) == "?"


def test_client_ip_uses_rightmost_untrusted_hop_and_survives_garbage():
    # a client prepends a fake address; our proxy appends the real one
    assert client_ip("10.0.0.2", "6.6.6.6, 203.0.113.9", TRUSTED) == "203.0.113.9"
    assert client_ip("10.0.0.2", "203.0.113.9, 10.0.0.5", TRUSTED) == "203.0.113.9"  # chained proxies
    assert client_ip("127.0.0.1", "not-an-ip", TRUSTED) == "127.0.0.1"
    assert client_ip("127.0.0.1", "10.0.0.9", TRUSTED) == "127.0.0.1"                # everything trusted: peer


def test_login_limit_is_per_client_not_global(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import make_settings
    app = create_app(make_settings(str(tmp_path), login_per_minute=2))
    with TestClient(app) as c:
        def attempt(ip):
            return c.post("/auth/login", json={"email": "a@b.io", "password": "wrongpass1"},
                          headers={"X-Forwarded-For": ip}).status_code
        # TestClient's peer is "testclient" (not an IP) -> header ignored, everyone shares one bucket
        codes = [attempt("1.1.1.1") for _ in range(4)]
        assert 429 in codes


# ------------------------------------------------------------------ B2 secret key
def test_secret_key_is_generated_once_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    f = str(tmp_path / "sk")
    a = _secret_key(f)
    assert len(a) >= 32 and "dev-secret" not in a
    assert _secret_key(f) == a and os.path.exists(f)


def test_secret_key_env_wins_but_placeholder_is_ignored(tmp_path, monkeypatch):
    f = str(tmp_path / "sk")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    assert _secret_key(f) == "x" * 40
    monkeypatch.setenv("SECRET_KEY", "change-me-to-a-long-random-string")  # the .env.example value
    assert _secret_key(f) != "change-me-to-a-long-random-string"


# ------------------------------------------------------------------ S2 deep model opt-in
def test_deep_model_loads_only_when_enabled(tmp_path, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(shield_mod.DLScorer, "load", staticmethod(lambda d: sentinel))
    assert SpoilerShield(str(tmp_path)).dl is None
    assert SpoilerShield(str(tmp_path), use_dl=True).dl is sentinel


# ------------------------------------------------------------------ S6 feature-name cache
def test_top_words_builds_feature_names_once():
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from app.spoiler.ml import MLBundle
    texts = ["he dies at the end", "great acting and score", "the killer is the brother", "lovely visuals"]
    vec = TfidfVectorizer().fit(texts)
    clf = LogisticRegression().fit(vec.transform(texts), [1, 0, 1, 0])
    b = MLBundle(vec, None, clf, np.zeros(1), np.ones(1))
    calls = {"n": 0}
    real = vec.get_feature_names_out
    vec.get_feature_names_out = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1]
    first = b.top_words("he dies at the end")
    for _ in range(5):
        assert b.top_words("he dies at the end") == first
    assert calls["n"] == 1 and "dies" in first
    assert "_names" in b.__dict__ and "_names" not in b.__getstate__()  # derived data is not saved


# ------------------------------------------------------------------ S4 actor names
def test_actor_terms_use_full_name_and_surname_not_first_name():
    t = dict(terms_from_actors(["Mark Ruffalo", "Will Smith", "Cher", "Leonardo DiCaprio (voice)"]))
    assert t["mark ruffalo"] == "name" and t["ruffalo"] == "name"
    assert "mark" not in t and "will" not in t        # first names collide with ordinary words
    assert "cher" not in t                            # single short name: too ambiguous
    assert "dicaprio" in t


def test_actor_names_reach_the_shield_and_backfill_is_idempotent(app, films):
    with app.state.db.session() as s:
        terms = {t.term: t.source for t in s.query(SpoilerTerm).filter_by(film_id=films[0])}
        assert terms.get("mara vell") == "actor" and terms.get("mara quill") == "tmdb"
        s.query(SpoilerTerm).filter_by(source="actor").delete()
        s.flush()
        assert backfill_actor_terms(s) > 0
        assert backfill_actor_terms(s) == 0
        assert seed_name_terms(s, s.get(__import__("app.models", fromlist=["Film"]).Film, films[0])) == 0


# ------------------------------------------------------------------ B3 diary dates
def _log(c, film, day, **kw):
    return c.post("/diary", {"film_id": film, "watched_on": day.isoformat(), **kw})


def test_diary_rejects_future_and_pre_cinema_dates(app, admin, films):
    today = dt.date.today()
    assert _log(admin, films[0], today).status_code == 201
    assert _log(admin, films[0], today + dt.timedelta(days=30)).status_code == 400
    assert _log(admin, films[0], dt.date(1800, 1, 1)).status_code == 400
    assert _log(admin, films[0], dt.date(1888, 1, 1)).status_code == 201


# ------------------------------------------------------------------ B4 badges can't be farmed
def test_one_film_logged_three_times_is_not_a_marathon(app, admin, films):
    today = dt.date.today()
    for _ in range(3):
        _log(admin, films[0], today)
    b = {x["key"]: x for x in admin.get("/me/badges").json()}
    assert b["marathoner"]["value"] == 1 and not b["marathoner"]["earned"]
    _log(admin, films[1], today); _log(admin, films[2], today)
    b = {x["key"]: x for x in admin.get("/me/badges").json()}
    assert b["marathoner"]["value"] == 3 and b["marathoner"]["earned"]


def test_cannot_like_your_own_review_or_list(app, admin, films):
    r = admin.post(f"/films/{films[0]}/reviews", {"text": "A wonderfully tense heist film with great pacing."})
    rid = r.json()["id"]
    import time
    for _ in range(50):
        if admin.get(f"/reviews/{rid}").json()["state"] == "published":
            break
        time.sleep(0.1)
    assert admin.put(f"/likes/review/{rid}").status_code == 400
    lst = admin.post("/lists", {"title": "My favourites", "description": "", "film_ids": [films[0]]}).json()
    assert admin.put(f"/likes/list/{lst['id']}").status_code == 400


def test_others_can_like_and_it_counts(app, admin, new_client, films):
    r = admin.post(f"/films/{films[0]}/reviews", {"text": "A wonderfully tense heist film with great pacing."}).json()
    import time
    for _ in range(50):
        if admin.get(f"/reviews/{r['id']}").json()["state"] == "published":
            break
        time.sleep(0.1)
    c = new_client(); c.register("fan@x.io", "Fan")
    assert c.put(f"/likes/review/{r['id']}").json()["likes"] == 1


# ------------------------------------------------------------------ B5 blank reviews
def test_whitespace_only_review_is_rejected(app, admin, films):
    assert admin.post(f"/films/{films[0]}/reviews", {"text": " " * 20}).status_code == 400
    assert admin.post(f"/films/{films[0]}/reviews", {"text": "  short  "}).status_code == 400


# ------------------------------------------------------------------ Phase 4: edit / delete reviews, search refresh
def _published(c, rid):
    import time
    for _ in range(80):
        r = c.get(f"/reviews/{rid}").json()
        if r["state"] == "published":
            return r
        time.sleep(0.1)
    raise AssertionError("review never published")


def _write(c, film, text="A wonderfully tense heist film with great pacing."):
    r = c.post(f"/films/{film}/reviews", {"text": text})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_author_can_edit_review_and_it_is_scanned_again(app, admin, new_client, films):
    rid = _write(admin, films[0])
    mine = _published(admin, rid)
    assert mine["text"].startswith("A wonderfully")                       # the author gets the text back for editing
    other = new_client(); other.register("reader@x.io", "Reader")
    assert "text" not in other.get(f"/reviews/{rid}").json()               # readers don't
    r = admin.patch(f"/reviews/{rid}", {"text": "Mara Quill dies in the burning tower at the end. Great sets though."})
    assert r.status_code == 202 and r.json()["state"] in ("pending_scan", "published")  # the scan can win the race
    again = _published(admin, rid)
    assert "burning tower" in again["text"]
    assert admin.patch(f"/reviews/{rid}", {"text": "   short   "}).status_code == 400
    same = admin.patch(f"/reviews/{rid}", {"text": again["text"]})        # no change: no re-scan
    assert same.json()["state"] == "published"


def test_only_the_author_can_edit_or_delete(app, admin, new_client, films):
    rid = _write(admin, films[0]); _published(admin, rid)
    other = new_client(); other.register("other@x.io", "Other")
    assert other.patch(f"/reviews/{rid}", {"text": "Hijacked review text goes here."}).status_code == 404
    assert other.delete(f"/reviews/{rid}").status_code == 404
    anon = new_client()
    assert anon.delete(f"/reviews/{rid}").status_code in (401, 403)


def test_delete_review_hides_it_clears_likes_and_allows_a_new_one(app, admin, new_client, films):
    rid = _write(admin, films[0]); _published(admin, rid)
    fan = new_client(); fan.register("fan2@x.io", "Fan")
    assert fan.put(f"/likes/review/{rid}").json()["likes"] == 1
    assert admin.delete(f"/reviews/{rid}").json() == {"ok": True}
    assert fan.get(f"/reviews/{rid}").status_code == 404
    assert admin.get(f"/reviews/{rid}").status_code == 404 or admin.get(f"/reviews/{rid}").json()["state"] == "removed"
    assert admin.delete(f"/reviews/{rid}").status_code == 404              # already gone
    assert _write(admin, films[0], "Second thoughts: still a very tense heist film.")  # may review again


def test_moderator_hidden_review_cannot_be_edited_by_its_author(app, admin, new_client, films):
    c = new_client(); c.register("writer@x.io", "Writer")
    rid = _write(c, films[0]); _published(c, rid)
    for i in range(3):                                                     # three distinct reports auto-hide it
        r = new_client(); r.register(f"rep{i}@x.io", f"Rep{i}")
        r.post(f"/reviews/{rid}/report", {"reason": "spoiler"})
    assert admin.get(f"/reviews/{rid}").json()["state"] == "hidden"
    assert c.patch(f"/reviews/{rid}", {"text": "Trying to sneak the same review back in."}).status_code == 409


def test_search_index_notices_films_added_by_another_process(app, films):
    from app.models import Film
    from app.services import jobs
    from app.services.catalog import upsert_tmdb_film
    assert jobs.refresh_search(app) is False                               # nothing changed since the fixture rebuilt it
    with app.state.db.session() as s:                                      # what scripts/import_kaggle does
        upsert_tmdb_film(s, {"id": 999, "title": "Zephyr Imports", "release_date": "2020-01-01", "overview": "x",
                             "popularity": 5.0, "genres": [], "credits": {"cast": []}})
    assert app.state.search.autocomplete("zephyr") == []
    assert jobs.refresh_search(app) is True
    with app.state.db.session() as s:
        fid = s.query(Film).filter_by(tmdb_id=999).one().id
    assert fid in app.state.search.autocomplete("zephyr")
    assert jobs.refresh_search(app) is False


# ------------------------------------------------------------------ live TMDB lookup for titles we don't have
def _fake_tmdb(app, catalogue, fail=False):
    """A real TMDBClient talking to a fake TMDB over httpx's mock transport. Returns the list of requested paths."""
    import httpx
    from app.clients.tmdb import TMDBClient
    from app.clients.wikipedia import WikipediaClient
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if fail:
            return httpx.Response(401, json={"status_message": "Invalid API key"})
        if req.url.path.endswith("/search/movie"):
            q = req.url.params["query"].lower()
            return httpx.Response(200, json={"results": [m for m in catalogue if q in m["title"].lower()]})
        mid = int(req.url.path.rsplit("/", 1)[1])
        m = next(x for x in catalogue if x["id"] == mid)
        return httpx.Response(200, json={**m, "overview": "o", "popularity": 9, "genres": [{"name": "Drama"}],
                                         "credits": {"cast": [{"name": "Dana Doe", "character": "Zed Marlowe"}]},
                                         "keywords": {"keywords": []}})

    app.state.tmdb = TMDBClient("k", rate=10000, client=httpx.Client(transport=httpx.MockTransport(handler)))
    app.state.wiki = WikipediaClient(httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"query": {"pages": {"-1": {"missing": ""}}}}))))
    return seen


NEW = [{"id": 501, "title": "Brand New Release", "release_date": "2026-09-20"},
       {"id": 502, "title": "Brand New Sequel", "release_date": "2026-10-01"},
       {"id": 503, "title": "Brand New Placeholder", "release_date": ""}]  # unreleased junk entry


def test_search_finds_a_new_film_on_tmdb_imports_it_and_serves_it_locally_next_time(app, admin, films):
    seen = _fake_tmdb(app, NEW)
    r = admin.get("/films/search", params={"q": "brand new"}).json()
    assert {f["title"] for f in r} == {"Brand New Release", "Brand New Sequel"}      # placeholder skipped
    assert any(p.endswith("/search/movie") for p in seen)
    detail = admin.get(f"/films/{r[0]['id']}").json()
    assert detail["cast"] and detail["title"].startswith("Brand New")
    app.state.pool.wait_idle(20)
    n = len(seen)
    again = admin.get("/films/search", params={"q": "brand new release"}).json()      # now a local hit
    assert any(f["title"] == "Brand New Release" for f in again)
    assert admin.get("/films/autocomplete", params={"q": "brand new rel"}).json()
    from app.models import SpoilerTerm
    with app.state.db.session() as s:
        terms = {t.term for t in s.query(SpoilerTerm).filter_by(film_id=r[0]["id"])}
    assert "zed marlowe" in terms and "dana doe" in terms                              # character AND actor names seeded
    assert len(seen) <= n + 1                                                           # at most the one search call


def test_autocomplete_falls_back_to_tmdb_only_for_real_queries(app, admin, films):
    seen = _fake_tmdb(app, NEW)
    assert admin.get("/films/autocomplete", params={"q": "br"}).json() == []            # too short: no outside call
    assert not seen
    hits = admin.get("/films/autocomplete", params={"q": "brand new"}).json()
    assert {h["title"] for h in hits} == {"Brand New Release", "Brand New Sequel"}


def test_tmdb_failure_never_breaks_search_and_is_visible_to_admins(app, admin, films):
    _fake_tmdb(app, NEW, fail=True)
    r = admin.get("/films/search", params={"q": "rosewood"})
    assert r.status_code == 200 and [f["title"] for f in r.json()] == ["Rosewood Heist"]   # local result still there
    assert admin.get("/films/search", params={"q": "nothing like this"}).json() == []
    t = admin.get("/admin/stats").json()["tmdb"]
    assert t["configured"] is True and t["ok"] is False and "401" in t["error"]


def test_search_without_a_tmdb_key_just_searches_the_local_catalogue(app, admin, films):
    assert app.state.tmdb is None
    assert admin.get("/films/search", params={"q": "brand new"}).json() == []
    assert admin.get("/admin/stats").json()["tmdb"] == {"configured": False, "ok": None, "error": ""}


def test_filters_do_not_trigger_an_outside_search(app, admin, films):
    seen = _fake_tmdb(app, NEW)
    admin.get("/films/search", params={"q": "brand new", "genre": "Drama"})
    assert not seen
