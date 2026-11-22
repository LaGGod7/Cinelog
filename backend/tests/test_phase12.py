"""Phase 12: roles in action (permission matrix, critics, sanctions) and the engagement features
(year in review, goal, recommendations, taste match, friends, club analytics and calendar)."""
import datetime as dt

import pytest
from sqlalchemy import select

from conftest import grant


def wait_scans(app):
    assert app.state.pool.wait_idle(20)


def log(c, film, stars=None, day=None, **kw):
    body = {"film_id": film, "watched_on": (day or dt.date.today()).isoformat(), **kw}
    if stars is not None:
        body["stars"] = stars
    r = c.post("/diary", body)
    assert r.status_code == 201, r.text
    return r.json()


def review(app, c, film, text="A calm, lovely film with a great cast and a warm soundtrack."):
    r = c.post(f"/films/{film}/reviews", {"text": text})
    assert r.status_code == 202, r.text
    wait_scans(app)
    return r.json()["id"]


def person(new_client, email, name):
    c = new_client()
    u = c.register(email, name)
    return c, u["id"]


@pytest.fixture()
def crowd(app, admin, new_client, films):
    """An admin, a moderator, two viewers; the viewers have logged enough to apply as critics."""
    mod, mid = person(new_client, "mod@x.io", "Mona")
    grant(admin, mid, "moderator")
    a, aid = person(new_client, "ann@x.io", "Ann")
    b, bid = person(new_client, "bob@x.io", "Bob")
    return dict(admin=admin, mod=mod, mid=mid, a=a, aid=aid, b=b, bid=bid, films=films)


def make_eligible(app, c, films):
    log(c, films[0], 4.5); log(c, films[1], 4); log(c, films[2], 3.5)
    from app.models import Film
    with app.state.db.session() as s:  # two more films, so the applicant has logged five
        from app.services.catalog import upsert_tmdb_film
        extra = [upsert_tmdb_film(s, {"id": 90 + i, "title": f"Extra {i}", "release_date": "2010-01-01", "popularity": 1.0,
                                      "genres": [{"name": "Drama"}]}).id for i in range(2)]
    for i in extra:
        log(c, i, 3)
    review(app, c, films[1])


# ============================================================== permission matrix
def test_permission_matrix_is_served_to_staff_only_and_matches_the_enforced_table(crowd):
    from app.rbac import MATRIX
    assert crowd["a"].get("/admin/permissions").status_code == 403
    r = crowd["mod"].get("/admin/permissions").json()
    served = {p["key"]: set(p["roles"]) for p in r["permissions"]}
    assert served == {k: set(v) for k, v in MATRIX.items()}  # one source of truth
    assert [x["name"] for x in r["roles"]] == ["viewer", "critic", "convener", "moderator", "admin"]
    assert next(x for x in r["roles"] if x["name"] == "moderator")["people"] == 1
    club = {x["key"]: x["roles"] for x in r["club_actions"]}
    assert club["analytics"] == ["convener", "co_convener"] and club["appoint_co_convener"] == ["convener"]
    assert "member" in club["vote"]


def test_role_change_keeps_reason_notifies_the_person_and_can_be_filtered(crowd):
    admin, aid = crowd["admin"], crowd["aid"]
    r = admin.post(f"/admin/users/{aid}/roles", {"role": "convener", "action": "grant", "reason": "runs the Friday club"})
    assert r.status_code == 200
    log_rows = admin.get("/admin/audit", params={"prefix": "role."}).json()
    assert log_rows[0]["action"] == "role.grant" and "runs the Friday club" in log_rows[0]["detail"]
    assert all(x["action"].startswith("role.") for x in log_rows)
    notes = crowd["a"].get("/notifications").json()
    assert any("convener" in n["text"] and "Friday" in n["text"] for n in (notes["items"] if isinstance(notes, dict) else notes))


