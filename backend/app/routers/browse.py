"""Read-only endpoints for the browsing screens: film grid, genres, my stats, user profiles."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (ClubMember, Club, DiaryEntry, Film, FilmGenre, Follow, Review, User, WatchlistItem)
from ..gamification import badge_progress, streaks
from ..rbac import get_db, get_wdb, user_optional, user_required
from ..services.catalog import film_card, film_ratings
from ..services.reviews import review_view

router = APIRouter(tags=["browse"])


@router.get("/genres")
def genres(db: Session = Depends(get_db)):
    rows = db.execute(select(FilmGenre.genre, func.count()).group_by(FilmGenre.genre).order_by(func.count().desc())).all()
    return [{"genre": g, "films": n} for g, n in rows]


@router.get("/films")
def browse(genre: Optional[str] = None, decade: Optional[int] = None, sort: str = "popular", limit: int = 24,
           offset: int = 0, db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    """Film grid for Discover. sort = popular | top (average star rating) | new."""
    if sort not in ("popular", "top", "new"):
        raise HTTPException(422, "sort must be popular, top or new")
    limit = max(1, min(limit, 60))
    stmt = select(Film)
    if genre:
        stmt = stmt.join(FilmGenre, FilmGenre.film_id == Film.id).where(func.lower(FilmGenre.genre) == genre.lower())
    if decade:
        stmt = stmt.where(Film.year >= decade, Film.year < decade + 10)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort == "top":
        avg = (select(DiaryEntry.film_id, func.avg(DiaryEntry.stars).label("a")).where(DiaryEntry.stars.is_not(None))
               .group_by(DiaryEntry.film_id).subquery())
        stmt = stmt.outerjoin(avg, avg.c.film_id == Film.id).order_by(func.coalesce(avg.c.a, 0).desc(), Film.popularity.desc())
    elif sort == "new":
        stmt = stmt.order_by(func.coalesce(Film.year, 0).desc(), Film.popularity.desc())
    else:
        stmt = stmt.order_by(Film.popularity.desc(), Film.id)
    films = list(db.scalars(stmt.limit(limit).offset(offset)).unique())
    ratings = film_ratings(db, [f.id for f in films])
    saved = set()
    if user and films:
        saved = {fid for (fid,) in db.execute(select(WatchlistItem.film_id).where(
            WatchlistItem.user_id == user.id, WatchlistItem.film_id.in_([f.id for f in films])))}
    return {"total": total, "films": [{**film_card(f, ratings), "on_watchlist": f.id in saved} for f in films]}


def streak_of(dates: List[dt.date], today: Optional[dt.date] = None) -> int:
    """Consecutive days with a diary entry, ending today or yesterday."""
    days = set(dates)
    d = today or dt.date.today()
    if d not in days:
        d -= dt.timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def _stats(db: Session, uid: int) -> dict:
    year = dt.date.today().year
    rows = db.execute(select(DiaryEntry.watched_on, DiaryEntry.stars, Film.runtime)
                      .join(Film, Film.id == DiaryEntry.film_id).where(DiaryEntry.user_id == uid)).all()
    stars = [s for _, s, _ in rows if s is not None]
    this_year = [r for r in rows if r[0].year == year]
    return {"films": len(rows), "films_this_year": len(this_year),
            "hours_this_year": round(sum((rt or 0) for _, _, rt in this_year) / 60),
            "avg_stars": round(sum(stars) / len(stars), 2) if stars else None,
            "reviews": db.scalar(select(func.count()).select_from(Review).where(
                Review.user_id == uid, Review.state == "published")) or 0,
            "watchlist": db.scalar(select(func.count()).select_from(WatchlistItem).where(WatchlistItem.user_id == uid)) or 0,
            "followers": db.scalar(select(func.count()).select_from(Follow).where(Follow.followee_id == uid)) or 0,
            "following": db.scalar(select(func.count()).select_from(Follow).where(Follow.follower_id == uid)) or 0,
            "streak": streak_of([r[0] for r in rows]), "longest_streak": streaks([r[0] for r in rows])["longest"]}


@router.get("/me/stats")
def my_stats(db: Session = Depends(get_db), user: User = Depends(user_required)):
    return _stats(db, user.id)


@router.get("/me/following")
def my_following(db: Session = Depends(get_db), user: User = Depends(user_required)):
    rows = db.execute(select(User.id, User.display_name).join(Follow, Follow.followee_id == User.id)
                      .where(Follow.follower_id == user.id)).all()
    return [{"user_id": i, "name": n} for i, n in rows]


@router.get("/users/{uid}")
def profile(uid: int, db: Session = Depends(get_wdb), viewer: Optional[User] = Depends(user_optional)):
    """Public profile: name, roles, counts, favourite four (highest-rated diary films), recent published reviews, clubs."""
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "user not found")
    best: Dict[int, float] = {}
    for fid, s in db.execute(select(DiaryEntry.film_id, func.max(DiaryEntry.stars)).where(
            DiaryEntry.user_id == uid, DiaryEntry.stars.is_not(None)).group_by(DiaryEntry.film_id)):
        best[fid] = s
    fav_ids = [fid for fid, _ in sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))[:4]]
    films = {f.id: f for f in db.scalars(select(Film).where(Film.id.in_(fav_ids or [0])))}
    reviews = []
    from .community import like_info
    rev_ids = [i for (i,) in db.execute(select(Review.id).where(Review.user_id == uid, Review.state == "published")
                                        .order_by(Review.id.desc()).limit(5))]
    likes = like_info(db, "review", rev_ids, viewer)
    for r, f in db.execute(select(Review, Film).join(Film, Film.id == Review.film_id)
                           .where(Review.user_id == uid, Review.state == "published").order_by(Review.id.desc()).limit(5)):
        v = review_view(r, viewer)
        v["likes"], v["liked"] = likes.get(r.id, (0, False))
        v["film"] = film_card(f)
        v["stars"] = best.get(f.id)
        reviews.append(v)
    clubs = db.execute(select(Club.id, Club.name).join(ClubMember, ClubMember.club_id == Club.id)
                       .where(ClubMember.user_id == uid, Club.is_public)).all()
    return {"id": u.id, "name": u.display_name, "bio": u.bio or "", "avatar": u.avatar or "", "roles": sorted(r for r in u.role_names if r != "viewer"),
            "is_me": bool(viewer and viewer.id == uid),
            "following": bool(viewer and db.get(Follow, (viewer.id, uid))),
            "stats": _stats(db, uid), "favourites": [{**film_card(films[i]), "stars": best[i]} for i in fav_ids if i in films],
            "reviews": reviews, "clubs": [{"id": i, "name": n} for i, n in clubs],
            "badges": badge_progress(db, uid, save=bool(viewer and viewer.id == uid))}
