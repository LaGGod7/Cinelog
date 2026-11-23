"""DEF-13 (found 23-11-2026): new TMDB releases did not show up.

1. There was no scheduled sync: films arrived only when an admin pressed Admin > Sync (FR05 asks for a schedule).
2. Search asked TMDB only when the local catalogue had no match (autocomplete) or fewer than 3 (search), so a new
   film never appeared once a few older films shared its words.
"""
from tests.test_phase1 import _fake_tmdb

OLD_AND_NEW = [{"id": 601, "title": "Galaxy Raiders", "release_date": "1999-05-01"},
               {"id": 602, "title": "Galaxy Raiders II", "release_date": "2003-05-01"},
               {"id": 603, "title": "Galaxy Raiders III", "release_date": "2008-05-01"},
               {"id": 604, "title": "Galaxy Raiders: Reborn", "release_date": "2026-11-14"}]


def _import_old_ones(app, admin):
    """Put the three old films in the local catalogue, as an earlier sync would have."""
    from app.services.catalog import upsert_tmdb_film
    with app.state.db.session() as s:
        for m in OLD_AND_NEW[:3]:
            upsert_tmdb_film(s, {**m, "overview": "o", "popularity": 50, "genres": [{"name": "Action"}],
                                 "credits": {"cast": []}, "keywords": {"keywords": []}})
    with app.state.db.session() as s:
        app.state.search.rebuild(s)


def test_tc_e1_12_search_shows_a_new_release_even_when_older_films_match(app, admin, films):
    _import_old_ones(app, admin)
    _fake_tmdb(app, OLD_AND_NEW)
    titles = [f["title"] for f in admin.get("/films/search", params={"q": "galaxy raiders"}).json()]
    assert "Galaxy Raiders: Reborn" in titles                  # before the fix: only the 3 old films
    assert titles[:3] == ["Galaxy Raiders", "Galaxy Raiders II", "Galaxy Raiders III"] or len(titles) == 4


def test_tc_e1_13_autocomplete_shows_a_new_release_next_to_local_matches(app, admin, films):
    _import_old_ones(app, admin)
    _fake_tmdb(app, OLD_AND_NEW)
    titles = [f["title"] for f in admin.get("/films/autocomplete", params={"q": "galaxy"}).json()]
    assert "Galaxy Raiders: Reborn" in titles and len(titles) <= 10


def test_tc_e1_14_short_queries_and_no_key_still_stay_local(app, admin, films):
    assert app.state.tmdb is None
    assert admin.get("/films/autocomplete", params={"q": "galaxy"}).json() == []      # no key: local only, no error
    seen = _fake_tmdb(app, OLD_AND_NEW)
    admin.get("/films/autocomplete", params={"q": "ga"})
    assert not seen                                                                     # under 3 letters: never asks TMDB


def test_tc_e3_07_catalogue_sync_runs_on_a_schedule(app, admin, films):
    from app.services import jobs
    calls = []
    jobs_submit = jobs.submit_sync
    jobs.submit_sync = lambda a, pages=5: calls.append(pages)
    try:
        assert not jobs.maybe_auto_sync(app, 0.0)                    # no TMDB key: never
        _fake_tmdb(app, OLD_AND_NEW)
        assert not jobs.maybe_auto_sync(app, 1000.0)                 # first call only sets the clock (+2 min)
        assert not jobs.maybe_auto_sync(app, 1100.0)
        assert jobs.maybe_auto_sync(app, 1121.0)                     # 2 minutes after start-up: first sync
        assert calls == [app.state.settings.sync_pages]
        assert not jobs.maybe_auto_sync(app, 1121.0 + 3600)          # not again within SYNC_EVERY_HOURS (6 h)
        assert jobs.maybe_auto_sync(app, 1121.0 + 6 * 3600 + 1)      # next one 6 h later
        app.state.sync_status["running"] = True
        assert not jobs.maybe_auto_sync(app, 1121.0 + 13 * 3600)     # never two syncs at once
        app.state.sync_status["running"] = False
        app.state.settings.sync_every_hours = 0
        assert not jobs.maybe_auto_sync(app, 1121.0 + 20 * 3600)     # SYNC_EVERY_HOURS=0 turns it off
    finally:
        jobs.submit_sync = jobs_submit
    assert len(calls) == 2


def test_tc_e3_08_a_finished_sync_records_when_it_ran(app, admin):
    import httpx
    from app.clients.tmdb import TMDBClient
    from app.services import jobs

    def handler(req):
        if req.url.path.endswith(("/movie/popular", "/movie/now_playing", "/movie/upcoming")):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)
    app.state.tmdb = TMDBClient("k", rate=1000, client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = jobs.sync_catalog(app, pages=1)
    assert out["running"] is False and out["last_finished"]
    assert admin.get("/admin/stats").json()["sync"]["last_finished"] == out["last_finished"]