# ============================================================== critics
def test_critic_application_flow_with_separation_of_duties(app, crowd):
    films, a, mod, admin = crowd["films"], crowd["a"], crowd["mod"], crowd["admin"]
    statement = "I review films for my college magazine and have written about cinema for three years."
    early = a.post("/critics/apply", {"statement": statement})
    assert early.status_code == 400 and "log at least" in early.json()["detail"]
    st = a.get("/me/critic").json()
    assert st["is_critic"] is False and st["progress"]["eligible"] is False and st["application"] is None
    make_eligible(app, a, films)
    assert a.get("/me/critic").json()["progress"]["eligible"] is True

    assert a.post("/critics/apply", {"statement": "too short"}).status_code == 400
    r = a.post("/critics/apply", {"statement": statement, "links": "https://example.com/me"})
    assert r.status_code == 201 and r.json()["state"] == "pending"
    assert a.post("/critics/apply", {"statement": statement}).status_code == 409  # one at a time

    assert a.get("/critics/applications").status_code == 403  # viewers cannot see the queue
    assert a.post(f"/critics/applications/{r.json()['id']}/approve").status_code == 403  # nor decide
    queue = mod.get("/critics/applications").json()
    assert len(queue) == 1 and queue[0]["applicant"]["films"] == 5 and queue[0]["applicant"]["name"] == "Ann"
    assert mod.get("/moderation/stats").json()["critic_applications_waiting"] == 1

    assert mod.post(f"/critics/applications/{queue[0]['id']}/reject", {"note": ""}).status_code == 400  # a reason is required
    ok = mod.post(f"/critics/applications/{queue[0]['id']}/approve", {"note": "Great magazine pieces"})
    assert ok.status_code == 200 and ok.json()["state"] == "approved"
    assert "critic" in a.get("/auth/me").json()["roles"]
    assert mod.post(f"/critics/applications/{queue[0]['id']}/approve").status_code == 409  # decided once
    assert any(x["action"] == "critic.approve" for x in admin.get("/admin/audit").json())
    assert a.post("/critics/apply", {"statement": statement}).status_code == 409  # already one

    # a moderator who applies cannot approve their own application
    make_eligible(app, mod, films)
    mine = mod.post("/critics/apply", {"statement": statement})
    assert mine.status_code == 201
    assert mod.post(f"/critics/applications/{mine.json()['id']}/approve").status_code == 403
    assert admin.post(f"/critics/applications/{mine.json()['id']}/reject", {"note": "come back with more reviews"}).json()["state"] == "rejected"


def test_withdraw_and_reject_leave_the_door_open(app, crowd):
    films, a, mod = crowd["films"], crowd["a"], crowd["mod"]
    make_eligible(app, a, films)
    statement = "Years of writing about cinema for local papers and festival programmes, happy to share links."
    first = a.post("/critics/apply", {"statement": statement}).json()
    assert a.delete("/critics/apply").json()["state"] == "withdrawn"
    assert a.delete("/critics/apply").status_code == 404
    assert mod.post(f"/critics/applications/{first['id']}/approve").status_code == 409  # withdrawn is final
    second = a.post("/critics/apply", {"statement": statement}).json()
    rej = mod.post(f"/critics/applications/{second['id']}/reject", {"note": "Please write a few more reviews"}).json()
    assert rej["state"] == "rejected" and rej["note"].startswith("Please")
    assert a.get("/me/critic").json()["application"]["state"] == "rejected"
    assert a.post("/critics/apply", {"statement": statement}).status_code == 201  # may apply again


def test_critics_get_a_split_score_picks_and_the_critic_filter(app, crowd):
    films, a, b, admin = crowd["films"], crowd["a"], crowd["b"], crowd["admin"]
    grant(admin, crowd["aid"], "critic")
    log(a, films[0], 5); log(b, films[0], 3); log(admin, films[0], 4)
    film = b.get(f"/films/{films[0]}").json()
    assert film["rating_split"]["critics"] == {"avg": 5.0, "n": 1}
    assert film["rating_split"]["viewers"] == {"avg": 3.5, "n": 2}
    assert film["rating"]["avg"] == 4.0 and film["rating"]["n"] == 3  # the overall score is unchanged

    assert b.put(f"/films/{films[0]}/pick", {"blurb": "Watch it blind and thank me later."}).status_code == 403
    assert a.put(f"/films/{films[0]}/pick", {"blurb": "short"}).status_code == 400
    assert a.put(f"/films/{films[0]}/pick", {"blurb": "Watch it blind and thank me later."}).status_code == 200
    assert a.put(f"/films/{films[0]}/pick", {"blurb": "Watch it blind. Seriously."}).status_code == 200  # edit in place
    got = b.get(f"/films/{films[0]}").json()["picks"]
    assert got == [{"user_id": crowd["aid"], "name": "Ann", "blurb": "Watch it blind. Seriously."}]
    latest = b.get("/critics/picks").json()
    assert latest[0]["film"]["id"] == films[0] and latest[0]["critic"]["name"] == "Ann"
    assert a.get(f"/films/{films[0]}").json()["my_pick"] is True
    a.delete(f"/films/{films[0]}/pick")
    assert b.get("/critics/picks").json() == []

    review(app, a, films[0]); review(app, b, films[0])
    assert len(b.get(f"/films/{films[0]}/reviews").json()) == 2
    only = b.get(f"/films/{films[0]}/reviews", params={"critic_only": "true"}).json()
    assert [r["author"]["name"] for r in only] == ["Ann"] and only[0]["author"]["critic"] is True


