"""Likes, lists, club discussion threads, watch-alongs, badges and the streak leaderboard."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..gamification import award, badge_progress, user_streaks
from ..models import (LIKE_KINDS, Club, ClubThread, Film, FilmList, FilmListItem, Follow, Like, Review, ThreadReply,
                      User, Watchalong, WatchalongRsvp)
from ..rbac import CLUB_MANAGE, club_role, ensure_can_post, get_db, has_perm, require_club_role, require_perm, user_optional, user_required
from ..services.catalog import film_card, film_ratings
from ..services.notifications import notify

router = APIRouter(tags=["community"])


# ================================================================= likes
def like_info(db: Session, kind: str, ids: Iterable[int], viewer: Optional[User]) -> Dict[int, Tuple[int, bool]]:
    ids = list(ids)
    if not ids:
        return {}
    counts = dict(db.execute(select(Like.target_id, func.count()).where(Like.kind == kind, Like.target_id.in_(ids))
                             .group_by(Like.target_id)).all())
    mine = set()
    if viewer:
        mine = {t for (t,) in db.execute(select(Like.target_id).where(
            Like.kind == kind, Like.user_id == viewer.id, Like.target_id.in_(ids)))}
    return {i: (counts.get(i, 0), i in mine) for i in ids}


def _like_target(db: Session, kind: str, target_id: int) -> int:
    """Returns the owner's user id (to re-check their badges); 404 if the thing does not exist or is not public."""
    if kind not in LIKE_KINDS:
        raise HTTPException(404, "unknown kind")
    if kind == "review":
        r = db.get(Review, target_id)
        if r is None or r.state != "published":
            raise HTTPException(404, "review not found")
        return r.user_id
    obj = db.get(FilmList if kind == "list" else ClubThread, target_id)
    if obj is None:
        raise HTTPException(404, f"{kind} not found")
    return obj.user_id


def _like_link(db: Session, kind: str, target_id: int) -> str:
    if kind == "review":
        r = db.get(Review, target_id)
        return f"/films/{r.film_id}" if r else ""
    if kind == "list":
        return f"/lists/{target_id}"
    t = db.get(ClubThread, target_id)
    return f"/clubs/{t.club_id}" if t else ""


@router.put("/likes/{kind}/{target_id}")
def like(kind: str, target_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("like.write"))):
    owner = _like_target(db, kind, target_id)
    if owner == user.id:
        raise HTTPException(400, "you can't like your own " + kind)
    if db.get(Like, (user.id, kind, target_id)) is None:
        db.add(Like(user_id=user.id, kind=kind, target_id=target_id)); db.flush()
        notify(db, owner, "like", f"{user.display_name} liked your {kind}", _like_link(db, kind, target_id), user.id)
        award(db, owner)
    return {"liked": True, "likes": like_info(db, kind, [target_id], user)[target_id][0]}


@router.delete("/likes/{kind}/{target_id}")
def unlike(kind: str, target_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("like.write"))):
    _like_target(db, kind, target_id)
    row = db.get(Like, (user.id, kind, target_id))
    if row:
        db.delete(row); db.flush()
    return {"liked": False, "likes": like_info(db, kind, [target_id], user)[target_id][0]}


# ================================================================= badges & streaks
@router.get("/me/badges")
def my_badges(request: Request, db: Session = Depends(get_db), user: User = Depends(user_required)):
    out = badge_progress(db, user.id, save=False)  # the common case: nothing new, so no write lock is needed
    if any(not b["earned"] and b["value"] >= b["target"] for b in out):  # a badge was just reached: store it (and flag it new)
        with request.app.state.db.session() as w:
            out = badge_progress(w, user.id)
    return out


@router.get("/users/{uid}/badges")
def user_badges(uid: int, db: Session = Depends(get_db)):
    if db.get(User, uid) is None:
        raise HTTPException(404, "user not found")
    return badge_progress(db, uid, save=False)


@router.get("/leaderboard/streaks")
def streak_board(db: Session = Depends(get_db), user: User = Depends(user_required)):
    """You and the people you follow, by current diary streak."""
    ids = [user.id] + [u for (u,) in db.execute(select(Follow.followee_id).where(Follow.follower_id == user.id))]
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(ids)))}
    rows = []
    for i in ids:
        s = user_streaks(db, i)
        rows.append({"user_id": i, "name": names.get(i), "days": s["current"], "longest": s["longest"], "me": i == user.id})
    rows.sort(key=lambda r: (-r["days"], -r["longest"], r["name"] or ""))
    return rows[:10]


# ================================================================= lists
class ListIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    description: str = Field("", max_length=1000)
    film_ids: List[int] = Field(default_factory=list, max_length=100)


