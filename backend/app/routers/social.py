from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..dsa.feed import cosine, merge_feeds
from ..dsa.inverted_index import top_k
from ..gamification import BY_KEY
from ..models import AspectRating, DiaryEntry, Film, FilmList, Follow, Review, User, UserBadge
from ..rbac import get_db, require_perm, user_required
from ..services.notifications import notify
from ..services.reviews import segments_of

router = APIRouter(tags=["social"])


@router.put("/follow/{uid}")
def follow(uid: int, db: Session = Depends(get_db), user: User = Depends(require_perm("social.follow"))):
    if uid == user.id:
        raise HTTPException(400, "you cannot follow yourself")
    if db.get(User, uid) is None:
        raise HTTPException(404, "user not found")
    if db.get(Follow, (user.id, uid)) is None:
        db.add(Follow(follower_id=user.id, followee_id=uid))
        notify(db, uid, "follow", f"{user.display_name} started following you", f"/users/{user.id}", user.id)
    return {"following": True}


@router.delete("/follow/{uid}")
def unfollow(uid: int, db: Session = Depends(get_db), user: User = Depends(require_perm("social.follow"))):
    f = db.get(Follow, (user.id, uid))
    if f:
        db.delete(f)
    return {"following": False}


def _ts(d: dt.datetime) -> float:
    return d.replace(tzinfo=dt.timezone.utc).timestamp()


@router.get("/feed")
def feed(limit: int = 20, db: Session = Depends(get_db), user: User = Depends(user_required)):
    """Latest activity of followed users: one newest-first list per user, merged with a min-heap (k-way merge)."""
    followees = [u for (u,) in db.execute(select(Follow.followee_id).where(Follow.follower_id == user.id))]
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(followees or [0])))}
    feeds: List[List[dict]] = []
    for uid in followees:
        items = []
        for e, f in db.execute(select(DiaryEntry, Film).join(Film, Film.id == DiaryEntry.film_id)
                               .where(DiaryEntry.user_id == uid).order_by(DiaryEntry.id.desc()).limit(limit)):
            items.append({"at": _ts(e.created_at), "user": names.get(uid), "user_id": uid, "type": "watched",
                          "film": f.title, "film_id": f.id, "poster": f.poster_path, "year": f.year, "stars": e.stars})
        for r, f in db.execute(select(Review, Film).join(Film, Film.id == Review.film_id)
                               .where(Review.user_id == uid, Review.state == "published")
                               .order_by(Review.id.desc()).limit(limit)):
            segs = segments_of(r)  # only sentences the shield left visible ever reach the feed
            excerpt = " ".join(g["text"].strip() for g in segs if not g["blurred"])[:280]
            items.append({"at": _ts(r.created_at), "user": names.get(uid), "user_id": uid, "type": "reviewed",
                          "film": f.title, "film_id": f.id, "poster": f.poster_path, "year": f.year,
                          "review_id": r.id, "excerpt": excerpt, "has_spoilers": any(g["blurred"] for g in segs)})
        for b in db.scalars(select(UserBadge).where(UserBadge.user_id == uid).order_by(UserBadge.earned_at.desc()).limit(limit)):
            if b.key in BY_KEY:
                items.append({"at": _ts(b.earned_at), "user": names.get(uid), "user_id": uid, "type": "badge",
                              "badge": BY_KEY[b.key].name, "badge_color": BY_KEY[b.key].color})
        for fl in db.scalars(select(FilmList).where(FilmList.user_id == uid).order_by(FilmList.id.desc()).limit(limit)).unique():
            items.append({"at": _ts(fl.created_at), "user": names.get(uid), "user_id": uid, "type": "list",
                          "list_id": fl.id, "list": fl.title, "count": len(fl.items)})
        items.sort(key=lambda x: -x["at"])
        feeds.append(items)
    return merge_feeds(feeds, min(limit, 50))


@router.get("/me/similar")
def similar(db: Session = Depends(get_db), user: User = Depends(user_required)):
    """Top-5 users with similar taste: cosine similarity over co-rated films (>= 5 in common)."""
    vecs: Dict[int, Dict[int, float]] = defaultdict(dict)
    rows = db.execute(select(AspectRating.user_id, AspectRating.film_id, func.avg(AspectRating.value))
                      .group_by(AspectRating.user_id, AspectRating.film_id)).all()
    for uid, fid, v in rows:
        vecs[uid][fid] = float(v) - 3.0  # centre on the middle of the 0.5-5 scale: raw cosine of all-positive ratings is always ~1
    mine = vecs.get(user.id, {})
    scored = []
    for uid, v in vecs.items():
        if uid == user.id:
            continue
        sim, common = cosine(mine, v)
        if common >= 5 and sim > 0:
            scored.append((sim, uid))
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_([u for _, u in scored] or [0])))}
    return [{"user_id": uid, "name": names.get(uid), "similarity": round(s, 3)} for s, uid in top_k(scored, 5)]