# ============================================================== sanctions
def test_moderators_strike_and_mute_but_only_downwards(crowd):
    mod, admin, a = crowd["mod"], crowd["admin"], crowd["a"]
    aid, mid = crowd["aid"], crowd["mid"]
    assert a.post(f"/moderation/users/{crowd['bid']}/strike", {"reason": "spoiling in public"}).status_code == 403
    assert mod.post(f"/moderation/users/{mid}/strike", {"reason": "myself, somehow"}).status_code == 400
    assert mod.post("/moderation/users/1/strike", {"reason": "an admin, no way"}).status_code == 403   # admin outranks mod
    assert mod.post("/moderation/users/1/mute", {"days": 1, "reason": "an admin, no way"}).status_code == 403
    assert admin.post("/moderation/users/1/strike", {"reason": "the other admin"}).status_code == 400  # self
    assert admin.post(f"/moderation/users/{mid}/strike", {"reason": "admin may act on a moderator"}).status_code == 201

    assert mod.post(f"/moderation/users/{aid}/strike", {"reason": "x"}).status_code == 400  # a reason is required
    assert mod.post(f"/moderation/users/{aid}/strike", {"reason": "posted a spoiler as a joke"}).json() == {
        "strikes": 1, "auto_muted": False, "muted_until": None}
    hist = mod.get(f"/moderation/users/{aid}").json()
    assert hist["recent_strikes"] == 1 and hist["can_sanction"] is True and hist["strikes"][0]["reason"].startswith("posted")
    assert mod.get("/moderation/users/1").json()["can_sanction"] is False


def test_three_strikes_mute_and_a_mute_blocks_posting_but_not_watching(app, crowd):
    mod, a, admin, films = crowd["mod"], crowd["a"], crowd["admin"], crowd["films"]
    aid = crowd["aid"]
    for i in range(2):
        mod.post(f"/moderation/users/{aid}/strike", {"reason": f"warning number {i}"})
    last = mod.post(f"/moderation/users/{aid}/strike", {"reason": "third warning, final"}).json()
    assert last["auto_muted"] is True and last["muted_until"]
    assert any(x["action"] == "user.automute" for x in admin.get("/admin/audit").json())

    assert a.get("/auth/me").json()["muted_until"]
    assert a.post(f"/films/{films[0]}/reviews", {"text": "I would love to say something nice here."}).status_code == 403
    cid = admin.post("/clubs", {"name": "Quiet", "description": "", "is_public": True}).json()["id"]
    a.post(f"/clubs/{cid}/join")
    assert a.post(f"/clubs/{cid}/threads", {"title": "Hello there", "body": "hi"}).status_code == 403
    log(a, films[0], 4)  # logging, rating and following stay open
    assert a.put(f"/follow/{crowd['bid']}").status_code == 200

    assert mod.delete(f"/moderation/users/{aid}/mute").json() == {"muted_until": None}
    assert a.get("/auth/me").json()["muted_until"] is None
    assert a.post(f"/clubs/{cid}/threads", {"title": "Back again", "body": "hi"}).status_code == 201
    assert mod.post(f"/moderation/users/{aid}/mute", {"days": 400, "reason": "too long"}).status_code == 400
    assert mod.post(f"/moderation/users/{aid}/mute", {"days": 2, "reason": "cooling off"}).status_code == 200