def list_view(db: Session, fl: FilmList, viewer: Optional[User], likes: Optional[dict] = None, full: bool = False) -> dict:
    ids = [it.film_id for it in fl.items]
    films = {f.id: f for f in db.scalars(select(Film).where(Film.id.in_(ids or [0])))}
    shown = ids if full else ids[:5]
    ratings = film_ratings(db, shown) if full else {}
    n, liked = (likes or like_info(db, "list", [fl.id], viewer)).get(fl.id, (0, False))
    return {"id": fl.id, "title": fl.title, "description": fl.description, "created_at": fl.created_at.isoformat(),
            "author": {"id": fl.user_id, "name": fl.author.display_name}, "count": len(ids), "likes": n, "liked": liked,
            "mine": bool(viewer and viewer.id == fl.user_id),
            "films": [film_card(films[i], ratings) for i in shown if i in films]}


@router.get("/lists")
def lists(tab: str = "popular", user_id: Optional[int] = None, db: Session = Depends(get_db),
          viewer: Optional[User] = Depends(user_optional)):
    """tab = popular (most liked) | new | friends (people you follow, and you)."""
    stmt = select(FilmList)
    if user_id:
        stmt = stmt.where(FilmList.user_id == user_id)
    if tab == "friends":
        if viewer is None:
            return []
        ids = [viewer.id] + [u for (u,) in db.execute(select(Follow.followee_id).where(Follow.follower_id == viewer.id))]
        stmt = stmt.where(FilmList.user_id.in_(ids))
    rows = list(db.scalars(stmt.order_by(FilmList.id.desc()).limit(200)).unique())
    likes = like_info(db, "list", [r.id for r in rows], viewer)
    if tab == "popular":
        rows.sort(key=lambda r: (-likes[r.id][0], -r.id))
    return [list_view(db, r, viewer, likes) for r in rows[:60]]


def _own_list(db: Session, list_id: int, user: User) -> FilmList:
    fl = db.get(FilmList, list_id)
    if fl is None:
        raise HTTPException(404, "list not found")
    if fl.user_id != user.id and not has_perm(user, "review.moderate"):
        raise HTTPException(403, "only the author can change this list")
    return fl


def _real_films(db: Session, ids: List[int]) -> List[int]:
    ok = {i for (i,) in db.execute(select(Film.id).where(Film.id.in_(ids or [0])))}
    return [i for i in dict.fromkeys(ids) if i in ok]


@router.post("/lists", status_code=201)
def create_list(body: ListIn, db: Session = Depends(get_db), user: User = Depends(require_perm("list.write"))):
    fl = FilmList(user_id=user.id, title=body.title.strip(), description=body.description.strip())
    fl.items = [FilmListItem(film_id=f, position=k) for k, f in enumerate(_real_films(db, body.film_ids))]
    db.add(fl); db.flush()
    out = list_view(db, fl, user, full=True)
    out["new_badges"] = award(db, user.id)
    return out


@router.get("/lists/{list_id}")
def get_list(list_id: int, db: Session = Depends(get_db), viewer: Optional[User] = Depends(user_optional)):
    fl = db.get(FilmList, list_id)
    if fl is None:
        raise HTTPException(404, "list not found")
    return list_view(db, fl, viewer, full=True)


class ListEdit(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)


@router.patch("/lists/{list_id}")
def edit_list(list_id: int, body: ListEdit, db: Session = Depends(get_db), user: User = Depends(require_perm("list.write"))):
    fl = _own_list(db, list_id, user)
    if body.title is not None:
        fl.title = body.title.strip()
    if body.description is not None:
        fl.description = body.description.strip()
    db.flush()
    return list_view(db, fl, user, full=True)


@router.delete("/lists/{list_id}")
def delete_list(list_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("list.write"))):
    fl = _own_list(db, list_id, user)
    if fl.user_id != user.id:
        audit(db, user.id, "list.remove", f"list:{fl.id}", fl.title)
    for lk in db.scalars(select(Like).where(Like.kind == "list", Like.target_id == fl.id)):
        db.delete(lk)
    db.delete(fl)
    return {"ok": True}


@router.put("/lists/{list_id}/films/{film_id}")
def add_to_list(list_id: int, film_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("list.write"))):
    fl = _own_list(db, list_id, user)
    if db.get(Film, film_id) is None:
        raise HTTPException(404, "film not found")
    if len(fl.items) >= 100:
        raise HTTPException(409, "a list holds at most 100 films")
    if all(it.film_id != film_id for it in fl.items):
        fl.items.append(FilmListItem(film_id=film_id, position=max([it.position for it in fl.items] or [-1]) + 1))
        db.flush()
    return {"count": len(fl.items)}


