"""Numbers about a person's own viewing: the year in review, the yearly goal, and how two people's tastes compare.

All of it is read from the diary (plus reviews, likes and badges); nothing here writes except `set_goal`.
"""
from __future__ import annotations

import calendar
import datetime as dt
import math
from collections import Counter
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..gamification import streaks
from ..models import DiaryEntry, Film, Like, Review, UserBadge, WatchGoal
from .catalog import film_card

MONTHS = [calendar.month_abbr[i] for i in range(1, 13)]
WEEKDAYS = list(calendar.day_abbr)


# ---------------------------------------------------------------- persona: a playful label from the numbers
def persona(films: int, rewatch_share: float, big_screen_share: float, top_genre: Optional[str], genres: int,
            avg_stars: Optional[float], rated: int) -> Tuple[str, str]:
    """First rule that fits wins. Rules go from the most distinctive habit to the most general."""
    if films < 5:
        return "The Newcomer", "Only just getting started: the reel is wide open."
    if big_screen_share >= 0.4:
        return "The Big-Screen Believer", "If it isn't loud and enormous, is it even cinema?"
    if rewatch_share >= 0.25:
        return "The Comfort Rewatcher", "You know what you love, and you go back to it."
    if rated >= 10 and avg_stars is not None and avg_stars < 3.0:
        return "The Tough Critic", "Four stars is a rare gift from you, and everyone knows it."
    if rated >= 10 and avg_stars is not None and avg_stars >= 4.2:
        return "The Easy Believer", "You went in wanting to love it, and mostly did."
    by_genre = {"Horror": ("The Midnight Watcher", "Lights off, volume up."),
                "Drama": ("The Feeler", "You came for the story and stayed for the tears."),
                "Comedy": ("The Mood Lifter", "Life is short; you watch accordingly."),
                "Science Fiction": ("The Futurist", "Always one film ahead of the present."),
                "Sci-Fi": ("The Futurist", "Always one film ahead of the present."),
                "Thriller": ("The Edge-of-Seat Regular", "You like not knowing what happens next."),
                "Animation": ("The Forever Young", "Drawn, painted or rendered: it all counts."),
                "Romance": ("The Hopeless Romantic", "A fan of the slow look across the room."),
                "Action": ("The Adrenaline Seeker", "If nothing explodes, you check your watch."),
                "Documentary": ("The Curious Mind", "You watch to learn something real.")}
    if genres >= 8:
        return "The Wanderer", "Eight-plus genres in a year: no map, no problem."
    if top_genre in by_genre:
        return by_genre[top_genre]
    return "The Cinephile", "Steady, curious, always one more film."


def _latest_stars(db: Session, uid: int) -> Dict[int, float]:
    """The most recent star rating for each film this person logged."""
    out: Dict[int, float] = {}
    for fid, stars in db.execute(select(DiaryEntry.film_id, DiaryEntry.stars).where(
            DiaryEntry.user_id == uid, DiaryEntry.stars.is_not(None)).order_by(DiaryEntry.watched_on, DiaryEntry.id)):
        out[fid] = stars
    return out


def years_with_entries(db: Session, uid: int) -> List[int]:
    ys = {d.year for (d,) in db.execute(select(DiaryEntry.watched_on).where(DiaryEntry.user_id == uid))}
    return sorted(ys, reverse=True)