def test_decision_notes_reach_the_author_and_become_training_labels(app, crowd):
    films, a, b, mod = crowd["films"], crowd["a"], crowd["b"], crowd["mod"]
    rid1 = review(app, a, films[0], "Mara Quill dies in the burning tower while Tobin escapes with the diamond. Brutal.")
    rid2 = review(app, b, films[1], "A quiet harbour town, a quiet film, and a very good soundtrack throughout.")
    seg = [s["idx"] for s in mod.get(f"/reviews/{rid1}").json()["segments"] if s.get("blurred")] or [0]
    assert mod.post(f"/moderation/{rid1}/reblur", {"segments": seg, "note": "ending is spoiled"}).status_code == 200
    assert mod.post(f"/moderation/{rid2}/approve", {"note": "fine, no spoilers"}).status_code == 200
    assert mod.post(f"/moderation/{rid2}/approve").status_code == 200  # a note is optional
    texts = [n["text"] for n in (lambda r: r["items"] if isinstance(r, dict) else r)(a.get("/notifications").json())]
    assert any("ending is spoiled" in t for t in texts)

    labels = {x["review_id"]: x for x in mod.get("/moderation/labels").json()}
    assert labels[rid1]["label"] == "spoiler" and labels[rid1]["spoiler_sentences"]
    assert labels[rid2]["label"] == "clean" and labels[rid2]["spoiler_sentences"] == []
    assert a.get("/moderation/labels").status_code == 403
    audit = {x["target"]: x["detail"] for x in crowd["admin"].get("/admin/audit").json() if x["action"] == "review.reblur"}
    assert "ending is spoiled" in audit[f"review:{rid1}"]


def test_moderator_dashboard_numbers(app, crowd):
    films, a, mod = crowd["films"], crowd["a"], crowd["mod"]
    rid = review(app, a, films[0])
    mod.post(f"/moderation/{rid}/approve")
    mod.post(f"/moderation/users/{crowd['aid']}/strike", {"reason": "being rude about spoilers"})
    st = mod.get("/moderation/stats").json()
    assert st["last_7_days"]["review.approve"] == 1 and st["last_7_days"]["user.strike"] == 1
    assert st["decisions_30_days"][0]["name"] == "Mona" and st["strikes_30_days"] == 1
    assert set(st["queue"]) == {"reported", "uncertain", "warned"}
    assert a.get("/moderation/stats").status_code == 403


# ============================================================== reader and writer controls
def test_writer_can_tag_the_whole_review_as_spoilers(app, crowd):
    films, a, b = crowd["films"], crowd["a"], crowd["b"]
    r = a.post(f"/films/{films[1]}/reviews", {"text": "It was all a dream and everyone knows it by the end.", "spoilers": True})
    assert r.status_code == 202
    wait_scans(app)
    segs = b.get(f"/reviews/{r.json()['id']}").json()["segments"]
    assert segs and all(s["blurred"] for s in segs)
    # an author who already used ||tags|| is not wrapped a second time
    r2 = b.post(f"/films/{films[2]}/reviews", {"text": "Great. ||The captain was a robot|| Loved it.", "spoilers": True})
    assert r2.status_code == 202
    wait_scans(app)
    assert b.get(f"/reviews/{r2.json()['id']}").json()["segments"][0]["blurred"] is False


def test_spoiler_safe_preference_is_saved(crowd):
    a = crowd["a"]
    assert a.get("/auth/me").json()["spoiler_safe"] is True  # on by default
    assert a.patch("/auth/me", {"spoiler_safe": False}).json()["spoiler_safe"] is False
    assert a.get("/auth/me").json()["spoiler_safe"] is False
    f = crowd["films"][0]
    assert a.get(f"/films/{f}").json()["i_watched"] is False
    log(a, f, 4)
    assert a.get(f"/films/{f}").json()["i_watched"] is True


# ============================================================== year in review, goal
def test_persona_rules():
    from app.services.insights import persona
    assert persona(2, 0, 0, "Drama", 1, 4, 2)[0] == "The Newcomer"
    assert persona(20, 0, 0.5, "Drama", 3, 4, 10)[0] == "The Big-Screen Believer"
    assert persona(20, 0.3, 0.1, "Drama", 3, 4, 10)[0] == "The Comfort Rewatcher"
    assert persona(20, 0, 0, "Drama", 3, 2.5, 12)[0] == "The Tough Critic"
    assert persona(20, 0, 0, "Drama", 3, 4.5, 12)[0] == "The Easy Believer"
    assert persona(20, 0, 0, "Horror", 3, 3.5, 12)[0] == "The Midnight Watcher"
    assert persona(20, 0, 0, "Drama", 9, 3.5, 12)[0] == "The Wanderer"
    assert persona(20, 0, 0, "Western", 3, 3.5, 12)[0] == "The Cinephile"


