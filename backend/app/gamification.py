"""Badges and streaks.

HOW TO ADD A BADGE: append one Badge(...) line to BADGES. It needs a metric name and a target number.
HOW TO ADD A METRIC: write a function decorated with @metric("name") that returns a number for a user.
Nothing else changes: progress bars, the profile shelf, the feed and the "badge earned" toast all read this registry.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (ClubMember, ClubThread, DiaryEntry, Film, FilmGenre, FilmList, Follow, Like, Review, ThreadReply,
                     UserBadge, Vote, WatchalongRsvp)
from .services.notifications import notify

METRICS: Dict[str, Callable[[Session, int], float]] = {}


def metric(name: str):
    def deco(fn):
        METRICS[name] = fn
        return fn
    return deco


@dataclass(frozen=True)
class Badge:
    key: str          # stable id stored in user_badges - never rename
    name: str
    description: str
    metric: str       # key in METRICS
    target: float
    color: str        # one of the six palette keys: m t g j c v


# ---------------------------------------------------------------- streaks
def streaks(dates: List[dt.date], today: Optional[dt.date] = None) -> Dict[str, int]:
    """current = consecutive days ending today or yesterday; longest = best run ever."""
    days = sorted(set(dates))
    longest = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    s = set(days)
    d = today or dt.date.today()
    if d not in s:
        d -= dt.timedelta(days=1)
    cur = 0
    while d in s:
        cur += 1
        d -= dt.timedelta(days=1)
    return {"current": cur, "longest": longest}


def _dates(db: Session, uid: int) -> List[dt.date]:
    return [d for (d,) in db.execute(select(DiaryEntry.watched_on).where(DiaryEntry.user_id == uid))]


def _count(db: Session, stmt) -> int:
    return db.scalar(stmt) or 0


# ---------------------------------------------------------------- metrics
@metric("films")
def m_films(db, uid):
    return _count(db, select(func.count(func.distinct(DiaryEntry.film_id))).where(DiaryEntry.user_id == uid))


def _date_films(db: Session, uid: int) -> set:
    """Distinct (day, film) pairs: logging one film again must not look like watching more films."""
    return {(d, f) for d, f in db.execute(select(DiaryEntry.watched_on, DiaryEntry.film_id).where(DiaryEntry.user_id == uid))}


@metric("films_this_year")
def m_films_year(db, uid):
    y = dt.date.today().year
    return len({f for d, f in _date_films(db, uid) if d.year == y})


@metric("films_one_day")
def m_one_day(db, uid):
    c = Counter(d for d, _ in _date_films(db, uid))
    return max(c.values()) if c else 0


@metric("longest_streak")
def m_streak(db, uid):
    return streaks(_dates(db, uid))["longest"]


@metric("rewatches")
def m_rewatches(db, uid):
    return _count(db, select(func.count()).select_from(DiaryEntry).where(DiaryEntry.user_id == uid, DiaryEntry.rewatch))


@metric("cinema_trips")
def m_cinema(db, uid):
    return _count(db, select(func.count()).select_from(DiaryEntry).where(
        DiaryEntry.user_id == uid, DiaryEntry.format.in_(("Theatre", "IMAX"))))


@metric("genres")
def m_genres(db, uid):
    return _count(db, select(func.count(func.distinct(FilmGenre.genre))).join(DiaryEntry, DiaryEntry.film_id == FilmGenre.film_id)
                  .where(DiaryEntry.user_id == uid))


@metric("decades")
def m_decades(db, uid):
    years = [y for (y,) in db.execute(select(Film.year).join(DiaryEntry, DiaryEntry.film_id == Film.id)
                                      .where(DiaryEntry.user_id == uid, Film.year.is_not(None)))]
    return len({y // 10 for y in years})


@metric("reviews")
def m_reviews(db, uid):
    return _count(db, select(func.count()).select_from(Review).where(Review.user_id == uid, Review.state == "published"))


@metric("likes_received")
def m_likes(db, uid):
    r = _count(db, select(func.count()).select_from(Like).join(Review, Review.id == Like.target_id)
               .where(Like.kind == "review", Review.user_id == uid, Like.user_id != uid))
    l = _count(db, select(func.count()).select_from(Like).join(FilmList, FilmList.id == Like.target_id)
               .where(Like.kind == "list", FilmList.user_id == uid, Like.user_id != uid))
    return r + l


@metric("lists")
def m_lists(db, uid):
    return _count(db, select(func.count()).select_from(FilmList).where(FilmList.user_id == uid))


@metric("followers")
def m_followers(db, uid):
    return _count(db, select(func.count()).select_from(Follow).where(Follow.followee_id == uid))


@metric("clubs_joined")
def m_clubs(db, uid):
    return _count(db, select(func.count()).select_from(ClubMember).where(ClubMember.user_id == uid))


@metric("clubs_convened")
def m_convened(db, uid):
    return _count(db, select(func.count()).select_from(ClubMember).where(ClubMember.user_id == uid, ClubMember.role == "convener"))


@metric("votes")
def m_votes(db, uid):
    return _count(db, select(func.count()).select_from(Vote).where(Vote.user_id == uid))


@metric("club_posts")
def m_posts(db, uid):
    return (_count(db, select(func.count()).select_from(ClubThread).where(ClubThread.user_id == uid))
            + _count(db, select(func.count()).select_from(ThreadReply).where(ThreadReply.user_id == uid)))


@metric("rsvps")
def m_rsvps(db, uid):
    return _count(db, select(func.count()).select_from(WatchalongRsvp).where(WatchalongRsvp.user_id == uid))


# ---------------------------------------------------------------- the badge shelf (order = display order)
BADGES: List[Badge] = [
    Badge("first_reel", "First Reel", "Log your first film", "films", 1, "g"),
    Badge("regular", "Regular", "Log 25 different films", "films", 25, "j"),
    Badge("century", "Century", "A hundred films in one year", "films_this_year", 100, "g"),
    Badge("marathoner", "Marathoner", "Three films in one day", "films_one_day", 3, "t"),
    Badge("week_streak", "Seven Nights", "A seven-day diary streak", "longest_streak", 7, "t"),
    Badge("month_streak", "Thirty Nights", "A thirty-day diary streak", "longest_streak", 30, "m"),
    Badge("big_screen", "Big Screen", "Ten trips to the cinema", "cinema_trips", 10, "c"),
    Badge("genre_hopper", "Genre Hopper", "Films from eight genres", "genres", 8, "v"),
    Badge("time_traveller", "Time Traveller", "Films from five decades", "decades", 5, "c"),
    Badge("rewatcher", "Comfort Rewatcher", "Five rewatches", "rewatches", 5, "j"),
    Badge("critic", "Critic", "Publish ten reviews", "reviews", 10, "j"),
    Badge("crowd_favourite", "Crowd Favourite", "Twenty-five likes on your reviews and lists", "likes_received", 25, "m"),
    Badge("curator", "Curator", "Make three lists", "lists", 3, "v"),
    Badge("club_regular", "Club Regular", "Vote in five club polls", "votes", 5, "g"),
    Badge("talker", "Thread Starter", "Ten posts in club discussions", "club_posts", 10, "c"),
    Badge("club_captain", "Club Captain", "Run a club as convener", "clubs_convened", 1, "v"),
    Badge("front_row", "Front Row", "RSVP to three watch-alongs", "rsvps", 3, "t"),
]
BY_KEY = {b.key: b for b in BADGES}


def badge_progress(db: Session, uid: int, save: bool = True) -> List[dict]:
    """Every badge with the user's progress. Newly reached badges are stored (and flagged new=True) when save is on."""
    earned = {b.key: b.earned_at for b in db.scalars(select(UserBadge).where(UserBadge.user_id == uid))}
    cache: Dict[str, float] = {}
    out = []
    for b in BADGES:
        if b.metric not in cache:
            cache[b.metric] = float(METRICS[b.metric](db, uid))
        v = cache[b.metric]
        is_new = False
        if b.key not in earned and v >= b.target and save:
            ub = UserBadge(user_id=uid, key=b.key)
            db.add(ub); db.flush()
            notify(db, uid, "badge", f"Badge earned: {b.name}", "/me")
            earned[b.key] = ub.earned_at
            is_new = True
        got = b.key in earned
        out.append({"key": b.key, "name": b.name, "description": b.description, "color": b.color, "earned": got,
                    "earned_at": earned[b.key].isoformat() if got else None, "new": is_new,
                    "value": int(min(v, b.target)) if not got else int(b.target), "target": int(b.target),
                    "percent": 100 if got else int(min(99, 100 * v / b.target))})
    return out


def award(db: Session, uid: int) -> List[dict]:
    """Call after anything that could earn a badge. Returns only the badges earned just now."""
    return [b for b in badge_progress(db, uid) if b["new"]]


def user_streaks(db: Session, uid: int) -> Dict[str, int]:
    return streaks(_dates(db, uid))
