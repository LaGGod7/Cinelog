"""Things that make the site worth coming back to: year in review, yearly goal, recommendations, taste match,
friends who watched, film of the day, upcoming watch-alongs."""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Club, ClubMember, DiaryEntry, Film, Follow, Review, User, Watchalong, WatchalongRsvp
from ..rbac import get_db, require_perm, user_optional, user_required
from ..services import insights, recommend
from ..services.catalog import film_card, film_ratings

router = APIRouter(tags=["insights"])


@router.get("/me/year")
def my_year(year: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(user_required)):
    years = insights.years_with_entries(db, user.id)
    y = year or (years[0] if years else dt.date.today().year)
    if not 1888 <= y <= dt.date.today().year + 1:
        raise HTTPException(422, "pick a real year")
    out = insights.year_in_review(db, user.id, y)
    out["years"] = years
    out["share"] = insights.share_text(out, user.display_name)
    return out


class GoalIn(BaseModel):
    target: int = Field(ge=1, le=1000)
    year: Optional[int] = None


@router.get("/me/goal")
def my_goal(year: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(user_required)):
    return {"goal": insights.goal_progress(db, user.id, year or dt.date.today().year)}


@router.put("/me/goal")
def set_my_goal(body: GoalIn, db: Session = Depends(get_db), user: User = Depends(require_perm("diary.write"))):
    y = body.year or dt.date.today().year
    if y < dt.date.today().year:
        raise HTTPException(422, "that year is over")
    insights.set_goal(db, user.id, y, body.target)
    return {"goal": insights.goal_progress(db, user.id, y)}


@router.get("/me/recommendations")
def my_recommendations(limit: int = 12, db: Session = Depends(get_db), user: User = Depends(user_required)):
    return recommend.recommend(db, user.id, limit)


@router.get("/users/{uid}/match")
def match(uid: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    if uid == user.id:
        raise HTTPException(400, "that's you")
    other = db.get(User, uid)
    if other is None:
        raise HTTPException(404, "user not found")
    return {"user": {"id": other.id, "name": other.display_name}, **insights.taste_match(db, user.id, uid)}


@router.get("/films/{film_id}/friends")
def friends_who_watched(film_id: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    """People you follow who logged this film (their latest entry), with their rating and whether they reviewed it."""
    rows = db.execute(select(DiaryEntry, User).join(User, User.id == DiaryEntry.user_id)
                      .join(Follow, Follow.followee_id == DiaryEntry.user_id)
                      .where(Follow.follower_id == user.id, DiaryEntry.film_id == film_id)
                      .order_by(DiaryEntry.watched_on.desc(), DiaryEntry.id.desc())).all()
    seen, out = set(), []
    for e, u in rows:
        if u.id in seen:
            continue
        seen.add(u.id)
        out.append({"user_id": u.id, "name": u.display_name, "avatar": u.avatar or "", "stars": e.stars,
                    "watched_on": e.watched_on.isoformat(), "rewatch": e.rewatch})
    reviewed = {uid for (uid,) in db.execute(select(Review.user_id).where(
        Review.film_id == film_id, Review.state == "published", Review.user_id.in_(seen or [0])))}
    for o in out:
        o["reviewed"] = o["user_id"] in reviewed
    rated = [o["stars"] for o in out if o["stars"] is not None]
    return {"count": len(out), "avg": round(sum(rated) / len(rated), 2) if rated else None, "friends": out[:20]}


@router.get("/discover/film-of-the-day")
def film_of_the_day(db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    """One film for everyone today. Same answer all day: it is a hash of the date over the catalogue's popular films."""
    ids = [i for (i,) in db.execute(select(Film.id).where(Film.poster_path.is_not(None), Film.overview != "")
                                    .order_by(Film.popularity.desc()).limit(300))]
    if not ids:
        ids = [i for (i,) in db.execute(select(Film.id).order_by(Film.popularity.desc()).limit(300))]
    if not ids:
        return {"film": None}
    ids.sort()
    today = dt.date.today()
    pick = ids[int(hashlib.sha1(today.isoformat().encode()).hexdigest(), 16) % len(ids)]
    f = db.get(Film, pick)
    out = {"date": today.isoformat(), "film": {**film_card(f, film_ratings(db, [pick])), "overview": f.overview}}
    if user:
        out["watched"] = db.scalar(select(DiaryEntry.id).where(DiaryEntry.user_id == user.id, DiaryEntry.film_id == pick).limit(1)) is not None
    return out


@router.get("/me/upcoming")
def upcoming(limit: int = 5, db: Session = Depends(get_db), user: User = Depends(user_required)):
    """The next watch-alongs of the clubs you belong to."""
    rows = db.execute(select(Watchalong, Club.name).join(Club, Club.id == Watchalong.club_id)
                      .join(ClubMember, (ClubMember.club_id == Watchalong.club_id) & (ClubMember.user_id == user.id))
                      .where(Watchalong.starts_at >= dt.datetime.utcnow()).order_by(Watchalong.starts_at)
                      .limit(max(1, min(limit, 20)))).all()
    mine = {wid for (wid,) in db.execute(select(WatchalongRsvp.watchalong_id).where(WatchalongRsvp.user_id == user.id))}
    out = []
    for w, club in rows:
        f = db.get(Film, w.film_id)
        out.append({"id": w.id, "club_id": w.club_id, "club": club, "starts_at": w.starts_at.isoformat(),
                    "rsvp": w.id in mine, "film": film_card(f)})
    return out