def test_year_in_review_numbers(app, crowd):
    from app.models import Film
    films, a = crowd["films"], crowd["a"]
    y = dt.date.today().year
    with app.state.db.session() as s:
        for fid, rt in zip(films, (120, 90, 150)):
            s.get(Film, fid).runtime = rt
    log(a, films[0], 5, dt.date(y, 1, 10), format="Theatre")
    log(a, films[1], 3, dt.date(y, 1, 11))
    log(a, films[2], 4, dt.date(y, 3, 2))
    log(a, films[0], 4.5, dt.date(y, 3, 3))  # a rewatch
    log(a, films[2], 2, dt.date(y - 1, 12, 31))  # last year: must not count
    r = a.get("/me/year").json()
    assert r["year"] == y and r["films"] == 3 and r["entries"] == 4 and r["rewatches"] == 1
    assert r["hours"] == 8.0 and r["avg_stars"] == round((5 + 3 + 4 + 4.5) / 4, 2) and r["rated"] == 4
    assert r["busiest_month"] in ("Jan", "Mar") and r["longest_streak"] == 2
    assert r["longest_film"] == {"title": "Dark Orbit", "minutes": 150} and r["shortest_film"]["minutes"] == 90
    assert [f["id"] for f in r["top_films"]][:1] == [films[0]] and r["top_films"][0]["stars"] == 5
    assert r["first_film"]["on"] == f"{y}-01-10" and r["last_film"]["on"] == f"{y}-03-03"
    assert {g["name"] for g in r["genres"]} == {"Thriller", "Drama", "Sci-Fi"}
    assert r["by_month"][0] == 2 and r["by_month"][2] == 2 and sum(r["by_weekday"]) == 4
    assert r["formats"]["Theatre"] == 1 and r["persona"]["title"] == "The Newcomer"
    assert r["years"] == [y, y - 1] and "3 films" in r["share"]
    old = a.get("/me/year", params={"year": y - 1}).json()
    assert old["films"] == 1 and old["entries"] == 1
    assert a.get("/me/year", params={"year": 1500}).status_code == 400
    nothing = a.get("/me/year", params={"year": y - 5}).json()
    assert nothing["empty"] is True and "yet" in nothing["share"]


def test_goal_progress_and_pace(app, crowd):
    from app.services.insights import goal_progress
    films, a = crowd["films"], crowd["a"]
    y = dt.date.today().year
    assert a.get("/me/goal").json() == {"goal": None}
    assert a.put("/me/goal", {"target": 0}).status_code == 400
    assert a.put("/me/goal", {"target": 2000}).status_code == 400
    assert a.put("/me/goal", {"target": 50, "year": y - 1}).status_code == 400  # last year is over
    g = a.put("/me/goal", {"target": 10}).json()["goal"]
    assert g["target"] == 10 and g["done"] == 0 and g["percent"] == 0 and g["reached"] is False
    log(a, films[0], 4); log(a, films[1], 4); log(a, films[0], 4)  # a repeat of one film counts once
    g = a.get("/me/goal").json()["goal"]
    assert g["done"] == 2 and g["percent"] == 20
    assert a.put("/me/goal", {"target": 2}).json()["goal"]["reached"] is True


def test_goal_pace_math(app, crowd):
    from app.models import WatchGoal
    from app.services.insights import goal_progress
    uid = crowd["aid"]
    with app.state.db.session() as s:
        s.add(WatchGoal(user_id=uid, year=2026, target=365))
        s.flush()
        g = goal_progress(s, uid, 2026, today=dt.date(2026, 4, 10))   # day 100
        assert g["expected"] == 100.0 and g["ahead_by"] == -100.0 and g["days_left"] == 265
        assert g["per_week_needed"] == round(365 / 265 * 7, 1)
        assert goal_progress(s, uid, 2025) is None


