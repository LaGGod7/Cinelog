from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (Club, ClubMember, ClubWatchlist, Film, Poll, PollOption, User, Vote)
from ..rbac import CLUB_MANAGE, club_role, get_db, get_wdb, require_club_role, require_perm, user_optional, user_required
from ..security import SESSION_COOKIE, read_token
from ..services import jobs
from ..services.polls import finalize_poll, poll_view
from ..workflow import InvalidTransition, poll_transition

router = APIRouter(tags=["clubs"])


def _club_or_404(db: Session, club_id: int) -> Club:
    c = db.get(Club, club_id)
    if c is None:
        raise HTTPException(404, "club not found")
    return c


def _can_view(db: Session, club: Club, user: Optional[User]) -> bool:
    return club.is_public or (user is not None and club_role(db, club.id, user.id) is not None)


def _club_json(db: Session, c: Club, user: Optional[User]) -> dict:
    members = db.scalars(select(ClubMember).where(ClubMember.club_id == c.id))
    mine = club_role(db, c.id, user.id) if user else None
    out = {"id": c.id, "name": c.name, "description": c.description, "is_public": c.is_public, "my_role": mine}
    if mine or c.is_public:
        out["members"] = [{"user_id": m.user_id, "name": m.user.display_name, "role": m.role} for m in members]
        out["watchlist"] = [{"film_id": fid, "title": t, "year": y, "poster": p} for fid, t, y, p in db.execute(
            select(Film.id, Film.title, Film.year, Film.poster_path).join(ClubWatchlist, ClubWatchlist.film_id == Film.id)
            .where(ClubWatchlist.club_id == c.id))]
    return out


class ClubIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field("", max_length=1000)
    is_public: bool = True


@router.post("/clubs", status_code=201)
def create_club(body: ClubIn, db: Session = Depends(get_db), user: User = Depends(require_perm("club.create"))):
    if db.scalar(select(Club.id).where(Club.name == body.name.strip())):
        raise HTTPException(409, "a club with this name exists")
    c = Club(name=body.name.strip(), description=body.description, is_public=body.is_public)
    db.add(c); db.flush()
    db.add(ClubMember(club_id=c.id, user_id=user.id, role="convener"))
    audit(db, user.id, "club.create", f"club:{c.id}")
    db.flush()
    return _club_json(db, c, user)


