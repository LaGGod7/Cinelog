"""Critics: a verified tier of reviewer.

A viewer applies, a moderator (or admin) decides, approval grants the `critic` role. That role then changes what the
site does for them: a Critic badge on reviews, a separate critic score on each film, and the right to publish a pick.
Separation of duties: nobody can decide their own application.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import CriticApplication, CriticPick, DiaryEntry, Film, Follow, Review, User, UserRole
from ..rbac import ensure_can_post, get_db, require_perm, user_optional, user_required
from ..services import jobs
from ..services.catalog import film_card, film_ratings
from ..services.notifications import notify
from ..workflow import InvalidTransition, application_transition

router = APIRouter(tags=["critics"])

NEED_FILMS = 5      # distinct films logged
NEED_REVIEWS = 1    # published reviews


def progress(db: Session, uid: int) -> dict:
    films = db.scalar(select(func.count(func.distinct(DiaryEntry.film_id))).where(DiaryEntry.user_id == uid)) or 0
    reviews = db.scalar(select(func.count()).select_from(Review).where(Review.user_id == uid, Review.state == "published")) or 0
    return {"films": {"have": films, "need": NEED_FILMS}, "reviews": {"have": reviews, "need": NEED_REVIEWS},
            "eligible": films >= NEED_FILMS and reviews >= NEED_REVIEWS}


def _app_json(db: Session, a: CriticApplication, with_applicant: bool = False) -> dict:
    out = {"id": a.id, "state": a.state, "statement": a.statement, "links": a.links, "note": a.decision_note,
           "created_at": a.created_at.isoformat(), "decided_at": a.decided_at.isoformat() if a.decided_at else None}
    if a.decided_by:
        by = db.get(User, a.decided_by)
        out["decided_by"] = by.display_name if by else None
    if with_applicant:
        u = db.get(User, a.user_id)
        p = progress(db, a.user_id)
        out["applicant"] = {"id": a.user_id, "name": u.display_name if u else "?", "films": p["films"]["have"],
                            "reviews": p["reviews"]["have"],
                            "followers": db.scalar(select(func.count()).select_from(Follow).where(Follow.followee_id == a.user_id)) or 0,
                            "member_since": u.created_at.isoformat() if u else None}
    return out


@router.get("/me/critic")
def my_critic_status(db: Session = Depends(get_db), user: User = Depends(user_required)):
    last = db.scalar(select(CriticApplication).where(CriticApplication.user_id == user.id).order_by(CriticApplication.id.desc()).limit(1))
    return {"is_critic": "critic" in user.role_names, "progress": progress(db, user.id),
            "application": _app_json(db, last) if last else None}


class ApplyIn(BaseModel):
    statement: str = Field(min_length=40, max_length=1500)
    links: str = Field("", max_length=300)


@router.post("/critics/apply", status_code=201)
def apply(body: ApplyIn, db: Session = Depends(get_db), user: User = Depends(require_perm("critic.apply"))):
    ensure_can_post(user)
    if "critic" in user.role_names:
        raise HTTPException(409, "you are already a critic")
    if db.scalar(select(CriticApplication.id).where(CriticApplication.user_id == user.id, CriticApplication.state == "pending")):
        raise HTTPException(409, "you already have an application waiting for a decision")
    p = progress(db, user.id)
    if not p["eligible"]:
        raise HTTPException(400, f"log at least {NEED_FILMS} films and publish {NEED_REVIEWS} review first "
                                 f"(you have {p['films']['have']} films, {p['reviews']['have']} reviews)")
    a = CriticApplication(user_id=user.id, statement=body.statement.strip(), links=body.links.strip())
    db.add(a); db.flush()
    audit(db, user.id, "critic.apply", f"application:{a.id}")
    deciders = db.scalars(select(User).join(UserRole, UserRole.user_id == User.id).where(UserRole.role.in_(("moderator", "admin"))).distinct())
    for m in deciders:
        notify(db, m.id, "critic", f"{user.display_name} applied to be a critic", "/moderation?tab=critics", user.id)
    return _app_json(db, a)


@router.delete("/critics/apply")
def withdraw(db: Session = Depends(get_db), user: User = Depends(user_required)):
    a = db.scalar(select(CriticApplication).where(CriticApplication.user_id == user.id, CriticApplication.state == "pending"))
    if a is None:
        raise HTTPException(404, "nothing to withdraw")
    application_transition(db, a, "withdrawn")
    a.decided_at = dt.datetime.utcnow()
    audit(db, user.id, "critic.withdraw", f"application:{a.id}")
    return {"state": a.state}


@router.get("/critics/applications")
def applications(state: str = "pending", db: Session = Depends(get_db), _: User = Depends(require_perm("critic.review"))):
    stmt = select(CriticApplication).order_by(CriticApplication.id.desc()).limit(100)
    if state != "all":
        stmt = stmt.where(CriticApplication.state == state)
    return [_app_json(db, a, with_applicant=True) for a in db.scalars(stmt)]


class Decision(BaseModel):
    note: str = Field("", max_length=400)


def _decide(request: Request, db: Session, app_id: int, mod: User, dst: str, note: str) -> dict:
    a = db.get(CriticApplication, app_id)
    if a is None:
        raise HTTPException(404, "application not found")
    if a.user_id == mod.id:
        raise HTTPException(403, "you cannot decide your own application")  # separation of duties
    try:
        application_transition(db, a, dst)
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    a.decided_by, a.decided_at, a.decision_note = mod.id, dt.datetime.utcnow(), note.strip()
    u = db.get(User, a.user_id)
    if dst == "approved" and "critic" not in u.role_names:
        u.roles.append(UserRole(user_id=u.id, role="critic"))
    audit(db, mod.id, f"critic.{'approve' if dst == 'approved' else 'reject'}", f"application:{a.id}", f"user:{u.id} {note.strip()}"[:300])
    word = "approved" if dst == "approved" else "not approved"
    notify(db, u.id, "critic", f"Your critic application was {word}", "/me", mod.id)
    mail = f"A moderator reviewed your CineLog critic application: {word}." + (f"\n\nNote: {note.strip()}" if note.strip() else "")
    ids = jobs.queue_emails(db, [u], f"Your critic application was {word}", mail)
    out = _app_json(db, a, with_applicant=True)
    db.commit(); jobs.dispatch_emails(request.app, ids)
    return out


@router.post("/critics/applications/{app_id}/approve")
def approve(app_id: int, request: Request, body: Decision = Decision(), db: Session = Depends(get_db),
            mod: User = Depends(require_perm("critic.review"))):
    return _decide(request, db, app_id, mod, "approved", body.note)


@router.post("/critics/applications/{app_id}/reject")
def reject(app_id: int, request: Request, body: Decision = Decision(), db: Session = Depends(get_db),
           mod: User = Depends(require_perm("critic.review"))):
    if len(body.note.strip()) < 5:
        raise HTTPException(400, "say why (at least a few words): the applicant will read it")
    return _decide(request, db, app_id, mod, "rejected", body.note)


# ---------------------------------------------------------------- critic's picks
class PickIn(BaseModel):
    blurb: str = Field(min_length=10, max_length=280)


@router.put("/films/{film_id}/pick")
def make_pick(film_id: int, body: PickIn, db: Session = Depends(get_db), user: User = Depends(require_perm("critic.pick"))):
    ensure_can_post(user)
    if db.get(Film, film_id) is None:
        raise HTTPException(404, "film not found")
    row = db.get(CriticPick, (user.id, film_id))
    if row is None:
        db.add(CriticPick(user_id=user.id, film_id=film_id, blurb=body.blurb.strip()))
    else:
        row.blurb = body.blurb.strip()
    return {"ok": True}


@router.delete("/films/{film_id}/pick")
def drop_pick(film_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("critic.pick"))):
    row = db.get(CriticPick, (user.id, film_id))
    if row:
        db.delete(row)
    return {"ok": True}


def picks_for_film(db: Session, film_id: int) -> List[dict]:
    rows = db.execute(select(CriticPick, User.display_name).join(User, User.id == CriticPick.user_id)
                      .where(CriticPick.film_id == film_id).order_by(CriticPick.created_at.desc()).limit(10)).all()
    return [{"user_id": p.user_id, "name": n, "blurb": p.blurb} for p, n in rows]


@router.get("/critics/picks")
def latest_picks(limit: int = 8, db: Session = Depends(get_db)):
    rows = db.execute(select(CriticPick, Film, User.display_name).join(Film, Film.id == CriticPick.film_id)
                      .join(User, User.id == CriticPick.user_id).order_by(CriticPick.created_at.desc())
                      .limit(max(1, min(limit, 30)))).all()
    ratings = film_ratings(db, [f.id for _, f, _ in rows])
    return [{"film": film_card(f, ratings), "blurb": p.blurb, "critic": {"id": p.user_id, "name": n}} for p, f, n in rows]


def rating_split(db: Session, film_id: int) -> dict:
    """Average stars from critics and from everyone else: the same diary data, split by role."""
    critic_ids = select(UserRole.user_id).where(UserRole.role == "critic")
    out = {}
    for key, cond in (("critics", DiaryEntry.user_id.in_(critic_ids)), ("viewers", DiaryEntry.user_id.not_in(critic_ids))):
        avg, n = db.execute(select(func.avg(DiaryEntry.stars), func.count()).where(
            DiaryEntry.film_id == film_id, DiaryEntry.stars.is_not(None), cond)).one()
        out[key] = {"avg": round(float(avg), 2) if avg is not None else None, "n": n}
    return out