# ============================================================== recommendations, taste match, friends, film of the day
def test_recommendations_cold_start_then_personal_with_reasons(app, crowd):
    films, a = crowd["films"], crowd["a"]
    cold = a.get("/me/recommendations").json()
    assert cold["ready"] is False and cold["needed"] == 3 and cold["items"] and cold["items"][0]["reason"] == "Popular on CineLog"

    from app.services.catalog import upsert_tmdb_film
    with app.state.db.session() as s:
        for i in range(4):  # unseen films: two thrillers, two comedies
            upsert_tmdb_film(s, {"id": 200 + i, "title": f"{'Thriller' if i < 2 else 'Comedy'} Pick {i}", "release_date": "2018-01-01",
                                 "popularity": 5.0, "genres": [{"name": "Thriller" if i < 2 else "Comedy"}]})
    log(a, films[0], 5)   # Thriller, loved
    log(a, films[1], 2)   # Drama, disliked
    log(a, films[2], 3)
    rec = a.get("/me/recommendations", params={"limit": 20}).json()
    assert rec["ready"] is True and rec["logged"] == 3
    ids = [x["id"] for x in rec["items"]]
    assert not set(ids) & set(films)  # never what you already watched
    titles = [x["title"] for x in rec["items"]]
    assert titles.index("Thriller Pick 0") < titles.index("Comedy Pick 2")  # taste ranks thrillers first
    top = next(x for x in rec["items"] if x["title"] == "Thriller Pick 0")
    assert "Rosewood Heist" in top["reason"] and "Thriller" in top["reason"]


def test_recommendations_use_friends_ratings(app, crowd):
    films, a, b = crowd["films"], crowd["a"], crowd["b"]
    from app.services.catalog import upsert_tmdb_film
    with app.state.db.session() as s:
        pick = upsert_tmdb_film(s, {"id": 300, "title": "Friend Favourite", "release_date": "2017-01-01", "popularity": 1.0,
                                    "genres": [{"name": "Western"}]}).id
    log(a, films[0], 4); log(a, films[1], 4); log(a, films[2], 4)
    a.put(f"/follow/{crowd['bid']}")
    log(b, pick, 5)
    item = next(x for x in a.get("/me/recommendations", params={"limit": 30}).json()["items"] if x["id"] == pick)
    assert item["reason"].startswith("Bob rated it ★5") and item["friends"][0]["name"] == "Bob"


def test_taste_match(app, crowd):
    films, a, b = crowd["films"], crowd["a"], crowd["b"]
    assert a.get(f"/users/{crowd['aid']}/match").status_code == 400
    assert a.get("/users/9999/match").status_code == 404
    assert new_anon(app).get(f"/users/{crowd['bid']}/match").status_code == 401
    empty = a.get(f"/users/{crowd['bid']}/match").json()
    assert empty["score"] is None and empty["basis"] == "none"

    for f, x, y in ((films[0], 5, 5), (films[1], 4, 4.5), (films[2], 2, 4.5)):
        log(a, f, x); log(b, f, y)
    m = a.get(f"/users/{crowd['bid']}/match").json()
    assert m["basis"] == "ratings" and m["rated_together"] == 3 and m["shared_films"] == 3
    assert m["user"]["name"] == "Bob" and 60 <= m["score"] <= 95 and m["label"]
    assert {f["id"] for f in m["both_loved"]} == {films[0], films[1]}
    assert [f["id"] for f in m["disagree"]] == [films[2]] and m["disagree"][0]["you"] == 2


def new_anon(app):
    from conftest import Api
    return Api(app)


def test_taste_match_with_few_shared_films_uses_genres_only(app, crowd):
    films, a, b = crowd["films"], crowd["a"], crowd["b"]
    log(a, films[0], 4); log(b, films[0], 4); log(b, films[1], 4)
    m = a.get(f"/users/{crowd['bid']}/match").json()
    assert m["basis"] == "genres" and m["score"] is not None and m["score"] <= 85 and m["rated_together"] == 1


def test_friends_who_watched(app, crowd):
    films, a, b = crowd["films"], crowd["a"], crowd["b"]
    f = films[0]
    assert a.get(f"/films/{f}/friends").json() == {"count": 0, "avg": None, "friends": []}
    log(b, f, 4, dt.date.today() - dt.timedelta(days=3)); log(b, f, 5)
    assert a.get(f"/films/{f}/friends").json()["count"] == 0  # not following yet
    a.put(f"/follow/{crowd['bid']}")
    review(app, b, f)
    got = a.get(f"/films/{f}/friends").json()
    assert got["count"] == 1 and got["avg"] == 5.0
    assert got["friends"][0]["name"] == "Bob" and got["friends"][0]["stars"] == 5 and got["friends"][0]["reviewed"] is True
    assert new_anon(app).get(f"/films/{f}/friends").status_code == 401


def test_film_of_the_day_is_stable_within_a_day(app, crowd):
    anon = new_anon(app)
    one, two = anon.get("/discover/film-of-the-day").json(), anon.get("/discover/film-of-the-day").json()
    assert one["film"]["id"] == two["film"]["id"] and one["date"] == dt.date.today().isoformat()
    a = crowd["a"]
    assert a.get("/discover/film-of-the-day").json()["watched"] is False
    log(a, one["film"]["id"], 4)
    assert a.get("/discover/film-of-the-day").json()["watched"] is True