@router.get("/clubs")
def list_clubs(db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    mine = set()
    if user:
        mine = {cid for (cid,) in db.execute(select(ClubMember.club_id).where(ClubMember.user_id == user.id))}
    rows = db.scalars(select(Club).order_by(Club.name))
    n = dict(db.execute(select(ClubMember.club_id, func.count()).group_by(ClubMember.club_id)).all())
    open_polls = dict(db.execute(select(Poll.club_id, func.count()).where(Poll.state == "open").group_by(Poll.club_id)).all())
    return [{"id": c.id, "name": c.name, "description": c.description, "is_public": c.is_public, "mine": c.id in mine,
             "members": n.get(c.id, 0), "open_polls": open_polls.get(c.id, 0)}
            for c in rows if c.is_public or c.id in mine]


@router.get("/clubs/{club_id}")
def get_club(club_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    c = _club_or_404(db, club_id)
    if not _can_view(db, c, user):
        raise HTTPException(403, "this club is private")
    return _club_json(db, c, user)


@router.post("/clubs/{club_id}/join")
def join(club_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("club.join"))):
    c = _club_or_404(db, club_id)
    if not c.is_public:
        raise HTTPException(403, "private club: ask a convener to add you")
    if club_role(db, club_id, user.id) is None:
        db.add(ClubMember(club_id=club_id, user_id=user.id, role="member"))
    return {"joined": True}


class MemberIn(BaseModel):
    email: str
    role: str = "member"


@router.post("/clubs/{club_id}/members", status_code=201)
def add_member(club_id: int, body: MemberIn, db: Session = Depends(get_db), user: User = Depends(user_required)):
    _club_or_404(db, club_id)
    mine = require_club_role(db, club_id, user, CLUB_MANAGE)
    if body.role not in ("member", "co_convener"):
        raise HTTPException(400, "role must be member or co_convener")
    if body.role == "co_convener" and mine != "convener":
        raise HTTPException(403, "only the convener can appoint co-conveners")
    target = db.scalar(select(User).where(User.email == body.email.lower()))
    if target is None:
        raise HTTPException(404, "no user with that e-mail")
    m = db.get(ClubMember, (club_id, target.id))
    if m:
        if m.role == "convener":
            raise HTTPException(409, "cannot change the convener's role here")
        m.role = body.role
    else:
        db.add(ClubMember(club_id=club_id, user_id=target.id, role=body.role))
    audit(db, user.id, "club.member", f"club:{club_id}", f"{target.id}:{body.role}")
    return {"ok": True}


@router.delete("/clubs/{club_id}/members/{uid}")
def remove_member(club_id: int, uid: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    _club_or_404(db, club_id)
    m = db.get(ClubMember, (club_id, uid))
    if m is None:
        raise HTTPException(404, "not a member")
    if uid == user.id:
        if m.role == "convener":
            raise HTTPException(409, "hand over the convener role before leaving")
    else:
        require_club_role(db, club_id, user, CLUB_MANAGE)
        if m.role == "convener":
            raise HTTPException(403, "the convener cannot be removed")
    db.delete(m)
    return {"ok": True}


@router.post("/clubs/{club_id}/transfer/{uid}")
def hand_over(club_id: int, uid: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    require_club_role(db, club_id, user, {"convener"})
    target = db.get(ClubMember, (club_id, uid))
    if target is None:
        raise HTTPException(404, "not a member")
    target.role = "convener"
    db.get(ClubMember, (club_id, user.id)).role = "co_convener"
    audit(db, user.id, "club.transfer", f"club:{club_id}", str(uid))
    return {"ok": True}


@router.put("/clubs/{club_id}/watchlist/{film_id}")
def watch_add(club_id: int, film_id: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    require_club_role(db, club_id, user, CLUB_MANAGE)
    if db.get(Film, film_id) is None:
        raise HTTPException(404, "film not found")
    if db.get(ClubWatchlist, (club_id, film_id)) is None:
        db.add(ClubWatchlist(club_id=club_id, film_id=film_id, added_by=user.id))
    return {"ok": True}


@router.delete("/clubs/{club_id}/watchlist/{film_id}")
def watch_remove(club_id: int, film_id: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    require_club_role(db, club_id, user, CLUB_MANAGE)
    w = db.get(ClubWatchlist, (club_id, film_id))
    if w:
        db.delete(w)
    return {"ok": True}


# ---------------------------------------------------------------- polls
class PollIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    film_ids: List[int] = Field(min_length=2, max_length=12)
    deadline: Optional[dt.datetime] = None


def _naive_utc(d: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if d is None:
        return None
    return d.astimezone(dt.timezone.utc).replace(tzinfo=None) if d.tzinfo else d


@router.post("/clubs/{club_id}/polls", status_code=201)
def create_poll(club_id: int, body: PollIn, db: Session = Depends(get_db), user: User = Depends(user_required)):
    _club_or_404(db, club_id)
    require_club_role(db, club_id, user, CLUB_MANAGE)
    films = set(body.film_ids)
    if len(films) < 2 or db.query(Film).filter(Film.id.in_(films)).count() != len(films):
        raise HTTPException(400, "pick at least 2 existing, distinct films")
    p = Poll(club_id=club_id, title=body.title, state="draft", deadline=_naive_utc(body.deadline), created_by=user.id)
    p.options = [PollOption(film_id=f) for f in sorted(films)]
    db.add(p); db.flush()
    return poll_view(db, p)


@router.get("/clubs/{club_id}/polls")
def club_polls(club_id: int, db: Session = Depends(get_wdb), user: Optional[User] = Depends(user_optional)):
    c = _club_or_404(db, club_id)
    if not _can_view(db, c, user):
        raise HTTPException(403, "this club is private")
    out = []
    for p in db.scalars(select(Poll).where(Poll.club_id == club_id).order_by(Poll.id.desc())):
        _lazy_close(db, p)
        out.append(poll_view(db, p))
    return out


def _lazy_close(db: Session, p: Poll) -> None:
    if p.state == "open" and p.deadline and p.deadline <= dt.datetime.utcnow():
        try:
            finalize_poll(db, p)
        except InvalidTransition:
            pass


def _poll_or_404(db: Session, poll_id: int) -> Poll:
    p = db.get(Poll, poll_id)
    if p is None:
        raise HTTPException(404, "poll not found")
    return p


@router.get("/polls/{poll_id}")
def get_poll(poll_id: int, db: Session = Depends(get_wdb), user: Optional[User] = Depends(user_optional)):
    p = _poll_or_404(db, poll_id)
    c = db.get(Club, p.club_id)
    if not _can_view(db, c, user):
        raise HTTPException(403, "this club is private")
    _lazy_close(db, p)
    mine = db.scalar(select(Vote.option_id).where(Vote.poll_id == poll_id, Vote.user_id == user.id)) if user else None
    return poll_view(db, p, mine)


def _transition(db: Session, p: Poll, dst: str) -> None:
    try:
        poll_transition(db, p, dst)
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e


@router.post("/polls/{poll_id}/open")
def open_poll(poll_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(user_required)):
    p = _poll_or_404(db, poll_id)
    require_club_role(db, p.club_id, user, CLUB_MANAGE)
    if p.deadline and p.deadline <= dt.datetime.utcnow():
        raise HTTPException(400, "deadline is in the past")
    _transition(db, p, "open")
    members = [m.user for m in db.scalars(select(ClubMember).where(ClubMember.club_id == p.club_id))]
    ids = jobs.queue_emails(db, members, f"Poll open: {p.title}", f"Vote now in {db.get(Club, p.club_id).name}.")
    audit(db, user.id, "poll.open", f"poll:{p.id}")
    db.commit(); jobs.dispatch_emails(request.app, ids)
    return poll_view(db, p)


@router.post("/polls/{poll_id}/cancel")
def cancel_poll(poll_id: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    p = _poll_or_404(db, poll_id)
    require_club_role(db, p.club_id, user, CLUB_MANAGE)
    _transition(db, p, "cancelled")  # only Draft can be cancelled
    audit(db, user.id, "poll.cancel", f"poll:{p.id}")
    return poll_view(db, p)


@router.post("/polls/{poll_id}/close")
async def close_poll(poll_id: int, request: Request, user: User = Depends(user_required)):
    def work():
        with request.app.state.db.session() as db:
            p = _poll_or_404(db, poll_id)
            require_club_role(db, p.club_id, user, CLUB_MANAGE)
            try:
                finalize_poll(db, p)
            except InvalidTransition as e:
                raise HTTPException(409, str(e)) from e
            audit(db, user.id, "poll.close", f"poll:{p.id}")
            db.flush()
            return poll_view(db, p)

    view = await run_in_threadpool(work)
    await request.app.state.hub.broadcast(poll_id, view)
    return view


class VoteIn(BaseModel):
    option_id: int


@router.post("/polls/{poll_id}/vote")
async def vote(poll_id: int, body: VoteIn, request: Request, user: User = Depends(user_required)):
    def work():
        with request.app.state.db.session() as db:
            # lock order is always: poll row, then votes - so two voters can never deadlock each other
            p = db.execute(select(Poll).where(Poll.id == poll_id).with_for_update()).scalar_one_or_none()
            if p is None:
                raise HTTPException(404, "poll not found")
            if club_role(db, p.club_id, user.id) is None:
                raise HTTPException(403, "only club members can vote")
            _lazy_close(db, p)
            if p.state != "open":
                raise HTTPException(409, f"poll is {p.state}: voting is closed")
            if body.option_id not in {o.id for o in p.options}:
                raise HTTPException(400, "option does not belong to this poll")
            try:
                db.add(Vote(poll_id=poll_id, user_id=user.id, option_id=body.option_id))
                db.flush()
            except IntegrityError:  # UNIQUE(poll_id, user_id): the database itself refuses the second vote
                raise HTTPException(409, "already voted") from None
            db.flush()
            return poll_view(db, p, body.option_id)

    view = await run_in_threadpool(work)
    await request.app.state.hub.broadcast(poll_id, {**view, "my_vote": None})
    return view


class ScreeningIn(BaseModel):
    when: dt.datetime


@router.post("/polls/{poll_id}/screening")
def fix_screening(poll_id: int, body: ScreeningIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(user_required)):
    p = _poll_or_404(db, poll_id)
    require_club_role(db, p.club_id, user, CLUB_MANAGE)
    if p.state != "closed" or p.winner_film_id is None:
        raise HTTPException(409, "close the poll with a winner first")
    p.screening_date = _naive_utc(body.when)
    from .community import upsert_poll_watchalong
    upsert_poll_watchalong(db, p, user.id)
    film = db.get(Film, p.winner_film_id)
    members = [m.user for m in db.scalars(select(ClubMember).where(ClubMember.club_id == p.club_id))]
    ids = jobs.queue_emails(db, members, f"Screening fixed: {film.title}", f"{film.title} on {p.screening_date:%d %b %Y %H:%M}.")
    audit(db, user.id, "poll.screening", f"poll:{p.id}", p.screening_date.isoformat())
    db.commit(); jobs.dispatch_emails(request.app, ids)
    return poll_view(db, p)


@router.websocket("/ws/polls/{poll_id}")
async def poll_ws(ws: WebSocket, poll_id: int):
    app = ws.app
    uid = None
    tok = ws.cookies.get(SESSION_COOKIE)
    if tok:
        uid = read_token(tok, app.state.settings)

    def check():
        with app.state.db.session() as db:
            p = db.get(Poll, poll_id)
            if p is None:
                return None
            c = db.get(Club, p.club_id)
            if not (c.is_public or (uid and club_role(db, c.id, uid))):
                return None
            _lazy_close(db, p)
            return poll_view(db, p)

    view = await run_in_threadpool(check)
    if view is None:
        await ws.close(code=4403)
        return
    await ws.accept()
    await app.state.hub.join(poll_id, ws)
    try:
        await ws.send_json(view)
        while True:
            await ws.receive_text()  # keep-alive; updates are pushed by the vote endpoint
    except WebSocketDisconnect:
        pass
    finally:
        app.state.hub.leave(poll_id, ws)