@router.delete("/lists/{list_id}/films/{film_id}")
def remove_from_list(list_id: int, film_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("list.write"))):
    fl = _own_list(db, list_id, user)
    fl.items = [it for it in fl.items if it.film_id != film_id]
    db.flush()
    return {"count": len(fl.items)}


# ================================================================= club discussion
THREAD_TAGS = ("Discussion", "Hot take", "Recommendation", "Question", "Welcome")


def _club_view_or_403(db: Session, club_id: int, user: Optional[User]) -> Club:
    c = db.get(Club, club_id)
    if c is None:
        raise HTTPException(404, "club not found")
    if not (c.is_public or (user is not None and club_role(db, c.id, user.id))):
        raise HTTPException(403, "this club is private")
    return c


def _member_or_403(db: Session, club_id: int, user: User) -> str:
    role = club_role(db, club_id, user.id)
    if role is None:
        raise HTTPException(403, "join the club to take part")
    return role


def thread_view(t: ClubThread, likes: dict, viewer: Optional[User], can_remove: bool, full: bool = False) -> dict:
    n, liked = likes.get(t.id, (0, False))
    out = {"id": t.id, "club_id": t.club_id, "title": t.title, "body": t.body, "tag": t.tag, "created_at": t.created_at.isoformat(),
           "author": {"id": t.user_id, "name": t.author.display_name}, "replies": len(t.replies), "votes": n, "voted": liked,
           "can_remove": can_remove or bool(viewer and viewer.id == t.user_id)}
    if full:
        out["reply_list"] = [{"id": r.id, "body": r.body, "created_at": r.created_at.isoformat(),
                              "author": {"id": r.user_id, "name": r.author.display_name}} for r in t.replies]
    return out


def _can_remove(db: Session, club_id: int, user: Optional[User]) -> bool:
    return bool(user) and (club_role(db, club_id, user.id) in CLUB_MANAGE or has_perm(user, "review.moderate"))


@router.get("/clubs/{club_id}/threads")
def threads(club_id: int, db: Session = Depends(get_db), viewer: Optional[User] = Depends(user_optional)):
    _club_view_or_403(db, club_id, viewer)
    rows = list(db.scalars(select(ClubThread).where(ClubThread.club_id == club_id).order_by(ClubThread.id.desc()).limit(100)).unique())
    likes = like_info(db, "thread", [t.id for t in rows], viewer)
    cr = _can_remove(db, club_id, viewer)
    return [thread_view(t, likes, viewer, cr) for t in rows]


class ThreadIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field("", max_length=4000)
    tag: str = "Discussion"


@router.post("/clubs/{club_id}/threads", status_code=201)
def new_thread(club_id: int, body: ThreadIn, db: Session = Depends(get_db), user: User = Depends(require_perm("thread.write"))):
    ensure_can_post(user)
    _club_view_or_403(db, club_id, user)
    _member_or_403(db, club_id, user)
    if body.tag not in THREAD_TAGS:
        raise HTTPException(400, f"tag must be one of {', '.join(THREAD_TAGS)}")
    t = ClubThread(club_id=club_id, user_id=user.id, title=body.title.strip(), body=body.body.strip(), tag=body.tag)
    db.add(t); db.flush()
    out = thread_view(t, {}, user, True, full=True)
    out["new_badges"] = award(db, user.id)
    return out


def _thread_or_404(db: Session, thread_id: int, viewer: Optional[User]) -> ClubThread:
    t = db.get(ClubThread, thread_id)
    if t is None:
        raise HTTPException(404, "thread not found")
    _club_view_or_403(db, t.club_id, viewer)
    return t


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, db: Session = Depends(get_db), viewer: Optional[User] = Depends(user_optional)):
    t = _thread_or_404(db, thread_id, viewer)
    return thread_view(t, like_info(db, "thread", [t.id], viewer), viewer, _can_remove(db, t.club_id, viewer), full=True)


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/threads/{thread_id}/replies", status_code=201)
def reply(thread_id: int, body: ReplyIn, db: Session = Depends(get_db), user: User = Depends(require_perm("thread.write"))):
    ensure_can_post(user)
    t = _thread_or_404(db, thread_id, user)
    _member_or_403(db, t.club_id, user)
    t.replies.append(ThreadReply(user_id=user.id, body=body.body.strip()))
    db.flush(); db.refresh(t)
    notify(db, t.user_id, "reply", f"{user.display_name} replied to your thread \"{t.title[:60]}\"", f"/clubs/{t.club_id}", user.id)
    out = thread_view(t, like_info(db, "thread", [t.id], user), user, _can_remove(db, t.club_id, user), full=True)
    out["new_badges"] = award(db, user.id)
    return out