def test_film_of_the_day_with_an_empty_catalogue(app, new_client):
    assert new_client().get("/discover/film-of-the-day").json() == {"film": None}


# ============================================================== clubs: analytics, calendar, ics, upcoming
@pytest.fixture()
def club(app, crowd):
    admin, a, b, films = crowd["admin"], crowd["a"], crowd["b"], crowd["films"]
    cid = admin.post("/clubs", {"name": "Friday Frames", "description": "weekly", "is_public": True}).json()["id"]
    a.post(f"/clubs/{cid}/join"); b.post(f"/clubs/{cid}/join")
    return cid


def test_club_analytics_are_for_conveners_only(app, crowd, club):
    from app.models import Poll, PollOption, Vote, Watchalong, WatchalongRsvp
    admin, a, b, films, cid = crowd["admin"], crowd["a"], crowd["b"], crowd["films"], club
    assert a.get(f"/clubs/{cid}/analytics").status_code == 403           # a plain member
    assert crowd["mod"].get(f"/clubs/{cid}/analytics").status_code == 403  # site role does not carry into the club
    assert new_anon(app).get(f"/clubs/{cid}/analytics").status_code == 401
    assert admin.get("/clubs/9999/analytics").status_code == 404

    admin.post(f"/clubs/{cid}/members", {"email": "ann@x.io", "role": "co_convener"})
    assert a.get(f"/clubs/{cid}/analytics").status_code == 200           # a co-convener may

    a.post(f"/clubs/{cid}/threads", {"title": "Opening night", "body": "who is in?"})
    admin.post(f"/clubs/{cid}/threads", {"title": "Hello", "body": "welcome"})
    t = admin.get(f"/clubs/{cid}/threads").json()[0]["id"]
    b.post(f"/threads/{t}/replies", {"body": "me!"})
    with app.state.db.session() as s:
        past = Watchalong(club_id=cid, film_id=films[0], starts_at=dt.datetime.utcnow() - dt.timedelta(days=3), created_by=1)
        s.add(past); s.flush()
        s.add(WatchalongRsvp(watchalong_id=past.id, user_id=crowd["aid"])); s.add(WatchalongRsvp(watchalong_id=past.id, user_id=crowd["bid"]))
        poll = Poll(club_id=cid, title="Pick a film", state="closed", winner_film_id=films[1], created_by=1)
        poll.options = [PollOption(film_id=films[1]), PollOption(film_id=films[2])]
        s.add(poll); s.flush()
        opt = poll.options[0].id
        s.add(Vote(poll_id=poll.id, user_id=crowd["aid"], option_id=opt)); s.add(Vote(poll_id=poll.id, user_id=1, option_id=opt))
    soon = (dt.datetime.utcnow() + dt.timedelta(days=2)).isoformat()
    admin.post(f"/clubs/{cid}/watchalongs", {"film_id": films[2], "starts_at": soon})
    log(a, films[0], 5); log(b, films[0], 3); log(a, films[1], 4)

    r = admin.get(f"/clubs/{cid}/analytics").json()
    assert r["members"]["total"] == 3 and r["members"]["by_role"] == {"convener": 1, "co_convener": 1, "member": 1}
    assert r["polls"]["total"] == 1 and r["polls"]["closed"] == 1 and r["polls"]["participation"] == 0.67
    assert r["polls"]["recent"][0]["winner"] == "Quiet Harbour" and r["polls"]["recent"][0]["votes"] == 2
    assert r["watchalongs"]["upcoming"] == 1 and r["watchalongs"]["past"] == 1
    assert r["watchalongs"]["avg_rsvps"] == 2.0 and r["watchalongs"]["rsvp_rate"] == 0.67
    assert r["watchalongs"]["next"]["title"] == "Dark Orbit"
    assert r["discussion"]["threads"] == 2 and r["discussion"]["replies"] == 1 and len(r["discussion"]["weekly"]) == 8
    assert sum(w["posts"] for w in r["discussion"]["weekly"]) == 3
    assert {w["name"] for w in r["discussion"]["top_writers"]} == {"Admin", "Ann", "Bob"}
    best = r["films"][0]
    assert best["title"] == "Rosewood Heist" or best["title"] == "Quiet Harbour"
    heist = next(f for f in r["films"] if f["title"] == "Rosewood Heist")
    assert heist["watched_by"] == 2 and heist["avg"] == 4.0


