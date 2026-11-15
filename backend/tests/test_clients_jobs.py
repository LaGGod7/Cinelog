import httpx

from app.clients.tmdb import TMDBClient, TMDBError
from app.clients.wikipedia import WikipediaClient, extract_plot


def test_tmdb_backs_off_on_429_and_caches():
    calls, sleeps = [], []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if len(calls) <= 2:
            return httpx.Response(429, headers={"Retry-After": "0.5"})
        return httpx.Response(200, json={"results": [{"id": 1}]})

    c = TMDBClient("k", rate=1000, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    assert c.popular(1) == [{"id": 1}]
    assert len(calls) == 3 and 0.5 in sleeps  # waited and retried
    c.popular(1)
    assert len(calls) == 3  # second call served from the LRU cache


def test_tmdb_gives_up_and_raises():
    c = TMDBClient("k", rate=1000, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
                   sleep=lambda s: None)
    try:
        c.popular(1)
        raise AssertionError("expected TMDBError")
    except TMDBError:
        pass


def test_wikipedia_plot_extraction():
    text = ("Intro text.\n\n== Plot ==\nA thief steals a diamond. She is betrayed.\n\n=== Part two ===\nShe dies.\n\n"
            "== Cast ==\nSomeone as Someone.")
    plot = extract_plot(text)
    assert plot.startswith("A thief steals") and "She dies." in plot and "Someone as" not in plot

    def handler(req):
        title = req.url.params["titles"]
        if title == "Heat (1995 film)":
            body = {"query": {"pages": {"1": {"extract": "x\n== Plot ==\n" + "Neil robs a bank. " * 30 + "\n== Cast ==\n"}}}}
        else:
            body = {"query": {"pages": {"-1": {"missing": ""}}}}
        return httpx.Response(200, json=body)

    w = WikipediaClient(httpx.Client(transport=httpx.MockTransport(handler)))
    assert "Neil robs a bank" in w.plot_for("Heat", 1995)
    assert w.plot_for("Nonexistent", 2000) == ""


def test_catalog_sync_and_plot_fetch_jobs(app, admin):
    def handler(req: httpx.Request):
        p = req.url.path
        if p.endswith("/movie/popular"):
            return httpx.Response(200, json={"results": [{"id": 101}, {"id": 102}]})
        if p.endswith(("/movie/now_playing", "/movie/upcoming")):
            return httpx.Response(200, json={"results": []})
        mid = int(p.rsplit("/", 1)[1])
        return httpx.Response(200, json={"id": mid, "title": f"Synced {mid}", "release_date": "2020-02-02",
                                         "overview": "o", "popularity": 5, "genres": [{"name": "Drama"}],
                                         "credits": {"cast": [{"name": "Ann Actor", "character": "Zed Marlowe"}]},
                                         "keywords": {"keywords": []}})

    app.state.tmdb = TMDBClient("k", rate=1000, client=httpx.Client(transport=httpx.MockTransport(handler)))
    plot = "Zed Marlowe finds a map. " + "Zed Marlowe follows it into the hills and meets an old sailor. " * 4
    app.state.wiki = WikipediaClient(httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"query": {"pages": {"1": {"extract": "== Plot ==\n" + plot * 3 + "\n== Cast =="}}}}))))
    assert admin.post("/admin/sync", params={"pages": 1}).status_code == 202
    assert app.state.pool.wait_idle(20)
    assert app.state.pool.wait_idle(20)  # plot fetches queued by the sync
    r = admin.get("/films/search", params={"q": "synced"}).json()
    assert {f["title"] for f in r} == {"Synced 101", "Synced 102"}
    assert admin.get("/films/autocomplete", params={"q": "syn"}).json()
    fid = r[0]["id"]
    assert admin.get(f"/films/{fid}").json()["has_plot_context"]
    assert app.state.sync_status["synced"] == 2
    # character names were seeded as weak spoiler terms
    from sqlalchemy import select
    from app.models import SpoilerTerm
    with app.state.db.session() as s:
        assert "zed marlowe" in {t for (t,) in s.execute(select(SpoilerTerm.term).where(SpoilerTerm.film_id == fid))}


def test_sync_without_key_is_503(admin):
    assert admin.post("/admin/sync").status_code == 503