@router.delete("/threads/{thread_id}")
def remove_thread(thread_id: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    t = _thread_or_404(db, thread_id, user)
    if t.user_id != user.id:
        if not _can_remove(db, t.club_id, user):
            raise HTTPException(403, "only the author, a convener or a moderator can remove a thread")
        audit(db, user.id, "thread.remove", f"thread:{t.id}", t.title)
    for lk in db.scalars(select(Like).where(Like.kind == "thread", Like.target_id == t.id)):
        db.delete(lk)
    db.delete(t)
    return {"ok": True}


# ================================================================= watch-alongs
def watchalong_view(db: Session, w: Watchalong, viewer: Optional[User]) -> dict:
    f = db.get(Film, w.film_id)
    going = db.scalar(select(func.count()).select_from(WatchalongRsvp).where(WatchalongRsvp.watchalong_id == w.id)) or 0
    mine = bool(viewer and db.get(WatchalongRsvp, (w.id, viewer.id)))
    return {"id": w.id, "club_id": w.club_id, "starts_at": w.starts_at.isoformat(), "going": going, "rsvp": mine,
            "past": w.starts_at < dt.datetime.utcnow(), "from_poll": w.poll_id is not None, "film": film_card(f)}


def upsert_poll_watchalong(db: Session, poll, user_id: int) -> None:
    """A poll's winner with a screening date becomes (or updates) a watch-along."""
    w = db.scalar(select(Watchalong).where(Watchalong.poll_id == poll.id))
    if w is None:
        db.add(Watchalong(club_id=poll.club_id, film_id=poll.winner_film_id, starts_at=poll.screening_date,
                          poll_id=poll.id, created_by=user_id))
    else:
        w.starts_at, w.film_id = poll.screening_date, poll.winner_film_id
    db.flush()


@router.get("/clubs/{club_id}/watchalongs")
def watchalongs(club_id: int, db: Session = Depends(get_db), viewer: Optional[User] = Depends(user_optional)):
    _club_view_or_403(db, club_id, viewer)
    rows = list(db.scalars(select(Watchalong).where(Watchalong.club_id == club_id).order_by(Watchalong.starts_at)))
    views = [watchalong_view(db, w, viewer) for w in rows]
    return [v for v in views if not v["past"]] + [v for v in reversed(views) if v["past"]][:5]


class WatchalongIn(BaseModel):
    film_id: int
    starts_at: dt.datetime


@router.post("/clubs/{club_id}/watchalongs", status_code=201)
def new_watchalong(club_id: int, body: WatchalongIn, db: Session = Depends(get_db), user: User = Depends(user_required)):
    _club_view_or_403(db, club_id, user)
    require_club_role(db, club_id, user, CLUB_MANAGE)
    if db.get(Film, body.film_id) is None:
        raise HTTPException(404, "film not found")
    when = body.starts_at.astimezone(dt.timezone.utc).replace(tzinfo=None) if body.starts_at.tzinfo else body.starts_at
    if when < dt.datetime.utcnow():
        raise HTTPException(400, "pick a time in the future")
    w = Watchalong(club_id=club_id, film_id=body.film_id, starts_at=when, created_by=user.id)
    db.add(w); db.flush()
    audit(db, user.id, "watchalong.create", f"club:{club_id}", f"film:{body.film_id} at {when.isoformat()}")
    return watchalong_view(db, w, user)


def _watchalong(db: Session, wid: int, user: User) -> Watchalong:
    w = db.get(Watchalong, wid)
    if w is None:
        raise HTTPException(404, "watch-along not found")
    _club_view_or_403(db, w.club_id, user)
    return w


@router.put("/watchalongs/{wid}/rsvp")
def rsvp(wid: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    w = _watchalong(db, wid, user)
    _member_or_403(db, w.club_id, user)
    if db.get(WatchalongRsvp, (wid, user.id)) is None:
        db.add(WatchalongRsvp(watchalong_id=wid, user_id=user.id)); db.flush()
    out = watchalong_view(db, w, user)
    out["new_badges"] = award(db, user.id)
    return out


@router.delete("/watchalongs/{wid}/rsvp")
def un_rsvp(wid: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    w = _watchalong(db, wid, user)
    row = db.get(WatchalongRsvp, (wid, user.id))
    if row:
        db.delete(row); db.flush()
    return watchalong_view(db, w, user)


@router.delete("/watchalongs/{wid}")
def cancel_watchalong(wid: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    w = _watchalong(db, wid, user)
    require_club_role(db, w.club_id, user, CLUB_MANAGE)
    audit(db, user.id, "watchalong.cancel", f"watchalong:{wid}")
    db.delete(w)
    return {"ok": True}