def test_club_calendar_month_view_and_ics(app, crowd, club):
    admin, films, cid = crowd["admin"], crowd["films"], club
    when = dt.datetime.utcnow().replace(hour=19, minute=30, second=0, microsecond=0) + dt.timedelta(days=2)
    w = admin.post(f"/clubs/{cid}/watchalongs", {"film_id": films[0], "starts_at": when.isoformat()}).json()
    crowd["a"].put(f"/watchalongs/{w['id']}/rsvp")
    month = when.strftime("%Y-%m")
    cal = crowd["a"].get(f"/clubs/{cid}/calendar", params={"month": month}).json()
    assert cal["month"] == month and 28 <= cal["days"] <= 31 and 0 <= cal["first_weekday"] <= 6
    ev = [e for e in cal["events"] if e["type"] == "watchalong"]
    assert len(ev) == 1 and ev[0]["title"] == "Rosewood Heist" and ev[0]["going"] == 1 and ev[0]["rsvp"] is True
    assert admin.get(f"/clubs/{cid}/calendar", params={"month": "2020-01"}).json()["events"] == []
    assert admin.get(f"/clubs/{cid}/calendar", params={"month": "nope"}).status_code == 400

    ics = crowd["a"].get(f"/clubs/{cid}/calendar.ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    body = ics.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Watch-along: Rosewood Heist" in body and f"DTSTART:{when.strftime('%Y%m%dT%H%M%SZ')}" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    assert crowd["a"].get("/me/calendar.ics").text.count("BEGIN:VEVENT") == 1
    assert new_anon(app).get(f"/clubs/{cid}/calendar.ics").status_code == 200  # a public club's calendar is public


def test_private_club_calendar_is_members_only(app, crowd):
    admin = crowd["admin"]
    cid = admin.post("/clubs", {"name": "Secret Society", "description": "", "is_public": False}).json()["id"]
    assert crowd["a"].get(f"/clubs/{cid}/calendar").status_code == 403
    assert crowd["a"].get(f"/clubs/{cid}/calendar.ics").status_code == 403
    assert admin.get(f"/clubs/{cid}/calendar").status_code == 200


def test_ics_escaping_and_folding():
    from app.routers.club_insights import _fold, _ics_text, build_ics
    assert _ics_text("A, B; C\nD") == "A\\, B\\; C\\nD"
    long = "SUMMARY:" + "é" * 100
    folded = _fold(long).split("\r\n")
    assert all(len(x.encode()) <= 75 for x in folded) and "".join(x.lstrip(" ") if i else x for i, x in enumerate(folded)) == long
    out = build_ics([{"type": "poll_deadline", "id": 1, "at": "2026-10-10T18:00:00", "title": "Voting closes: Pick", "club": "C"}], "Cal")
    assert "DTEND:20261010T183000Z" in out


def test_upcoming_watchalongs_across_my_clubs(app, crowd, club):
    admin, a, films, cid = crowd["admin"], crowd["a"], crowd["films"], club
    soon = (dt.datetime.utcnow() + dt.timedelta(days=1)).isoformat()
    later = (dt.datetime.utcnow() + dt.timedelta(days=5)).isoformat()
    admin.post(f"/clubs/{cid}/watchalongs", {"film_id": films[2], "starts_at": later})
    first = admin.post(f"/clubs/{cid}/watchalongs", {"film_id": films[0], "starts_at": soon}).json()
    a.put(f"/watchalongs/{first['id']}/rsvp")
    up = a.get("/me/upcoming").json()
    assert [u["film"]["title"] for u in up] == ["Rosewood Heist", "Dark Orbit"] and up[0]["rsvp"] is True and up[0]["club"] == "Friday Frames"
    assert crowd["mod"].get("/me/upcoming").json() == []  # not in the club


# ============================================================== schema
def test_migration_3_adds_columns_to_an_old_users_table(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app.migrations import migrate
    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(254))"))
        c.execute(text("INSERT INTO users (id, email) VALUES (1, 'a@x.io')"))
    assert 3 in migrate(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    assert {"muted_until", "spoiler_safe"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT spoiler_safe FROM users")).scalar() in (1, True)  # existing people default to safe
    assert migrate(eng) == []