def year_in_review(db: Session, uid: int, year: int) -> dict:
    start, end = dt.date(year, 1, 1), dt.date(year, 12, 31)
    rows = db.execute(select(DiaryEntry, Film).join(Film, Film.id == DiaryEntry.film_id).where(
        DiaryEntry.user_id == uid, DiaryEntry.watched_on >= start, DiaryEntry.watched_on <= end)
        .order_by(DiaryEntry.watched_on, DiaryEntry.id)).all()
    out: dict = {"year": year, "entries": len(rows), "empty": not rows}
    if not rows:
        out["goal"] = goal_progress(db, uid, year)
        return out
    films = {f.id: f for _, f in rows}
    entries = [e for e, _ in rows]
    stars = [e.stars for e in entries if e.stars is not None]
    minutes = sum((f.runtime or 0) for _, f in rows)
    by_month = [0] * 12
    by_weekday = [0] * 7
    for e in entries:
        by_month[e.watched_on.month - 1] += 1
        by_weekday[e.watched_on.weekday()] += 1
    genres = Counter(g.genre for f in films.values() for g in f.genres)
    decades = Counter(f.year // 10 * 10 for f in films.values() if f.year)
    formats = Counter(e.format for e in entries)
    actors = Counter(c.actor for f in films.values() for c in f.cast[:3])
    rewatches = sum(1 for e in entries if e.rewatch)
    big = formats.get("Theatre", 0) + formats.get("IMAX", 0)
    best: Dict[int, float] = {}
    for e in entries:
        if e.stars is not None:
            best[e.film_id] = max(best.get(e.film_id, 0), e.stars)
    top = sorted(best.items(), key=lambda kv: (-kv[1], films[kv[0]].title))[:5]
    hist = [0] * 10
    for s in stars:
        hist[int(round(s * 2)) - 1] += 1
    timed = [f for f in films.values() if f.runtime]
    top_genre = genres.most_common(1)[0][0] if genres else None
    title, blurb = persona(len(films), rewatches / len(entries), big / len(entries), top_genre, len(genres),
                           sum(stars) / len(stars) if stars else None, len(stars))
    busiest_m = max(range(12), key=lambda i: by_month[i])
    busiest_d = max(range(7), key=lambda i: by_weekday[i])
    reviews = db.scalar(select(func.count()).select_from(Review).where(
        Review.user_id == uid, Review.state == "published", Review.created_at >= dt.datetime.combine(start, dt.time()),
        Review.created_at < dt.datetime.combine(end + dt.timedelta(days=1), dt.time()))) or 0
    likes = db.scalar(select(func.count()).select_from(Like).join(Review, Review.id == Like.target_id).where(
        Like.kind == "review", Review.user_id == uid, Like.user_id != uid,
        Like.created_at >= dt.datetime.combine(start, dt.time()),
        Like.created_at < dt.datetime.combine(end + dt.timedelta(days=1), dt.time()))) or 0
    badges = db.scalar(select(func.count()).select_from(UserBadge).where(
        UserBadge.user_id == uid, UserBadge.earned_at >= dt.datetime.combine(start, dt.time()),
        UserBadge.earned_at < dt.datetime.combine(end + dt.timedelta(days=1), dt.time()))) or 0
    first, last = rows[0], rows[-1]
    out.update({
        "films": len(films), "hours": round(minutes / 60, 1), "days_equivalent": round(minutes / 60 / 24, 1),
        "rewatches": rewatches, "avg_stars": round(sum(stars) / len(stars), 2) if stars else None, "rated": len(stars),
        "rating_hist": hist,
        "top_films": [{**film_card(films[i]), "stars": s} for i, s in top],
        "genres": [{"name": g, "n": n} for g, n in genres.most_common(6)],
        "top_decade": f"{decades.most_common(1)[0][0]}s" if decades else None,
        "decades": [{"name": f"{d}s", "n": n} for d, n in sorted(decades.items())],
        "formats": dict(formats), "big_screen_share": round(big / len(entries), 2),
        "by_month": by_month, "busiest_month": MONTHS[busiest_m] if by_month[busiest_m] else None,
        "by_weekday": by_weekday, "busiest_weekday": WEEKDAYS[busiest_d] if by_weekday[busiest_d] else None,
        "longest_streak": streaks([e.watched_on for e in entries], today=end)["longest"],
        "longest_film": ({"title": max(timed, key=lambda f: f.runtime).title, "minutes": max(f.runtime for f in timed)} if timed else None),
        "shortest_film": ({"title": min(timed, key=lambda f: f.runtime).title, "minutes": min(f.runtime for f in timed)} if timed else None),
        "first_film": {"title": first[1].title, "on": first[0].watched_on.isoformat()},
        "last_film": {"title": last[1].title, "on": last[0].watched_on.isoformat()},
        "top_actor": ({"name": actors.most_common(1)[0][0], "films": actors.most_common(1)[0][1]} if actors and actors.most_common(1)[0][1] >= 2 else None),
        "reviews": reviews, "likes_received": likes, "badges_earned": badges,
        "persona": {"title": title, "blurb": blurb},
        "goal": goal_progress(db, uid, year),
    })
    return out


def share_text(r: dict, name: str) -> str:
    """The year as a few lines of plain text, ready to paste anywhere."""
    if r.get("empty"):
        return f"{name} hasn't logged any films in {r['year']} yet."
    lines = [f"{name}'s {r['year']} on CineLog: {r['persona']['title']}",
             f"{r['films']} films · {r['hours']} hours · avg {r['avg_stars'] if r['avg_stars'] is not None else '–'}★",
             f"Most watched: {r['genres'][0]['name'] if r['genres'] else '–'} · busiest month: {r['busiest_month']}",
             f"Longest streak: {r['longest_streak']} days"]
    if r["top_films"]:
        lines.append("Top films: " + ", ".join(f["title"] for f in r["top_films"][:3]))
    return "\n".join(lines)


# ---------------------------------------------------------------- yearly goal
def goal_progress(db: Session, uid: int, year: int, today: Optional[dt.date] = None) -> Optional[dict]:
    g = db.get(WatchGoal, (uid, year))
    if g is None:
        return None
    today = today or dt.date.today()
    done = db.scalar(select(func.count(func.distinct(DiaryEntry.film_id))).where(
        DiaryEntry.user_id == uid, DiaryEntry.watched_on >= dt.date(year, 1, 1), DiaryEntry.watched_on <= dt.date(year, 12, 31))) or 0
    days_in_year = 366 if calendar.isleap(year) else 365
    if year < today.year:
        elapsed, left = days_in_year, 0
    elif year > today.year:
        elapsed, left = 0, days_in_year
    else:
        elapsed = today.timetuple().tm_yday
        left = days_in_year - elapsed
    expected = g.target * elapsed / days_in_year
    remaining = max(0, g.target - done)
    return {"year": year, "target": g.target, "done": done, "percent": min(100, int(100 * done / g.target)),
            "expected": round(expected, 1), "ahead_by": round(done - expected, 1), "days_left": left,
            "per_week_needed": round(remaining / max(1, left) * 7, 1) if left else None,
            "reached": done >= g.target}


def set_goal(db: Session, uid: int, year: int, target: int) -> None:
    g = db.get(WatchGoal, (uid, year))
    if g is None:
        db.add(WatchGoal(user_id=uid, year=year, target=target))
    else:
        g.target = target
    db.flush()


# ---------------------------------------------------------------- how alike are two people?
def _cosine_counts(a: Counter, b: Counter) -> float:
    dot = sum(a[k] * b[k] for k in a if k in b)
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _genre_counts(db: Session, uid: int) -> Counter:
    c: Counter = Counter()
    ids = {fid for (fid,) in db.execute(select(DiaryEntry.film_id).where(DiaryEntry.user_id == uid))}
    if not ids:
        return c
    from ..models import FilmGenre
    for (g,) in db.execute(select(FilmGenre.genre).where(FilmGenre.film_id.in_(ids))):
        c[g] += 1
    return c


def label_for(score: int) -> str:
    return ("Kindred spirits" if score >= 85 else "Same wavelength" if score >= 70 else "Some common ground" if score >= 50
            else "Different tastes" if score >= 30 else "Opposites attract")


def taste_match(db: Session, me: int, other: int) -> dict:
    mine, theirs = _latest_stars(db, me), _latest_stars(db, other)
    both = sorted(set(mine) & set(theirs))
    seen_me = {fid for (fid,) in db.execute(select(DiaryEntry.film_id).where(DiaryEntry.user_id == me))}
    seen_them = {fid for (fid,) in db.execute(select(DiaryEntry.film_id).where(DiaryEntry.user_id == other))}
    shared_films = len(seen_me & seen_them)
    gc_me, gc_them = _genre_counts(db, me), _genre_counts(db, other)
    genre_sim = _cosine_counts(gc_me, gc_them)
    shared_genres = [g for g, _ in sorted(((g, min(gc_me[g], gc_them[g])) for g in gc_me if g in gc_them), key=lambda kv: -kv[1])[:3]]
    out = {"shared_films": shared_films, "rated_together": len(both), "shared_genres": shared_genres}
    if len(both) >= 3:
        diff = sum(abs(mine[f] - theirs[f]) for f in both) / len(both)
        agree = max(0.0, 1 - diff / 4.5)
        score = round(100 * (0.7 * agree + 0.3 * genre_sim))
        out["basis"] = "ratings"
    elif gc_me and gc_them:
        score = round(100 * genre_sim * 0.85)  # genres alone are weaker evidence, so they cap lower
        out["basis"] = "genres"
    else:
        out.update({"score": None, "label": None, "basis": "none", "both_loved": [], "disagree": []})
        return out
    ids = set(both)
    films = {f.id: f for f in db.scalars(select(Film).where(Film.id.in_(ids or [0])))}
    loved = [f for f in both if mine[f] >= 4 and theirs[f] >= 4]
    gaps = sorted((f for f in both if abs(mine[f] - theirs[f]) >= 1.5), key=lambda f: -abs(mine[f] - theirs[f]))
    out.update({"score": score, "label": label_for(score),
                "both_loved": [{**film_card(films[f]), "you": mine[f], "them": theirs[f]} for f in loved[:5] if f in films],
                "disagree": [{**film_card(films[f]), "you": mine[f], "them": theirs[f]} for f in gaps[:3] if f in films]})
    return out
